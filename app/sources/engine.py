# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
搜索调度：
- 按站点优先级（动漫花园 > 爱恋动漫 > Nyaa）并发搜索
- 关键词策略：先「字幕组 + 番剧名」，搜不到再单独用番剧名
- 跨站去重、字幕组汇总、按分辨率/做种数排序
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Optional

from ..core import config, http, keywords as keywords_store, logger
from ..core.bangumi import (
    Subject, alias_group_map, alias_groups_for_source, aliases_for_source,
)
from ..core.util import to_simplified
from .base import LANG_LABELS, Resource, apply_filters, dedupe, sort_resources
from .dmhy import DmhyAdapter
from .kisssub import KisssubAdapter
from .nyaa import NyaaAdapter

ADAPTERS: dict[str, type] = {
    DmhyAdapter.id: DmhyAdapter,
    KisssubAdapter.id: KisssubAdapter,
    NyaaAdapter.id: NyaaAdapter,
}

# 站点单次搜索的关键词数量上限（控制请求数与后台占用）
#: 每个站点最多搜几个写法。必须 >= 3：简体 / 繁体 / 英文三种语言各搜一次（用户要求）；
#: 给到 10/8/10 是因为「结果不够时应该继续换写法」——实测有番剧的正确罗马字排在第 5 位，
#: 上限 4 时会被截断，最后只搜到 1 条（用户反馈：黑暗召唤师在地下恋爱中）。
#: 实际用几个由配置 search.max_keyword_variants 决定（默认 8），这里只是硬上限。
_ALIAS_LIMIT = {"dmhy": 10, "kisssub": 8, "nyaa": 10}
#: 关键词预算下限（配置里写得比它小也按它走）
_KEYWORD_BUDGET = 10
#: 一个站点已经凑够这么多条就不再试下一个关键词（多数热门番 3~4 个关键词就停，省请求）
_ENOUGH_HITS = 5
#: 单个站点的关键词尝试**总时长**上限（秒）：站点抽风时别把一次搜索拖到十分钟
#: （实测：动漫花园整站超时 + 每词重试 → 10 个关键词跑了 582 秒，页面一直显示「正在搜索资源…」）
_SEARCH_BUDGET_SECONDS = 45


def get_adapter(source_conf: dict):
    cls = ADAPTERS.get(source_conf.get("id", ""))
    if cls is None:
        return None
    return cls(source_conf.get("base"))


# 站内搜索无意义的修饰符前缀（如 Bangumi 的 #标签名）
_JUNK_PREFIX = re.compile(r"^[#＃@＠]")


def normalize_group(name: str) -> str:
    """
    归一化字幕组名（仅做无损规范化，不删词）：
    去首尾括号、繁体转简体、去掉空白与常见分隔符、转小写。
    保留「字幕组/字幕社」等后缀，便于 UI 展示；匹配时的宽松处理放在 _group_match。
    """
    s = (name or "").strip()
    s = re.sub(r"^[\[【（(]+|[\]】）)]+$", "", s)
    s = to_simplified(s)
    s = re.sub(r"[\s_\-&＆+、,，。/\\|·.]+", "", s)
    return s.lower()


# 匹配时可忽略的字幕组后缀/修饰词（去掉后仍能互相匹配）
_GROUP_SUFFIX = re.compile(
    r"(字幕组|字幕社|汉化组|製作組|制作组|发布组|發佈組|压制组|壓制組|raws?|subs?|fansub|team|组|社)$",
    re.I,
)


def _strip_group_suffix(name: str) -> str:
    prev = None
    cur = name
    while prev != cur and len(cur) > 2:
        prev = cur
        cur = _GROUP_SUFFIX.sub("", cur)
    return cur or name


def _informative(name: str) -> bool:
    """
    这个名字是否「有足够信息量」，允许参与宽松的包含匹配。

    纯 ASCII 的短名不行：`ANi` 与 `AnoZu` 都归一化成几个小写字母，用「前 2 个字符相同」
    判等会把 AnoZu 当成 ANi（真实踩过：订阅选了 ANi，自动追番却下到了 [AnoZu] 的第 3 集）。
    中文两个字就有足够区分度（如「喵萌」），所以按「非 ASCII 或长度 ≥4」判断。
    """
    return len(name) >= 4 or not name.isascii()


def _group_match(res_group: str, want: str) -> bool:
    """
    字幕组匹配（跨站名称常有繁简、后缀差异）：
    1) 归一化后完全相等
    2) 去掉「字幕组」等后缀后相等
    3) 短名**有信息量**时互为子串（「天月動漫&發佈組」↔「天月动漫」、「喵萌奶茶屋」↔「喵萌」）
    4) 中日文名的前缀相似（「喵萌奶茶屋」↔「喵萌奶茶」这类写法差异）

    刻意**不做**的事：ASCII 短名之间不做前缀匹配 —— 旧规则对 2 个字符也生效，
    `ANi` 于是命中了 `AnoZu`，这是「选了 A 组却下了 B 组」的根因之一。
    """
    a, b = normalize_group(res_group), normalize_group(want)
    if not b:
        return True
    if not a:
        return False
    if a == b:
        return True

    sa, sb = _strip_group_suffix(a), _strip_group_suffix(b)
    if sa == sb:
        return True

    for x, y in ((sa, sb), (a, b)):
        if not x or not y:
            continue
        shorter, longer = (x, y) if len(x) <= len(y) else (y, x)
        if shorter == longer or (_informative(shorter) and shorter in longer):
            return True

    shorter = sa if len(sa) <= len(sb) else sb
    longer = sb if shorter is sa else sa
    if shorter and not shorter.isascii():        # 只有中日文名才做前缀相似
        for n in (4, 3, 2):
            if len(shorter) >= n and longer.startswith(shorter[:n]):
                return True
    return False


def usable_keywords(keywords: list[str], limit: int) -> list[str]:
    """过滤掉站内搜索无意义的关键词并截断数量。"""
    out: list[str] = []
    for k in keywords:
        k = (k or "").strip()
        if len(k) < 2 or _JUNK_PREFIX.match(k):
            continue
        if k not in out:
            out.append(k)
        if len(out) >= limit:
            break
    return out


class SearchOutcome:
    def __init__(self):
        self.resources: list[Resource] = []
        self.groups: list[str] = []
        self.source_status: dict[str, dict] = {}
        self.keywords_used: dict[str, list[str]] = {}
        self.elapsed: float = 0.0
        self.strategy: str = ""

    def to_dict(self) -> dict:
        return {
            "resources": [r.to_dict() for r in self.resources],
            "groups": self.groups,
            "source_status": self.source_status,
            "keywords_used": self.keywords_used,
            "elapsed": round(self.elapsed, 2),
            "strategy": self.strategy,
        }


def search_by_subject(subject: Subject, *, source_ids: Optional[Iterable[str]] = None,
                      group: str = "", group_first: Optional[bool] = None,
                      page: int = 1, lang: str = "", keyword: str = "") -> SearchOutcome:
    """
    按番剧搜索所有已启用站点。

    lang: 字幕语言偏好（'chs' | 'cht' | 'both' | ''），会作为站内原生搜索后缀传给
    支持的站点（dmhy / kisssub），并在结果里保留 lang 字段供 UI 二次筛选。
    keyword: 手动搜索关键词。给了就**只用这一个词**（不再展开番剧别名），
    用于自动搜索搜不到 / 想指定某条资源的情况；订阅会把它记住，之后自动追新也用它。
    """
    out = SearchOutcome()
    confs = [s for s in config.enabled_sources() if not source_ids or s["id"] in set(source_ids)]
    if not confs:
        out.strategy = "无可用资源站点"
        return out

    custom = (keyword or "").strip()
    want_group_first = config.get("subscription.search_group_first", True) \
        if group_first is None else group_first
    if custom:
        out.strategy = f"手动关键词「{custom}」"
    else:
        out.strategy = ("字幕组+番剧名" if (group and want_group_first) else "番剧名") + \
                       ("（搜不到自动回退番剧名）" if (group and want_group_first) else "")
    if lang:
        out.strategy += f" · {LANG_LABELS.get(lang, lang)}"

    started = time.time()

    def work(conf: dict) -> tuple[str, list[Resource], list[str], dict]:
        sid = conf["id"]
        adapter = get_adapter(conf)
        meta = {"id": sid, "name": conf.get("name", sid), "ok": True, "error": "",
                "count": 0, "keywords": []}
        if adapter is None:
            meta.update(ok=False, error="未实现的资源站")
            return sid, [], [], meta

        groups: dict[str, list[str]] = {}
        learned_kws: list[str] = []
        if custom:
            aliases = [custom]           # 手动搜索：用户给什么搜什么，不做别名展开
        else:
            alias_cap = max(1, int(config.get("search.max_keyword_variants", _KEYWORD_BUDGET)))
            groups = alias_groups_for_source(subject, sid) or {}
            # 预算：配置值优先，但不低于 _KEYWORD_BUDGET（老配置里存的是 4，会被迁移到 8），不高于站点硬上限
            budget = max(_KEYWORD_BUDGET, min(alias_cap, _ALIAS_LIMIT.get(sid, 3)))
            aliases = usable_keywords(aliases_for_source(subject, sid), budget)
            # 以前搜到过资源的关键词挪到最前面（用户实测：`Dark Summoner to Dekiteiru` 能搜到一堆，
            # 但排在候选表第 5 位被上限截断了）。学习记录保证「管用的关键词」永远排在最前。
            learned_kws = [k for k in keywords_store.learned(subject.id, sid) if k]
            if learned_kws:
                lset = set(learned_kws)
                aliases = learned_kws + [a for a in aliases if a not in lset]
        # 关键词 → 语言分组（chs/cht/en）：三种语言必须各搜一次，
        # 用户要求「三种搜索词（简体/繁体/英文）每种的结果都显示」，
        # 不能因为简体那组已经搜到东西就不搜繁体/英文
        group_of = alias_group_map(subject, sid) if not custom else {}
        wanted_groups = {k for k, v in groups.items() if v}
        used: list[str] = []
        collected: list[Resource] = []

        def run(kw: str, grp: str) -> list[Resource]:
            nonlocal failed
            used.append(f"{grp} + {kw}" if grp else kw)
            try:
                got = adapter.search(kw, group=grp, page=page, lang=lang)
            except (OSError, ValueError, http.HttpError) as e:
                meta["ok"] = False
                meta["error"] = str(e)[:200]
                failed = True
                logger.warn("[%s] 搜索失败（%s）：%s", sid, kw, e)
                return []
            if got and subject.id:
                keywords_store.record(subject.id, sid, kw, len(got))   # 记下「哪个关键词真管用」
                meta.setdefault("keyword_hits", {})[kw] = len(got)
            return got

        failed = False
        covered: set[str] = set()
        started = time.time()
        budget = float(config.get("search.budget_seconds", _SEARCH_BUDGET_SECONDS) or _SEARCH_BUDGET_SECONDS)

        def enough() -> bool:
            """三种语言都搜过了、而且条数够了才收手（否则继续换写法）。"""
            return (not wanted_groups or wanted_groups.issubset(covered)) and len(collected) >= _ENOUGH_HITS

        def stop_now() -> bool:
            """
            该不该停手：
              - 站点整站抽风（一个关键词就超时/50x）→ 别再拿剩下的关键词去打它
                （实测：动漫花园超时 + 每词重试，10 个关键词跑了 582 秒，页面一直转圈）
              - 或者整体已经超过时长预算
            """
            if failed:
                logger.warn("[%s] 该站点请求失败，停止继续换关键词（本次已试 %d 个）", sid, len(used))
                meta["stopped"] = "site_error"
                return True
            if time.time() - started > budget:
                logger.warn("[%s] 已用 %.0f 秒仍未凑够结果，停止继续换关键词（本次已试 %d 个）",
                            sid, time.time() - started, len(used))
                meta["budget_exceeded"] = True
                return True
            return False

        def mark(aliases_done: list[str]) -> None:
            for k in aliases_done:
                g = group_of.get(k)
                if g:
                    covered.add(g)

        # 阶段一：字幕组 + 关键词（用户指定了字幕组时优先这样搜；只从该组里挑，不混别的组）
        if group and want_group_first:
            for kw in aliases:
                got = run(kw, group)
                collected.extend(got)
                mark([kw])
                if any(_group_match(r.group, group) for r in got) and enough():
                    break
                if stop_now():
                    break
        if not collected or not any(_group_match(r.group, group) for r in collected):
            # 组里没搜到（或本来就不限组）→ 只按关键词搜，顺序是「简体 -> 繁体 -> 英文」交错，
            # 前三轮就覆盖三种语言；之后还有余量就继续换写法，直到 _ENOUGH_HITS 条或超时
            for kw in aliases:
                got = run(kw, "")
                collected.extend(got)
                mark([kw])
                if enough():
                    break
                if stop_now():
                    break

        meta["count"] = len(collected)
        meta["keywords"] = used
        return sid, collected, [], meta

    results: dict[str, list[Resource]] = {}
    max_workers = max(1, min(4, len(confs)))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="srch") as pool:
        futs = {pool.submit(work, c): c for c in confs}
        for fut in as_completed(futs):
            conf = futs[fut]
            try:
                sid, items, _, meta = fut.result()
            except Exception as e:  # 单个站点异常不影响整体
                logger.error("[%s] 搜索任务异常：%s", conf.get("id"), e)
                out.source_status[conf["id"]] = {
                    "id": conf["id"], "name": conf.get("name", ""), "ok": False,
                    "error": str(e)[:200], "count": 0, "keywords": [],
                }
                continue
            results[sid] = items
            out.keywords_used[sid] = list(meta.get("keywords") or [])
            out.source_status[sid] = meta

    # 按优先级合并
    ordered: list[Resource] = []
    for conf in confs:
        items = results.get(conf["id"]) or []
        if group:
            exact = [r for r in items if _group_match(r.group, group)]
            other = [r for r in items if not _group_match(r.group, group)]
            items = exact if exact else other
        ordered.extend(items)

    out.resources = dedupe(ordered)

    # 汇总字幕组（保持站点优先级顺序）
    seen: set[str] = set()
    for r in out.resources:
        g = (r.group or "").strip()
        n = normalize_group(g)
        if g and n and n not in seen and not r.is_noise:
            seen.add(n)
            out.groups.append(g)

    out.elapsed = time.time() - started
    return out


def filter_outcome(out: SearchOutcome, *, group: str = "", resolution: str = "",
                   source: str = "", min_seeders: int = 0,
                   drop_noise: bool = True, sort: bool = True) -> list[Resource]:
    """对搜索结果做 UI 侧筛选。"""
    items = out.resources
    if source:
        items = [r for r in items if r.source == source]
    if group:
        items = [r for r in items if _group_match(r.group, group)]
    items = apply_filters(items, resolution=resolution, min_seeders=min_seeders, drop_noise=drop_noise)
    if sort:
        items = sort_resources(items, "")     # 不再按全局分辨率偏好加权（严格按订阅筛选）
    return items


def collect_groups(subject: Subject, *, source_ids: Optional[Iterable[str]] = None,
                   by_source: bool = True) -> dict:
    """
    获取字幕组列表。

    by_source=True（默认，用户要求）：**按资源站分开**，同一个字幕组在几个站点出现就算几条。
      返回 {"groups": [{"name": "桜都字幕组", "source": "dmhy", "source_name": "动漫花园",
                        "count": 42, "team_id": "619", "value": "dmhy::桜都字幕组", "key": "..."}]}
    by_source=False：旧行为，跨站合并（同一个组只出现一次，sources 列出所有站点）。

    为什么默认要分开：不同站的同名组其实是不同的发布源，合集数量/命名/清晰度都不一样，
    合并成一条会让用户没法指定「只要动漫花园那家的」。
    """
    outcome = search_by_subject(subject, source_ids=source_ids, group="")

    if by_source:
        buckets: dict[tuple[str, str], dict] = {}
        for r in outcome.resources:
            g = (r.group or "").strip()
            if not g:
                continue
            key = (r.source, normalize_group(g))
            item = buckets.get(key)
            if item is None:
                item = {
                    "name": g,
                    "source": r.source,
                    "source_name": r.source_name or r.source,
                    "count": 0,
                    "team_id": getattr(r, "team_id", "") or "",
                    "sources": [r.source_name or r.source],
                    # value：给前端下拉用的唯一标识（站点 + 组名）
                    "value": f"{r.source}::{g}",
                }
                buckets[key] = item
            item["count"] += 1
            if not item["team_id"] and getattr(r, "team_id", ""):
                item["team_id"] = r.team_id
        # 站点保持配置里的优先级顺序，站点内按出现次数降序
        order = {c["id"]: c.get("priority", 99) for c in config.enabled_sources()}
        groups = sorted(buckets.values(),
                        key=lambda x: (order.get(x["source"], 99), -x["count"], x["name"]))
        return {"groups": groups, "status": outcome.source_status,
                "total": len(outcome.resources), "by_source": True}

    buckets: dict[str, dict] = {}
    for r in outcome.resources:
        g = (r.group or "").strip()
        if not g:
            continue
        key = normalize_group(g)
        item = buckets.setdefault(key, {"name": g, "sources": [], "count": 0, "team_id": ""})
        item["count"] += 1
        if r.source_name not in item["sources"]:
            item["sources"].append(r.source_name)
        if getattr(r, "team_id", "") and not item["team_id"]:
            item["team_id"] = r.team_id
    groups = sorted(buckets.values(), key=lambda x: (-x["count"], x["name"]))
    return {"groups": groups, "status": outcome.source_status,
            "total": len(outcome.resources), "by_source": False}
