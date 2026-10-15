# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
番剧更新时刻（北京时间精确到分钟）—— 来自社区维护的 bangumi-data。

为什么不用 Bangumi 官方接口：`/v0/subjects/{id}` 只有 `date`（首播日期）与 infobox 里的
「放送星期 / 播放电视台」，`/v0/episodes` 的 `airdate` 也只有 `YYYY-MM-DD` —— **都没有几点几分**。
实测（`_probe/t_airtime.py`）：

    bangumi-data   begin=2026-10-04T16:20:00.000Z → 北京时间 2026-10-05 00:20（周一）
    AniList        nextAiringEpisode → 北京时间 2026-10-12 00:20（周一）   ← 两个独立来源一致

数据来源：npm 包 `bangumi-data` 的 `dist/data.json`（约 7.5MB / 8900 条，jsDelivr CDN）。
字段用法：
    begin     放送时刻（UTC ISO，精确到分钟）→ +8 小时 = 北京时间
    broadcast RFC5545 重复区间，如 `R/2026-10-04T16:20:00.000Z/P7D`（每周一集）
    sites     各站 ID 映射（bangumi / aniList / mal / bilibili …）

落地方式：**每天刷新一次**，解析成精简索引存 `data/airtimes.json`（只留需要的字段，
几百 KB），接口按 subject_id 直接查，永不阻塞请求：
    - 服务启动时后台刷一次（不挡启动）
    - 之后任何一次查询发现缓存超过 refresh_hours（默认 24 小时）就后台刷新，期间先用旧数据
    - 下载失败保留旧缓存（新番收录本来就滞后，宁可用旧数据也别报错）
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config, logger

#: 数据源（npm 包 dist/data.json；想换镜像改这里或用环境变量覆盖）
DATA_URL = os.environ.get("BANGUMI_DATA_URL") or \
    "https://cdn.jsdelivr.net/npm/bangumi-data@0.3.230/dist/data.json"
#: 本地缓存（每天刷新）
CACHE_PATH = os.path.join(config.DATA_DIR, "airtimes.json")
#: 缓存格式版本（结构变了就自动重建）
SCHEMA = 1

CST = timezone(timedelta(hours=8))     # 北京时间
JST = timezone(timedelta(hours=9))     # 日本时间

_lock = threading.RLock()
_cache: Optional[dict] = None
_refreshing = False
_last_error = ""
_last_success = 0.0


# --------------------------------------------------------------------------- #
# 时间解析
# --------------------------------------------------------------------------- #
def _parse_iso(text: str) -> Optional[datetime]:
    if not text:
        return None
    s = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_period(rrule: str) -> float:
    """
    `broadcast` 是 RFC5545 重复区间：`R/2026-10-04T16:20:00.000Z/P7D`
    → 返回周期秒数（解析不出来按一周算）。
    """
    parts = str(rrule or "").split("/")
    if len(parts) < 3:
        return 7 * 86400.0
    m = re.match(r"^P(?:(\d+)W)?(?:(\d+)D)?$", parts[2].strip().upper())
    if not m:
        return 7 * 86400.0
    weeks = int(m.group(1) or 0)
    days = int(m.group(2) or 0)
    total = (weeks * 7 + days) * 86400.0
    return total if total > 0 else 7 * 86400.0


def next_airing(begin_ts: float, period: float, now: Optional[float] = None) -> Optional[float]:
    """按周期推到下一次放送时刻（epoch 秒）。"""
    if not begin_ts or period <= 0:
        return None
    now = time.time() if now is None else now
    if begin_ts > now:
        return begin_ts
    steps = int((now - begin_ts) // period) + 1
    return begin_ts + period * steps


def _fmt(dt: datetime) -> str:
    return dt.strftime("%m-%d %H:%M")


def _weekday_cn(dt: datetime) -> str:
    return "周" + "一二三四五六日"[dt.weekday()]


def describe(item: dict, now: Optional[float] = None, total_episodes: int = 0) -> Optional[dict]:
    """
    把索引里的一条转成界面要的文案。

        next_text      10-12 00:20（周一）
        next_full      2026-10-12 00:20（周一）· 北京时间
        jst_text       10-12 01:20（周一）· 日本时间
        finished       True/False —— 已完结（不再算「下一次更新」）
        finished_text  已完结（最后一集 09-25（周四））

    「已完结」怎么判（用户要求：完结的番别显示假的更新时间）：
      ① bangumi-data 自带 `end` 且已经过去 → 完结
      ② 知道总话数时：最后一集 = 首播 + 周期×(总话数-1)，再宽限 1 天 → 之后算完结
      ③ 总话数未知且没有 end → 不敢下结论，照常显示下一次更新（宁可不判）
    """
    if not item:
        return None
    begin_ts = float(item.get("begin") or 0)
    period = float(item.get("period") or 0)
    if begin_ts <= 0:
        return None
    now = time.time() if now is None else now
    total = int(total_episodes or 0)
    end_field = float(item.get("end") or 0)
    last_ts = begin_ts + period * (total - 1) if (total > 0 and period > 0) else 0
    finished = bool((end_field and now > end_field) or (last_ts and now > last_ts + 86400))
    nxt = next_airing(begin_ts, period, now)
    if not nxt:
        return None
    # 「已经更新到哪一集」：最近一次**已经播出**的时刻（完结的按最后一集算）
    aired_ts = 0.0
    episode_no = 0
    if period > 0 and begin_ts <= now:
        aired_ts = begin_ts + period * int((now - begin_ts) // period)
        if end_field and aired_ts > end_field:
            aired_ts = end_field
        if last_ts and aired_ts > last_ts:
            aired_ts = last_ts
        episode_no = int((aired_ts - begin_ts) // period) + 1
    n_cst = datetime.fromtimestamp(nxt, CST)
    b_cst = datetime.fromtimestamp(begin_ts, CST)
    n_jst = datetime.fromtimestamp(nxt, JST)
    a_cst = datetime.fromtimestamp(aired_ts, CST) if aired_ts else None
    end_ts = end_field or last_ts
    e_cst = datetime.fromtimestamp(end_ts, CST) if end_ts else None
    days = int(round(period / 86400)) if period else 7
    return {
        "begin_ts": int(begin_ts),
        "next_ts": int(nxt),
        "end_ts": int(end_ts) if end_ts else 0,
        "finished": finished,
        "finished_text": "已完结",
        "end_text": (f"最后一集 {e_cst.strftime('%m-%d %H:%M')}（{_weekday_cn(e_cst)}）· 北京时间"
                     if e_cst else ""),
        # 已经更新（最近一次已播）：侧栏「最近更新」用这个排序与显示
        "aired_ts": int(aired_ts) if aired_ts else 0,
        "aired_text": a_cst.strftime("%m-%d %H:%M") if a_cst else "",
        "aired_full": (f"{a_cst.strftime('%Y-%m-%d %H:%M')}（{_weekday_cn(a_cst)}）· 北京时间"
                       if a_cst else ""),
        "episode_no": episode_no,
        "days": days,
        "weekly": abs(period - 7 * 86400) < 3600,
        "next_text": f"{_fmt(n_cst)}（{_weekday_cn(n_cst)}）",
        "next_full": f"{n_cst.strftime('%Y-%m-%d %H:%M')}（{_weekday_cn(n_cst)}）",
        "cst_text": f"{n_cst.strftime('%m-%d %H:%M')}（{_weekday_cn(n_cst)}）· 北京时间",
        "jst_text": f"{n_jst.strftime('%m-%d %H:%M')}（{_weekday_cn(n_jst)}）· 日本时间",
        "begin_text": f"首播 {b_cst.strftime('%m-%d %H:%M')}（{_weekday_cn(b_cst)}）",
        "title": item.get("title") or "",
    }


# --------------------------------------------------------------------------- #
# 缓存读写与刷新
# --------------------------------------------------------------------------- #
def _load_disk() -> Optional[dict]:
    try:
        if not os.path.exists(CACHE_PATH):
            return None
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or int(raw.get("schema") or 0) != SCHEMA:
            return None
        if not isinstance(raw.get("items"), dict):
            return None
        return raw
    except (OSError, ValueError) as e:
        logger.warn("更新时刻缓存读取失败：%s", e)
        return None


def _save_disk(data: dict) -> None:
    tmp = CACHE_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, CACHE_PATH)
    except OSError as e:
        logger.warn("更新时刻缓存写入失败：%s", e)


def _index(raw: bytes) -> dict:
    """把整份 bangumi-data 压成 {subject_id: {...}} 的索引。"""
    data = json.loads(raw.decode("utf-8"))
    items = data.get("items") or []
    out: dict[str, dict] = {}
    for it in items:
        begin = _parse_iso(it.get("begin"))
        if not begin:
            continue
        period = parse_period(it.get("broadcast"))
        sites = {s.get("site"): s.get("id") for s in (it.get("sites") or []) if isinstance(s, dict)}
        sid = sites.get("bangumi")
        if not sid:
            continue
        zh = ((it.get("titleTranslate") or {}).get("zh-Hans") or [])
        end = _parse_iso(it.get("end"))
        out[str(sid)] = {
            "title": it.get("title") or "",
            "title_cn": zh[0] if zh else "",
            "begin": int(begin.timestamp()),
            "end": int(end.timestamp()) if end else 0,
            "period": int(period),
            "sites": {k: sites[k] for k in ("aniList", "mal", "bilibili", "tmdb") if k in sites},
            "site": it.get("officialSite") or "",
        }
    return {"schema": SCHEMA, "updated": int(time.time()), "source": DATA_URL,
            "count": len(out), "items": out}


def refresh(force: bool = False) -> bool:
    """
    下载并重建缓存。返回是否有更新。**永不抛异常**（网络/代理抖动是常态）。
    """
    global _cache, _refreshing, _last_error, _last_success
    with _lock:
        if _refreshing:
            return False
        if not force and _cache and not is_stale(_cache):
            return False
        _refreshing = True
    try:
        from . import http
        raw = http.download_bytes(DATA_URL, proxy=config.proxy_for("bangumi"), timeout=180,
                                  max_bytes=40 * 1024 * 1024)
        data = _index(raw)
        if not data.get("items"):
            raise ValueError("数据里没有条目")
        with _lock:
            _cache = data
            _last_success = time.time()
            _last_error = ""
        _save_disk(data)
        logger.info("更新时刻数据已刷新：%d 部番（来源 bangumi-data，每天刷新一次）", data.get("count", 0))
        return True
    except Exception as e:                                  # noqa: BLE001
        with _lock:
            _last_error = str(e)[:200]
        logger.warn("更新时刻数据刷新失败（继续用旧数据）：%s", e)
        return False
    finally:
        with _lock:
            _refreshing = False


def is_stale(data: Optional[dict] = None, *, hours: Optional[float] = None) -> bool:
    data = data if data is not None else load()
    if not data:
        return True
    hours = float(config.get("airtime.refresh_hours", 24) or 24) if hours is None else hours
    return (time.time() - float(data.get("updated") or 0)) > hours * 3600


def load() -> Optional[dict]:
    """读缓存（内存 → 磁盘）。第一次调用会尝试从磁盘载入。"""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_disk()
        return _cache


def ensure_fresh_async() -> None:
    """
    需要刷新就在后台线程里刷（接口调用路径上永不阻塞）。
    服务启动时调一次；之后每次查询发现过期也会调。
    """
    if not config.get("airtime.enabled", True):
        return
    if not is_stale():
        return
    with _lock:
        if _refreshing:
            return
    threading.Thread(target=refresh, kwargs={"force": True}, name="airtime-refresh",
                     daemon=True).start()


def for_subject(subject_id, total_episodes: int = 0) -> Optional[dict]:
    """某个番剧的更新时刻（含界面文案）。没有数据返回 None。"""
    if not config.get("airtime.enabled", True) or not subject_id:
        return None
    ensure_fresh_async()
    data = load()
    if not data:
        return None
    item = (data.get("items") or {}).get(str(int(subject_id)))
    if not item:
        return None
    info = describe(item, total_episodes=total_episodes)
    if not info:
        return None
    info["source"] = "bangumi-data"
    info["updated"] = int(data.get("updated") or 0)
    info["stale"] = is_stale(data)
    return info


def attach(subject_id, station: str = "", total_episodes: int = 0) -> dict:
    """
    给接口用：把界面要的字段拼好（含「日本时间 / 电视台 / 数据来源」的悬浮说明，
    以及「已完结」判断 —— 完结的番不再显示假的「下次更新」）。
    station 来自 Bangumi infobox 的「播放电视台」（bangumi-data 里没有电视台）。
    """
    info = for_subject(subject_id, total_episodes=total_episodes)
    if not info:
        return {}
    updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.get("updated") or 0))
    tip_lines = []
    if info.get("aired_ts"):
        ep = f"第 {info['episode_no']} 集" if info.get("episode_no") else "最新一集"
        tip_lines.append(f"已更新：{ep} · {info.get('aired_full') or info.get('aired_text')}")
    if info.get("finished"):
        # 已完结：不再给「下一次更新」，只说明最后一集
        tip_lines.append(f"已完结：{info.get('end_text') or '最后一集已播完'}")
    else:
        tip_lines.append(f"下次更新：{info['next_full']} · 北京时间")
        tip_lines.append(f"日本时间：{info['jst_text'].split('·')[0].strip()}")
    # 电视台来自 Bangumi 条目（bangumi-data 里没有这个字段）；个别番剧 Bangumi 没收录就如实写
    tip_lines.append(f"电视台：{station or 'Bangumi 未收录'}")
    tip_lines.append(f"数据来源：bangumi-data（每天刷新，更新于 {updated}）")
    if info.get("stale"):
        tip_lines.append("（缓存已过期，正在后台刷新）")
    info["station"] = station
    info["tip"] = "\n".join(tip_lines)
    return info


def status() -> dict:
    """给 /api/status：缓存状态（界面右上角/设置页排障用）。"""
    data = load() or {}
    return {
        "enabled": bool(config.get("airtime.enabled", True)),
        "count": int(data.get("count") or 0),
        "updated": int(data.get("updated") or 0),
        "updated_text": time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("updated") or 0))
        if data.get("updated") else "",
        "stale": is_stale(data or None),
        "refreshing": _refreshing,
        "error": _last_error,
        "path": CACHE_PATH,
        "source": data.get("source") or DATA_URL,
    }
