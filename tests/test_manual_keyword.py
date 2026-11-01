# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""手动搜索（自定义关键词）的离线测试：不联网，用假适配器记录 engine 实际发出的关键词。

覆盖：
- engine.search_by_subject(keyword=...) 只发用户给的那一个词，不展开番剧别名
- 不带 keyword 时仍然按别名展开（回归保护）
- 字幕组限定时「组+词」优先、搜不到再退回单个词
- watcher.search_for() 会把订阅里的 custom_keyword 传给 engine（自动追新也用这个词）
- **自动追新只用手动关键词**：不要别名、也不要「关键词学习记录」里的词
- **字幕组候选（/api/groups）也用同一个关键词**：下拉里不能出现这个词搜不到的组
- **关键词口径的缓存绝不回退别名缓存**：否则「搜索框里的词」等于摆设
- Subscription.custom_keyword 的存取与向后兼容（老订阅文件没有这个键）
"""
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import subs, watcher  # noqa: E402
from app.core.bangumi import Subject  # noqa: E402
from app.sources import engine  # noqa: E402
from app.sources.base import Resource, enrich  # noqa: E402


class FakeAdapter:
    """记录 engine 实际调用的 (关键词, 字幕组) 组合，并按需返回一条资源。"""

    id = "dmhy"
    name = "假站点"
    native_group_field = True
    supports_group_in_query = True
    supports_lang_in_query = True
    default_base = "http://fake"

    def __init__(self, always_hit=True):
        self.calls = []
        self.always_hit = always_hit

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)

    def search(self, keyword, *, group="", page=1, limit=None, lang=""):
        self.calls.append((keyword, group, lang))
        if not self.always_hit and group:
            return []                       # 模拟「组+词」搜不到，逼 engine 走回退
        title = f"[{group or '组'}] {keyword} - 01 [1080p][简日内嵌]"
        return [Resource(source="dmhy", source_name="假站点", title=title)]


class EnrichingAdapter(FakeAdapter):
    """返回补全过派生字段的资源（有字幕组 / 集数 / 磁力），用来验证候选与字幕组列表。"""

    def search(self, keyword, *, group="", page=1, limit=None, lang=""):
        self.calls.append((keyword, group, lang))
        return [enrich(Resource(source="dmhy", source_name="假站点",
                                title=f"[假组] {keyword} - 01 [1080p][简日内嵌]",
                                magnet="magnet:?xt=urn:btih:" + "a" * 40))]


def make_subject() -> Subject:
    s = Subject(id=1, name="FX Senshi Kurumi-chan", name_cn="FX战士久留美")
    s.aliases = ["FX战士久留美", "FX Senshi Kurumi-chan", "FX戦士くるみちゃん"]
    return s


class KeywordSearchTest(unittest.TestCase):
    def setUp(self):
        self._saved = dict(engine.ADAPTERS)
        self._sources = engine.config.enabled_sources
        self.adapter = FakeAdapter()
        engine.ADAPTERS["dmhy"] = lambda conf: self.adapter
        engine.config.enabled_sources = lambda: [
            {"id": "dmhy", "name": "假站点", "enabled": True, "base": "http://fake", "priority": 1}
        ]

    def tearDown(self):
        engine.ADAPTERS.clear()
        engine.ADAPTERS.update(self._saved)
        engine.config.enabled_sources = self._sources

    def test_without_keyword_uses_aliases(self):
        subject = make_subject()
        out = engine.search_by_subject(subject)
        words = [c[0] for c in self.adapter.calls]
        self.assertTrue(words, "应该发出了搜索请求")
        # 注意：候选表最前面可能是「关键词学习记录」里学到的词（见 core/keywords.py），
        # 所以这里断言「别名确实被搜到」而不是「第一个词就是别名」
        self.assertTrue(any(w in subject.aliases for w in words), f"应按别名搜索，实际 {words}")
        self.assertNotIn("手动关键词", out.strategy)
        self.assertTrue(out.resources)

    def test_without_keyword_walks_through_aliases(self):
        """第一个别名搜不到时应继续试下一个别名（别名展开确实生效）。"""

        class PickyAdapter(FakeAdapter):
            def search(self, keyword, *, group="", page=1, limit=None, lang=""):
                self.calls.append((keyword, group, lang))
                if keyword == "FX Senshi Kurumi-chan":
                    return [Resource(source="dmhy", source_name="假站点", title="[组] FX Senshi Kurumi-chan - 01 [1080p][简日内嵌]")]
                return []

        picky = PickyAdapter()
        engine.ADAPTERS["dmhy"] = lambda conf: picky
        subject = make_subject()
        engine.search_by_subject(subject)
        words = [c[0] for c in picky.calls]
        self.assertGreater(len(words), 1, f"应继续尝试其它别名，实际 {words}")
        self.assertIn("FX Senshi Kurumi-chan", words)

    def test_keyword_only_uses_that_word(self):
        out = engine.search_by_subject(make_subject(), keyword="  自定义关键词  ")
        self.assertEqual([c[0] for c in self.adapter.calls], ["自定义关键词"], "手动搜索只应发这一个词")
        self.assertIn("手动关键词", out.strategy)
        self.assertIn("自定义关键词", out.strategy)
        self.assertTrue(out.resources)

    def test_group_first_then_fallback(self):
        adapter = FakeAdapter(always_hit=False)
        engine.ADAPTERS["dmhy"] = lambda conf: adapter
        engine.search_by_subject(make_subject(), keyword="自定义词", group="ANi")
        self.assertEqual(adapter.calls[0], ("自定义词", "ANi", ""), "先试「字幕组 + 词」")
        self.assertEqual(adapter.calls[-1], ("自定义词", "", ""), "组里搜不到再退回只按词搜")
        self.assertTrue(all(c[0] == "自定义词" for c in adapter.calls), adapter.calls)

    def test_keyword_with_lang_suffix(self):
        engine.search_by_subject(make_subject(), keyword="自定义词", lang="chs")
        self.assertEqual(self.adapter.calls[0][2], "chs", "语言偏好要一起传给站点")


class WatcherKeywordTest(unittest.TestCase):
    """订阅里存了自定义搜索词 → 自动追新必须用它。"""

    def setUp(self):
        self._saved = engine.search_by_subject
        self.seen = []

        def fake_search(subject, **kw):
            self.seen.append(kw)
            return engine.SearchOutcome()

        engine.search_by_subject = fake_search

    def tearDown(self):
        engine.search_by_subject = self._saved

    def test_search_for_passes_custom_keyword(self):
        sub = subs.Subscription(subject_id=1, name="FX战士久留美", group="ANi", custom_keyword="FX 戰士久留美")
        watcher.search_for(sub)
        self.assertEqual(self.seen[0].get("keyword"), "FX 戰士久留美")
        self.assertEqual(self.seen[0].get("group"), "ANi")

    def test_search_for_without_keyword(self):
        sub = subs.Subscription(subject_id=1, name="FX战士久留美")
        watcher.search_for(sub)
        self.assertEqual(self.seen[0].get("keyword"), "")


class KeywordOnlySourceTest(unittest.TestCase):
    """手动关键词是**唯一**的搜索词：不展开别名，也不让「关键词学习记录」插队。"""

    def setUp(self):
        self._saved = dict(engine.ADAPTERS)
        self._sources = engine.config.enabled_sources
        self.adapter = EnrichingAdapter()
        engine.ADAPTERS["dmhy"] = lambda conf: self.adapter
        engine.config.enabled_sources = lambda: [
            {"id": "dmhy", "name": "假站点", "enabled": True, "base": "http://fake", "priority": 1}
        ]

    def tearDown(self):
        engine.ADAPTERS.clear()
        engine.ADAPTERS.update(self._saved)
        engine.config.enabled_sources = self._sources

    def test_learned_keywords_never_leak_into_manual_search(self):
        """学习记录里存着「以前管用的词」也不能拿去搜：用户指定了词就只搜这个词。"""
        saved = engine.keywords_store

        class StubStore:
            def learned(self, *a, **kw):
                return ["学到的别名甲", "学到的别名乙"]

            def record(self, *a, **kw):
                return None

        engine.keywords_store = StubStore()
        try:
            engine.search_by_subject(make_subject(), keyword="我的词")
        finally:
            engine.keywords_store = saved
        self.assertEqual({c[0] for c in self.adapter.calls}, {"我的词"},
                         f"只该搜手动关键词，实际 {self.adapter.calls}")

    def test_collect_groups_uses_same_keyword(self):
        """字幕组候选（/api/groups）必须和资源列表同一批结果：只按手动关键词搜。"""
        out = engine.collect_groups(make_subject(), keyword="我的词")
        self.assertEqual({c[0] for c in self.adapter.calls}, {"我的词"},
                         f"字幕组候选只该按这个关键词搜，实际 {self.adapter.calls}")
        names = {g["name"] for g in out["groups"]}
        self.assertIn("假组", names, f"关键词搜到的组要出现在候选里：{names}")


class WatcherOnlyManualKeywordTest(unittest.TestCase):
    """订阅指定了关键词 → 自动追番的**自动检查只用这个词**搜更新资源。"""

    def setUp(self):
        self._saved = dict(engine.ADAPTERS)
        self._sources = engine.config.enabled_sources
        self.adapter = EnrichingAdapter()
        engine.ADAPTERS["dmhy"] = lambda conf: self.adapter
        engine.config.enabled_sources = lambda: [
            {"id": "dmhy", "name": "假站点", "enabled": True, "base": "http://fake", "priority": 1}
        ]

    def tearDown(self):
        engine.ADAPTERS.clear()
        engine.ADAPTERS.update(self._saved)
        engine.config.enabled_sources = self._sources

    def test_only_manual_keyword_is_searched(self):
        sub = subs.Subscription(subject_id=1, name="FX战士久留美", group="假组",
                                custom_keyword="FX 戰士久留美")
        out = watcher.search_for(sub)
        words = [c[0] for c in self.adapter.calls]
        self.assertTrue(words, "应该发出搜索请求")
        self.assertEqual(set(words), {"FX 戰士久留美"},
                         f"自动追新只该用手动关键词（不展开别名），实际 {words}")
        self.assertTrue(out.resources, "关键词搜到的资源要进候选")


class WarmupKeywordTest(unittest.TestCase):
    """后台预热也要按「订阅里存的手动关键词」再存一份，点开弹窗才能秒显示。"""

    def test_warmup_caches_manual_keyword_variant(self):
        from unittest import mock

        from app.core import cache, warmup

        seen = []

        def fake_search(subject, **kw):
            seen.append(kw.get("keyword", ""))
            out = engine.SearchOutcome()
            out.strategy = "手动关键词" if kw.get("keyword") else "番剧名"
            return out

        subject = Subject(id=424242, name="测试番", name_cn="测试番")
        sub = subs.Subscription(subject_id=subject.id, name="测试番", custom_keyword="我的词")
        with mock.patch.object(warmup.engine, "search_by_subject", side_effect=fake_search), \
                mock.patch.object(subs, "get", lambda sid: sub if int(sid) == subject.id else None):
            warmup._run_one(subject, force=True)

        self.assertIn("我的词", seen, f"应额外预热手动关键词口径，实际搜了 {seen}")
        key = cache.search_key(subject.id, "kw=我的词")
        cached, _age = cache.get_stale(key)
        self.assertIsNotNone(cached, "手动关键词口径的搜索结果要落盘（否则点开弹窗还得现搜）")
        self.assertEqual((cached or {}).get("search_keyword"), "我的词")


class SearchCacheVariantTest(unittest.TestCase):
    """关键词口径的缓存**绝不回退**别名缓存（否则搜索框里的词等于摆设）。"""

    def test_keyword_variant_never_falls_back_to_base(self):
        from app.web import server as srv

        seen = []

        def fake_any_age(subject_id, variant=""):
            seen.append(variant)
            if variant == "":
                return {"strategy": "别名结果", "items": []}, 5.0
            return None, 0.0

        saved = srv.warmup.search_any_age
        srv.warmup.search_any_age = fake_any_age
        try:
            got, _age = srv._pick_search_cache(1, "kw=我的词")
            self.assertIsNone(got, "关键词口径没缓存时必须去联网，不能拿别名缓存顶替")
            self.assertEqual(seen, ["kw=我的词"], "关键词口径连基础缓存都不该读")
            seen.clear()
            got2, _age2 = srv._pick_search_cache(1, "lang=chs")
            self.assertEqual((got2 or {}).get("strategy"), "别名结果",
                             "非关键词口径（语言/字幕组）仍然可以复用基础缓存")
        finally:
            srv.warmup.search_any_age = saved


class SubscriptionStorageTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="anime-subs-")
        self._path = subs._SUBS_PATH
        subs._SUBS_PATH = os.path.join(self._dir, "subscriptions.json")
        subs._cache = None

    def tearDown(self):
        subs._SUBS_PATH = self._path
        subs._cache = None

    def test_roundtrip_custom_keyword(self):
        subs.upsert(subs.Subscription(subject_id=7, name="测试番", custom_keyword="自定义 关键词"))
        subs._cache = None                       # 强制从磁盘重读
        got = subs.get(7)
        self.assertEqual(got.custom_keyword, "自定义 关键词")
        self.assertIn("custom_keyword", got.to_dict())

    def test_old_file_without_key_still_loads(self):
        with open(subs._SUBS_PATH, "w", encoding="utf-8") as f:
            json.dump([{"subject_id": 9, "name": "老订阅", "group": "ANi"}], f, ensure_ascii=False)
        subs._cache = None
        got = subs.get(9)
        self.assertIsNotNone(got, "老订阅文件必须还能读出来")
        self.assertEqual(got.custom_keyword, "", "缺字段时默认空字符串")

    def test_default_is_empty(self):
        self.assertEqual(subs.Subscription(subject_id=1).custom_keyword, "")


if __name__ == "__main__":
    unittest.main()
