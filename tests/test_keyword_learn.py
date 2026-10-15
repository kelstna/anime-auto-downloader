# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""关键词预算 + 学习记录的离线测试（不联网，用假适配器看 engine 实际发了哪些词）。

对应用户反馈：
    「黑暗召唤师在地下恋爱中」只搜到 1 条。Bangumi 别名里
    `Dark Samon atodekiteiru` / `Dark Summoner to Dekiteiru` 看着都像罗马字，
    实际只有后者能搜到一堆资源 —— 而它排在候选表第 5 位，被「每站只试 4 个关键词」截断了。

结论：规则猜不准哪个关键词有用，得靠「多试几个 + 记住哪个管用」：
- `looks_like_romaji()` 用「独立成词的日语助词」把真罗马字挑出来（to/no/ni/wa…）
- 关键词预算 4 → 8（结果够就早停，热门番不会多打站点）
- `keywords_store` 记录每个关键词在每站的命中数，下次把它排到最前面
"""
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import keywords as keywords_store  # noqa: E402
from app.core.bangumi import Subject, alias_groups  # noqa: E402
from app.sources import engine  # noqa: E402
from app.sources.base import Resource  # noqa: E402
from app.sources.romaji import looks_like_romaji, romaji_score  # noqa: E402

# 用户截图里那部番的原始数据（Bangumi 名称 + 别名，一字不改）
DARK_NAME = "ダークサモナーとデキている"
DARK_ALIASES = ["黑暗召唤师在地下恋爱中", "黑暗召唤师在地下戀愛中", "Dark Samon atodekiteiru",
                "Dark Samonatodekiteiru", "Dark Summoner to Dekiteiru", "Dark Samon'atodekiteiru"]
GOOD_KEYWORD = "Dark Summoner to Dekiteiru"


def dark_subject() -> Subject:
    return Subject(id=630160, name=DARK_NAME, name_cn="黑暗召唤师在地下恋爱中",
                   infobox={"别名": list(DARK_ALIASES)}, aliases=list(DARK_ALIASES))


class RomajiPickTest(unittest.TestCase):
    """同一批别名里挑出「真罗马字」。"""

    def test_good_alias_is_recognised(self):
        self.assertTrue(looks_like_romaji(GOOD_KEYWORD), "Dark Summoner to Dekiteiru 应被认成罗马字")
        for bad in ("Dark Samon atodekiteiru", "Dark Samonatodekiteiru", "Dark Samon'atodekiteiru"):
            self.assertFalse(looks_like_romaji(bad), f"{bad} 是机器生拼的串，别当罗马字")
        self.assertGreater(romaji_score(GOOD_KEYWORD), romaji_score("Dark Samon atodekiteiru"))

    def test_good_alias_sorts_first_in_english_group(self):
        en = alias_groups(dark_subject())["en"]
        self.assertTrue(en, "英文组不该为空")
        self.assertEqual(en[0], GOOD_KEYWORD, f"能搜到资源的罗马字要排第一：{en}")

    def test_good_alias_is_tried_and_finds_results(self):
        """只让 `Dark Summoner to Dekiteiru` 有结果：engine 必须搜到它并拿到资源。"""
        case = _EngineCase()
        case.setUp()
        try:
            ad = case.Adapter({GOOD_KEYWORD: 12})
            engine.ADAPTERS["dmhy"] = lambda conf: ad
            out = engine.search_by_subject(dark_subject())
            self.assertIn(GOOD_KEYWORD, ad.calls, f"该关键词必须被搜：{ad.calls}")
            self.assertGreaterEqual(len(out.resources), 12, f"实际 {len(out.resources)} 条")
        finally:
            case.tearDown()


class _EngineCase:
    """复用「假适配器 + 只留一个站点」的测试夹具（供多个 TestCase 使用）。"""

    class Adapter:
        id = "dmhy"
        name = "假站点"
        supports_lang_in_query = True

        def __init__(self, hits_per_keyword):
            self.calls = []
            self.hits = hits_per_keyword

        def search(self, keyword, *, group="", page=1, limit=None, lang=""):
            self.calls.append(keyword)
            return [Resource(source="dmhy", source_name="假站点",
                             title=f"[组] {keyword} - {i + 1:02d} [1080p][简日内嵌]")
                    for i in range(self.hits.get(keyword, 0))]

    def setUp(self):
        self._saved_adapters = dict(engine.ADAPTERS)
        self._saved_sources = engine.config.enabled_sources
        engine.config.enabled_sources = lambda: [
            {"id": "dmhy", "name": "假站点", "enabled": True, "base": "http://fake", "priority": 1}]
        # 学习记录写到临时目录：绝不碰用户真实的 data/keyword_stats.json
        self._tmp = tempfile.mkdtemp(prefix="kwlearn-")
        self._saved_path = keywords_store._STATS_PATH
        keywords_store._STATS_PATH = os.path.join(self._tmp, "keyword_stats.json")
        keywords_store.clear()

    def tearDown(self):
        engine.ADAPTERS.clear()
        engine.ADAPTERS.update(self._saved_adapters)
        engine.config.enabled_sources = self._saved_sources
        keywords_store._STATS_PATH = self._saved_path
        keywords_store.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)


class BudgetTest(unittest.TestCase):
    """关键词预算：结果不够时继续换写法，不要卡在 4 个。"""

    def setUp(self):
        self.case = _EngineCase()
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_tries_beyond_four_keywords(self):
        """第 5 个候选才有结果时也要搜到（旧上限 4 会漏掉，用户踩的就是这个）。"""
        aliases = ["黑暗召唤师在地下一", "黑暗召唤师在地下二", "黑暗召唤师在地下三",
                   "黑暗召唤师在地下五"]        # name_cn + 别名 = 5 个不同名字
        subject = Subject(id=999001, name=DARK_NAME, name_cn="黑暗召唤师在地下恋爱中",
                          infobox={"别名": list(aliases)}, aliases=list(aliases))
        ad = self.case.Adapter({aliases[3]: 7})       # 只有最后一个名字有结果
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        out = engine.search_by_subject(subject)
        self.assertIn(aliases[3], ad.calls, f"第 5 个候选必须被试：{ad.calls}")
        self.assertGreaterEqual(len(out.resources), 7, f"实际 {len(out.resources)} 条")
        self.assertGreater(len(ad.calls), 4, f"试的关键词数要多于旧上限 4：{len(ad.calls)}")

    def test_every_distinct_name_gets_a_slot(self):
        """分层展开：第 1 层（各名字的清洗版）要覆盖所有不同名字，别让第一个名字的变体占满预算。"""
        from app.core.bangumi import alias_groups
        aliases = ["黑暗召唤师在地下一", "黑暗召唤师在地下二", "黑暗召唤师在地下三"]
        subject = Subject(id=999002, name=DARK_NAME, name_cn="黑暗召唤师在地下恋爱中",
                          infobox={"别名": list(aliases)}, aliases=list(aliases))
        chs = alias_groups(subject)["chs"]
        self.assertEqual(chs[:3], ["黑暗召唤师在地下恋爱中", "黑暗召唤师在地下一", "黑暗召唤师在地下二"],
                         f"前三个候选应该是三个不同名字：{chs[:6]}")

    def test_stops_when_time_budget_exceeded(self):
        """站点抽风时（每个请求都很慢）不能把一次搜索拖到十分钟：超预算就停手。"""
        import time as _time

        class SlowAdapter(_EngineCase.Adapter):
            def search(self, keyword, *, group="", page=1, limit=None, lang=""):
                self.calls.append(keyword)
                _time.sleep(0.35)                     # 模拟站点慢/超时
                return []

        aliases = [f"黑暗召唤师在地下{i}" for i in range(1, 11)]
        subject = Subject(id=999003, name=DARK_NAME, name_cn="黑暗召唤师在地下恋爱中",
                          infobox={"别名": list(aliases)}, aliases=list(aliases))
        ad = SlowAdapter({})
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        saved_get = engine.config.get
        engine.config.get = lambda key, default=None: (1 if key == "search.budget_seconds" else default)
        try:
            started = _time.time()
            engine.search_by_subject(subject)
            elapsed = _time.time() - started
        finally:
            engine.config.get = saved_get
        # 预算 1 秒 → 只该试两三个关键词（而不是把 10 个都试完 ~3.5 秒）
        self.assertLess(len(ad.calls), 6, f"超预算后还在继续试：{len(ad.calls)} 个")
        self.assertLess(elapsed, 2.0, f"实际耗时 {elapsed:.1f}s")

    def test_hot_show_still_stops_early(self):
        """热门番：第一个关键词就一大堆结果，不该把 8 个写法全打完（省请求）。"""
        subject = dark_subject()
        ad = self.case.Adapter({"黑暗召唤师在地下恋爱中": 30, "黑暗召唤师在地下戀愛中": 30,
                                GOOD_KEYWORD: 30})
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        engine.search_by_subject(subject)
        self.assertLessEqual(len(ad.calls), 4, f"结果够就该早停：{ad.calls}")


class LearnTest(unittest.TestCase):
    """学习记录：记住「哪个关键词在哪个站点真搜到过」，下次排最前。"""

    def setUp(self):
        self.case = _EngineCase()
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_record_and_read(self):
        keywords_store.record(630160, "dmhy", GOOD_KEYWORD, 12)
        keywords_store.record(630160, "nyaa", GOOD_KEYWORD, 3)
        keywords_store.record(630160, "dmhy", "黑暗召唤师在地下恋爱中", 2)
        self.assertEqual(keywords_store.learned(630160)[0], GOOD_KEYWORD, "命中多的排前面")
        self.assertEqual(keywords_store.learned(630160, "dmhy")[0], GOOD_KEYWORD, "该站点搜到过的优先")
        self.assertEqual(set(keywords_store.learned(630160)), {GOOD_KEYWORD, "黑暗召唤师在地下恋爱中"})
        self.assertTrue(keywords_store.signature(630160), "学到了关键词就该有指纹")
        self.assertEqual(keywords_store.learned(1), [], "没学过的番返回空")

    def test_zero_hits_not_recorded(self):
        keywords_store.record(630160, "dmhy", "Dark Samon atodekiteiru", 0)
        self.assertEqual(keywords_store.learned(630160), [])
        self.assertEqual(keywords_store.signature(630160), "")

    def test_learned_keyword_tried_first(self):
        """上次是第 5 个写法搜到的 → 这次它排第一（不再被预算截断）。"""
        keywords_store.record(630160, "dmhy", GOOD_KEYWORD, 9)
        ad = self.case.Adapter({GOOD_KEYWORD: 9})
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        engine.search_by_subject(dark_subject())
        self.assertEqual(ad.calls[0], GOOD_KEYWORD, f"学到的关键词要第一个搜：{ad.calls[:3]}")

    def test_signature_covers_learned_set(self):
        keywords_store.record(630160, "dmhy", GOOD_KEYWORD, 9)
        first = keywords_store.signature(630160)
        keywords_store.record(630160, "dmhy", "黑暗召唤师在地下戀愛中", 4)
        self.assertNotEqual(first, keywords_store.signature(630160), "学到新的关键词，指纹要变（缓存随之失效）")

    def test_stats(self):
        keywords_store.record(1, "dmhy", "a关键词", 3)
        keywords_store.record(2, "dmhy", "b关键词", 5)
        st = keywords_store.stats()
        self.assertEqual(st["subjects"], 2)
        self.assertEqual(st["keywords"], 2)


if __name__ == "__main__":
    unittest.main()
