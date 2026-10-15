# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
磁盘缓存（JSON 文件，标准库实现）。

用途与策略：
- Bangumi 用户信息 / 在看收藏：TTL 15 分钟，命中即秒回，过期后后台线程刷新（stale-while-revalidate）
- 每部番剧的搜索结果：TTL 由配置决定（默认 90 分钟），"拉取在看番剧"后自动预热全部番剧
- 写入原子（tmp + os.replace），读取失败一律当未命中，绝不影响主流程
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable, Optional

from . import config, logger

_lock = threading.RLock()
_mem: dict[str, tuple[float, Any]] = {}          # key -> (存入时间, 值)
_refreshing: set[str] = set()

CACHE_DIR = os.path.join(config.DATA_DIR, "cache")


def ensure_dir() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return CACHE_DIR


def _path(key: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in key)
    return os.path.join(CACHE_DIR, f"{safe}.json")


def enabled() -> bool:
    return bool(config.get("cache.enabled", True))


def get(key: str, ttl: float) -> Optional[Any]:
    """
    读取缓存。命中且未过期返回 value，否则返回 None。
    内存优先，其次磁盘。
    """
    if not enabled():
        return None
    now = time.time()
    with _lock:
        hit = _mem.get(key)
    if hit is not None:
        ts, value = hit
        if ttl <= 0 or now - ts < ttl:
            return value
        return None
    try:
        with open(_path(key), "r", encoding="utf-8") as f:
            disk = json.load(f)
        ts = float(disk.get("ts") or 0)
        value = disk.get("value")
    except (OSError, ValueError, TypeError):
        return None
    with _lock:
        _mem[key] = (ts, value)
    if ttl <= 0 or now - ts < ttl:
        return value
    return None


def get_stale(key: str) -> tuple[Optional[Any], float]:
    """读取缓存（忽略 TTL），返回 (值, 存入时间戳)。用于 stale-while-revalidate。"""
    with _lock:
        hit = _mem.get(key)
    if hit is not None:
        return hit[1], hit[0]
    try:
        with open(_path(key), "r", encoding="utf-8") as f:
            disk = json.load(f)
        ts = float(disk.get("ts") or 0)
        value = disk.get("value")
        with _lock:
            _mem[key] = (ts, value)
        return value, ts
    except (OSError, ValueError, TypeError):
        return None, 0.0


def set(key: str, value: Any) -> None:      # noqa: A001 - 与 get 对称，语义清晰
    """写入缓存（内存 + 磁盘）。"""
    if not enabled():
        return
    now = time.time()
    with _lock:
        _mem[key] = (now, value)
    try:
        ensure_dir()
        p = _path(key)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": now, "value": value}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except (OSError, TypeError, ValueError) as e:
        logger.debug("写缓存失败 %s: %s", key, e)


def delete(key: str) -> None:
    with _lock:
        _mem.pop(key, None)
    try:
        os.remove(_path(key))
    except OSError:
        pass


def clear(prefix: str = "") -> int:
    """
    清空（可选前缀）缓存，返回删除的文件数。
    前缀会按文件名规则做同样的净化（key 里的 ':' 会变成 '_'），
    因此既支持传 'search:' 也支持传净化后的 'search_'。
    """
    n = 0
    raw = prefix or ""
    sane = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in raw)
    # 内存键用原始前缀比较；文件名用净化后的前缀比较（两者都试，避免用户写法差异）
    with _lock:
        for k in [k for k in _mem if not raw or k.startswith(raw) or k.startswith(sane)]:
            _mem.pop(k, None)
    if os.path.isdir(CACHE_DIR):
        for name in os.listdir(CACHE_DIR):
            if not name.endswith(".json"):
                continue
            if raw and not (name.startswith(sane) or name.startswith(raw)):
                continue
            try:
                os.remove(os.path.join(CACHE_DIR, name))
                n += 1
            except OSError:
                pass
    return n


def cached(key: str, ttl: float, producer: Callable[[], Any],
           background_refresh: bool = True, refresh_ttl: Optional[float] = None) -> tuple[Any, bool, float]:
    """
    带缓存的取值：
    1) 命中且新鲜 -> 直接返回 (值, True, 年龄)
    2) 有旧值但过期 -> 立即返回旧值，并后台刷新（stale-while-revalidate），避免界面等待
    3) 无缓存 -> 同步执行 producer 并写入缓存

    返回 (值, 是否来自缓存, 缓存年龄秒)。producer 抛错时向上抛（调用方决定降级）。
    """
    ttl = float(ttl)
    stale_value, ts = get_stale(key)
    age = (time.time() - ts) if ts else 0.0

    if stale_value is not None and ttl > 0 and age < ttl:
        return stale_value, True, age

    if stale_value is not None and background_refresh:
        _spawn_refresh(key, ttl, producer, refresh_ttl)
        return stale_value, True, age

    value = producer()
    set(key, value)
    return value, False, 0.0


def _spawn_refresh(key: str, ttl: float, producer: Callable[[], Any], refresh_ttl: Optional[float]) -> None:
    with _lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def work():
        try:
            value = producer()
            set(key, value)
            logger.debug("后台刷新缓存成功：%s", key)
        except Exception as e:                      # noqa: BLE001 - 后台任务不能抛
            logger.warn("后台刷新缓存失败（继续用旧数据）：%s -> %s", key, e)
        finally:
            with _lock:
                _refreshing.discard(key)

    threading.Thread(target=work, name=f"cache-refresh-{key[:24]}", daemon=True).start()


# --------------------------------------------------------------------------- #
# 针对本项目的语义化封装
# --------------------------------------------------------------------------- #
COLLECTIONS_KEY = "bangumi:collections:doing"
ME_KEY = "bangumi:me"


def search_key(subject_id: int, variant: str = "") -> str:
    """
    搜索缓存的键。

    variant 用于区分「同一部番剧的不同搜索口径」：
    - 空字符串 = 不限定字幕组的全量搜索（预热时写的就是这份）
    - 非空 = 带字幕组限定的搜索，结果集不同，必须分开缓存，
      否则「限定某字幕组」会命中全量缓存，用户会看到别的组的资源（踩过这个坑）
    """
    base = f"search:{int(subject_id)}"
    return f"{base}:{variant}" if variant else base


def token_fingerprint(token: str) -> str:
    """token 指纹：token 没变就继续用同一份缓存（用户要求）。"""
    import hashlib
    t = (token or "").strip()
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:12] if t else "none"


def collections_ttl() -> float:
    return float(config.get("cache.collections_ttl_minutes", 15)) * 60


def search_ttl() -> float:
    return float(config.get("cache.search_ttl_minutes", 90)) * 60


def stats() -> dict:
    """缓存概况，供 UI 显示。"""
    files = []
    if os.path.isdir(CACHE_DIR):
        for name in sorted(os.listdir(CACHE_DIR)):
            if not name.endswith(".json"):
                continue
            p = os.path.join(CACHE_DIR, name)
            try:
                st = os.stat(p)
                files.append({"key": name[:-5], "size": st.st_size, "mtime": st.st_mtime})
            except OSError:
                continue
    now = time.time()
    return {
        "dir": CACHE_DIR,
        "count": len(files),
        "bytes": sum(f["size"] for f in files),
        "items": [
            {
                "key": f["key"],
                "size": f["size"],
                "age_seconds": int(now - f["mtime"]),
            }
            for f in sorted(files, key=lambda x: -x["mtime"])[:50]
        ],
    }
