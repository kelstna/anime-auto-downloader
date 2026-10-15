# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
搜索关键词的「学习记录」：哪个关键词在哪个站点真的搜到过资源。

为什么需要它（用户实测的坑）：
    「黑暗召唤师在地下恋爱中」的 Bangumi 别名里，`Dark Samon atodekiteiru`、
    `Dark Summoner to Dekiteiru` 看起来都像罗马字，机器分不出哪个是对的 ——
    实际只有 `Dark Summoner to Dekiteiru` 能搜到一堆资源，而它恰好排在候选表第 5 位，
    被「每站只试 4 个关键词」的上限截断了，最后只搜到 1 条。

结论：**光靠规则猜哪个关键词对是猜不准的，得靠实测**。于是：
    ① 关键词预算放大（默认 8 个），结果不够就先别收手（见 engine._ALIAS_LIMIT / search.max_keyword_variants）
    ② 每搜一次就把「站点 + 关键词 + 命中条数」记下来（本模块）
    ③ 下次搜同一部番时，把**搜到过资源的关键词排在最前面**（engine 会把它们插到候选表最前），
       并且命中数从高到低排 —— 排在前面的关键词一定会被试，所以好关键词不会再被上限截掉

记录按 subject_id 分开存（同一部番换个站点也能用），最多保留 600 部番，命中数为 0 的不记。
文件：data/keyword_stats.json（原子写；读写异常一律吞掉，绝不能影响搜索）
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Optional

from . import config, logger

_lock = threading.RLock()
_STATS_PATH = os.path.join(config.DATA_DIR, "keyword_stats.json")
_MAX_SUBJECTS = 600
_MAX_KEYWORDS_PER_SUBJECT = 40
_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        data: dict = {}
        try:
            if os.path.exists(_STATS_PATH):
                with open(_STATS_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
        except (OSError, ValueError) as e:
            logger.warn("关键词学习记录读取失败（忽略）：%s", e)
        _cache = data
        return data


def _save(data: dict) -> None:
    tmp = _STATS_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(_STATS_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _STATS_PATH)
    except OSError as e:
        logger.warn("关键词学习记录写入失败（忽略）：%s", e)


def _entry(data: dict, subject_id) -> dict:
    key = str(int(subject_id))
    ent = data.get(key)
    if not isinstance(ent, dict):
        ent = {}
        data[key] = ent
    ent.setdefault("kw", {})          # {关键词: {"hits": n, "src": {站点: 条数}, "time": ts}}
    return ent


def _last_used(ent: dict) -> int:
    items = (ent or {}).get("kw") or {}
    return max((int((v or {}).get("time") or 0) for v in items.values()), default=0)


def record(subject_id, source_id: str, keyword: str, hits: int) -> None:
    """记一次搜索结果：这个关键词在这个站点搜到几条。hits<=0 不记（没必要留垃圾）。"""
    kw = (keyword or "").strip()
    if not kw or not subject_id or int(hits or 0) <= 0:
        return
    with _lock:
        data = _load()
        ent = _entry(data, subject_id)
        items = ent.setdefault("kw", {})
        cur = items.get(kw)
        if not isinstance(cur, dict):
            cur = {"hits": 0, "src": {}}
        src = cur.get("src") if isinstance(cur.get("src"), dict) else {}
        src[str(source_id)] = int(hits)
        cur["src"] = src
        cur["hits"] = sum(int(v or 0) for v in src.values())
        cur["time"] = int(time.time())
        items[kw] = cur
        # 控制体积：每部番只留命中数最高的若干关键词；番剧数也封顶（按最近使用时间淘汰）
        if len(items) > _MAX_KEYWORDS_PER_SUBJECT:
            keep = sorted(items.items(), key=lambda kv: -int((kv[1] or {}).get("hits", 0)))
            ent["kw"] = dict(keep[:_MAX_KEYWORDS_PER_SUBJECT])
        if len(data) > _MAX_SUBJECTS:
            recent = sorted(data.items(), key=lambda kv: -_last_used(kv[1] if isinstance(kv[1], dict) else {}))
            trimmed = dict(recent[:_MAX_SUBJECTS])
            data.clear()
            data.update(trimmed)
        _save(data)


def learned(subject_id, source_id: str = "") -> list[str]:
    """
    这部番「以前搜到过资源」的关键词，按命中数从高到低。
    source_id 非空时，优先返回该站点搜到过的，其次才是别的站点搜到过的。
    """
    if not subject_id:
        return []
    with _lock:
        data = _load()
        ent = data.get(str(int(subject_id)))
        if not isinstance(ent, dict):
            return []
        items = ent.get("kw") or {}
        rows = []
        for kw, info in items.items():
            if not isinstance(info, dict):
                continue
            hits = int(info.get("hits") or 0)
            if hits <= 0:
                continue
            src = info.get("src") or {}
            site_hits = int(src.get(source_id) or 0) if source_id else 0
            rows.append((site_hits, hits, str(kw)))
        rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
        return [r[2] for r in rows]


def signature(subject_id) -> str:
    """
    学习结果指纹（进缓存键）：关键词学习结果变了，旧的搜索结果缓存就该作废重搜。
    只跟「学到了哪些关键词」有关，条数变化不影响（避免频繁失效）。
    """
    kws = learned(subject_id)
    if not kws:
        return ""
    return hashlib.sha1("|".join(kws).encode("utf-8")).hexdigest()[:10]


def clear() -> None:
    """清空学习记录（测试 / 排障用）。"""
    global _cache
    with _lock:
        _cache = {}
        try:
            if os.path.exists(_STATS_PATH):
                os.remove(_STATS_PATH)
        except OSError:
            pass


def stats() -> dict:
    """概览：学习到了多少部番 / 多少关键词（给状态接口和排障用）。"""
    with _lock:
        data = _load()
        subjects = 0
        keywords = 0
        for ent in data.values():
            items = (ent or {}).get("kw") or {}
            if items:
                subjects += 1
                keywords += len(items)
        return {"subjects": subjects, "keywords": keywords, "path": _STATS_PATH}
