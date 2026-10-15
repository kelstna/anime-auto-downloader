# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
本地 Web 服务（标准库 http.server）：
- 提供现代化前端页面
- 提供 REST API：Bangumi / 资源搜索 / 订阅 / qBittorrent
- 封面图代理与本地缓存（走代理设置，避免浏览器直连失败）
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import posixpath
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

from ..core import (
    airtimes, bangumi, cache, config, http, keywords as keywords_store, logger, pending,
    meta, qbittorrent, rules, subs, warmup, watcher,
)
from ..core.util import human_size, lan_ipv4_addresses, parse_episode, sanitize_name
from ..sources import engine
from ..sources.base import Resource, lang_matches, normalize_items, resolution_matches

_mimetypes_added = False
COVER_DIR = os.path.join(config.DATA_DIR, "covers")
_ALLOWED_IMAGE_HOSTS = ("lain.bgm.tv", "bgm.tv", "api.bgm.tv")


def _compute_asset_version() -> str:
    """
    静态资源版本号：取前端文件的内容哈希。
    改了 CSS/JS 版本号就变，浏览器会自动重新拉取（避免「新 JS + 旧 CSS」导致的样式崩坏）。
    """
    try:
        h = hashlib.sha1()
        for name in ("styles.css", "ui.js", "app.js"):
            p = os.path.join(config.WEB_DIR, name)
            try:
                with open(p, "rb") as f:
                    h.update(f.read())
            except OSError:
                h.update(name.encode())
        return h.hexdigest()[:10]
    except Exception:      # noqa: BLE001
        return "0"


_ASSET_VERSION = _compute_asset_version()


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


class Router:
    def __init__(self):
        self.routes: list[tuple[str, re.Pattern, Callable]] = []

    def add(self, method: str, pattern: str, handler: Callable) -> None:
        regex = re.compile("^" + pattern + "$")
        self.routes.append((method.upper(), regex, handler))

    def match(self, method: str, path: str):
        for m, regex, handler in self.routes:
            if m != method.upper():
                continue
            hit = regex.match(path)
            if hit:
                return handler, hit.groupdict()
        return None, None


router = Router()


def route(method: str, pattern: str):
    def deco(fn):
        router.add(method, pattern, fn)
        return fn
    return deco


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _subject_payload(s: bangumi.Subject) -> dict:
    return s.to_dict()


def _station_of(subject) -> str:
    """番剧的播放电视台（Bangumi infobox 的「播放电视台」），用于更新时刻的悬浮说明。"""
    info = getattr(subject, "infobox", None) or {}
    for key in ("播放电视台", "放送局", "电视台"):
        val = info.get(key)
        if isinstance(val, list):
            for x in val:
                name = (x.get("v") if isinstance(x, dict) else x) or ""
                if str(name).strip():
                    return str(name).strip()
        elif val:
            return str(val).strip()
    return ""


def _warm_stations(subject_ids: list[int]) -> None:
    """
    后台补齐番剧详情（只为拿「播放电视台」，列表接口本身不等它）。
    同一时刻只跑一个补齐线程，避免用户连点刷新时把 Bangumi 打爆。
    """
    ids = [int(i) for i in subject_ids if i]
    if not ids:
        return
    with _station_warm_lock:
        if _station_warm_state["running"]:
            return
        _station_warm_state["running"] = True

    def work() -> None:
        try:
            got = bangumi.warm_subjects(ids)
            if got:
                logger.info("已后台补齐 %d 部番剧详情（下次打开页面就能看到电视台）", len(got))
        except Exception as e:                 # noqa: BLE001 - 纯补充信息，失败不打扰
            logger.warn("后台补齐番剧详情失败（忽略）：%s", e)
        finally:
            with _station_warm_lock:
                _station_warm_state["running"] = False

    threading.Thread(target=work, name="warm-stations", daemon=True).start()


_station_warm_lock = threading.Lock()
_station_warm_state = {"running": False}


def _airtime_payload(subject_id, station: str = "", total_episodes: int = 0) -> dict:
    """番剧更新时刻（北京时间精确到分钟，来自 bangumi-data）；完结的番返回「已完结」。"""
    try:
        return airtimes.attach(subject_id, station, total_episodes)
    except Exception as e:                     # noqa: BLE001 - 更新时刻绝不能拖垮接口
        logger.warn("读取更新时刻失败（忽略）：%s", e)
        return {}


def _require_token() -> str:
    token = config.bangumi_token()
    if not token:
        raise ApiError("请先填写 Bangumi Access Token", 400)
    return token


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("1", "true", "yes", "on")


def _split_sub_group(value: str) -> tuple[str, str]:
    """把 'dmhy::桜都字幕组' 拆成 (站点 id, 组名)；没有 '::' 时站点为空。"""
    raw = (value or "").strip()
    if "::" in raw:
        src, _, name = raw.partition("::")
        return src.strip(), name.strip()
    return "", raw


def _resource_from_payload(payload: dict) -> Optional[Resource]:
    """从请求体还原 Resource（只接受已知字段）。"""
    if not isinstance(payload, dict) or not payload:
        return None
    known = {k: v for k, v in payload.items() if k in Resource.__dataclass_fields__}
    if not known.get("source"):
        known["source"] = "manual"
    try:
        return Resource(**known)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@route("GET", r"/api/config")
def api_get_config(q, body):
    cfg = config.load()
    safe = json.loads(json.dumps(cfg))
    safe["bangumi_token_masked"] = _mask(cfg.get("bangumi_token", ""))
    safe["token_url"] = bangumi.TOKEN_URL
    safe["data_dir"] = config.DATA_DIR
    safe["config_path"] = config.CONFIG_PATH
    return safe


@route("POST", r"/api/config")
def api_set_config(q, body):
    if not isinstance(body, dict):
        raise ApiError("请求体必须是 JSON 对象")
    patch = dict(body)
    # token 为空字符串时表示不修改（避免误清空）
    if "bangumi_token" in patch and not str(patch["bangumi_token"]).strip():
        patch.pop("bangumi_token")
    cfg = config.update(patch)
    logger.info("配置已更新：%s", ", ".join(k for k in patch.keys()))
    return {"ok": True, "config": cfg}


def _mask(token: str) -> str:
    token = (token or "").strip()
    if not token:
        return ""
    if len(token) <= 10:
        return token[:2] + "***"
    return f"{token[:6]}...{token[-4:]}"


# --------------------------------------------------------------------------- #
# Bangumi
# --------------------------------------------------------------------------- #
@route("POST", r"/api/bangumi/token")
def api_check_token(q, body):
    token = (body or {}).get("token") or config.bangumi_token()
    if not token or not str(token).strip():
        raise ApiError("Token 不能为空")
    token = str(token).strip()
    try:
        me = bangumi.get_me(token)
    except bangumi.BangumiError as e:
        raise ApiError(str(e), 401) from None
    # 校验通过即保存
    config.update({"bangumi_token": token})
    bangumi.clear_cache()
    return {"ok": True, "user": me}


@route("GET", r"/api/bangumi/me")
def api_me(q, body):
    token = _require_token()
    try:
        return {"ok": True, "user": bangumi.get_me(token)}
    except bangumi.BangumiError as e:
        raise ApiError(str(e), 401) from None


@route("GET", r"/api/bangumi/meta")
def api_bangumi_meta(q, body):
    """本地 Bangumi 元数据缓存的状态（有多少条、存在哪、多久算过期）。"""
    return {"ok": True, **meta.stats()}


@route("GET", r"/api/bangumi/collections")
def api_collections(q, body):
    token = _require_token()
    collect_type = _int((q.get("type") or ["3"])[0], 3)
    force = _bool((q.get("force") or ["0"])[0], False)
    warm = _bool((q.get("warm") or ["1"])[0], True)
    try:
        # 缓存优先：token 未变则复用上次结果，过期先回旧值再后台刷新（force=1 强制同步刷新）
        items = bangumi.get_collections(token, collect_type=collect_type, force=force)
        # 一次性把这批番剧的元数据（首播/总话数/更新时刻/封面/评分）存到本地，
        # 后面集号偏移、季判定、卡片信息都直接读本地，不再反复请求 Bangumi
        try:
            meta.save_many(items)
        except Exception as e:                  # noqa: BLE001
            logger.warn("写入 Bangumi 元数据缓存失败：%s", e)
    except bangumi.BangumiError as e:
        msg = str(e)
        # 网络类失败时，直接告诉用户去开代理（不让用户猜）
        if "无法连接" in msg or "超时" in msg or "timed out" in msg:
            hint = network_hint()
            if hint.get("message"):
                msg = f"{msg}。{hint['message']}"
        raise ApiError(msg, 401 if "Token" in msg else 502) from None
    except (http.HttpError, OSError, ValueError) as e:
        raise ApiError(f"拉取失败：{e}", 502) from None

    if warm:
        warmup.warm(items, force=force)

    subscribed = {s.subject_id for s in subs.all_subs()}
    payload = []
    for s in items:
        d = _subject_payload(s)
        d["subscribed"] = s.id in subscribed
        cached, age = warmup.search_any_age(s.id)
        d["resources_cached"] = cached is not None
        d["resources_cached_count"] = (cached or {}).get("total", 0) if cached else 0
        d["resources_cached_age"] = int(age) if cached else None
        # 电视台只能读缓存（绝不在这里联网）：Bangumi 抽风时 35 个详情接口会把接口拖到一分钟
        cached_subject = bangumi.cached_subject(s.id)
        d["airtime"] = _airtime_payload(s.id, _station_of(cached_subject) if cached_subject else "",
                                        int(getattr(s, "total_episodes", 0) or 0))
        payload.append(d)
    _warm_stations([s.id for s in items if not bangumi.cached_subject(s.id)])
    return {
        "ok": True,
        "total": len(payload),
        "items": payload,
        "from_cache": not force,
        "warmup": warmup.status(),
    }


@route("GET", r"/api/cache/status")
def api_cache_status(q, body):
    return {"ok": True, **warmup.status()}


@route("POST", r"/api/cache/clear")
def api_cache_clear(q, body):
    body = body or {}
    prefix = str(body.get("prefix") or "")
    n = cache.clear(prefix)
    logger.info("清理缓存：prefix=%r，删除 %d 个文件", prefix, n)
    return {"ok": True, "removed": n}


@route("POST", r"/api/cache/warm")
def api_cache_warm(q, body):
    """手动触发资源预热（可选 force 强制重搜）。"""
    body = body or {}
    force = _bool(body.get("force"), False)
    try:
        items = bangumi.get_collections(config.bangumi_token())
    except (bangumi.BangumiError, http.HttpError, OSError, ValueError) as e:
        raise ApiError(f"获取在看列表失败：{e}", 502) from None
    started = warmup.start(items, force=force)
    if not started:
        raise ApiError("已有预热任务在运行", 409)
    return {"ok": True, "total": len(items), "status": warmup.status()}


@route("POST", r"/api/cache/warm/stop")
def api_cache_warm_stop(q, body):
    warmup.stop()
    return {"ok": True, "status": warmup.status()}


@route("GET", r"/api/bangumi/subject/(?P<sid>\d+)")
def api_subject(q, body, sid):
    token = config.bangumi_token()
    try:
        s = bangumi.get_subject(_int(sid), token=token or None)
    except (http.HttpError, OSError, ValueError) as e:
        raise ApiError(f"获取条目失败：{e}", 502) from None
    d = _subject_payload(s)
    d["total_episodes_resolved"] = bangumi.total_episodes(s, token=token or None)
    d["source_keywords"] = {sid_: bangumi.aliases_for_source(s, sid_)[:6]
                            for sid_ in ("dmhy", "kisssub", "nyaa")}
    return d


def _prepare_episodes(items: list[dict], subject_payload: dict = None, *,
                      subject_id: int = 0,
                      all_seasons: bool = False) -> tuple[list[dict], int, int]:
    """
    页面搜索 / 补下载用：一行调用 core.rules（和自动追番同一套季判定与集号换算）。

    规则本身在 `core/rules.py: filter_items` + `core/util.py: apply_season_rules`，
    这里只负责把「番剧信息」装配成上下文，不再自己算起点/别名/集号。
    """
    ctx = rules.SeasonContext.load(subject_id, payload=subject_payload or {})
    return rules.filter_items(items, ctx, all_seasons=all_seasons)


def _pick_search_cache(subject_id: int, variant: str) -> tuple[Optional[dict], float]:
    """
    选一份搜索结果缓存，返回 (内容, 年龄秒)。

    规则：
      1. 先挑变体缓存（字幕组 / 语言 / 关键词口径各自独立）
      2. 变体没有 → 用基础缓存（全量，筛选在读的时候再做，省一次联网）
      3. **「关键词学习签名」变体（lk=）和基础缓存是同一批资源的两种排序**，预热只刷新基础那份，
         所以这两者取更新的一份 —— 否则弹窗会一直停在几天前的缓存（用户报过「预热完还是过期」）
    """
    cached, age = warmup.search_any_age(subject_id, variant)
    if not variant:
        return cached, age
    base, base_age = warmup.search_any_age(subject_id, "")
    if cached is None:
        return base, base_age
    if variant.startswith("lk=") and base is not None and base_age < age:
        return base, base_age
    return cached, age


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #
def _matches_search_filters(r, *, source: str = "", group: str = "", lang: str = "",
                            resolution: str = "") -> bool:
    """
    「站点 → 字幕组 → 语言 → 分辨率」四道筛选。

    **缓存命中和联网搜索必须走同一套口径**：缓存的 payload 里存的是全量资源
    （这样一份缓存能服务多种筛选），以前只在联网分支做了筛选，于是「限定字幕组」
    第二次打开（命中缓存）会看到别的组的资源 —— 用户抱怨过这个。
    """
    if source and getattr(r, "source", "") != source:
        return False
    if group and not engine._group_match(getattr(r, "group", ""), group):
        return False
    if lang and not lang_matches(getattr(r, "lang", ""), lang):
        return False
    if resolution and not resolution_matches(getattr(r, "resolution", ""), resolution):
        return False
    return True


@route("POST", r"/api/search")
def api_search(q, body):
    """搜索某番剧的资源（用于弹窗展示）。

    优先用预热的缓存（点开秒显示）；force=true 时忽略缓存重新联网搜索。
    """
    body = body or {}
    subject_id = _int(body.get("subject_id"))
    if not subject_id:
        raise ApiError("缺少 subject_id")
    force = _bool(body.get("force"), False)
    token = config.bangumi_token()

    group = (body.get("group") or "").strip()
    # sub_group：站点限定的字幕组，"<source>::<组名>"（用户在订阅里指定「动漫花园的那家 ANi」）
    sub_group = (body.get("sub_group") or "").strip()
    sub_source, sub_group_name = _split_sub_group(sub_group)
    source_ids = body.get("source_ids") or None
    if isinstance(source_ids, str):
        source_ids = [x for x in source_ids.split(",") if x]
    # 手动搜索关键词：给了就只按这个词搜（不再展开番剧别名），缓存键也必须带上它
    keyword = (body.get("keyword") or "").strip()
    # 搜索口径决定缓存键：站点 + 字幕组 + 语言组合，互不串味
    lang = (body.get("lang") or "").strip().lower()
    variant = sub_group or group
    if keyword:
        variant = f"{variant}|kw={keyword}" if variant else f"kw={keyword}"
    if lang:
        variant = f"{variant}|lang={lang}" if variant else f"lang={lang}"
    if not keyword:
        # 关键词学习结果变了就该重新搜（学习会把「真管用的关键词」排到最前，
        # 旧缓存是拿老关键词搜出来的，条数可能少一大截）
        sig = keywords_store.signature(subject_id)
        if sig:
            variant = f"{variant}|lk={sig}" if variant else f"lk={sig}"

    # 筛选口径（缓存分支与联网分支共用，见 _matches_search_filters）
    filt = {
        "source": sub_source or str(body.get("source") or ""),
        "group": sub_group_name or group,
        "lang": lang,
        "resolution": str(body.get("resolution") or ""),
    }

    # 1) 命中缓存的整份搜索结果 -> 直接返回（含筛选也不重新联网）
    if not force:
        cached, age = _pick_search_cache(subject_id, variant)
        fresh = cached is not None and age < warmup.search_ttl()
        if cached is not None and (fresh or not _bool(body.get("refresh_if_stale"), False)):
            # 缓存可能是上一版程序写的（缺少新增字段），读出来统一重算一遍派生字段，
            # 否则新加的「字幕语言」会一直显示成「未标注」
            cached_items = normalize_items(cached.get("items"))
            items = [it for it in cached_items
                     if _matches_search_filters(Resource.from_dict(it), **filt)]
            subject_payload = _subject_payload(bangumi.get_subject(subject_id, token=token or None))
            items, episode_offset, hidden_season = _prepare_episodes(
                items, subject_payload, subject_id=subject_id,
                all_seasons=_bool(body.get("all_seasons"), False))
            return {
                "ok": True,
                "subject": subject_payload,
                "strategy": cached.get("strategy", ""),
                "elapsed": 0.0,
                "cached": True,
                # 来源与「为什么是 0 条」要说清楚：是缓存里本来就没有，还是被筛选排掉了
                "origin": "cache",
                "raw_total": len(cached_items),
                "filtered_out": max(0, len(cached_items) - len(items)),
                "reason": "cache_hit" if items else ("cache_filtered_empty" if cached_items else "cache_empty"),
                "cache_age": int(age),
                "cache_stale": not fresh,
                "keywords_used": cached.get("keywords_used", {}),
                "source_status": cached.get("source_status", {}),
                "groups": cached.get("groups", []),
                "total": len(items),
                "items": items,
                "episode_offset": episode_offset,
                "hidden_other_season": hidden_season,
                "search_group": group,
                "search_sub_group": sub_group,
                "search_lang": lang,
                "search_keyword": keyword,
            }

    # 2) 未命中或强制刷新 -> 联网搜索并写回缓存
    try:
        subject = bangumi.get_subject(subject_id, token=token or None)
    except (http.HttpError, OSError, ValueError) as e:
        raise ApiError(f"获取番剧信息失败：{e}", 502) from None

    search_ids = [sub_source] if sub_source else source_ids
    keyword_hint = sub_group_name or group
    try:
        outcome = engine.search_by_subject(subject, source_ids=search_ids, group=keyword_hint,
                                           lang=lang, keyword=keyword)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"搜索失败：{e}", 502) from None

    all_items = [r.to_dict() for r in outcome.resources]
    cache.set(cache.search_key(subject_id, variant), {
        "schema": warmup.SEARCH_SCHEMA,
        "subject_id": subject_id,
        "display_name": subject.display_name,
        "search_group": group,
        "search_sub_group": sub_group,
        "search_lang": lang,
        "search_keyword": keyword,
        "strategy": outcome.strategy,
        "elapsed": round(outcome.elapsed, 2),
        "keywords_used": outcome.keywords_used,
        "source_status": outcome.source_status,
        "groups": outcome.groups,
        "total": len(all_items),
        "items": all_items,
        "searched_at": time.time(),
    })

    items = [r for r in outcome.resources if _matches_search_filters(r, **filt)]
    subject_payload = _subject_payload(subject)
    item_dicts, episode_offset, hidden_season = _prepare_episodes(
        [r.to_dict() for r in items], subject_payload, subject_id=subject_id,
        all_seasons=_bool(body.get("all_seasons"), False))

    return {
        "ok": True,
        "subject": subject_payload,
        "strategy": outcome.strategy,
        "elapsed": round(outcome.elapsed, 2),
        "cached": False,
        "origin": "live",
        "raw_total": len(all_items),
        "filtered_out": max(0, len(all_items) - len(item_dicts)),
        "site_errors": [{"id": sid, "name": (meta or {}).get("name", sid),
                         "error": str((meta or {}).get("error") or "")}
                        for sid, meta in (outcome.source_status or {}).items()
                        if not (meta or {}).get("ok")],
        "reason": "live_failed" if any(not (m or {}).get("ok") for m in (outcome.source_status or {}).values())
                  else ("live_ok" if item_dicts else "live_empty"),
        "cache_age": 0,
        "cache_stale": False,
        "keywords_used": outcome.keywords_used,
        "source_status": outcome.source_status,
        "groups": outcome.groups,
        "total": len(item_dicts),
        "items": item_dicts,
        "episode_offset": episode_offset,
        "hidden_other_season": hidden_season,
        "search_group": group,
        "search_sub_group": sub_group,
        "search_lang": lang,
        "search_keyword": keyword,
    }


@route("POST", r"/api/groups")
def api_groups(q, body):
    """获取番剧的字幕组列表（默认按资源站分开，前端下拉用 optgroup 分组展示）。"""
    body = body or {}
    subject_id = _int(body.get("subject_id"))
    if not subject_id:
        raise ApiError("缺少 subject_id")
    token = config.bangumi_token()
    by_source = _bool(body.get("by_source"), True)
    try:
        subject = bangumi.get_subject(subject_id, token=token or None)
        result = engine.collect_groups(subject, source_ids=body.get("source_ids") or None,
                                       by_source=by_source)
    except (http.HttpError, OSError, ValueError) as e:
        raise ApiError(f"获取字幕组失败：{e}", 502) from None
    return {"ok": True, **result}


# --------------------------------------------------------------------------- #
# 订阅
# --------------------------------------------------------------------------- #
def _absolute_folder(sub) -> str:
    """订阅对应的绝对目录（folder 存的是绝对路径就原样用，否则拼下载根目录）。"""
    folder = str(getattr(sub, "folder", "") or "")
    if os.path.isabs(folder):
        return folder
    return os.path.join(config.get("download.root", ""), folder)


def _start_ep_of(subject_id: int) -> int:
    """Bangumi 章节表里本季第一集的累计编号（拿不到返回 0，退回标题推断）。"""
    try:
        item = meta.get(int(subject_id)) or {}
        return int(item.get("start_ep") or 0)
    except Exception:                           # noqa: BLE001
        return 0


def _attach_torrent_state(items: list[dict]) -> dict:
    """
    给订阅列表补上「真实存在」状态：进度与已下载记录要和 qBittorrent 里的种子对应。

    背景：`downloaded` 只记累计下载过多少，文件删了、种子移了它不动，
    于是出现「文件夹里 1 个文件、卡片写已下载 5 集」。

    匹配口径：**按种子保存路径**。加种子时 savepath 就是该订阅的文件夹，
    所以「保存路径 = 下载根目录\\番剧文件夹」的种子数，就是这个订阅现在的真实集数。
    qB 连不上时返回 online=False，前端沿用旧计数（不会突然全变 0）。
    """
    try:
        torrents = qbittorrent.torrents()
    except Exception as e:                       # noqa: BLE001 - 连不上退回旧口径
        logger.debug("读取 qBittorrent 种子列表失败：%s", e)
        return {"online": False}

    def norm_path(value: str) -> str:
        return str(value or "").replace("/", "\\").rstrip("\\").strip().lower()

    folder_counts: dict[str, int] = {}
    folder_eps: dict[str, set] = {}
    names_norm: list[str] = []
    for t in torrents:
        key = norm_path(t.get("save_path") or "")
        if key:
            folder_counts[key] = folder_counts.get(key, 0) + 1
            ep = parse_episode(str(t.get("name") or ""))
            if ep:
                folder_eps.setdefault(key, set()).add(int(ep))
        nm = str(t.get("name") or "").strip().lower()
        if nm:
            names_norm.append(nm)

    root = norm_path(config.get("download.root", ""))
    for item in items:
        folder = str(item.get("folder") or "").strip()
        if folder and root:
            key = norm_path(os.path.join(root, folder))
        else:
            key = ""
        alive = folder_counts.get(key, 0)
        item["qb_online"] = True
        item["qb_torrents"] = alive
        # 真实集数：该文件夹里现在还有多少种子；取不到（路径没配）时退回旧计数
        # 真实集数：优先「该文件夹种子里出现的不同集号数量」，
        # 同一集重复下过多个种子时只算一集（用户看到的是文件夹里那几集）
        distinct = len(folder_eps.get(key) or ())
        item["actual_count"] = (distinct or alive) if key else None
        hist = item.get("history")
        if isinstance(hist, list):
            for h in hist:
                title = str(h.get("title") or "").strip().lower()
                if not title:
                    continue
                if any(n in title for n in names_norm):
                    h["in_qb"] = True
        try:
            entries = os.listdir(os.path.join(config.get("download.root", ""), folder)) if folder else []
        except OSError:
            entries = []
        file_eps = set()
        for name in entries:
            if os.path.splitext(name)[1].lower() not in (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".rmvb", ".mov"):
                continue
            ep = parse_episode(name)
            if ep:
                # 文件名里是发布组的连续编号（16、173…），要按订阅的偏移换算成本季集号，
                # 否则和 history 里存的本季集号（4、3…）对不上，全被当成「文件不存在」
                offset = int(item.get("episode_offset") or 0)
                file_eps.add(max(1, int(ep) - offset) if offset else int(ep))
        item["file_episodes"] = sorted(file_eps)
        # qB 里该文件夹的种子覆盖了哪些集（同样按偏移换算），用于「已下载只显示 qB 里有的」
        offset = int(item.get("episode_offset") or 0)
        torrent_eps = set()
        for t in torrents:
            if norm_path(t.get("save_path") or "") != key:
                continue
            ep = parse_episode(str(t.get("name") or ""))
            if ep:
                torrent_eps.add(max(1, int(ep) - offset) if offset else int(ep))
        item["qb_episodes"] = sorted(torrent_eps)
        # 该文件夹里 qB 现存的种子明细：历史上没有记录时（比如刚重新添加订阅）
        # 也能在「管理已下载」里看到真实存在的种子
        qb_items = []
        for t in torrents:
            if norm_path(t.get("save_path") or "") != key:
                continue
            ep = parse_episode(str(t.get("name") or ""))
            if ep:
                ep = max(1, int(ep) - offset) if offset else int(ep)
            size = t.get("size") or t.get("total_size") or 0
            qb_items.append({
                "hash": str(t.get("hash") or "").lower(),
                "name": str(t.get("name") or ""),
                "episode": ep,
                "size": int(size or 0),
                "progress": t.get("progress"),
                "state": t.get("state") or "",
            })
        qb_items.sort(key=lambda x: (x.get("episode") or 0), reverse=True)
        item["qb_items"] = qb_items
        if isinstance(hist, list) and torrent_eps:
            for h in hist:
                ep = h.get("episode")
                if ep:
                    h["from_qb"] = int(ep) in torrent_eps
        if isinstance(hist, list) and file_eps:
            for h in hist:
                ep = h.get("episode")
                if ep:
                    h["file_exists"] = int(ep) in file_eps
        video_exts = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".rmvb", ".mov")
        files = []
        for name in entries:
            if os.path.splitext(name)[1].lower() not in video_exts:
                continue
            full = os.path.join(config.get("download.root", ""), folder, name)
            try:
                st = os.stat(full)
                size = st.st_size
                mtime = st.st_mtime
            except OSError:
                size, mtime = 0, 0
            ep = parse_episode(name)
            if ep and offset:
                ep = max(1, int(ep) - offset)
            files.append({"name": name, "size": int(size), "mtime": mtime,
                          "episode": int(ep) if ep else None})
        files.sort(key=lambda x: (x.get("episode") or 0), reverse=True)
        item["files"] = files
        item["file_count"] = len(files)
    return {"online": True, "torrents": len(torrents)}


@route("GET", r"/api/subscriptions")
def api_subs(q, body):
    items = []
    need_warm = []
    for s in subs.all_subs():
        d = s.to_dict()
        d["folder_exists"] = os.path.isdir(d.get("folder") or "")
        # qBittorrent 掉线期间攒下的待下载项：卡片上提示「待补 N 集」，恢复后自动下载
        queued = pending.for_subject(s.subject_id)
        d["pending_count"] = len(queued)
        d["pending_episodes"] = [_int(i.get("episode")) for i in queued if i.get("episode")]
        # 更新时刻：电视台取自 Bangumi 条目 —— 只读缓存，绝不在这里联网
        # （以前这里逐个 get_subject：Bangumi 抖动时 13 个详情接口各超时几秒，
        #   /api/subscriptions 要 60 多秒才返回，整页都卡住）
        cached = bangumi.cached_subject(s.subject_id)
        if cached is None:
            need_warm.append(s.subject_id)
        d["airtime"] = _airtime_payload(s.subject_id, _station_of(cached) if cached else "",
                                        int(s.total_episodes or 0))
        items.append(d)
    _warm_stations(need_warm)
    # 排序只按「首次加入订阅的时间」倒序：修改订阅、检查、开关都不许让顺序跳
    items.sort(key=lambda x: (-(x.get("created_at") or 0), -(x.get("subject_id") or 0)))
    _attach_torrent_state(items)
    return {"ok": True, "items": items, "status": watcher.status(), "queue": pending.summary()}


def _join_sub_group(source: str, group: str) -> str:
    """拼出订阅里的 sub_group：'<站点>::<组名>'（没有站点时只存组名）。"""
    src = str(source or "").strip()
    grp = str(group or "").strip()
    if not grp:
        return ""
    return f"{src}::{grp}" if src else grp


def _search_lang(body: dict, resource: dict, existing) -> str:
    """订阅读取「字幕语言」：请求 > 所选资源 > 已有订阅（空=不限）。"""
    for value in (body.get("lang"), (resource or {}).get("lang")):
        text = str(value or "").strip().lower()
        if text:
            return text
    return str(getattr(existing, "lang", "") or "").strip().lower()


@route("POST", r"/api/subscriptions")
def api_sub_add(q, body):
    """新增/更新订阅（选择一个资源加入订阅）。"""
    body = body or {}
    subject_id = _int(body.get("subject_id"))
    if not subject_id:
        raise ApiError("缺少 subject_id")
    token = config.bangumi_token()
    try:
        subject = bangumi.get_subject(subject_id, token=token or None)
    except (http.HttpError, OSError, ValueError) as e:
        raise ApiError(f"获取番剧信息失败：{e}", 502) from None

    resource = body.get("resource") or {}
    # sub_group：站点限定的字幕组 "dmhy::ANi"。group 仍存组名用于搜索关键词，
    # sub_group 用于「只从该站点的该组下载」以及补下载时预填筛选。
    sub_group = str(body.get("sub_group") or "").strip()
    group = (body.get("group") or resource.get("group") or "").strip()
    if not group and sub_group:
        group = _split_sub_group(sub_group)[1]
    folder = (body.get("folder") or "").strip() or subs.default_folder(subject.display_name)
    total = _int(body.get("total_episodes")) or bangumi.total_episodes(subject, token=token or None)

    existing = subs.get(subject_id)
    # 手动搜索关键词：请求里带了就用请求的（空字符串=清掉），没带就保留订阅里原来的
    if "custom_keyword" in body:
        custom_keyword = str(body.get("custom_keyword") or "").strip()
    else:
        custom_keyword = (existing.custom_keyword if existing else "")
    sub = subs.Subscription(
        subject_id=subject_id,
        name=subject.display_name,
        name_original=subject.name,
        cover=subject.cover,
        group=group,
        sub_group=sub_group,
        custom_keyword=custom_keyword,
        team_id=str(resource.get("team_id") or ""),
        aliases=subject.search_aliases(),
        resolution=(body.get("resolution") or "").strip(),
        lang=_search_lang(body, resource, existing),
        source_ids=body.get("source_ids") or ([] if not existing else existing.source_ids),
        folder=folder,
        total_episodes=total,
        last_episode=existing.last_episode if existing else 0,
        downloaded=dict(existing.downloaded) if existing else {},
        history=list(existing.history) if existing else [],
        enabled=_bool(body.get("enabled"), True),
        initial_mode=(body.get("initial_mode") or subs.INITIAL_LATEST),
        created_at=existing.created_at if existing else time.time(),
        last_check=existing.last_check if existing else 0.0,
    )

    added = False
    error = ""
    queued = False
    res = _resource_from_payload(resource)
    if res is not None and res.magnet:
        try:
            added = watcher.download_resource(sub, res, reason="加入订阅时下载")
        except Exception as e:  # noqa: BLE001
            error = str(e)
            logger.warn("订阅时下载失败：%s", e)
            # qBittorrent 没开：先把资源入队，等它恢复连接后自动补下载
            queued = bool(watcher._queue_failed(sub, res, res.episode, error))
    elif resource and not (resource.get("magnet")):
        error = "所选资源没有可用的磁力链接"

    subs.upsert(sub)
    return {"ok": True, "subscription": sub.to_dict(), "downloaded_now": added, "error": error,
            "queued": queued, "queue": pending.summary()}


@route("POST", r"/api/subscriptions/(?P<sid>\d+)/update")
def api_sub_update(q, body, sid):
    body = body or {}
    fields = {k: v for k, v in body.items() if k in subs.Subscription.__dataclass_fields__}
    if "folder" in fields and not str(fields["folder"]).strip():
        fields.pop("folder")
    s = subs.update_fields(_int(sid), **fields)
    if s is None:
        raise ApiError("订阅不存在", 404)
    return {"ok": True, "subscription": s.to_dict()}


@route("DELETE", r"/api/subscriptions/(?P<sid>\d+)")
def api_sub_del(q, body, sid):
    ok = subs.remove(_int(sid))
    if not ok:
        raise ApiError("订阅不存在", 404)
    return {"ok": True}


@route("GET", r"/api/groups/cached")
def api_groups_cached(q, body):
    """字幕组候选（只读缓存，不联网）：把所有订阅的预热搜索结果里的组按站点汇总。

    批量订阅设置用它给「字幕组」下拉填选项 —— 打开就秒出，不会像逐部搜索那样卡半天。
    """
    buckets: dict[str, dict] = {}
    for sub in subs.all_subs():
        cached, _age = warmup.search_any_age(sub.subject_id, "")
        if cached is None:
            continue
        for it in normalize_items(cached.get("items")):
            r = Resource.from_dict(it)
            name = (r.group or "").strip()
            if not name:
                continue
            key = f"{r.source}|{engine.normalize_group(name)}"
            item = buckets.get(key)
            if item is None:
                buckets[key] = {"name": name, "source": r.source,
                                "source_name": r.source_name or r.source, "count": 1}
            else:
                item["count"] += 1
    groups = sorted(buckets.values(), key=lambda g: (-g["count"], g["name"]))
    sources = {s["id"]: s.get("name", s["id"]) for s in config.enabled_sources()}
    for g in groups:
        g["source_name"] = sources.get(g["source"], g["source_name"])
    return {"ok": True, "groups": groups[:400]}


@route("POST", r"/api/subscriptions/(?P<sid>\d+)/file/delete")
def api_sub_file_delete(q, body, sid):
    """删除「已下载文件管理」里的一个文件。

    规则（用户定）：
      - 有文件、没有对应种子  → 直接删文件
      - 有文件、也有对应种子  → 先删种子（连同文件一起删，qB delete_files=True）
    只允许删该订阅文件夹里的**单个文件名**，不接受路径，防止越界删除。
    """
    body = body or {}
    name = os.path.basename(str(body.get("name") or "").strip())
    if not name:
        raise ApiError("缺少文件名")
    sub = subs.get(int(sid))
    if sub is None:
        raise ApiError("订阅不存在", 404)
    folder = _absolute_folder(sub)
    path = os.path.join(folder, name)
    if not os.path.isfile(path):
        raise ApiError("文件已不存在")
    # 找这个文件对应的种子：同目录、且种子名与文件名相近
    hex_hash = ""
    try:
        for t in qbittorrent.torrents():
            save = str(t.get("save_path") or "")
            tname = str(t.get("name") or "")
            if os.path.normcase(os.path.normpath(save)) != os.path.normcase(os.path.normpath(folder)):
                continue
            stem = os.path.splitext(name)[0]
            if tname and (tname in stem or stem in tname or os.path.splitext(tname)[0] == stem):
                hex_hash = str(t.get("hash") or "")
                break
    except Exception as e:                      # noqa: BLE001 - qB 不可用时退化为只删文件
        logger.warn("删除文件时读取 qB 种子失败（改为只删文件）：%s", e)

    if hex_hash:
        qbittorrent.delete_torrents([hex_hash], delete_files=True)
        mode = "torrent"
    else:
        try:
            os.remove(path)
        except OSError as e:
            raise ApiError(f"删除文件失败：{e}") from e
        mode = "file"

    # 顺手把历史记录里对应这一集的条目去掉（文件已经不在了）
    ep = parse_episode(name)
    if ep:
        offset = int(sub.episode_offset or 0)
        rel = max(1, int(ep) - offset) if offset else int(ep)
        kept = [h for h in (sub.history or []) if int(h.get("episode") or 0) != rel]
        if len(kept) != len(sub.history or []):
            sub.history = kept
            subs.upsert(sub)
    return {"ok": True, "mode": mode, "torrent_deleted": bool(hex_hash)}


@route("POST", r"/api/subscriptions/batch")
def api_sub_batch(q, body):
    """批量订阅：按「规则顺序」逐个尝试，第一条没匹配到就试下一条；都不匹配则不订阅。

    body: {subject_ids: [...], rules: [{source, group, lang, resolution}], dry_run: bool}
    - 只挑单集（合集一律不要）
    - 每部番取「最新一集」立即下载；订阅的 initial_mode 记成 latest（以后自动追新）
    - 订阅里存的是命中那条规则的筛选（站点/字幕组/语言/分辨率）
    """
    body = body or {}
    ids = [_int(x) for x in (body.get("subject_ids") or []) if _int(x)]
    rules = [r for r in (body.get("rules") or []) if isinstance(r, dict)]
    dry = _bool(body.get("dry_run"), False)
    if not ids:
        raise ApiError("缺少 subject_ids")
    if not rules:
        raise ApiError("请至少添加一条订阅规则")
    token = config.bangumi_token()
    subscribed, skipped = [], []

    def cached_resources(sid: int):
        cached, _age = warmup.search_any_age(sid, "")
        if cached is None:
            return None
        return [Resource.from_dict(it) for it in normalize_items(cached.get("items"))]

    for sid in ids:
        try:
            subject = bangumi.get_subject(sid, token=token or None)
        except (http.HttpError, OSError, ValueError) as e:
            skipped.append({"subject_id": sid, "name": f"#{sid}", "reason": f"获取番剧信息失败：{e}"})
            continue
        pool = cached_resources(sid)
        picked, used = None, -1
        for idx, rule in enumerate(rules):
            src = str(rule.get("source") or "").strip()
            grp = str(rule.get("group") or "").strip()
            lang = str(rule.get("lang") or "").strip().lower()
            res = str(rule.get("resolution") or "").strip()
            if pool is None:
                try:
                    outcome = engine.search_by_subject(subject, source_ids=[src] if src else None,
                                                       group=grp, lang=lang, keyword="")
                except Exception as e:      # noqa: BLE001
                    logger.warn("批量订阅搜索失败（%s）：%s", subject.display_name, e)
                    continue
                items = outcome.resources
            else:
                items = pool
            cand = [r for r in items
                    if r.magnet and not r.is_batch and not r.is_noise and r.episode
                    and _matches_search_filters(r, source=src, group=grp, lang=lang, resolution=res)]
            if not cand:
                continue
            top = max(int(r.episode) for r in cand)
            best = watcher.pick_best([r for r in cand if int(r.episode) == top], res)
            if best is not None:
                picked, used = best, idx
                break
        if picked is None:
            skipped.append({"subject_id": sid, "name": subject.display_name,
                            "reason": "所有规则都没有匹配到可用资源"})
            continue
        rule = rules[used]
        subscribed.append({
            "subject_id": sid, "name": subject.display_name, "rule_index": used,
            "episode": picked.episode, "title": picked.title, "source": picked.source_name,
            "group": picked.group, "rule": rule, "dry_run": dry,
        })
        if dry:
            continue
        src = str(rule.get("source") or "").strip()
        grp = str(rule.get("group") or "").strip()
        new_sub = subs.Subscription(
            subject_id=sid, name=subject.display_name, name_original=subject.name, cover=subject.cover,
            group=grp or picked.group, sub_group=_join_sub_group(src, grp or picked.group),
            aliases=subject.search_aliases(), resolution=str(rule.get("resolution") or "").strip(),
            lang=str(rule.get("lang") or "").strip().lower(),
            source_ids=[src] if src else [],
            folder=subs.default_folder(subject.display_name),
            total_episodes=bangumi.total_episodes(subject, token=token or None),
            enabled=True, initial_mode=subs.INITIAL_LATEST, primed=True,
        )
        subs.upsert(new_sub)
        try:
            ok = watcher.download_resource(new_sub, picked, reason="批量订阅时下载")
            subscribed[-1]["downloaded"] = bool(ok)
        except Exception as e:              # noqa: BLE001
            subscribed[-1]["error"] = str(e)
    return {"ok": True, "subscribed": subscribed, "skipped": skipped, "dry_run": dry,
            "queue": pending.summary()}


@route("POST", r"/api/subscriptions/(?P<sid>\d+)/episodes/delete")
def api_sub_episode_delete(q, body, sid):
    """
    删除某个已下载剧集（用户要求）：同时删掉 qBittorrent 里的做种任务和本地文件，并清掉下载记录。

    body: {infohash, title, delete_files=true}
    infohash 可能是 magnet 里的 base32 形式，qBittorrent 那边要 40 位十六进制，这里统一转换；
    找不到任务（已被手动删掉）时按标题兜底匹配；都不在就只清记录，并在返回里说清楚。
    """
    body = body or {}
    sub = subs.get(_int(sid))
    if sub is None:
        raise ApiError("订阅不存在", 404)
    infohash = str(body.get("infohash") or "").strip()
    title = str(body.get("title") or "").strip()
    if not infohash and not title:
        raise ApiError("请给出要删除的剧集（infohash 或标题）", 400)
    delete_files = _bool(body.get("delete_files"), True)

    removed_torrent = False
    torrent_name = ""
    error = ""
    try:
        qbittorrent.login()
        found = qbittorrent.find_torrent(infohash, title)
        if found:
            torrent_name = str(found.get("name") or "")
            qbittorrent.delete_torrents([str(found.get("hash") or "")], delete_files=delete_files)
            removed_torrent = True
        else:
            error = "qBittorrent 里没有找到这条任务（可能已经被手动删除了）"
    except Exception as e:  # noqa: BLE001
        error = f"删除 qBittorrent 任务失败：{e}"
        logger.warn("删除已下载剧集失败：%s", e)

    # 清下载记录（downloaded 的 key 大小写可能不一致；history 按 infohash/标题匹配）
    for key in [k for k in list(sub.downloaded.keys())
                if (infohash and k.lower() == infohash.lower()) or (not infohash and sub.downloaded[k] == title)]:
        sub.downloaded.pop(key, None)
    before = len(sub.history)
    sub.history = [h for h in sub.history
                   if not _same_download_entry(h, infohash, title)]
    removed_history = before - len(sub.history)
    subs.upsert(sub)
    logger.info("已删除下载记录：[%s] %s（qB 任务：%s，文件：%s）",
                sub.display_name, torrent_name or title[:60],
                "已删" if removed_torrent else "未找到", "已删" if (removed_torrent and delete_files) else "保留")
    return {
        "ok": True,
        "removed_torrent": removed_torrent,
        "torrent_name": torrent_name,
        "deleted_files": bool(removed_torrent and delete_files),
        "removed_history": removed_history,
        "error": error,
        "subscription": sub.to_dict(),
    }


def _same_download_entry(entry: dict, infohash: str, title: str) -> bool:
    """history 里这条记录是不是要删的那一集（按 magnet 里的 infohash 或标题匹配）。"""
    if not isinstance(entry, dict):
        return False
    entry_hash = ""
    magnet = str(entry.get("magnet") or "")
    m = re.search(r"btih:([0-9a-zA-Z]{32,40})", magnet)
    if m:
        entry_hash = m.group(1)
    if infohash and entry_hash and entry_hash.lower() == infohash.lower():
        return True
    entry_title = str(entry.get("title") or "").strip()
    return bool(title) and entry_title == title


@route("POST", r"/api/subscriptions/(?P<sid>\d+)/check")
def api_sub_check(q, body, sid):
    sub = subs.get(_int(sid))
    if sub is None:
        raise ApiError("订阅不存在", 404)
    qbittorrent.login()
    try:
        result = watcher.check_subscription(sub, manual=True)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"检查失败：{e}", 502) from None
    return {"ok": True, "result": result, "subscription": sub.to_dict()}


@route("POST", r"/api/subscriptions/check-all")
def api_sub_check_all(q, body):
    qbittorrent.login()
    result = watcher.run_once(manual=True)
    return {"ok": True, "result": result}


@route("POST", r"/api/subscriptions/(?P<sid>\d+)/download")
def api_sub_manual_download(q, body, sid):
    """订阅详情里手动下载某一集（或整个合集）。

    qBittorrent 没开时不报错到底：先把资源存进待下载队列，返回 queued=true，
    等 qBittorrent 恢复连接后由巡检线程自动补下载（用户要求）。
    """
    body = body or {}
    sub = subs.get(_int(sid))
    if sub is None:
        raise ApiError("订阅不存在", 404)
    resource = body.get("resource") or {}
    res = _resource_from_payload(resource)
    if res is None or not res.magnet:
        raise ApiError("缺少资源信息或磁力链接")
    try:
        ok = watcher.download_resource(sub, res, reason="手动下载")
    except Exception as e:  # noqa: BLE001
        queued = bool(watcher._queue_failed(sub, res, res.episode, str(e)))
        if not queued:
            raise ApiError(f"下载失败：{e}", 502) from None
        return {
            "ok": True, "queued": True, "downloaded_now": False,
            "message": "qBittorrent 未连接，已加入待下载队列，恢复后会自动补下载",
            "queue": pending.summary(),
            "subscription": sub.to_dict(),
        }
    return {"ok": ok, "queued": False, "subscription": sub.to_dict(), "queue": pending.summary()}


# --------------------------------------------------------------------------- #
# 待下载队列（qBittorrent 掉线期间攒下的资源）
# --------------------------------------------------------------------------- #
@route("GET", r"/api/queue")
def api_queue(q, body):
    return {"ok": True, **pending.summary()}


@route("POST", r"/api/queue/flush")
def api_queue_flush(q, body):
    """立刻尝试补下载（界面上「重试」按钮）。qBittorrent 还没起来就返回错误原因。"""
    result = watcher.flush_pending(manual=True)
    if result.get("error") and not result.get("flushed"):
        return {
            "ok": False, "error": f"qBittorrent 仍未连接：{result['error']}",
            "flushed": 0, "queue": pending.summary(),
        }
    return {"ok": True, "flushed": int(result.get("flushed") or 0),
            "remaining": int(result.get("remaining") or 0), "queue": pending.summary()}


@route("POST", r"/api/queue/delete")
def api_queue_delete(q, body):
    """从队列里删掉一条（或某部番的全部）待下载项。"""
    body = body or {}
    item_id = str(body.get("id") or "").strip()
    if item_id:
        removed = 1 if pending.remove(item_id) else 0
    elif body.get("subject_id") is not None:
        episode = _int(body.get("episode")) or None
        removed = pending.remove_subject(_int(body.get("subject_id")), episode)
    elif body.get("all"):
        removed = pending.clear()
    else:
        raise ApiError("请给出要删除的队列项（id / subject_id / all）", 400)
    return {"ok": True, "removed": removed, "queue": pending.summary()}


# --------------------------------------------------------------------------- #
# qBittorrent
# --------------------------------------------------------------------------- #
@route("GET", r"/api/qb/test")
def api_qb_test(q, body):
    return {"ok": True, **qbittorrent.test_connection()}


@route("POST", r"/api/qb/login")
def api_qb_login(q, body):
    cfg = (body or {}).get("qbittorrent")
    if cfg:
        config.update({"qbittorrent": cfg})
    ok = qbittorrent.login(force=True)
    info = qbittorrent.test_connection()
    return {"ok": ok or info.get("ok", False), "logged_in": ok, **info}


@route("GET", r"/api/qb/torrents")
def api_qb_torrents(q, body):
    try:
        items = qbittorrent.torrents(filter_=(q.get("filter") or ["all"])[0])
    except qbittorrent.QBError as e:
        raise ApiError(str(e), 502) from None
    out = []
    for t in items[:200]:
        out.append({
            "hash": t.get("hash"),
            "name": t.get("name"),
            "category": t.get("category"),
            "state": t.get("state"),
            "progress": round(float(t.get("progress") or 0) * 100, 1),
            "size": human_size(int(t.get("size") or 0)),
            "dlspeed": human_size(int(t.get("dlspeed") or 0)) + "/s",
            "eta": t.get("eta"),
            "save_path": t.get("save_path"),
        })
    return {"ok": True, "items": out, "total": len(items)}


@route("GET", r"/api/qb/folders")
def api_qb_folders(q, body):
    """列出下载根目录下已有的番剧文件夹（用于快速识别）。"""
    root = config.get("download.root", "")
    exists = os.path.isdir(root)
    dirs = []
    if exists:
        try:
            for name in sorted(os.listdir(root)):
                p = os.path.join(root, name)
                if os.path.isdir(p):
                    try:
                        size = sum(os.path.getsize(os.path.join(p, f))
                                   for f in os.listdir(p)
                                   if os.path.isfile(os.path.join(p, f)))
                    except OSError:
                        size = 0
                    dirs.append({"name": name, "path": p, "size": human_size(size)})
        except OSError as e:
            raise ApiError(f"读取下载目录失败：{e}", 500) from None
    return {"ok": True, "root": root, "root_exists": exists, "folders": dirs}


@route("POST", r"/api/qb/open-folder")
def api_open_folder(q, body):
    """在资源管理器中打开番剧目录。"""
    path = (body or {}).get("path") or ""
    path = os.path.abspath(path)
    root = os.path.abspath(config.get("download.root", "") or os.path.abspath("."))
    if not path.startswith(root):
        raise ApiError("只能打开下载根目录内的文件夹", 403)
    if not os.path.isdir(path):
        raise ApiError("目录不存在", 404)
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except OSError as e:
        raise ApiError(f"打开失败：{e}", 500) from None
    return {"ok": True}


# --------------------------------------------------------------------------- #
# 状态与日志
# --------------------------------------------------------------------------- #
@route("GET", r"/api/status")
def api_status(q, body):
    qb_info = qbittorrent.test_connection()
    lan_on = bool(config.get("server.allow_lan", False)) or config.get("server.host", "") in ("0.0.0.0", "::")
    port = int(config.get("server.port", 7788) or 7788)
    return {
        "ok": True,
        "version": "1.2",
        "token_set": bool(config.bangumi_token()),
        "token_url": bangumi.TOKEN_URL,
        "qb": qb_info,
        "proxy": {
            "enabled": config.get("proxy.enabled", False),
            "url": config.get("proxy.url", ""),
            "for_bangumi": config.get("proxy.for_bangumi", True),
            "for_sources": config.get("proxy.for_sources", True),
            "qb_proxied": False,
        },
        "download_root": config.get("download.root", ""),
        "sources": config.enabled_sources(),
        "watcher": watcher.status(),
        "queue": pending.summary(),
        "subscriptions": len(subs.all_subs()),
        "warmup": warmup.status(),
        "cache_enabled": cache.enabled(),
        "network_hint": network_hint(),
        # 局域网访问：开了才把这些地址显示给用户（手机/平板照着填）
        "lan_enabled": lan_on,
        "lan_port": port,
        "lan_urls": [f"http://{ip}:{port}/" for ip in lan_ipv4_addresses()] if lan_on else [],
        # 关键词学习：学到了多少部番「哪个写法真能搜到资源」（见 core/keywords.py）
        "keyword_learning": keywords_store.stats(),
        # 番剧更新时刻数据（bangumi-data 缓存，每天刷新一次）
        "airtime": airtimes.status(),
    }


def network_hint() -> dict:
    """
    网络连通性提示：直连不通但代理通时，明确告诉用户「去开代理」。
    只在国内网络/无梯子场景下才会触发，正常环境返回 {"level": "ok"}。
    """
    proxy_enabled = bool(config.get("proxy.enabled", False))
    proxy_url = (config.get("proxy.url") or "").strip()
    try:
        direct = http.probe(f"{bangumi.API_BASE}/v0/subjects/1", proxy=None,
                            timeout=5.0, ttl=180, key="probe:bgm:direct")
        if direct.get("ok"):
            return {"level": "ok", "direct_ok": True,
                    "message": "", "proxy_enabled": proxy_enabled}
        if proxy_enabled and proxy_url:
            via = http.probe(f"{bangumi.API_BASE}/v0/subjects/1", proxy=proxy_url,
                             timeout=8.0, ttl=180, key="probe:bgm:proxy")
            if via.get("ok"):
                return {"level": "warn", "direct_ok": False, "proxy_ok": True,
                        "message": f"直连 Bangumi 失败，但通过代理 {proxy_url} 可以访问："
                                   f"当前已在用代理，功能正常。",
                        "proxy_enabled": True}
            return {"level": "error", "direct_ok": False, "proxy_ok": False,
                    "message": f"直连与代理（{proxy_url}）都无法访问 Bangumi，"
                               f"请检查网络或代理设置。",
                    "proxy_enabled": True}
        # 直连不通、代理没开 -> 探测本机常见代理端口，给出可直接照做的建议
        suggestions = []
        for cand in ("http://127.0.0.1:7890", "http://127.0.0.1:7897", "http://127.0.0.1:10809"):
            if http.probe(f"{bangumi.API_BASE}/v0/subjects/1", proxy=cand, timeout=6.0,
                          ttl=180, key=f"probe:bgm:{cand}").get("ok"):
                suggestions.append(cand)
        if suggestions:
            msg = (f"直连 Bangumi 超时，但检测到本机代理 {suggestions[0]} 可用："
                   f"请在「设置 → 代理设置」勾选「启用代理」并把地址填成 {suggestions[0]}。")
        else:
            msg = "直连 Bangumi 超时，且未检测到可用代理：请检查网络，或在「设置 → 代理设置」里填写你的代理地址。"
        return {"level": "error", "direct_ok": False, "proxy_ok": None,
                "suggestions": suggestions, "message": msg, "proxy_enabled": False}
    except Exception as e:      # noqa: BLE001 - 提示功能不该影响状态接口
        return {"level": "unknown", "message": f"连通性检测失败：{e}", "proxy_enabled": proxy_enabled}


@route("GET", r"/api/logs")
def api_logs(q, body):
    n = _int((q.get("n") or ["200"])[0], 200)
    return {"ok": True, "lines": logger.tail(min(max(n, 10), 1000))}


@route("GET", r"/api/cover")
def api_cover(q, body):
    """封面代理：允许的图片域名 + 本地磁盘缓存。"""
    url = (q.get("url") or [""])[0]
    if not url:
        raise ApiError("缺少 url")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in _ALLOWED_IMAGE_HOSTS:
        raise ApiError("不允许的图片地址", 403)
    os.makedirs(COVER_DIR, exist_ok=True)
    name = hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img"
    path = os.path.join(COVER_DIR, name)
    if not os.path.exists(path):
        try:
            data = http.download_bytes(url, proxy=config.proxy_for("bangumi"), timeout=25)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except (OSError, http.HttpError, ValueError):
            raise ApiError("图片下载失败", 502) from None
    with open(path, "rb") as f:
        data = f.read()
    ctype = mimetypes.guess_type(path)[0] or "image/jpeg"
    if data[:3] == b"\xff\xd8\xff":
        ctype = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ctype = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ctype = "image/webp"
    return RawResponse(data, ctype, cache_seconds=86400)


# --------------------------------------------------------------------------- #
# HTTP 处理
# --------------------------------------------------------------------------- #
class RawResponse:
    def __init__(self, data: bytes, content_type: str, cache_seconds: int = 0, status: int = 200):
        self.data = data
        self.content_type = content_type
        self.cache_seconds = cache_seconds
        self.status = status


class Handler(BaseHTTPRequestHandler):
    server_version = "AnimeAutoDL/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ #
    def log_message(self, fmt, *args):  # 静默访问日志（写入 app.log 由业务日志负责）
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_PUT(self):
        self._dispatch("PUT")

    # ------------------------------------------------------------------ #
    def _dispatch(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                self._handle_api(method, path, query)
            else:
                self._handle_static(path)
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.error("请求处理异常 %s %s: %s", method, path, e)
            try:
                self._send_json(500, {"ok": False, "error": f"服务器内部错误：{e}"})
            except OSError:
                pass

    def _read_body(self) -> Any:
        length = _int(self.headers.get("Content-Length"), 0)
        if length <= 0:
            return {}
        if length > 20 * 1024 * 1024:
            raise ApiError("请求体过大", 413)
        raw = self.rfile.read(length)
        ctype = (self.headers.get("Content-Type") or "").lower()
        text = raw.decode("utf-8", "replace")
        if "application/json" in ctype or text.strip().startswith(("{", "[")):
            try:
                return json.loads(text) if text.strip() else {}
            except json.JSONDecodeError:
                raise ApiError("JSON 解析失败") from None
        return {k: v[0] for k, v in urllib.parse.parse_qs(text).items()}

    def _handle_api(self, method: str, path: str, query: dict) -> None:
        handler, params = router.match(method, path)
        if handler is None:
            # 路径存在但方法不对时给出更明确提示
            for m, regex, _h in router.routes:
                if regex.match(path):
                    self._send_json(405, {"ok": False, "error": f"该方法不支持 {method}，请使用 {m}"})
                    return
            self._send_json(404, {"ok": False, "error": f"未知接口：{path}"})
            return
        body = self._read_body() if method in ("POST", "PUT", "DELETE") else {}
        try:
            result = handler(query, body, **(params or {})) if params else handler(query, body)
        except ApiError as e:
            self._send_json(e.status, {"ok": False, "error": e.message})
            return
        except bangumi.BangumiError as e:
            self._send_json(401, {"ok": False, "error": str(e)})
            return
        except qbittorrent.QBError as e:
            self._send_json(502, {"ok": False, "error": str(e)})
            return
        except (http.HttpError, OSError, ValueError) as e:
            logger.warn("接口 %s 执行失败：%s", path, e)
            self._send_json(502, {"ok": False, "error": str(e)})
            return
        if isinstance(result, RawResponse):
            self._send(result.status, result.data, result.content_type, result.cache_seconds)
        else:
            self._send_json(200, result)

    def _handle_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        # 防目录穿越
        safe = posixpath.normpath(path).lstrip("/")
        if safe.startswith("..") or os.path.isabs(safe):
            self._send(403, b"forbidden", "text/plain")
            return
        full = os.path.join(config.WEB_DIR, *safe.split("/"))
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        if safe.endswith(".html"):
            # 资源引用带版本号：改了 CSS/JS 之后浏览器不会再用旧缓存，
            # 用户不需要手动 Ctrl+F5（之前踩过「新 JS + 旧 CSS」把下拉渲染成白色大方块的坑）
            data = data.replace(b"__APP_VERSION__", _ASSET_VERSION.encode("ascii"))
            # HTML 本身绝不能长缓存：否则改完界面，用户刷新拿到的还是旧 HTML，
            # 新元素（比如手动搜索框）根本不出现 —— 用户以前就抱怨过「为什么我的 UI 还没有变」。
            # 用 ETag + no-cache：每次刷新都向服务器确认，没变就是 304，几乎不花时间。
            etag = '"' + hashlib.sha1(data).hexdigest()[:16] + '"'
            if (self.headers.get("If-None-Match") or "").strip() == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache, must-revalidate")
                self.end_headers()
                return
            self._send(200, data, ctype, 0, etag=etag,
                       cache_control="no-cache, must-revalidate")
            return
        # 带 ?v= 的资源（app.js / styles.css / ui.js）：内容变了 URL 就变，可以放心长缓存
        cache = 3600 if _ASSET_VERSION else 0
        self._send(200, data, ctype, cache)

    # ------------------------------------------------------------------ #
    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, data, "application/json; charset=utf-8")

    def _send(self, status: int, data: bytes, ctype: str, cache_seconds: int = 0,
              etag: str = "", cache_control: str = "") -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            else:
                self.send_header("Cache-Control",
                                 f"public, max-age={cache_seconds}" if cache_seconds else "no-store")
            if etag:
                self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD" and data:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def _meta_refresh_loop() -> None:
    """每 24 小时把过期的 Bangumi 元数据刷一遍（首播日/总话数/别名变了也能跟上）。"""
    while True:
        try:
            stale = meta.stale_ids(limit=50)
            if stale:
                for sid in stale:
                    try:
                        # force：缓存里那批老记录别名不全（来自「在看」列表，没有 infobox「别名」），
                        # 不强制联网就永远刷不出「凡人修仙传 慕兰之战篇」这类篇章名
                        bangumi.get_subject(sid, token=config.bangumi_token() or None, force=True)
                    except Exception as e:      # noqa: BLE001
                        logger.debug("刷新番剧 %s 元数据失败：%s", sid, e)
                        break
                logger.info("Bangumi 元数据已刷新 %d 条", len(stale))
        except Exception as e:                  # noqa: BLE001
            logger.warn("元数据后台刷新异常：%s", e)
        time.sleep(24 * 3600)


def serve_forever(host: str, port: int) -> ThreadingHTTPServer:
    global _mimetypes_added
    if not _mimetypes_added:
        mimetypes.add_type("application/javascript", ".js")
        mimetypes.add_type("text/css", ".css")
        mimetypes.add_type("image/webp", ".webp")
        _mimetypes_added = True
    httpd = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=_meta_refresh_loop, name="bangumi-meta", daemon=True).start()
    httpd.daemon_threads = True
    return httpd
