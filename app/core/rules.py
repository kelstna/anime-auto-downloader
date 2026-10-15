# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
资源挑选的**唯一规则入口**：首页卡片的筛选搜索、订阅里的补单集、自动追番的自动下载，
三条路都只经过这里。

以前「本季判定」在 `core/util.py`，但「起点/别名装配」在 `web/server.py` 和 `core/watcher.py`
各写一份，「集号换算」也跟着各写一遍 —— 改一条规则要动两三处。现在：

    ctx = SeasonContext.load(subject_id, ...)     # 起点 / 番名 / 别名（都取 Bangumi 缓存）
    kept, offset, hidden = filter_items(items, ctx)   # 季判定 + 集号换算

要改规则时只需要动两个文件：判定细节在 `util.apply_season_rules`（含 season_tokens /
in_current_season），装配与换算在本文件。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import meta
from .util import _item_field, apply_season_rules, resolve_episode_offset, season_of, season_tokens


def _push_unique(target: list[str], values) -> None:
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)


@dataclass
class SeasonContext:
    """一条番剧的季判定上下文（三条路共用同一份装配结果）。"""

    subject_id: int = 0
    start_ep: int = 0          # 本季第一集的「系列累计编号」（Bangumi 章节表 sort）
    end_ep: int = 0
    total: int = 0             # 本季总话数
    air_date: str = ""
    sub_season: int = 0        # 番剧自身是第几季（从名字里认）
    names: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    tokens: list = field(default_factory=list)

    @property
    def offset(self) -> int:
        """集号偏移 = 起点 - 1（凡人第五季 177 - 1 = 176）。"""
        return self.start_ep - 1 if self.start_ep and self.start_ep > 0 else 0

    @classmethod
    def load(cls, subject_id: int = 0, *, payload=None, sub=None, names=None,
             total_episodes: int = 0, sub_season: int = 0, air_date: str = "") -> "SeasonContext":
        """
        装配上下文。

        payload: 页面用的番剧 dict（display_name / name_cn / name / name_original / date）
        sub:     订阅对象（自动追番用；名字、别名、总话数从订阅里补）
        names / total_episodes / sub_season / air_date: 显式覆盖（调用方已有值时传进来）
        """
        item: dict = {}
        if subject_id:
            try:
                item = meta.get(int(subject_id)) or {}
            except Exception:                       # noqa: BLE001 - 缓存坏了不影响搜索
                item = {}

        ctx = cls(subject_id=int(subject_id or 0))
        # ---- 番剧名字（顺序：页面显示名 → 中文名 → 原名 → 订阅里的名字 → 缓存）----
        if isinstance(payload, dict):
            _push_unique(ctx.names, [payload.get("display_name"), payload.get("name_cn"),
                                     payload.get("name"), payload.get("name_original")])
        if sub is not None:
            _push_unique(ctx.names, [getattr(sub, "display_name", ""), getattr(sub, "name", ""),
                                     getattr(sub, "name_original", "")])
        _push_unique(ctx.names, [item.get("name_cn"), item.get("name"), names])

        # ---- 别名（Bangumi infobox 的「别名」也在这里，例如「凡人修仙传 慕兰之战篇」）----
        _push_unique(ctx.aliases, list(item.get("aliases") or []))
        if sub is not None:
            _push_unique(ctx.aliases, list(getattr(sub, "aliases", []) or []))
        if not ctx.aliases and ctx.subject_id:
            try:
                from . import bangumi
                cached = bangumi.get_subject(ctx.subject_id)
                _push_unique(ctx.aliases, list(getattr(cached, "aliases", []) or []))
            except Exception:                       # noqa: BLE001 - 拿不到别名就只靠番名
                pass

        # ---- 起点 / 总话数 / 首播日 ----
        try:
            ctx.start_ep = int(item.get("start_ep") or 0)
            ctx.end_ep = int(item.get("end_ep") or 0)
        except (TypeError, ValueError):
            ctx.start_ep = ctx.end_ep = 0
        ctx.total = int(total_episodes or 0) \
            or int(getattr(sub, "total_episodes", 0) or 0) \
            or int((payload or {}).get("total_episodes") or 0) \
            or int(item.get("total_episodes") or 0)
        # Bangumi 有时候 total_episodes 是 0（页面显示「0 话」），但章节表起止编号是有的
        if ctx.total < 1 and ctx.start_ep and ctx.end_ep >= ctx.start_ep:
            ctx.total = ctx.end_ep - ctx.start_ep + 1
        ctx.air_date = (str(air_date or "")
                        or str((payload or {}).get("date") or "")
                        or str(item.get("date") or ""))

        # ---- 「番剧自己是第几季」：从名字里认第一个带季数标记的 ----
        if sub_season:
            ctx.sub_season = int(sub_season)
        else:
            for name in ctx.names:
                found = season_of(name)
                if found:
                    ctx.sub_season = found
                    break

        ctx.tokens = season_tokens(ctx.names + ctx.aliases)
        return ctx


def _converted(item, offset: int):
    """把「系列累计集号」换算成本季集号。

    dict → 返回**副本**（附带 episode_absolute，页面要显示原始编号）；
    Resource 之类的对象 → 就地改（自动追番后面直接用它下载）。
    """
    if not offset:
        return item
    base = offset + 1
    ep = _item_field(item, "episode")
    if not isinstance(ep, int) or ep < base:
        return item
    if isinstance(item, dict):
        out = dict(item)
        out["episode_absolute"] = ep
        out["episode"] = max(1, ep - offset)
        end = out.get("episode_end")
        if isinstance(end, int) and end > 1 and end >= base:
            out["episode_end"] = max(1, end - offset)
        return out
    item.episode = max(1, ep - offset)
    end = getattr(item, "episode_end", None)
    if isinstance(end, int) and end > 1 and end >= base:
        item.episode_end = max(1, end - offset)
    return item


def filter_items(items, ctx: SeasonContext, *, total=None, sub_season=None, air_date=None,
                 all_seasons: bool = False, convert: bool = True):
    """
    季判定 + 集号换算（三条路唯一的实现）。

    返回 (保留的条目, 偏移量, 隐藏条数)。dict 条目返回换算后的副本，不会改入参；
    对象条目（Resource）就地改集号，方便直接拿去下载。

    all_seasons=True（页面关掉「只看本季」）：不隐藏任何资源，但集号换算照旧。
    """
    total = ctx.total if total is None else int(total or 0)
    sub_season = ctx.sub_season if sub_season is None else int(sub_season or 0)
    air_date = ctx.air_date if air_date is None else str(air_date or "")
    if all_seasons:
        keep, offset, hidden = list(range(len(items))), ctx.offset, 0
    else:
        keep, offset, hidden = apply_season_rules(
            items, total_episodes=total, sub_season=sub_season, air_date=air_date,
            start_ep=ctx.start_ep, aliases=ctx.aliases, names=ctx.names)
    kept = [_converted(items[idx], offset) if convert else items[idx] for idx in keep]
    return kept, offset, hidden


def resolve_base(ctx: SeasonContext, items, *, total=None, sub_season=None,
                 air_date=None) -> tuple[int, int]:
    """本季起点：优先 Bangumi 章节表；拿不到才退回「从资源集号推断」。返回 (offset, base)。"""
    if ctx.start_ep and ctx.start_ep > 0:
        return ctx.offset, ctx.start_ep
    return resolve_episode_offset(
        list(items),
        ctx.total if total is None else int(total or 0),
        ctx.sub_season if sub_season is None else int(sub_season or 0),
        ctx.air_date if air_date is None else str(air_date or ""))
