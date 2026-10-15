# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""三条路径「同一套规则」的离线测试（核心：`app/core/rules.py` 是唯一入口）。

用户要求：首页卡片的筛选搜索、订阅里的补单集、自动追番的自动下载，
规则只写一处，改一处就全部生效。这里锁住三件事：

  1. 上下文（起点 / 别名 / 番名 / 标识）只装配一次，页面和追番拿到的完全一样
  2. 季判定 + 集号换算只有 `filter_items` 一个实现，dict 和 Resource 走同一条路
  3. 追番命中「篇章名」的资源不会被当成上一季丢掉
"""
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import meta, rules, subs, watcher  # noqa: E402
from app.sources import engine  # noqa: E402

_FANREN_META = {
    "subject_id": 607915,
    "name": "凡人修仙传 第五季",
    "name_cn": "凡人修仙传 第五季",
    "total_episodes": 52,
    "start_ep": 177,
    "end_ep": 228,
    "date": "2026-06-13",
    "aliases": ["凡人修仙传", "凡人慕兰之战", "凡人修仙传 慕兰之战篇", "凡人修仙传 第五季"],
}

_ITEMS = [
    {"source": "dmhy", "title": "[GM-Team][国漫][凡人修仙传 慕兰之战][2026][16][AVC][GB][1080P]",
     "episode": 16},
    {"source": "dmhy", "title": "[GM-Team][国漫][凡人修仙传 星海飞驰][2026][120][AVC][GB][1080P]",
     "episode": 120},
    {"source": "nyaa", "title": "[FSP DN] A Record of a Mortal’s Journey to Immortality - 196 (1080p)",
     "episode": 196},
    {"source": "dmhy", "title": "[LoliHouse] 凡人修仙传 第二季 - 30 [1080p]", "episode": 30},
]


def _sub(**kw) -> subs.Subscription:
    params = dict(subject_id=607915, name="凡人修仙传 第五季", name_original="",
                  total_episodes=52, last_episode=0, enabled=True)
    params.update(kw)
    return subs.Subscription(**params)


def _ctx(sub=None, payload=None):
    with mock.patch.object(meta, "get", return_value=dict(_FANREN_META)):
        return rules.SeasonContext.load(607915, sub=sub, payload=payload)


class SeasonContextTest(unittest.TestCase):
    def test_aliases_and_tokens_come_from_bangumi_cache(self):
        """订阅里只有番名时，缓存里的篇章名要能补上（否则关键词和季判定都缺一块）。"""
        sub = _sub(aliases=["凡人修仙传"])
        ctx = _ctx(sub)
        self.assertIn("凡人修仙传 慕兰之战篇", ctx.aliases)
        self.assertIn("慕兰之战", ctx.tokens)
        self.assertIn("第五季", ctx.tokens)
        self.assertEqual((ctx.start_ep, ctx.total), (177, 52))
        self.assertEqual(ctx.offset, 176)

    def test_page_payload_and_subscription_give_same_context(self):
        """页面（payload）和追番（sub）装配出来的上下文必须一致。"""
        sub = _sub(aliases=["凡人修仙传"])
        with mock.patch.object(meta, "get", return_value=dict(_FANREN_META)):
            page_ctx = rules.SeasonContext.load(607915, payload={
                "display_name": "凡人修仙传 第五季", "name_cn": "凡人修仙传 第五季",
                "total_episodes": 52, "date": "2026-06-13"})
            sub_ctx = rules.SeasonContext.load(607915, sub=sub)
        self.assertEqual(page_ctx.start_ep, sub_ctx.start_ep)
        self.assertEqual(page_ctx.total, sub_ctx.total)
        self.assertEqual(page_ctx.sub_season, sub_ctx.sub_season)
        self.assertEqual(page_ctx.tokens, sub_ctx.tokens)


class FilterItemsTest(unittest.TestCase):
    def test_same_result_for_dicts_and_resources(self):
        """dict（页面）和 Resource（追番）走同一个实现，结果必须一致。"""
        ctx = _ctx(_sub())
        as_dicts, off1, hid1 = rules.filter_items([dict(it) for it in _ITEMS], ctx)
        as_res = [engine.Resource(source=it["source"], source_name=it["source"],
                                  title=it["title"], episode=it["episode"]) for it in _ITEMS]
        kept, off2, hid2 = rules.filter_items(as_res, ctx)
        self.assertEqual((off1, hid1), (off2, hid2))
        self.assertEqual([it["episode"] for it in as_dicts], [r.episode for r in kept])
        self.assertEqual(hid1, 2, "星海飞驰 120 和 第二季 30 要隐藏")
        self.assertEqual([it["episode"] for it in as_dicts], [16, 20],
                         "篇章资源保留原本的 16；196 换算成第 20 集")

    def test_all_seasons_keeps_everything(self):
        ctx = _ctx(_sub())
        kept, offset, hidden = rules.filter_items([dict(it) for it in _ITEMS], ctx,
                                                  all_seasons=True)
        self.assertEqual((len(kept), hidden, offset), (4, 0, 176))
        self.assertEqual(kept[2]["episode"], 20, "关掉只看本季后集号照样换算")


class WatcherParityTest(unittest.TestCase):
    def test_new_candidates_uses_same_context(self):
        """追番的候选筛选直接吃 SeasonContext，命中篇章名的资源算本季。"""
        sub = _sub()
        with mock.patch.object(meta, "get", return_value=dict(_FANREN_META)):
            ctx = watcher.season_context(sub)
            out = engine.SearchOutcome()
            out.resources = [engine.Resource(source=it["source"], source_name=it["source"],
                                             title=it["title"], episode=it["episode"],
                                             magnet="magnet:?xt=urn:btih:" + str(i) * 8,
                                             seeders=10)
                             for i, it in enumerate(_ITEMS)]
            kept = [r.title for r in watcher._new_candidates(sub, out, ctx=ctx)]
        self.assertTrue(any("慕兰之战" in t for t in kept))
        self.assertFalse(any("星海飞驰" in t for t in kept))
        self.assertFalse(any("第二季" in t for t in kept))

    def test_make_subject_uses_cached_aliases(self):
        sub = _sub(aliases=["凡人修仙传"])
        with mock.patch.object(meta, "get", return_value=dict(_FANREN_META)):
            subject = watcher.make_subject(sub)
        self.assertIn("凡人修仙传 慕兰之战篇", subject.aliases)


if __name__ == "__main__":
    unittest.main()
