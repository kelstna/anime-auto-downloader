# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
配置管理：config.json 持久化，支持默认值合并与原子写入。
"""
from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../app
PROJECT_ROOT = os.path.dirname(APP_ROOT)                                # 项目根目录
# 数据目录可用环境变量覆盖（测试/多实例隔离用，例如 ANIME_DATA_DIR=D:\tmp\anime-data）
DATA_DIR = os.environ.get("ANIME_DATA_DIR") or os.path.join(PROJECT_ROOT, "data")
WEB_DIR = os.path.join(APP_ROOT, "web")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 3,    # Bangumi
    "bangumi_token": "",
    # 番剧详情接口连续失败多少次就停止补齐详情（网络不通时避免逐部等超时）
    "bangumi": {"detail_fail_limit": 3},
    # 本地服务
    "server": {
        "host": "127.0.0.1",
        "port": 7788,
        "allow_lan": False,
        "open_browser_on_start": True,
    },
    # 代理：只作用于 Bangumi 与资源网站，不作用于 qBittorrent
    "proxy": {
        "enabled": False,
        "url": "http://127.0.0.1:7890",
        "for_bangumi": True,
        "for_sources": True,
    },
    # qBittorrent（qB 自身的连接不走代理）
    "qbittorrent": {
        "base_url": "http://127.0.0.1:8080",
        "username": "admin",
        "password": "",
        "category": "Bangumi",
        "tags": "自动追番",
        # 番剧目录本身已经是「一部番一个文件夹」，所以默认不再额外包一层，
        # 与在 qBittorrent 里手动添加磁链的行为一致
        "create_subfolder": False,
        "start_paused": False,
    },
    # 资源网站优先级
    "sources": [
        {"id": "dmhy", "name": "动漫花园", "enabled": True, "base": "https://share.dmhy.org", "priority": 1},
        {"id": "kisssub", "name": "爱恋动漫", "enabled": True, "base": "https://www.kisssub.org", "priority": 2},
        {"id": "nyaa", "name": "Nyaa", "enabled": True, "base": "https://nyaa.si", "priority": 3},
    ],
    # 下载
    "download": {
        "root": r"D:\Anime",
        "folder_mode": "name_cn",          # name_cn | name
        "preferred_resolution": "1080p",   # 已废弃：不再参与任何排序/筛选（严格按订阅筛选）
        "min_seeders": 0,
        "exclude_batch_on_subscribe": True,
    },
    # 追番
    "subscription": {
        "enabled": True,
        "interval_minutes": 30,
        "initial_mode": "latest",          # latest | all
        "max_episodes_per_round": 3,
        "search_group_first": True,        # 先「字幕组+番剧名」，搜不到再用番剧名
    },
    "search": {
        # 关键词预算：结果不够时多试几个写法（实测有番剧正确罗马字排第 5 位，4 个会被截断）
        "max_keyword_variants": 10,
        "per_source_limit": 100,
        "timeout_seconds": 20,
    },
    # 缓存：token 未变时复用上次结果，并在后台自动更新（用户要求）
    "cache": {
        "enabled": True,
        "collections_ttl_minutes": 15,     # 在看列表新鲜期，超期先回旧值再后台刷新
        "search_ttl_minutes": 90,          # 每部番剧搜索结果的新鲜期
        "auto_search_on_fetch": True,      # 拉取在看后自动搜索全部番剧资源并缓存
        "auto_search_concurrency": 3,      # 并发站点数（别调太高，避免被站点限流）
    },
    # 番剧更新时刻（来自 bangumi-data）：缓存到 data/airtimes.json，每天后台刷新一次
    "airtime": {
        "enabled": True,
        "refresh_hours": 24,               # 缓存新鲜期；过期后先用旧数据、后台刷新
    },
    # qBittorrent 掉线时的待下载队列：先把资源存下来，恢复连接后自动补下载
    # （用户场景：番剧更新时 qBittorrent 没开 → 之后打开也不会补，现在会自动补上）
    "queue": {
        "enabled": True,
        "retry_seconds": 60,               # 队列非空时多久探一次 qBittorrent
        "max_items": 200,                  # 队列上限（超了丢最早的）
        "max_age_hours": 168,              # 超过 7 天的待下载项自动清理
        "max_per_flush": 5,                # 每次补下载最多几条（避免一次性灌爆 qB）
    },
    "ui": {
        "theme": "dark",
    },
}

_lock = threading.RLock()
_cache: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _migrate(cfg: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    r"""
    配置迁移：把老版本遗留的值纠正为新的合理默认。

    为什么需要：`_deep_merge(DEFAULT_CONFIG, raw)` 会让**已存在的持久化值覆盖新默认值**，
    所以「把 DEFAULT_CONFIG 里的默认改成 false」对已经跑过的机器不生效。
    典型例子：qbittorrent.create_subfolder 早期默认 true，导致番剧目录里多包一层
    `D:\Anime\番剧\[组] 番剧 - 01 [1080P]...\...mp4`；用户明确不要这层，这里强制纠正。

    返回 (配置, 是否有改动)。调用方负责在改动时落盘。
    """
    changed = False
    ver = int(cfg.get("version") or 1)

    if ver < 2:
        qb = cfg.get("qbittorrent")
        if isinstance(qb, dict) and qb.get("create_subfolder") is not False:
            qb["create_subfolder"] = False
            changed = True
        ver = 2
        cfg["version"] = ver
        changed = True

    if ver < 3:
        # v3：关键词预算从 4 提到 10。实测有番剧**正确的罗马字排在第 5 位**
        # （黑暗召唤师在地下恋爱中 → `Dark Summoner to Dekiteiru`），只试 4 个就被截断，
        # 结果只搜到 1 条。结果不够时多试几个写法，热门番仍然靠「凑够 5 条就停」省请求。
        search = cfg.get("search")
        if isinstance(search, dict) and int(search.get("max_keyword_variants") or 0) < 10:
            search["max_keyword_variants"] = 10
            changed = True
        ver = 3
        cfg["version"] = ver
        changed = True

    return cfg, changed


def _log(msg: str, *args) -> None:
    """延迟导入 logger，避免 config <-> logger 循环依赖。"""
    try:
        from . import logger
        logger.info(msg, *args)
    except Exception:      # noqa: BLE001 - 日志失败绝不影响配置读取
        if args:
            try:
                msg = msg % args
            except (TypeError, ValueError):
                pass
        print(msg)


def load(force: bool = False) -> dict[str, Any]:
    """读取配置（带缓存 + 迁移）。"""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        ensure_dirs()
        raw: dict[str, Any] = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                raw = {}
        merged = _deep_merge(DEFAULT_CONFIG, raw)
        merged, changed = _migrate(merged)
        _cache = merged
        if changed:
            try:
                save(merged)
                _log("配置已迁移到 v%s（纠正了过期的 create_subfolder 等旧默认值）",
                     merged.get("version"))
            except OSError as e:
                _log("配置迁移落盘失败：%s", e)
        return _cache


def save(cfg: dict[str, Any]) -> dict[str, Any]:
    """原子写入配置。"""
    global _cache
    with _lock:
        merged = _deep_merge(DEFAULT_CONFIG, cfg or {})
        ensure_dirs()
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        _cache = merged
        return merged


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """深度合并写入配置。"""
    with _lock:
        return save(_deep_merge(load(), patch))


def get(path: str, default=None):
    """按 'a.b.c' 取配置项。"""
    cur: Any = load()
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def bangumi_token() -> str:
    return (get("bangumi_token") or "").strip()


def proxy_for(kind: str) -> str | None:
    """
    返回该用途应使用的代理 URL；不需要代理时返回 None。
    kind: 'bangumi' | 'sources' | 'qbittorrent'
    """
    if kind == "qbittorrent":
        return None  # 明确不代理 qBittorrent
    p = load().get("proxy", {})
    if not p.get("enabled"):
        return None
    if kind == "bangumi" and not p.get("for_bangumi", True):
        return None
    if kind == "sources" and not p.get("for_sources", True):
        return None
    url = (p.get("url") or "").strip()
    return url or None


def enabled_sources() -> list[dict]:
    srcs = [s for s in load().get("sources", []) if s.get("enabled")]
    return sorted(srcs, key=lambda s: s.get("priority", 99))
