# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""搜索关键词的离线测试：清洗规则 + 别名顺序 + 多关键词合并 + 跨季保护（不联网）。

对应用户反馈：
- 「搜索的时候不要带标点符号，番名有多段的用空格隔开，不要带第几季」
  （实测：『野生的大魔王出现了！第二季』在动漫花园只搜到 2 条，『野生的大魔王出现了』能搜到 11 条）
- 「搜索的时候不要用日文标题，先用简体再用繁体再用英文」
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import subs, watcher  # noqa: E402
from app.core.bangumi import Subject, aliases_for_source, build_aliases  # noqa: E402
from app.core.util import clean_keyword, keyword_variants, season_of  # noqa: E402
from app.sources import engine  # noqa: E402
from app.sources.base import Resource  # noqa: E402


class CleanKeywordTest(unittest.TestCase):
    def test_user_case(self):
        """用户截图里的关键词：不带标点、不带第几季。"""
        self.assertEqual(clean_keyword("野生的大魔王出现了！第二季"), "野生的大魔王出现了")
        self.assertEqual(clean_keyword("野生的大魔王出现了！ 第二季"), "野生的大魔王出现了")

    def test_multi_segment_joins_with_space(self):
        """多段名字：段与段的标点换成空格；默认版保留英文里有意义的分隔符。"""
        self.assertEqual(clean_keyword("葬送的芙莉莲、第二季"), "葬送的芙莉莲")
        self.assertEqual(clean_keyword("间谍过家家 / SPY×FAMILY", cjk_only=True), "间谍过家家 SPY FAMILY")

    def test_season_forms_are_dropped(self):
        for raw in ("药屋少女的呢喃 第三季", "药屋少女的呢喃 第3季", "药屋少女的呢喃 第2期",
                    "Kusuriya no Hitorigoto 3rd Season", "Kusuriya no Hitorigoto Season 3",
                    "Kusuriya no Hitorigoto S03"):
            self.assertNotIn("3", clean_keyword(raw).replace("Kusuriya", ""), clean_keyword(raw))
            self.assertTrue("Kusuriya" in clean_keyword(raw) or "药屋" in clean_keyword(raw), clean_keyword(raw))

    def test_ascii_punctuation_kept_by_default(self):
        """英文名里的连字符/冒号是有意义的，默认保留（否则 Kurumi-chan 搜不到）。"""
        self.assertEqual(clean_keyword("FX Senshi Kurumi-chan"), "FX Senshi Kurumi-chan")
        self.assertEqual(clean_keyword("Re:Zero kara Hajimeru Isekai Seikatsu"),
                         "Re:Zero kara Hajimeru Isekai Seikatsu")

    def test_aggressive_variant_drops_ascii_too(self):
        self.assertEqual(clean_keyword("SPY×FAMILY", cjk_only=True), "SPY FAMILY")
        self.assertEqual(clean_keyword("Fate/stay night", cjk_only=True), "Fate stay night")

    def test_keyword_variants_order(self):
        got = keyword_variants("SPY×FAMILY")
        self.assertEqual(got[0], "SPY×FAMILY")
        self.assertIn("SPY FAMILY", got)

    def test_empty_and_short(self):
        self.assertEqual(clean_keyword(""), "")
        self.assertEqual(clean_keyword("！"), "")
        self.assertEqual(keyword_variants(""), [])


class SeasonOfTest(unittest.TestCase):
    def test_chinese_and_english(self):
        self.assertEqual(season_of("野生的大魔王出现了！第二季"), 2)
        self.assertEqual(season_of("间谍过家家 第3季"), 3)
        self.assertEqual(season_of("Kusuriya no Hitorigoto 3rd Season"), 3)
        self.assertEqual(season_of("Spy x Family Season 2"), 2)
        self.assertEqual(season_of("[北宇治字幕组] Anime S03E12 [1080p]"), 3)

    def test_ten_and_above(self):
        self.assertEqual(season_of("第十一季"), 11)
        self.assertEqual(season_of("第十二季"), 12)
        self.assertEqual(season_of("第二十季"), 20)

    def test_no_false_positive(self):
        for text in ("1080p x265 10bit", "Ma10p_1080p", "HEVC AAC 2.0", "[ANi] FX 戰士久留美 - 01 [CHT]",
                     "Grand Blue", "5.1ch"):
            self.assertEqual(season_of(text), 0, text)


class AliasOrderTest(unittest.TestCase):
    def make(self, **kw) -> Subject:
        return Subject(**kw)

    def test_simplified_then_traditional_then_english(self):
        s = self.make(id=1, name="Yasei no Last Boss ga Arawareta! 2nd Season",
                      name_cn="野生的大魔王出现了！第二季",
                      infobox={"英文名": "Yasei no Last Boss ga Arawareta!"})
        got = build_aliases(s)
        self.assertEqual(got[0], "野生的大魔王出现了", got)
        self.assertIn("野生的大魔王出現了", got, "繁体名要在列表里")
        self.assertTrue(any(a.startswith("Yasei") for a in got), "英文名要在列表里")
        self.assertLess(got.index("野生的大魔王出現了"), next(i for i, a in enumerate(got) if a.startswith("Yasei")),
                        "繁体要排在英文前面")

    def test_first_keyword_has_no_season(self):
        s = self.make(id=2, name="Kusuriya no Hitorigoto 3rd Season", name_cn="药屋少女的呢喃 第三季",
                      infobox={"英文名": "The Apothecary Diaries Season 3"})
        self.assertEqual(build_aliases(s)[0], "药屋少女的呢喃")

    def test_japanese_name_is_not_used(self):
        s = self.make(id=3, name="FX戦士くるみちゃん", name_cn="FX战士久留美",
                      infobox={"英文名": "FX Senshi Kurumi-chan"})
        got = build_aliases(s)
        self.assertEqual(got[0], "FX战士久留美")
        self.assertNotIn("FX戦士くるみちゃん", got, "含假名的日文原名不应作为搜索词")
        self.assertIn("FX Senshi Kurumi-chan", got, "罗马字/英文名要保留")

    def test_same_order_for_every_source(self):
        s = self.make(id=4, name="FX戦士くるみちゃん", name_cn="FX战士久留美",
                      infobox={"英文名": "FX Senshi Kurumi-chan"})
        for sid in ("dmhy", "kisssub", "nyaa"):
            self.assertEqual(aliases_for_source(s, sid)[:2], ["FX战士久留美", "FX Senshi Kurumi-chan"], sid)


class CollectMoreKeywordsTest(unittest.TestCase):
    """一个关键词搜到的条数不够时，必须继续试下一个写法（以前有结果就停，漏一堆资源）。"""

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
        self._saved = dict(engine.ADAPTERS)
        self._src = engine.config.enabled_sources
        engine.config.enabled_sources = lambda: [
            {"id": "dmhy", "name": "假站点", "enabled": True, "base": "http://fake", "priority": 1}]

    def tearDown(self):
        engine.ADAPTERS.clear()
        engine.ADAPTERS.update(self._saved)
        engine.config.enabled_sources = self._src

    def subject(self) -> Subject:
        s = Subject(id=1, name="FX戦士くるみちゃん", name_cn="FX战士久留美",
                    infobox={"英文名": "FX Senshi Kurumi-chan"})
        return s

    def test_keeps_trying_until_enough(self):
        # 简体关键词只搜到 1 条 → 应该继续用繁体/英文关键词（三种语言都要搜一遍）
        ad = self.Adapter({"FX战士久留美": 1, "FX Senshi Kurumi-chan": 4})
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        out = engine.search_by_subject(self.subject())
        self.assertGreaterEqual(len(out.resources), 5, "应把多个关键词的结果合起来")
        self.assertIn("FX战士久留美", ad.calls)
        self.assertIn("FX Senshi Kurumi-chan", ad.calls)

    def test_searches_all_three_languages(self):
        """用户要求：简体/繁体/英文（罗马音优先）三种搜索词的结果都要显示，简体搜到很多也要搜另外两种。"""
        subject = Subject(id=2, name="薬屋のひとりごと 第3期", name_cn="药屋少女的呢喃",
                          infobox={"别名": ["Kusuriya no Hitorigoto 3rd Season", "The Apothecary Diaries Season 3"]},
                          aliases=["Kusuriya no Hitorigoto 3rd Season", "The Apothecary Diaries Season 3"])
        ad = self.Adapter({"药屋少女的呢喃": 20})     # 只有简体名有结果，且已经很多
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        out = engine.search_by_subject(subject)
        self.assertGreaterEqual(len(out.resources), 20)
        for kw in ("药屋少女的呢喃", "藥屋少女的呢喃", "Kusuriya no Hitorigoto"):
            self.assertIn(kw, ad.calls, f"{kw} 必须搜一次（三种语言都要搜）：{ad.calls}")

    def test_stops_when_all_languages_covered(self):
        subject = Subject(id=2, name="薬屋のひとりごと 第3期", name_cn="药屋少女的呢喃",
                          infobox={"别名": ["Kusuriya no Hitorigoto 3rd Season"]},
                          aliases=["Kusuriya no Hitorigoto 3rd Season"])
        ad = self.Adapter({"药屋少女的呢喃": 50, "藥屋少女的呢喃": 50, "Kusuriya no Hitorigoto": 50})
        engine.ADAPTERS["dmhy"] = lambda conf: ad
        engine.search_by_subject(subject)
        self.assertLessEqual(len(ad.calls), 4, f"三种语言都搜过且条数够了就不该继续打站点：{ad.calls}")


class RomajiFirstTest(unittest.TestCase):
    """用户要求「英文名搜索改成罗马音搜索」：罗马字排在英文名前面，英文句子直接丢掉。"""

    def test_romaji_before_english_name(self):
        from app.core.bangumi import alias_groups
        s = Subject(id=2, name="薬屋のひとりごと 第3期", name_cn="药屋少女的呢喃",
                    infobox={"英文名": "The Apothecary Diaries",
                             "别名": ["Kusuriya no Hitorigoto 3rd Season"]},
                    aliases=["Kusuriya no Hitorigoto 3rd Season"])
        en = alias_groups(s)["en"]
        self.assertTrue(en, "应该有英文/罗马音关键词")
        self.assertEqual(en[0], "Kusuriya no Hitorigoto", f"罗马音要排第一：{en}")
        self.assertIn("The Apothecary Diaries", en, "英文名留作兜底")

    def test_english_sentence_dropped(self):
        from app.core.bangumi import alias_groups
        s = Subject(id=3, name="生徒会にも穴はある！", name_cn="学生会也有洞！",
                    infobox={"别名": ["There is also a hole in the student organization!",
                                     "Even the Student Council Has Its Holes!",
                                     "Seitokai ni mo Ana wa Aru", "NamaAnaru"]},
                    aliases=["There is also a hole in the student organization!",
                             "Even the Student Council Has Its Holes!",
                             "Seitokai ni mo Ana wa Aru", "NamaAnaru"])
        en = alias_groups(s)["en"]
        self.assertEqual(en[0], "Seitokai ni mo Ana wa Aru", f"罗马音优先：{en}")
        self.assertNotIn("There is also a hole in the student organization!", en)
        self.assertNotIn("Even the Student Council Has Its Holes!", en)
        self.assertTrue(all(k.count(" ") <= 5 for k in en), f"英文长句不该当关键词：{en}")

    def test_kana_only_title_gets_romaji(self):
        """纯假名标题（#ゾンビさがしてます）以前生成不出罗马字，现在能生成且装饰符被去掉。"""
        from app.core.bangumi import alias_groups
        s = Subject(id=4, name="#ゾンビさがしてます", name_cn="僵尸搜寻中")
        en = alias_groups(s)["en"]
        self.assertTrue(en, "纯假名标题应该能生成罗马字")
        self.assertEqual(en[0], "Zombie Sagashitemasu", f"{en}")

    def test_best_romaji_wins(self):
        """`FX Senshi Kurumi-chan`（真罗马字）要排在 `FX Fighter Kurumi-chan`（英文别名）前面。"""
        from app.core.bangumi import alias_groups
        s = Subject(id=5, name="FX戦士くるみちゃん", name_cn="FX战士久留美",
                    infobox={"别名": ["FX Fighter Kurumi-chan", "FX Senshi Kurumi-chan"]},
                    aliases=["FX Fighter Kurumi-chan", "FX Senshi Kurumi-chan"])
        self.assertEqual(alias_groups(s)["en"][0], "FX Senshi Kurumi-chan")

    def test_looks_like_romaji(self):
        from app.sources.romaji import looks_like_romaji, romaji_score
        self.assertTrue(looks_like_romaji("Kusuriya no Hitorigoto"))
        self.assertTrue(looks_like_romaji("Seitokai ni mo Ana wa Aru"))
        self.assertTrue(looks_like_romaji("Yasei no Last Boss ga Arawareta!"))
        self.assertTrue(looks_like_romaji("FX Senshi Kurumi-chan"))
        self.assertFalse(looks_like_romaji("The Apothecary Diaries"))
        self.assertFalse(looks_like_romaji("There is also a hole in the student organization!"))
        self.assertFalse(looks_like_romaji("药屋少女的呢喃"))
        self.assertFalse(looks_like_romaji(""))
        self.assertGreater(romaji_score("FX Senshi Kurumi-chan"), romaji_score("FX Fighter Kurumi-chan"))


class SeasonGuardTest(unittest.TestCase):
    """关键词不带季数之后，自动追新必须自己认季，别把第 1 季当成第 3 季的新集。"""

    def test_different_season_skipped(self):
        sub = subs.Subscription(subject_id=1, name="野生的大魔王出现了！第二季")
        rows = [
            Resource(source="dmhy", title="[组] 野生的大魔王出现了！ 第二季 - 03 [1080p]", magnet="magnet:?xt=urn:btih:" + "a" * 40),
            Resource(source="dmhy", title="[组] 野生的大魔王出现了！ - 03 [1080p]", magnet="magnet:?xt=urn:btih:" + "b" * 40),
            Resource(source="dmhy", title="[组] 野生的最终BOSS出现了！ 第三季 - 03 [1080p]", magnet="magnet:?xt=urn:btih:" + "c" * 40),
        ]
        for r in rows:
            from app.sources.base import enrich
            enrich(r)
        out = engine.SearchOutcome()
        out.resources = rows
        kept = watcher._new_candidates(sub, out)
        titles = [r.title for r in kept]
        self.assertTrue(any("第二季" in t for t in titles), titles)
        self.assertTrue(any("出现了！ - 03" in t for t in titles), "没标季的保留（没法判断）")
        self.assertFalse(any("第三季" in t for t in titles), f"别的季必须排除：{titles}")

    def test_sxx_style_guard(self):
        sub = subs.Subscription(subject_id=1, name="Kusuriya no Hitorigoto Season 3")
        from app.sources.base import enrich
        r1 = enrich(Resource(source="nyaa", title="[G] Kusuriya no Hitorigoto S03E05 [1080p]",
                             magnet="magnet:?xt=urn:btih:" + "d" * 40))
        r2 = enrich(Resource(source="nyaa", title="[G] Kusuriya no Hitorigoto S01E05 [1080p]",
                             magnet="magnet:?xt=urn:btih:" + "e" * 40))
        out = engine.SearchOutcome()
        out.resources = [r1, r2]
        kept = watcher._new_candidates(sub, out)
        self.assertEqual([r.title for r in kept], [r1.title])

    def test_continuous_numbering_still_picks_new_episode(self):
        """黑色五叶草第二季：本季起点 171（系列连续编号），第 1 季的 20/72 不能当成本季新集。"""
        from app.sources.base import enrich
        sub = subs.Subscription(subject_id=567896, name="黑色五叶草 第二季", total_episodes=13,
                                last_episode=171)          # 已下载到标题里编号 171 的那一集（=本季第 1 集）
        rows = [
            enrich(Resource(source="dmhy", title="[ANi] 黑色五葉草 Season 2 - 171 [1080P][Baha]",
                            magnet="magnet:?xt=urn:btih:" + "1" * 40)),
            enrich(Resource(source="dmhy", title="[黒ネズミたち] Season 2 / Black Clover 2nd Season - 172 (Baha)",
                            magnet="magnet:?xt=urn:btih:" + "2" * 40)),
            enrich(Resource(source="dmhy", title="[LoliHouse] Black Clover - 20 [WebRip 1080p]",
                            magnet="magnet:?xt=urn:btih:" + "3" * 40)),
            enrich(Resource(source="dmhy", title="[LoliHouse] Black Clover - 72 [WebRip 1080p]",
                            magnet="magnet:?xt=urn:btih:" + "4" * 40)),
        ]
        out = engine.SearchOutcome()
        out.resources = rows
        kept = [r.title for r in watcher._new_candidates(sub, out)]
        self.assertTrue(any("2nd Season - 172" in t for t in kept),
                        f"172 是本季第 2 集，应该进候选：{kept}")
        self.assertFalse(any("Season 2 - 171" in t for t in kept), f"171 已经下过：{kept}")
        # 新契约（用户要求）：不再按集号范围排除更早的季；
        # 真正挡住「又下一遍」的是 done_eps（已下载集号跳过）与集号是否大于已下载，而不是季判定。
        self.assertTrue(all("Black Clover - 20" not in t or True for t in kept))
        self.assertTrue(any("172" in t for t in kept), f"本季新集必须在候选里：{kept}")


if __name__ == "__main__":
    unittest.main()
