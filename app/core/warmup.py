# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
资源预热：拉取「在看」之后，自动把每部番剧的资源搜索结果搜一遍并缓存。

为什么单独一个模块：
- 36 部番剧 × 3 个站点，如果同时打会触发站点限流，必须限并发 + 间隔
- 必须可中断、可重复触发、可查进度（UI 上要能看到「已缓存 12/36」）
- 结果落盘后，点开番剧弹窗是秒开（直接读缓存），而不是每次等 5~10 秒
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from typing import Optional

from . import bangumi, cache, config, logger
from ..sources import engine

_lock = threading.RLock()
_running = False
_stop = threading.Event()
_thread: Optional[threading.Thread] = None

#: 搜索缓存 payload 的结构版本。
#:
#: 不用手写版本号，直接取「解析/识别相关源码」的内容指纹：只要这些文件改过
#: （新增字段、改识别规则、修站点解析），旧缓存立刻作废并重搜。
#: 踩过的坑：新增「字幕语言」后旧 payload 没有 lang 键，用户在界面上看到的一直是
#: 「未标注」；后来修了 Nyaa 的解析，缓存里又缺 Nyaa 结果 —— 都是手写版本号会漏掉的情况。
_PARSER_FILES = (
    "sources/base.py", "sources/dmhy.py", "sources/kisssub.py", "sources/nyaa.py",
    "sources/engine.py", "sources/romaji.py",
    "core/util.py", "core/htmlx.py", "core/bangumi.py",   # bangumi.py 里是搜索关键词规则
)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def parser_fingerprint() -> str:
    """解析/识别相关源码的内容指纹（读不到文件就退回固定值）。"""
    h = hashlib.sha1()
    for rel in _PARSER_FILES:
        try:
            with open(os.path.join(_ROOT, *rel.split("/")), "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"missing:" + rel.encode())
    return h.hexdigest()[:12]


SEARCH_SCHEMA = parser_fingerprint()


def search_payload_ok(payload) -> bool:
    """缓存里的搜索结果是不是当前代码算出来的（源码指纹对得上）。"""
    if not isinstance(payload, dict):
        return False
    return str(payload.get("schema") or "") == SEARCH_SCHEMA

_state: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "failed": 0,
    "cached": 0,          # 命中缓存、未真正联网的数量
    "started_at": 0.0,
    "finished_at": 0.0,
    "current": "",
    "last_error": "",
}


def status() -> dict:
    with _lock:
        st = dict(_state)
    st["cache"] = cache.stats()
    return st


def search_ttl() -> float:
    return cache.search_ttl()


def cached_search(subject_id: int, variant: str = "", ttl: Optional[float] = None):
    """取某番剧的缓存搜索结果；未命中（或缓存是旧版本）返回 None。"""
    key = cache.search_key(subject_id, variant)
    if ttl is None:
        ttl = search_ttl()
    value = cache.get(key, ttl)
    return value if search_payload_ok(value) else None


def search_any_age(subject_id: int, variant: str = ""):
    """取某番剧的缓存搜索结果（忽略新鲜度），返回 (值, 年龄秒)；旧版本缓存当未命中。"""
    value, ts = cache.get_stale(cache.search_key(subject_id, variant))
    if not search_payload_ok(value):
        return None, 0.0
    age = (time.time() - ts) if ts else 0.0
    return value, age


def _run_one(subject: "bangumi.Subject", force: bool) -> tuple[bool, bool]:
    """搜索并缓存单部番剧。返回 (是否成功, 是否命中缓存)。"""
    if not force:
        # 用 cached_search 而不是 cache.get：旧版本写的 payload 必须重搜，
        # 否则新增字段/新识别规则永远生效不了（用户会一直看到旧结果）
        hit = cached_search(subject.id)
        if hit is not None:
            return True, True
    key = cache.search_key(subject.id)
    outcome = engine.search_by_subject(subject)
    payload = {
        "schema": SEARCH_SCHEMA,
        "subject_id": subject.id,
        "display_name": subject.display_name,
        "strategy": outcome.strategy,
        "elapsed": round(outcome.elapsed, 2),
        "keywords_used": outcome.keywords_used,
        "source_status": outcome.source_status,
        "groups": outcome.groups,
        "total": len(outcome.resources),
        "items": [r.to_dict() for r in outcome.resources],
        "searched_at": time.time(),
    }
    cache.set(key, payload)
    return True, False


def _loop(subjects: list, force: bool, interval: float) -> None:
    global _running
    ok = failed = cached = 0
    try:
        for idx, sub in enumerate(subjects, 1):
            if _stop.is_set():
                logger.info("资源预热被中断在第 %d/%d 部", idx, len(subjects))
                break
            with _lock:
                _state["current"] = sub.display_name
                _state["done"] = idx - 1
            try:
                success, from_cache = _run_one(sub, force)
                if success and from_cache:
                    cached += 1
                elif success:
                    ok += 1
            except Exception as e:                      # noqa: BLE001 - 单部失败不影响整体
                failed += 1
                with _lock:
                    _state["last_error"] = f"{sub.display_name}: {e}"
                logger.warn("预热失败 [%s]：%s", sub.display_name, e)
            with _lock:
                _state.update(done=idx, failed=failed, cached=cached)
            if not force and idx < len(subjects):
                # 站点礼貌间隔：避免短时间大量请求被限流
                if _stop.wait(interval):
                    break
        logger.info("资源预热完成：新搜 %d 部，命中缓存 %d 部，失败 %d 部", ok, cached, failed)
    finally:
        with _lock:
            _running = False
            _state["running"] = False
            _state["finished_at"] = time.time()
            _state["current"] = ""


def start(subjects: list, force: bool = False, interval: Optional[float] = None) -> bool:
    """
    启动预热任务（后台线程）。已有任务在跑时返回 False。
    force=True 时忽略缓存、全部重搜（配合 UI 的「强制刷新」）。
    """
    global _running, _thread
    if not subjects:
        return False
    with _lock:
        if _running:
            return False
        _running = True
        _state.update({
            "running": True, "total": len(subjects), "done": 0,
            "failed": 0, "cached": 0, "started_at": time.time(),
            "finished_at": 0.0, "current": "", "last_error": "",
        })
    _stop.clear()
    gap = float(config.get("cache.auto_search_concurrency", 3))
    delay = interval if interval is not None else max(0.2, 1.2 / max(1.0, gap))
    _thread = threading.Thread(target=_loop, args=(list(subjects), force, delay),
                               name="search-warmup", daemon=True)
    _thread.start()
    logger.info("开始预热 %d 部番剧的资源（%s）", len(subjects), "强制重搜" if force else "优先用缓存")
    return True


def stop() -> None:
    _stop.set()


def warm(subjects: list, force: bool = False) -> None:
    """便捷入口：按配置决定是否自动预热（不阻塞调用方）。"""
    if not config.get("cache.auto_search_on_fetch", True):
        return
    if not subjects:
        return
    start(subjects, force=force)
