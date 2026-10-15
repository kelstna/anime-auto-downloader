# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
qBittorrent 不在线时的「待下载队列」。

用户场景（原文）：番剧更新 → 要下载 → qBittorrent 没开 → 下载不了 → 之后打开 qBittorrent
也不会把那几集补上。期望：**先把资源信息存下来，qBittorrent 恢复连接后自动补下载**。

为什么必须自己存一条记录，而不是等下一轮重新搜索：
站点搜索结果会滚动（第一页按做种数/时间排），几小时后再搜未必还搜得到那一集；
而且 qBittorrent 关着的时候每一轮都白搜一遍。把 magnet 存下来，恢复后直接推送最可靠。

存储：`data/pending.json`（原子写），结构
    {"version": 1, "updated": 1790..., "state": {...}, "items": [ {...}, ... ]}
每条 item 就是一条「该下但还没送进 qBittorrent」的资源，字段见 `make_item()`。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Optional

from . import config, logger

VERSION = 1
_LOCK = threading.RLock()
_CACHE: Optional[dict[str, Any]] = None


def _path() -> str:
    return os.path.join(config.DATA_DIR, "pending.json")


def _empty() -> dict[str, Any]:
    return {
        "version": VERSION,
        "updated": 0.0,
        "state": {
            "last_error": "",       # 最近一次失败原因（qBittorrent 未连接时写入）
            "last_error_at": 0.0,
            "last_try": 0.0,        # 最近一次尝试补下载
            "last_ok": 0.0,         # 最近一次补下载成功
            "recovered_at": 0.0,    # 最近一次「从失败恢复到成功」的时刻（界面提示用）
            "flushed_total": 0,     # 累计补下载成功多少集
        },
        "items": [],
    }


def _read() -> dict[str, Any]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        data = _empty()
        try:
            if os.path.exists(_path()):
                with open(_path(), "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
                if isinstance(raw.get("items"), list):
                    data["items"] = [i for i in raw["items"] if isinstance(i, dict) and i.get("magnet")]
                if isinstance(raw.get("state"), dict):
                    data["state"].update(raw["state"])
                data["updated"] = float(raw.get("updated") or 0)
        except (OSError, ValueError) as e:
            logger.warn("读取待下载队列失败（按空队列处理）：%s", e)
        _CACHE = data
        return data


def _write(data: dict[str, Any]) -> None:
    global _CACHE
    with _LOCK:
        config.ensure_dirs()
        data["version"] = VERSION
        data["updated"] = time.time()
        tmp = _path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, _path())
        except OSError as e:
            logger.warn("保存待下载队列失败：%s", e)
            return
        _CACHE = data


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #
def items() -> list[dict]:
    """待下载项（按加入时间从早到晚，先补旧的）。"""
    out = [dict(i) for i in _read()["items"]]
    out.sort(key=lambda x: float(x.get("created") or 0))
    return out


def count() -> int:
    return len(_read()["items"])


def state() -> dict:
    return dict(_read()["state"])


def for_subject(subject_id: int) -> list[dict]:
    return [dict(i) for i in _read()["items"] if int(i.get("subject_id") or 0) == int(subject_id)]


def count_for(subject_id: int) -> int:
    return len(for_subject(subject_id))


def summary() -> dict:
    """给界面/接口用的汇总（不含 magnet，避免把磁力链撒到各处）。"""
    data = _read()
    rows = []
    for i in data["items"]:
        rows.append({
            "id": i.get("id"),
            "subject_id": i.get("subject_id"),
            "name": i.get("name") or "",
            "episode": i.get("episode"),
            "title": i.get("title") or "",
            "group": i.get("group") or "",
            "source": i.get("source") or "",
            "size": i.get("size") or "",
            "reason": i.get("reason") or "",
            "created": float(i.get("created") or 0),
            "attempts": int(i.get("attempts") or 0),
            "last_error": i.get("last_error") or "",
            "last_try": float(i.get("last_try") or 0),
        })
    rows.sort(key=lambda x: x["created"])
    st = dict(data["state"])
    subjects = {int(r["subject_id"]) for r in rows if r.get("subject_id")}
    st.update({
        "count": len(rows),
        "subjects": len(subjects),
        "items": rows,
        "oldest": rows[0]["created"] if rows else 0,
    })
    return st


# --------------------------------------------------------------------------- #
# 写
# --------------------------------------------------------------------------- #
def make_item(*, subject_id: int, name: str, folder: str, episode: Optional[int],
              title: str, magnet: str, reason: str = "自动追番", infohash: str = "",
              source: str = "", group: str = "", resolution: str = "", size: str = "",
              error: str = "") -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "subject_id": int(subject_id),
        "name": name or "",
        "folder": folder or "",
        "episode": int(episode) if episode else None,
        "title": title or "",
        "magnet": magnet or "",
        "infohash": (infohash or "").lower(),
        "source": source or "",
        "group": group or "",
        "resolution": resolution or "",
        "size": size or "",
        "reason": reason or "",
        "created": time.time(),
        "attempts": 0,
        "last_error": error or "",
        "last_try": 0.0,
    }


def _same(item: dict, new: dict) -> bool:
    """同一条资源吗：magnet/infohash 相同，或「同一部番 + 同一集」就算重复。"""
    a = (item.get("infohash") or "").lower()
    b = (new.get("infohash") or "").lower()
    if a and b and a == b:
        return True
    if (item.get("magnet") or "") and item.get("magnet") == new.get("magnet"):
        return True
    return (int(item.get("subject_id") or 0) == int(new.get("subject_id") or 0)
            and item.get("episode") is not None
            and new.get("episode") is not None
            and int(item["episode"]) == int(new["episode"]))


def add(item: dict) -> Optional[dict]:
    """入队（自动去重）。返回真正入队的那条；重复了返回 None。"""
    cfg = config.load().get("queue", {}) or {}
    max_items = max(1, int(cfg.get("max_items", 200) or 200))
    # 0 = 不按时间清理（只有显式写 0 才有这个意思，缺省仍然是 168 小时）
    _age = cfg.get("max_age_hours", 168)
    max_age_h = 168.0 if _age is None else float(_age)
    with _LOCK:
        data = _read()
        for old in data["items"]:
            if _same(old, item):
                # 同一条已经在队列里：更新失败原因，不重复入队
                if item.get("last_error"):
                    old["last_error"] = item["last_error"]
                _write(data)
                return None
        data["items"].append(item)
        _prune(data, max_age_h)
        # 队列太长时丢掉最老的（避免磁盘无限增长）
        while len(data["items"]) > max_items:
            dropped = data["items"].pop(0)
            logger.warn("待下载队列已满（%d 条），丢弃最早的一条：%s", max_items, dropped.get("title"))
        _write(data)
        logger.info("qBittorrent 暂不可用，已加入待下载队列：第 %s 集 %s",
                    item.get("episode") or "?", (item.get("title") or "")[:60])
        return item


def _prune(data: dict, max_age_hours: float) -> None:
    if max_age_hours <= 0:
        return
    limit = time.time() - max_age_hours * 3600
    keep = [i for i in data["items"] if float(i.get("created") or 0) >= limit]
    if len(keep) != len(data["items"]):
        logger.warn("待下载队列有 %d 条超过 %.0f 小时，已清理", len(data["items"]) - len(keep), max_age_hours)
        data["items"] = keep


def prune() -> int:
    """按配置清理过期项，返回清理数量。"""
    cfg = config.load().get("queue", {}) or {}
    _age = cfg.get("max_age_hours", 168)
    max_age_h = 168.0 if _age is None else float(_age)
    with _LOCK:
        data = _read()
        before = len(data["items"])
        _prune(data, max_age_h)
        if len(data["items"]) != before:
            _write(data)
        return before - len(data["items"])


def remove(item_id: str) -> bool:
    with _LOCK:
        data = _read()
        left = [i for i in data["items"] if i.get("id") != item_id]
        if len(left) == len(data["items"]):
            return False
        data["items"] = left
        _write(data)
        return True


def remove_subject(subject_id: int, episode: Optional[int] = None) -> int:
    """删掉某部番（或某一集）的待下载项，返回删掉几条。"""
    with _LOCK:
        data = _read()
        left = []
        removed = 0
        for i in data["items"]:
            same_sub = int(i.get("subject_id") or 0) == int(subject_id)
            same_ep = episode is None or (i.get("episode") is not None and int(i["episode"]) == int(episode))
            if same_sub and same_ep:
                removed += 1
            else:
                left.append(i)
        if removed:
            data["items"] = left
            _write(data)
        return removed


def clear() -> int:
    with _LOCK:
        data = _read()
        n = len(data["items"])
        if n:
            data["items"] = []
            _write(data)
        return n


def mark_try(item_id: str, error: str = "") -> None:
    with _LOCK:
        data = _read()
        st = data["state"]
        now = time.time()
        # 只记状态（item_id 为空）= 巡检发现 qBittorrent 仍然没连上：
        # 同一条错误 5 分钟内不重复写盘，免得队列空转时每分钟改一次文件
        if not item_id and error and st.get("last_error") == error \
                and now - float(st.get("last_error_at") or 0) < 300:
            return
        for i in data["items"]:
            if i.get("id") == item_id:
                i["attempts"] = int(i.get("attempts") or 0) + 1
                i["last_try"] = now
                if error:
                    i["last_error"] = error
                break
        st["last_try"] = now
        if error:
            st["last_error"] = error
            st["last_error_at"] = now
        _write(data)


def mark_ok(flushed: int) -> None:
    """补下载成功后记录状态（recovered_at 只在这一刻写，界面据此提示「已恢复」）。"""
    with _LOCK:
        data = _read()
        st = data["state"]
        now = time.time()
        prev_error = float(st.get("last_error_at") or 0)
        if flushed:
            st["last_ok"] = now
            st["flushed_total"] = int(st.get("flushed_total") or 0) + flushed
            if prev_error:
                st["recovered_at"] = now
            st["last_error"] = ""
            st["last_error_at"] = 0.0
        _write(data)


def reset_cache() -> None:
    """测试用：丢掉内存缓存，强制下次从磁盘读。"""
    global _CACHE
    with _LOCK:
        _CACHE = None
