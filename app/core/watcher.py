# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
自动追番引擎：
- 定期按「字幕组 + 番剧名」搜索（搜不到自动回退到只用番剧名）
- 发现比已下载集数更新的剧集就交给 qBittorrent 下载
- 只保留订阅所选字幕组的资源（站点搜索是模糊匹配，别的组会被带进来）
- 每个番剧一个目录：<下载根目录>/<Bangumi 简体名>
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

from . import bangumi, config, http, logger, pending, qbittorrent, rules, subs
from .bangumi import Subject
from .util import in_current_season, parse_episode, season_hit
from ..sources import engine
from ..sources.base import Resource, extract_group, resolution_matches

_lock = threading.RLock()
_running = False
_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_pending_thread: Optional[threading.Thread] = None
_last_run = 0.0
_next_run = 0.0
_status: dict = {"running": False, "last_run": 0.0, "last_summary": "", "checked": 0, "downloaded": 0}


# --------------------------------------------------------------------------- #
# 资源挑选
# --------------------------------------------------------------------------- #
def _site_priority(source_id: str) -> int:
    """站点优先级（数字越小越优先；1 = 动漫花园）。"""
    for conf in config.enabled_sources():
        if conf.get("id") == source_id:
            return int(conf.get("priority", 99))
    return 99


def score_resource(r: Resource, preferred_resolution: str = "1080p") -> tuple:
    """
    自动下载的打分顺序（与用户约定一致）：
    1) 站点优先级（动漫花园 > 爱恋动漫 > Nyaa）
    2) 分辨率是否符合偏好
    3) 做种数
    4) 体积（更小者优先，避免误抓超大合集）
    """
    return (
        _site_priority(r.source),
        0 if resolution_matches(r.resolution, preferred_resolution) else 1,
        -(r.seeders if r.seeders is not None else -1),
        r.size_bytes,
    )


def pick_best(candidates: list[Resource], preferred_resolution: str = "1080p") -> Optional[Resource]:
    usable = [r for r in candidates if r.magnet]
    if not usable:
        return None
    return sorted(usable, key=lambda r: score_resource(r, preferred_resolution))[0]


def episode_of(r: Resource) -> Optional[int]:
    if r.episode is not None:
        return r.episode
    return parse_episode(r.title)


def season_context(sub: subs.Subscription) -> rules.SeasonContext:
    """这条订阅的季判定上下文（和资源列表弹窗同一个装配函数）。"""
    return rules.SeasonContext.load(sub.subject_id, sub=sub)


def make_subject(sub: subs.Subscription, ctx: rules.SeasonContext = None) -> Subject:
    """
    把订阅还原成 Subject，用于搜索关键词生成。

    关键词口径和资源弹窗一致：先用 Bangumi 缓存里的最新别名（含 infobox「别名」），
    订阅里存的别名作补充；缓存里没有别名才现场生成。
    """
    ctx = ctx or season_context(sub)
    s = Subject(id=sub.subject_id, name=sub.name_original, name_cn=sub.name,
                cover=sub.cover, total_episodes=ctx.total)
    s.aliases = list(ctx.aliases)
    if not s.aliases:
        from . import bangumi
        s.aliases = bangumi.build_aliases(s)
    s.folder_name = sub.display_name
    return s


#: 字幕语言归一化（标题里常见写法 → chs/cht/both/jp）
_LANG_ALIASES = {
    "chs": "chs", "sc": "chs", "简体": "chs", "简中": "chs", "简": "chs", "gb": "chs",
    "cht": "cht", "tc": "cht", "繁体": "cht", "繁中": "cht", "繁": "cht", "big5": "cht",
    "both": "both", "简繁": "both", "简繁日": "both", "chs&cht": "both", "简日双语": "both",
    "jp": "jp", "日文": "jp", "生肉": "jp", "raw": "jp",
}


def _norm_lang(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return ""
    return _LANG_ALIASES.get(key, key)


def lang_matches(resource_lang: object, wanted: object) -> bool:
    """精确匹配：选简体就只要简体（简繁/繁体都不算），未标注只匹配「未标注」。"""
    want = _norm_lang(wanted)
    if not want:
        return True
    have = _norm_lang(resource_lang)
    if want == "unknown":
        return have == ""
    return have == want


def search_for(sub: subs.Subscription) -> engine.SearchOutcome:
    """搜索 + **和页面/补下载完全同一套季判定与集号换算**（core.rules.filter_items）。"""
    ctx = season_context(sub)
    subject = make_subject(sub, ctx)
    outcome = engine.search_by_subject(
        subject,
        source_ids=sub.source_ids or None,
        group=sub.group or "",
        group_first=bool(sub.group) or None,
        # 订阅里选的字幕语言：既作为站内搜索后缀（dmhy/kisssub 支持），也在下面按结果再筛一次
        lang=(sub.lang or ""),
        # 订阅里存了手动搜索关键词就只用它（用户手动搜到的那条资源，自动追新也按这个找）
        keyword=(sub.custom_keyword or ""),
    )
    kept, offset, hidden = rules.filter_items(outcome.resources, ctx)
    if hidden:
        logger.debug("[%s] 自动追番按季判定排除 %d 条（首播 %s）",
                     sub.display_name, hidden, ctx.air_date or "未知")
    outcome.resources = kept
    return outcome


# --------------------------------------------------------------------------- #
# 下载执行
# --------------------------------------------------------------------------- #
def _folder_of(sub: subs.Subscription) -> str:
    return sub.folder or subs.default_folder(sub.display_name)


def download_resource(sub: subs.Subscription, res: Resource, *, reason: str = "自动追番",
                      episode: Optional[int] = None) -> bool:
    """
    把一条资源交给 qBittorrent，并记录到订阅。

    episode: 记账用的集号。默认取标题里的编号，但发布组用「系列连续编号」时
    调用方会传本季编号（标题里的 49 记成第 1 集），订阅进度才不会变成「49 / 12 集」。
    """
    if not res.magnet:
        return False
    cfg = config.load()
    qb_cfg = cfg.get("qbittorrent", {}) or {}
    folder = _folder_of(sub)
    category = qb_cfg.get("category", "") or ""
    tags = qb_cfg.get("tags", "") or ""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        logger.warn("创建下载目录失败 %s：%s", folder, e)

    # 番剧目录 = D:\Anime\<简体名> 已经是「一部番一个文件夹」，
    # 默认不要再包一层（与手动添加磁链一致）；只有显式开启才用 Subfolder
    subfolder = "true" if qb_cfg.get("create_subfolder", False) else "false"
    qbittorrent.ensure_category(category, os.path.dirname(folder))
    qbittorrent.add_magnet(
        res.magnet, save_path=folder, category=category, tags=tags,
        paused=bool(qb_cfg.get("start_paused", False)), subfolder=subfolder,
    )
    ep = episode if episode is not None else episode_of(res)
    # 记账一律用「本季集号」：手动下载（资源列表里的「下载」/「补下载单集」）传进来的是
    # 标题原始编号（药屋第三季 49/50、冰之城墙第二季 15），不换算进度就会变成 50 / 12 集
    raw_ep = ep
    ep = normalize_episode_number(ep, sub.episode_offset, sub.total_episodes)
    sub.mark_downloaded(res.infohash or res.key, res.title, ep)
    sub.add_history({
        "time": time.time(),
        "title": res.title,
        "source": res.source_name or res.source,
        "group": res.group,
        "resolution": res.resolution,
        "size": res.size_text,
        "episode": ep,
        "episode_absolute": raw_ep if raw_ep != ep else None,
        "magnet": res.magnet[:600],
        "folder": folder,
        "reason": reason,
    })
    logger.info("已添加下载：[%s] %s → %s", res.group or res.source_name, res.title[:70], folder)
    return True


_RELEASE_NOISE = re.compile(r"[\s\[\]【】()（）\-_.]+")


def _release_key(r: Resource) -> str:
    """把标题归一化成「同一条发布」的指纹：去括号/空格/标点、忽略站点前缀，只比内容。"""
    text = str(getattr(r, "title", "") or "").lower()
    text = re.sub(r"^\[[^\]]*\]\s*", "", text)          # 去掉开头的 [字幕组]/[站点]
    return _RELEASE_NOISE.sub("", text)[:160]


def _new_candidates(sub: subs.Subscription, outcome: engine.SearchOutcome, *,
                    ctx: "rules.SeasonContext | None" = None,
                    air_date: str = "", total_episodes: int = 0,
                    sub_season: int = 0, start_ep: int = 0,
                    tokens=None) -> list[Resource]:
    """筛选出「比已下载集数更新」的单集资源。

    季判定/起点直接用 rules.SeasonContext（和资源列表弹窗同一口径）：
    起点优先用 Bangumi 章节表，命中本季标识（第N季/Season N/篇章名）的资源直接算本季。
    """
    cfg = config.load()
    min_seeders = int(config.get("download.min_seeders", 0) or 0)
    per_source_limit = int(config.get("search.per_source_limit", 100) or 100)
    used_per_source: dict[str, int] = {}
    ctx = ctx or season_context(sub)
    total = total_episodes or ctx.total
    sub_season = sub_season or ctx.sub_season
    air_date = air_date or ctx.air_date
    tokens = ctx.tokens if tokens is None else tokens
    start_ep = start_ep or ctx.start_ep
    # 搜索关键词里已经不带「第几季」了（用户要求，能多搜到一堆结果），
    # 所以这里必须自己认季：先判出本季起点，再把不属于本季的资源全部挡掉 ——
    # 药屋少女的呢喃第三季（12 话）用系列连续编号 49，以前的实现会把第 1/2 季的 1~48 也当成候选。
    if start_ep and start_ep > 0:
        base = int(start_ep)
        offset = base - 1
    else:
        # 拿不到章节表起点才退回「从资源集号推断」，这条规则和弹窗共用 rules.resolve_base
        offset, base = rules.resolve_base(ctx, outcome.resources, total=total,
                                          sub_season=sub_season, air_date=air_date)
    # 订阅里记的集号可能是老数据（系列连续编号，药屋第三季记成 49）：比较前先换算成本季编号
    last_rel = sub.last_episode
    if offset and base and last_rel >= base:
        last_rel -= offset
    # 已经下载过的集数（历史记录）—— 同一集不再重复下（换版本/换站点都不重复）
    done_eps: set[int] = set()
    for h in (sub.history or []):
        ep = h.get("episode")
        if isinstance(ep, int) and ep > 0:
            done_eps.add(ep)

    items: list[Resource] = []
    seen_title: set[str] = set()          # 同一部番的同一发布（两个站都有）只留一条
    for r in outcome.resources:
        if not r.magnet or r.is_noise:
            continue
        if r.is_batch:
            continue                       # 合集不自动下载（避免重复拉全季）
        # 订阅指定了字幕组时**必须**只留该组的资源：站点搜索是模糊匹配，
        # 用「[ANi] 番名」去 Nyaa 搜照样会带回别的组（用户反馈：选了 ANi 却下到 [AnoZu] 第 3 集）。
        # 组名没解析出来时从标题里现取一次，避免因为解析失败把该组的资源误杀。
        if sub.group and not engine._group_match(r.group or extract_group(r.title), sub.group):
            continue
        # 订阅里选的字幕语言：选简体时，繁体/简繁/英文/生肉一律不要（用户明确要求「选什么就订什么」）
        if sub.lang and not lang_matches(getattr(r, "lang", ""), sub.lang):
            continue
        # 季判定和资源列表一致：标题命中本季标识（篇章名等）就直接算本季，
        # 否则再按「别的季 / 集号区间」判断
        token_hit = bool(tokens) and season_hit(r.title or "", tokens)
        if not token_hit and not in_current_season(r, base=base, total_episodes=total,
                                                   sub_season=sub_season, air_date=air_date):
            continue                       # 标题写了别的季 / 集号不在本季区间
        rel_ep = normalize_episode_number(r.episode, offset, total)
        if rel_ep is not None and rel_ep < 1:
            continue                       # 换算后是 0/负数：上季或编号错位，不下载
        if rel_ep and rel_ep in done_eps:
            continue                       # 这一集已经下过了
        if rel_ep and last_rel and rel_ep <= last_rel:
            continue                       # 硬校验：不往回下载（只追比已下载更新的集）
        key = _release_key(r)
        if key in seen_title:
            continue                       # 两个站返回了同一条发布（标题一样），只留先出现的那条
        seen_title.add(key)
        if sub.resolution and not resolution_matches(r.resolution, sub.resolution):
            continue
        if min_seeders and (r.seeders is not None) and r.seeders < min_seeders:
            continue
        key = (r.infohash or r.key)
        if key in sub.downloaded:
            continue
        ep = episode_of(r)
        if ep is None:
            continue
        rel = (ep - offset) if (offset and base and ep >= base) else ep
        if last_rel and rel <= last_rel:
            continue
        # 每个站点最多参与候选的条数，避免单站刷屏挤掉其他站
        if used_per_source.get(r.source, 0) >= per_source_limit:
            continue
        used_per_source[r.source] = used_per_source.get(r.source, 0) + 1
        items.append(r)
    return items


def _group_by_episode(items: list[Resource], offset: int = 0, base: int = 0) -> dict[int, list[Resource]]:
    """按「本季集号」分桶：发布组用系列连续编号时这里就换算成本季编号。"""
    buckets: dict[int, list[Resource]] = {}
    for r in items:
        ep = episode_of(r)
        if ep is None:
            continue
        rel = (ep - offset) if (offset and base and ep >= base) else ep
        buckets.setdefault(rel, []).append(r)
    return buckets


def normalize_episode_number(episode: Optional[int], offset: int, total: int) -> Optional[int]:
    """
    把「标题里的原始集号」换算成本季集号。

    只在两种情况下换算（其余原样返回，绝不瞎猜）：
      - 订阅里存了偏移量（offset>0）且这个集号在偏移量之上 → 减掉偏移量
      - 集号大于总话数（明显是系列连续编号）→ 用偏移量换算
    """
    if episode is None:
        return None
    ep = int(episode)
    off = int(offset or 0)
    if off > 0 and ep > off:
        rel = ep - off
        if rel >= 1 and (not total or rel <= total):
            return rel
    return ep


def _normalize_last_episode(sub: subs.Subscription, offset: int, total: int,
                            old_offset: int = 0) -> Optional[int]:
    """
    修正订阅里的 `last_episode`（返回新值；不需要改返回 None）。

    为什么要单独修：进度显示成「50 / 12 集」就是这里没修正 —— 手动下载（资源列表里的
    「下载」/「补下载单集」）记的是标题原始编号，而检测到的偏移量会随可见资源漂移
    （药屋第三季 48→49、冰之城墙第二季 14→13），两边的口径对不上就会出现大于总话数的进度。
    这里逐个试「当前偏移量 / 订阅里存过的偏移量」，取落在 1..总话数 的那个。
    """
    cur = int(sub.last_episode or 0)
    if cur <= 0:
        return None
    if total and cur <= total and (not offset or cur <= offset):
        return None                      # 看起来已经是本季集号
    for off in (offset, old_offset):
        off = int(off or 0)
        if off <= 0 or cur <= off:
            continue
        rel = cur - off
        if rel >= 1 and (not total or rel <= total):
            return rel
    return None


def _queue_failed(sub: subs.Subscription, res: Resource, episode: Optional[int],
                  error: str) -> Optional[dict]:
    """
    下载失败（通常是 qBittorrent 没开）时把这条资源存进待下载队列。

    只存「连接不上/服务端错误」这类**重试有意义**的失败；磁力本身有问题（不是合法磁力）
    存了也没用，直接跳过。返回入队的那条（重复入队返回 None）。
    """
    cfg = config.load().get("queue", {}) or {}
    if not bool(cfg.get("enabled", True)):
        return None
    if not res.magnet or "磁力" in (error or ""):
        return None
    item = pending.make_item(
        subject_id=sub.subject_id, name=sub.display_name, folder=_folder_of(sub),
        episode=episode if episode is not None else episode_of(res),
        title=res.title, magnet=res.magnet, reason="自动追番",
        infohash=res.infohash or res.key, source=res.source_name or res.source,
        group=res.group, resolution=res.resolution, size=res.size_text, error=error,
    )
    stored = pending.add(item)
    if stored:
        pending.mark_try("", error)     # 队列状态也记下这次失败，界面能显示「最近一次失败」
        logger.warn("[%s] 第 %s 集先存进待下载队列，qBittorrent 恢复后自动补下载（原因：%s）",
                    sub.display_name, item.get("episode") or "?", error[:120])
    return stored


def _resource_of(item: dict) -> Resource:
    """把队列里的记录还原成 Resource（只用到真正下发的字段）。"""
    return Resource(
        source=item.get("source") or "",
        source_name=item.get("source") or "",
        title=item.get("title") or "",
        group=item.get("group") or "",
        resolution=item.get("resolution") or "",
        size_text=item.get("size") or "",
        magnet=item.get("magnet") or "",
        infohash=item.get("infohash") or "",
        episode=item.get("episode"),
    )


def flush_pending(*, manual: bool = False, limit: int = 0) -> dict:
    """
    尝试补下载队列里的资源（qBittorrent 恢复连接后调用）。

    先探一次 qBittorrent：连不上就只记一次状态、立刻返回，不逐条重试浪费时间；
    连上了就按加入顺序补，成功一条从队列里删一条。任何一条失败都停手（多半又掉线了）。
    """
    cfg = config.load().get("queue", {}) or {}
    if not bool(cfg.get("enabled", True)):
        return {"ok": False, "flushed": 0, "remaining": pending.count(), "error": "待下载队列已关闭"}
    items = pending.items()
    if not items:
        return {"ok": True, "flushed": 0, "remaining": 0, "error": "", "skipped": "队列为空"}
    max_flush = int(limit or cfg.get("max_per_flush", 5) or 5)
    result = {"ok": False, "flushed": 0, "remaining": len(items), "error": "", "items": []}

    # 先确认 qBittorrent 真的回来了（一次轻量请求，失败就立刻返回）
    try:
        qbittorrent.version()
    except Exception as e:                     # noqa: BLE001 - 连不上就是还没恢复
        msg = str(e)[:200]
        pending.mark_try("", msg)
        logger.debug("待下载队列：qBittorrent 仍未连接（%s），队列保留 %d 条", msg, len(items))
        result.update({"error": msg, "remaining": len(items)})
        return result

    all_subs = subs.all_subs()
    index = {s.subject_id: s for s in all_subs}
    changed = False
    for item in items[:max_flush]:
        item_id = str(item.get("id") or "")
        sub = index.get(int(item.get("subject_id") or 0))
        if sub is None:
            pending.remove(item_id)            # 番剧已取消订阅，队列里这条没意义了
            logger.info("待下载队列：番剧 #%s 已不在订阅里，丢弃这一条", item.get("subject_id"))
            changed = True
            continue
        pending.mark_try(item_id)
        try:
            download_resource(sub, _resource_of(item), reason="恢复补下载" if not manual else "手动补下载",
                              episode=item.get("episode"))
        except Exception as e:                 # noqa: BLE001
            msg = str(e)[:200]
            pending.mark_try(item_id, msg)
            logger.warn("[%s] 补下载第 %s 集失败：%s", sub.display_name, item.get("episode") or "?", msg)
            result["error"] = msg
            break
        pending.remove(item_id)
        result["flushed"] += 1
        result["items"].append({"subject_id": sub.subject_id, "name": sub.display_name,
                                "episode": item.get("episode"), "title": item.get("title")})
        changed = True

    if changed:
        subs.save_all(subs.all_subs())
    pending.mark_ok(result["flushed"])
    if result["flushed"]:
        logger.info("qBittorrent 已恢复：补下载 %d 集（队列还剩 %d 条）",
                    result["flushed"], pending.count())
    result["remaining"] = pending.count()
    result["ok"] = result["flushed"] > 0 or not result["error"]
    return result


def _pending_loop() -> None:
    """qBittorrent 恢复连接的巡检线程：队列非空时每 N 秒探一次，连上就补下载。"""
    logger.info("待下载队列巡检线程已启动（qBittorrent 恢复后自动补下载）")
    while not _stop.is_set():
        wait_s = 60
        try:
            cfg = config.load().get("queue", {}) or {}
            wait_s = max(10, int(cfg.get("retry_seconds", 60) or 60))
            if bool(cfg.get("enabled", True)) and pending.count():
                pending.prune()
                if pending.count():
                    flush_pending()
        except Exception as e:                 # noqa: BLE001
            logger.error("待下载队列巡检异常：%s", e)
        _stop.wait(wait_s)


def check_subscription(sub: subs.Subscription, *, manual: bool = False) -> dict:
    """检查单个订阅并下载新集。返回执行摘要。"""
    cfg = config.load()
    sub_cfg = cfg.get("subscription", {}) or {}
    max_eps = max(1, int(sub_cfg.get("max_episodes_per_round", 3)))
    # 严格按订阅筛选：订阅没限定分辨率就是「不限」，不再有全局默认偏好
    preferred = sub.resolution
    result = {"subject_id": sub.subject_id, "name": sub.display_name,
              "found": 0, "downloaded": 0, "queued": 0, "error": "", "items": []}
    try:
        outcome = search_for(sub)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"搜索失败：{e}"
        sub.last_check = time.time()
        sub.last_result = result["error"]
        subs.save_all(subs.all_subs())
        logger.warn("[%s] %s", sub.display_name, result["error"])
        return result

    result["found"] = len(outcome.resources)
    # 本季上下文（起点/总话数/首播日/第几季）和弹窗同一个装配函数
    ctx = season_context(sub)
    total = ctx.total
    candidates = _new_candidates(sub, outcome, ctx=ctx)
    offset, base = rules.resolve_base(ctx, candidates)
    # 订阅里记的「已下载集号」可能是老数据 / 手动下载记下的**标题原始编号**
    # （药屋第三季 49/50、冰之城墙第二季 15 这种），统一换算成本季集号
    fixed = _normalize_last_episode(sub, offset, total, old_offset=sub.episode_offset)
    if fixed is not None:
        logger.info("[%s] 已下载集号按本季换算：%d → %d", sub.display_name, sub.last_episode, fixed)
        sub.last_episode = fixed
    # 偏移是「发布组用系列连续编号」的换算依据：一旦定下来，别被一次判不出来的检查覆盖成 0
    if offset or base:
        sub.episode_offset = offset
    buckets = _group_by_episode(candidates, offset, base)

    # ---- 首次检查：按 initial_mode 决定历史剧集怎么处理 ----
    if not sub.primed:
        sub.primed = True
        if sub.initial_mode == subs.INITIAL_NONE:
            # 只追新：把当前已播出的最高集数记为基线，不下载历史
            if buckets:
                sub.last_episode = max(buckets.keys())
            sub.last_check = time.time()
            sub.last_new = 0
            sub.last_result = f"仅追新：基线设为第 {sub.last_episode} 集，不下载历史"
            subs.save_all(subs.all_subs())
            result["baseline"] = sub.last_episode
            return result
        if sub.initial_mode == subs.INITIAL_LATEST and buckets:
            buckets = {max(buckets): buckets[max(buckets)]}
        # INITIAL_ALL 保持全部候选，由下面的 max_eps 限制每轮数量
        mode_eps = sorted(buckets.keys())
        episodes = mode_eps[:max_eps] if sub.initial_mode == subs.INITIAL_ALL else mode_eps
    else:
        episodes = sorted(buckets.keys())[:max_eps]

    for ep in episodes:
        best = pick_best(buckets.get(ep, []), preferred)
        if best is None:
            continue
        try:
            if download_resource(sub, best, reason="手动检查" if manual else "自动追番"):
                result["downloaded"] += 1
                result["items"].append({
                    "episode": ep, "title": best.title, "source": best.source_name,
                    "group": best.group, "size": best.size_text,
                })
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)
            logger.warn("[%s] 第 %s 集下载失败：%s", sub.display_name, ep, e)
            # qBittorrent 没开（或临时连不上）时不能就这么算了：先把资源存进待下载队列，
            # 恢复连接后由巡检线程/下一轮检查自动补下载（用户要求）
            if _queue_failed(sub, best, ep, str(e)):
                result["queued"] = result.get("queued", 0) + 1
            break

    sub.last_check = time.time()
    sub.last_new = result["downloaded"]
    if result["downloaded"]:
        sub.last_result = f"新增 {result['downloaded']} 集"
    elif result.get("queued"):
        sub.last_result = f"qBittorrent 未连接，已排队 {result['queued']} 集，恢复后自动补下载"
    elif result["error"]:
        sub.last_result = result["error"]
    elif outcome.resources:
        sub.last_result = f"搜索到 {len(outcome.resources)} 条，无更新"
    else:
        sub.last_result = "未搜索到资源"
    subs.save_all(subs.all_subs())
    return result


# --------------------------------------------------------------------------- #
# 定时循环
# --------------------------------------------------------------------------- #
def run_once(manual: bool = False) -> dict:
    """对所有启用的订阅执行一轮检查。"""
    global _running, _last_run
    with _lock:
        if _running:
            return {"skipped": True, "reason": "上一轮检查仍在进行"}
        _running = True
    if manual:
        qbittorrent.login()
    summary = {"checked": 0, "downloaded": 0, "details": [], "started": time.time()}
    # 先看有没有 qBittorrent 掉线期间攒下的待下载项：连上了就先补上（每轮都顺手试一次）
    try:
        if pending.count():
            q = flush_pending()
            if q.get("flushed"):
                summary["flushed"] = q["flushed"]
                summary["downloaded"] += int(q.get("flushed") or 0)
    except Exception as e:  # noqa: BLE001 - 补下载失败不影响正常检查
        logger.warn("补下载待下载队列失败（继续常规检查）：%s", e)
    try:
        for sub in list(subs.all_subs()):
            if not sub.enabled:
                continue
            summary["checked"] += 1
            try:
                r = check_subscription(sub, manual=manual)
            except Exception as e:  # noqa: BLE001
                logger.error("[%s] 检查异常：%s", sub.display_name, e)
                r = {"subject_id": sub.subject_id, "name": sub.display_name, "error": str(e),
                     "downloaded": 0, "found": 0}
            summary["downloaded"] += r.get("downloaded", 0)
            summary["details"].append(r)
    finally:
        _running = False
        _last_run = time.time()
        summary["finished"] = _last_run
        summary["elapsed"] = round(_last_run - summary["started"], 1)
        _status.update({
            "running": False, "last_run": _last_run,
            "checked": summary["checked"], "downloaded": summary["downloaded"],
            "last_summary": f"检查 {summary['checked']} 部，下载 {summary['downloaded']} 集",
        })
        if summary["checked"]:
            logger.info("追番检查完成：%s", _status["last_summary"])
    return summary


def _loop() -> None:
    global _next_run
    logger.info("自动追番后台线程已启动")
    while not _stop.is_set():
        try:
            cfg = config.load()
            enabled = bool(cfg.get("subscription", {}).get("enabled", True))
            interval = max(5, int(cfg.get("subscription", {}).get("interval_minutes", 30))) * 60
            now = time.time()
            if enabled and now >= _next_run and subs.all_subs():
                _next_run = now + interval
                run_once(manual=False)
            else:
                if not _next_run:
                    _next_run = now + interval
        except Exception as e:  # noqa: BLE001
            logger.error("追番循环异常：%s", e)
        _stop.wait(30)


def start() -> None:
    global _thread, _pending_thread, _next_run
    with _lock:
        if not (_thread and _thread.is_alive()):
            _stop.clear()
            interval = max(5, int(config.get("subscription.interval_minutes", 30))) * 60
            _next_run = time.time() + interval
            _thread = threading.Thread(target=_loop, name="anime-watcher", daemon=True)
            _thread.start()
        # qBittorrent 恢复连接的巡检线程：即使追番循环在等下一轮，它也会每分钟探一次队列
        if not (_pending_thread and _pending_thread.is_alive()):
            _pending_thread = threading.Thread(target=_pending_loop, name="anime-pending", daemon=True)
            _pending_thread.start()


def stop() -> None:
    _stop.set()


def status() -> dict:
    cfg = config.load()
    with _lock:
        st = dict(_status)
    st["enabled"] = bool(config.get("subscription.enabled", True))
    # 注意：cfg 是嵌套 dict，点号路径必须走 config.get()，否则永远拿到默认值（曾经一直显示 30 分钟）
    st["interval_minutes"] = config.get("subscription.interval_minutes", 30)
    st["next_run"] = _next_run
    st["subscriptions"] = len(subs.all_subs())
    return st
