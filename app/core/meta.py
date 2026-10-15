# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
Bangumi 元数据本地缓存（`data/bangumi_meta.json`）。

为什么需要：集号偏移、首播日、总话数、更新时刻这些信息每次都要去 Bangumi 拿，
一次「拉取在看番剧」就要发几十个请求，慢且容易被限流；文件不全时还得反复查。
现在统一存一份，各处直接用本地数据，过期了再更新。

数据形状（每个番剧一条）：
    {
      "subject_id": 607915,
      "name": "...", "name_cn": "...",
      "cover": "https://...",
      "date": "2026-06-13",          # 首播（精确到天）
      "total_episodes": 52,
      "airtime": {...},              # 更新时间（周/时:分）
      "season": 5,                   # 从名字里判出来的第几季
      "score": 7.2, "rank": 1995,
      "eps": [{"ep": 1, "airdate": "2026-06-13"}, ...],   # 每集播出日（按需补）
      "updated_at": 1792660000.0
    }
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Iterable, Optional

from . import config

META_PATH = os.path.join(config.DATA_DIR, "bangumi_meta.json")
TTL_SECONDS = 7 * 24 * 3600          # 超过 7 天算过期，后台再刷
_lock = threading.RLock()
_cache: Optional[dict] = None
_cache_mtime: float = 0.0


def _load() -> dict:
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = os.path.getmtime(META_PATH)
        except OSError:
            mtime = 0.0
        if _cache is not None and mtime == _cache_mtime:
            return _cache
        _cache_mtime = mtime
        data: dict[str, Any] = {}
        try:
            with open(META_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
            if isinstance(raw, dict):
                data = {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, json.JSONDecodeError):
            data = {}
        _cache = data
        return data


def _save(data: dict) -> None:
    global _cache
    with _lock:
        _cache = data
        try:
            os.makedirs(config.DATA_DIR, exist_ok=True)
            tmp = META_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, META_PATH)
        except OSError:
            pass


def _normalize(subject: Any) -> dict:
    """把 bangumi.Subject / dict 统一成缓存条目。"""
    def pick(key, default=None):
        if isinstance(subject, dict):
            return subject.get(key, default)
        return getattr(subject, key, default)

    sid = pick("id") or pick("subject_id")
    airtime = pick("airtime") or None
    # Subject.eps 是「话数」（int），而缓存里的 eps 是**章节表**（list，见 fetch_episodes）。
    # 不能把 int 写进去，否则章节表会被话数冲掉。
    eps = pick("eps")
    return {
        "subject_id": int(sid) if sid else 0,
        "name": pick("name") or "",
        "name_cn": pick("name_cn") or "",
        "cover": pick("cover") or "",
        "date": str(pick("date") or ""),
        "total_episodes": int(pick("total_episodes") or 0),
        "airtime": airtime,
        "score": pick("score"),
        "rank": pick("rank"),
        "eps": eps if isinstance(eps, list) else [],
        "aliases": pick("aliases") or [],
        "updated_at": time.time(),
    }


def save_many(subjects: Iterable[Any]) -> int:
    """把一批番剧信息写进本地缓存（拉取在看列表时一次性存好）。"""
    data = dict(_load())
    n = 0
    for s in subjects or []:
        item = _normalize(s)
        if not item.get("subject_id"):
            continue
        old = data.get(str(item["subject_id"])) or {}
        # 新数据里为空的字段，保留旧值，别把已有信息冲掉
        # 章节表相关字段（start_ep/end_ep/eps）也要保住：
        # 拉取在看列表时 save_many 会用「列表项」覆盖整条记录，而这些字段只有章节接口才有
        for key in ("airtime", "eps", "score", "rank", "cover", "aliases",
                    "start_ep", "end_ep", "eps_updated_at"):
            if not item.get(key) and old.get(key):
                item[key] = old[key]
        # 别名只增不减：「在看」列表接口里没有 infobox 的「别名」，用它写缓存会把
        # 「凡人修仙传 慕兰之战篇」这类篇章名冲掉，季判定认不出按篇章名发的资源
        old_aliases = [a for a in (old.get("aliases") or []) if isinstance(a, str) and a]
        if old_aliases:
            merged = [a for a in (item.get("aliases") or []) if isinstance(a, str) and a]
            for a in old_aliases:
                if a not in merged:
                    merged.append(a)
            item["aliases"] = merged
        data[str(item["subject_id"])] = item
        n += 1
    if n:
        _save(data)
    return n


def fetch_episodes(subject_id: int, *, token: str = "") -> list:
    """
    拉一季的章节表，存下**起点集号**。

    Bangumi 的章节接口里有两个编号：
        sort = 系列累计编号（凡人第五季 = 177…228）  ← 发布组标题里用的就是这个
        ep   = 本季序号（1…52）
    所以偏移 = sort(第一集) - 1 = 176，可以完全由 Bangumi 数据推出来，不用猜资源标题。
    """
    from . import config, http

    url = f"https://api.bgm.tv/v0/episodes?subject_id={int(subject_id)}&type=0&limit=100&offset=0"
    headers = {"User-Agent": "anifetch/1.2"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = http.get_json(url, headers=headers, proxy=config.proxy_for("bangumi")) or {}
    eps = []
    for ep in (data.get("data") or []):
        sort = ep.get("sort")
        if not isinstance(sort, int):
            continue
        eps.append({"sort": sort, "ep": ep.get("ep"), "airdate": ep.get("airdate") or ""})
    eps.sort(key=lambda x: x["sort"])
    if not eps:
        return []
    item = _load().get(str(int(subject_id))) or {"subject_id": int(subject_id)}
    item["eps"] = eps[:400]
    item["start_ep"] = eps[0]["sort"]
    item["end_ep"] = eps[-1]["sort"]
    item["eps_updated_at"] = time.time()
    data_all = dict(_load())
    data_all[str(int(subject_id))] = item
    _save(data_all)
    return eps


def get(subject_id: int, *, allow_stale: bool = True) -> Optional[dict]:
    item = _load().get(str(subject_id))
    if not item:
        return None
    if not allow_stale and time.time() - float(item.get("updated_at") or 0) > TTL_SECONDS:
        return None
    return item


def is_fresh(subject_id: int) -> bool:
    item = _load().get(str(subject_id))
    if not item:
        return False
    return time.time() - float(item.get("updated_at") or 0) <= TTL_SECONDS


def stale_ids(limit: int = 200) -> list[int]:
    """过期（或没有）的番剧 id，用于后台补刷。"""
    out = []
    now = time.time()
    for sid, item in _load().items():
        if now - float(item.get("updated_at") or 0) > TTL_SECONDS:
            try:
                out.append(int(sid))
            except (TypeError, ValueError):
                continue
        if len(out) >= limit:
            break
    return out


def stats() -> dict:
    data = _load()
    return {"count": len(data), "path": META_PATH, "ttl_days": TTL_SECONDS // 86400}
