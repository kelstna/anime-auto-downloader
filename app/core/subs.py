# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
订阅存储：data/subscriptions.json，线程安全 + 原子写入。
"""
from __future__ import annotations

import json
import glob
import os
import shutil
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from . import config, logger
from .util import sanitize_name

_SUBS_PATH = os.path.join(config.DATA_DIR, "subscriptions.json")
_lock = threading.RLock()
_cache: Optional[list["Subscription"]] = None

# 初始下载策略
INITIAL_LATEST = "latest"      # 只下载最新一集
INITIAL_ALL = "all"            # 补齐已播出的所有集
INITIAL_NONE = "none"          # 不下载历史，仅追新


@dataclass
class Subscription:
    subject_id: int
    name: str = ""                    # 简体名（文件夹名也用这个）
    name_original: str = ""
    cover: str = ""
    group: str = ""                   # 选定字幕组（组名，空=不限）
    sub_group: str = ""               # 站点限定的字幕组，形如 "dmhy::ANi"（空=不限站点）
    custom_keyword: str = ""          # 手动搜索关键词（空=按番剧名/别名自动搜索）
    episode_offset: int = 0           # 发布组用系列连续编号时的换算偏移（49 → 第 1 集）
    team_id: str = ""                 # 动漫花园 team_id
    aliases: list[str] = field(default_factory=list)
    resolution: str = ""              # 分辨率偏好（空=不限）
    lang: str = ""                    # 字幕语言偏好 chs/cht/both/jp（空=不限）——订阅时就定下来，自动追新也守它
    source_ids: list[str] = field(default_factory=list)   # 限定资源站（空=全部）
    folder: str = ""                  # 下载目录（绝对路径）
    total_episodes: int = 0
    last_episode: int = 0             # 已下载到的集数
    downloaded: dict[str, str] = field(default_factory=dict)  # infohash -> 标题
    history: list[dict] = field(default_factory=list)         # 下载记录
    enabled: bool = True
    initial_mode: str = INITIAL_LATEST
    primed: bool = False               # 首次检查是否已完成（决定初始下载策略何时生效）
    created_at: float = field(default_factory=time.time)
    last_check: float = 0.0
    last_result: str = ""
    last_new: int = 0

    # ---------------------------------------------------------------- #
    @property
    def display_name(self) -> str:
        return self.name or self.name_original or f"subject-{self.subject_id}"

    @property
    def safe_folder(self) -> str:
        return sanitize_name(self.display_name)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["display_name"] = self.display_name
        d["downloaded_count"] = len(self.downloaded)
        return d

    def add_history(self, entry: dict) -> None:
        self.history.insert(0, entry)
        del self.history[200:]          # 只保留最近 200 条

    def mark_downloaded(self, infohash: str, title: str, episode: Optional[int]) -> None:
        if infohash:
            self.downloaded[infohash] = title[:200]
        if episode and episode > self.last_episode:
            self.last_episode = episode


def _load_raw() -> list[dict]:
    if not os.path.exists(_SUBS_PATH):
        return []
    try:
        with open(_SUBS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warn("订阅文件损坏，已忽略：%s", e)
        return []


def all_subs(force: bool = False) -> list[Subscription]:
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        subs: list[Subscription] = []
        for raw in _load_raw():
            try:
                known = {k: v for k, v in raw.items() if k in Subscription.__dataclass_fields__}
                subs.append(Subscription(**known))
            except (TypeError, ValueError) as e:
                logger.warn("订阅记录无效，已跳过：%s", e)
        _cache = subs
        return subs


def save_all(subs: list[Subscription]) -> None:
    global _cache
    with _lock:
        config.ensure_dirs()
        tmp = _SUBS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in subs], f, ensure_ascii=False, indent=2)
        os.replace(tmp, _SUBS_PATH)
        _cache = subs


def get(subject_id: int) -> Optional[Subscription]:
    for s in all_subs():
        if s.subject_id == subject_id:
            return s
    return None


def _snapshot(tag: str = "") -> str:
    """改动订阅库前留一份快照（订阅数很少，文件也就几十 KB）。

    为什么需要：批量删除时一旦点错、或者测试脚本误连到生产实例，用户攒了很久的
    订阅会瞬间清空。留一份带时间戳的备份，出问题还能手工捞回来。
    """
    try:
        if not os.path.exists(_SUBS_PATH):
            return ""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = f"{_SUBS_PATH}.{tag}{stamp}.bak" if tag else f"{_SUBS_PATH}.{stamp}.bak"
        shutil.copy2(_SUBS_PATH, dst)
        # 只保留最近 20 份，避免越积越多
        backups = sorted(glob.glob(f"{_SUBS_PATH}.*.bak"))
        for old in backups[:-20]:
            try:
                os.remove(old)
            except OSError:
                pass
        return dst
    except OSError:
        return ""


def upsert(sub: Subscription) -> Subscription:
    with _lock:
        subs = all_subs()
        for i, s in enumerate(subs):
            if s.subject_id == sub.subject_id:
                # 保留已有下载记录
                sub.downloaded = {**s.downloaded, **sub.downloaded}
                sub.history = sub.history or s.history
                sub.last_episode = max(s.last_episode, sub.last_episode)
                sub.created_at = s.created_at
                subs[i] = sub
                break
        else:
            subs.append(sub)
        save_all(subs)
        return sub


def remove(subject_id: int) -> bool:
    _snapshot("before-delete-")
    with _lock:
        subs = all_subs()
        left = [s for s in subs if s.subject_id != subject_id]
        if len(left) == len(subs):
            return False
        save_all(left)
        return True


def update_fields(subject_id: int, **fields) -> Optional[Subscription]:
    with _lock:
        subs = all_subs()
        for s in subs:
            if s.subject_id == subject_id:
                for k, v in fields.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                save_all(subs)
                return s
    return None


def default_folder(name: str) -> str:
    return os.path.normpath(os.path.join(config.get("download.root", r"D:\Anime"), sanitize_name(name)))
