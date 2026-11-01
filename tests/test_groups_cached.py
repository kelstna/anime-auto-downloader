# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""批量订阅的字幕组候选（/api/groups/cached）要来自「预热缓存」，不能只来自「订阅」。

踩过的坑：候选以前只从 `subs.all_subs()` 的缓存汇总。用户把订阅清空之后，批量订阅的
字幕组下拉就只剩「不限字幕组」—— 34 部番明明都预热过（`data/cache/search_<id>.json`
里带着 `source` + `group`），却一个组都选不了。

现在的口径：
- 传了 `subject_ids` → 候选只来自这几部番的预热缓存；
- 没传 → 退回旧口径（订阅里已有番剧的缓存），两者取并集；
- 两边都没有 → 空列表（绝不凭空扫全库，那要解析 19 MB）。
"""
import unittest

from app.core import subs
from app.sources.base import Resource
from app.web import server as srv


def _resource_dict(source: str, group: str, title: str = "") -> dict:
    """造一条和缓存里同构的资源（enrich 会重算分辨率/语言/集数，给个能解析的标题）。"""
    return Resource(
        source=source,
        title=title or f"[{group}] 测试番 - 01 [1080p][简日]",
        group=group,
        magnet="magnet:?xt=urn:btih:" + "a" * 40,
    ).to_dict()


def _fake_any_age(by_id: dict):
    """替身：按番剧 id 返回 (payload, 年龄)，没有就是未命中。"""

    def search_any_age(subject_id, variant=""):
        payload = by_id.get(int(subject_id))
        return (payload, 12.0) if payload is not None else (None, 0.0)

    return search_any_age


class GroupsCachedFromWarmupTest(unittest.TestCase):
    """字幕组候选 = 预热缓存里的组，与「有没有订阅」无关。"""

    def setUp(self):
        self._saved_any_age = srv.warmup.search_any_age
        self._saved_all_subs = srv.subs.all_subs

    def tearDown(self):
        srv.warmup.search_any_age = self._saved_any_age
        srv.subs.all_subs = self._saved_all_subs

    def _patch(self, payloads: dict, sub_list=()):
        srv.warmup.search_any_age = _fake_any_age(payloads)
        srv.subs.all_subs = lambda: list(sub_list)

    # ---------------------------------------------------------------- #
    def test_groups_come_from_selected_subject_cache(self):
        """订阅是空的（用户刚清空）也要出候选：靠 subject_ids 指的预热缓存。"""
        self._patch({100: {"items": [_resource_dict("dmhy", "假组"),
                                     _resource_dict("nyaa", "另一个组")]}})
        out = srv.api_groups_cached({"subject_ids": ["100"]}, None)
        names = {g["name"] for g in out["groups"]}
        self.assertEqual(names, {"假组", "另一个组"},
                         f"订阅为空时也要从预热缓存给出字幕组，实际 {names}")

    def test_group_carries_source_and_count(self):
        """同一部番里同一个组出现两条 → count=2，且带站点 id/中文名（下拉要按站点过滤）。"""
        self._patch({100: {"items": [_resource_dict("dmhy", "假组"),
                                     _resource_dict("dmhy", "假组", "[假组] 测试番 - 02 [1080p][简日]")]}})
        out = srv.api_groups_cached({"subject_ids": ["100"]}, None)
        self.assertEqual(len(out["groups"]), 1, f"同站点同组应该合并成一条：{out['groups']}")
        g = out["groups"][0]
        self.assertEqual(g["count"], 2, "命中的资源条数要累计，用于排序")
        self.assertEqual(g["source"], "dmhy")
        self.assertTrue(g["source_name"], "站点中文名要回填，前端下拉靠它显示")

    def test_multiple_ids_merge_with_dedup(self):
        """勾选多部：组名跨番剧合并（同一个组只出现一次）。"""
        self._patch({
            100: {"items": [_resource_dict("dmhy", "共享组")]},
            200: {"items": [_resource_dict("dmhy", "共享组"),
                            _resource_dict("nyaa", "独有组")]},
        })
        out = srv.api_groups_cached({"subject_ids": ["100,200"]}, None)
        names = [g["name"] for g in out["groups"]]
        self.assertEqual(sorted(names), ["共享组", "独有组"], f"实际 {names}")
        shared = [g for g in out["groups"] if g["name"] == "共享组"][0]
        self.assertEqual(shared["count"], 2, "跨番剧的同组资源数要累加")

    def test_chinese_comma_and_spaces_tolerated(self):
        self._patch({100: {"items": [_resource_dict("dmhy", "假组")]}})
        out = srv.api_groups_cached({"subject_ids": [" 100， 200 "]}, None)
        self.assertEqual([g["name"] for g in out["groups"]], ["假组"],
                         "中文逗号和空格要能解析，200 没缓存就跳过")

    # ---------------------------------------------------------------- #
    def test_no_ids_and_no_subscriptions_returns_empty(self):
        """什么都不给、订阅也空：返回空（不能为了「看起来有料」去扫全库 19 MB）。"""
        self._patch({100: {"items": [_resource_dict("dmhy", "假组")]}})
        out = srv.api_groups_cached({}, None)
        self.assertEqual(out["groups"], [],
                         "没有 subject_ids、也没有订阅时不该凭空汇总其它番剧的缓存")

    def test_subscription_cache_still_participates(self):
        """旧口径保留：不传 subject_ids 时，订阅里已有番剧的缓存照样出候选。"""
        sub = subs.Subscription(subject_id=200, name="老订阅")
        self._patch({200: {"items": [_resource_dict("dmhy", "旧组")]}}, [sub])
        out = srv.api_groups_cached({}, None)
        self.assertEqual([g["name"] for g in out["groups"]], ["旧组"],
                         "订阅口径必须还能用（批量订阅之外没人传 subject_ids）")

    def test_subscription_and_selected_ids_are_union(self):
        """订阅 + 勾选同时存在 → 两边的组都在（并集，不互相覆盖）。"""
        sub = subs.Subscription(subject_id=200, name="老订阅")
        self._patch({
            100: {"items": [_resource_dict("dmhy", "勾选组")]},
            200: {"items": [_resource_dict("dmhy", "旧组")]},
        }, [sub])
        out = srv.api_groups_cached({"subject_ids": ["100"]}, None)
        self.assertEqual(sorted(g["name"] for g in out["groups"]), ["勾选组", "旧组"],
                         "订阅口径和勾选口径要合并")

    def test_ids_without_cache_are_ignored(self):
        self._patch({})
        out = srv.api_groups_cached({"subject_ids": ["999"]}, None)
        self.assertEqual(out["groups"], [], "没预热过的番剧就老实返回空，等前端提示")

    # ---------------------------------------------------------------- #
    def test_does_not_normalize_items(self):
        """候选只要 source/group：走了 normalize_items 会把弹窗拖慢 20 多秒。

        实测：34 部 × 约 5800 条资源重算派生字段要 22.7 秒，只读原始字段 2 毫秒。
        这是「打开批量订阅弹窗」的主路径，慢一次用户就以为页面卡死了。
        """
        calls = []
        original = srv.normalize_items
        srv.normalize_items = lambda items: calls.append(len(items or [])) or original(items)
        self._patch({100: {"items": [_resource_dict("dmhy", "假组")]}})
        try:
            out = srv.api_groups_cached({"subject_ids": ["100"]}, None)
        finally:
            srv.normalize_items = original
        self.assertEqual([g["name"] for g in out["groups"]], ["假组"], "候选还得正常出")
        self.assertEqual(calls, [], f"字幕组候选不该调用 normalize_items，实际调用了 {calls}")

    def test_falls_back_to_title_when_group_missing(self):
        """极旧条目没有 group 字段：从标题里提取，别整条丢掉。"""
        item = _resource_dict("dmhy", "假组")
        item.pop("group", None)
        self._patch({100: {"items": [item]}})
        out = srv.api_groups_cached({"subject_ids": ["100"]}, None)
        self.assertEqual([g["name"] for g in out["groups"]], ["假组"],
                         "group 缺失时要用标题里的 [组名] 兜底")


if __name__ == "__main__":
    unittest.main()
