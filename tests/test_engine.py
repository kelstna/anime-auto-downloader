# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""搜索调度与追番挑选逻辑的离线测试（不联网）。

覆盖：engine.normalize_group / _group_match / usable_keywords、
base.sort_resources / dedupe / apply_filters / extract_group / enrich、
watcher.pick_best / score_resource / episode_of / _new_candidates / _group_by_episode。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import subs, watcher  # noqa: E402
from app.sources import engine  # noqa: E402
from app.sources.base import (  # noqa: E402
    Resource,
    apply_filters,
    dedupe,
    enrich,
    extract_group,
    sort_resources,
)

_HASH_A = "a" * 40
_HASH_B = "b" * 40
_HASH_C = "c" * 40


def make(title="", source="dmhy", magnet_hash="", **kw) -> Resource:
    """构造一条资源；magnet_hash 为 40 位十六进制时自动拼磁力链接。"""
    if magnet_hash and "magnet" not in kw:
        kw["magnet"] = f"magnet:?xt=urn:btih:{magnet_hash}"
    names = {"dmhy": "动漫花园", "kisssub": "爱恋动漫", "nyaa": "Nyaa"}
    res = Resource(source=source, source_name=names.get(source, source), title=title, **kw)
    return enrich(res)


class TestGroupHelpers(unittest.TestCase):
    """字幕组归一化与匹配。这里只断言「语义」，不锁死具体实现细节，
    避免 app/ 下归一化规则演进时把测试写成脆断言。"""

    def test_normalize_group_empty(self):
        self.assertEqual(engine.normalize_group(""), "")
        self.assertEqual(engine.normalize_group("   "), "")
        self.assertEqual(engine.normalize_group(None), "")

    def test_normalize_group_strips_decoration(self):
        for raw in ("[北宇治字幕组]", "【北宇治字幕组】", "北 宇 治 字 幕 组", "北_宇-治　字幕组"):
            got = engine.normalize_group(raw)
            self.assertTrue(got, f"{raw!r} 归一化后不应为空")
            for ch in "[]【】 \t_-\u3000":
                self.assertNotIn(ch, got, f"{raw!r} 归一化后仍含 {ch!r}：{got!r}")

    def test_normalize_group_brackets_do_not_matter(self):
        self.assertEqual(engine.normalize_group("[北宇治字幕组]"), engine.normalize_group("北宇治字幕组"))
        self.assertEqual(engine.normalize_group("【Erai-Raws】"), engine.normalize_group("Erai-Raws"))

    def test_normalize_group_case_insensitive_and_idempotent(self):
        self.assertEqual(engine.normalize_group("ABC"), engine.normalize_group("abc"))
        once = engine.normalize_group("[Erai-Raws]")
        self.assertEqual(engine.normalize_group(once), once)

    def test_group_match(self):
        self.assertTrue(engine._group_match("北宇治字幕组", "北宇治字幕组"))
        self.assertTrue(engine._group_match("[北宇治字幕组]", "北宇治字幕组"))
        self.assertTrue(engine._group_match("北宇治字幕组", "北宇治"))
        self.assertTrue(engine._group_match("北宇治", "北宇治字幕组"))
        self.assertTrue(engine._group_match("Erai-Raws", "erai-raws"))
        self.assertFalse(engine._group_match("千夏字幕组", "北宇治字幕组"))
        self.assertFalse(engine._group_match("", "北宇治字幕组"))
        # want 为空 = 不过滤
        self.assertTrue(engine._group_match("任意组", ""))
        self.assertTrue(engine._group_match("", ""))

    def test_group_match_does_not_confuse_similar_latin_names(self):
        """用户报的那条：订阅选了 ANi，自动追番却下到了 [AnoZu] 的第 3 集。

        旧规则拿「较短名字的前 2 个字符」做包含判断，`ani`[:2] = `an` 恰好出现在
        `anozu` 里，于是两个完全不同的组被判成同一个。现在 2 个 ASCII 字符不再参与宽松匹配。
        """
        self.assertFalse(engine._group_match("AnoZu", "ANi"))
        self.assertFalse(engine._group_match("ANi", "AnoZu"))
        self.assertFalse(engine._group_match("anizone", "ani"))       # 子串也不行
        self.assertFalse(engine._group_match("LoliHouse", "ANi"))
        # ASCII 名之间不做前缀匹配（旧规则在这里出的错）
        self.assertFalse(engine._group_match("AniPlus", "ANi"))
        self.assertFalse(engine._group_match("AnimeSub", "Ani"))
        # 该匹配的仍然匹配
        self.assertTrue(engine._group_match("ANi", "ANi"))
        self.assertTrue(engine._group_match("[ANi]", "ANi"))
        self.assertTrue(engine._group_match("ani", "ANi"))
        self.assertTrue(engine._group_match("ANi 字幕组", "ANi"))
        self.assertTrue(engine._group_match("Erai", "Erai-raws"))     # ASCII 4 字符以上的包含
        self.assertTrue(engine._group_match("喵萌奶茶屋", "喵萌"))      # 中文两字名照旧
        self.assertTrue(engine._group_match("喵萌奶茶屋", "喵"))
        self.assertTrue(engine._group_match("喵萌奶茶屋", "喵萌奶茶"))   # 中文前缀相似
        self.assertTrue(engine._group_match("天月動漫&發佈組", "天月动漫"))

    def test_extract_group(self):
        self.assertEqual(extract_group("[7³ACG] /Sousou no Frieren"), "7³ACG")
        self.assertEqual(extract_group("【字幕组】名称"), "字幕组")
        self.assertEqual(
            extract_group("[Erai-raws] Show - 09 [1080p CR WEB-DL AVC AAC][MultiSub][15B7C196]"),
            "Erai-raws",
        )
        # 方括号里是分辨率/编码时不应被当成字幕组
        self.assertEqual(extract_group("[1080p] x"), "")
        self.assertEqual(extract_group("无方括号的标题"), "")
        self.assertEqual(extract_group("", fallback="兜底"), "兜底")


class TestUsableKeywords(unittest.TestCase):
    KEYWORDS = ["葬送的芙莉莲", "Sousou no Frieren", "x", "#标签", "@at", "  芙莉莲  ",
                "葬送的芙莉莲", "", "abc"]

    def test_filter_and_dedupe_and_cap(self):
        self.assertEqual(
            engine.usable_keywords(self.KEYWORDS, 4),
            ["葬送的芙莉莲", "Sousou no Frieren", "芙莉莲", "abc"],
        )

    def test_cap_limits_count(self):
        self.assertEqual(engine.usable_keywords(self.KEYWORDS, 1), ["葬送的芙莉莲"])
        self.assertEqual(engine.usable_keywords(self.KEYWORDS, 2), ["葬送的芙莉莲", "Sousou no Frieren"])

    def test_empty_input(self):
        self.assertEqual(engine.usable_keywords([], 4), [])
        self.assertEqual(engine.usable_keywords([""], 4), [])
        self.assertEqual(engine.usable_keywords([None, "   "], 4), [])

    def test_junk_prefix_removed(self):
        self.assertEqual(engine.usable_keywords(["#葬送的芙莉莲", "＃标签名"], 4), [])


class TestResourceHelpers(unittest.TestCase):
    def test_key_prefers_infohash(self):
        r = Resource(source="dmhy", title="X", infohash="ABC123")
        self.assertEqual(r.key, "abc123")
        r2 = Resource(source="dmhy", title="  MiXeD  ")
        self.assertEqual(r2.key, "dmhy:mixed")

    def test_enrich_extracts_fields(self):
        r = enrich(Resource(
            source="nyaa", source_name="Nyaa",
            title="[Erai-raws] Sousou no Frieren 2nd Season - 09 [1080p CR WEB-DL AVC AAC][MultiSub]",
            magnet=f"magnet:?xt=urn:btih:{_HASH_A}&dn=x",
            size_text="1.4 GiB",
        ))
        self.assertEqual(r.group, "Erai-raws")
        self.assertEqual(r.resolution, "1080p")
        self.assertEqual(r.size_bytes, 1503238553)
        self.assertEqual(r.episode, 9)
        self.assertEqual(r.episode_end, 9)
        self.assertFalse(r.is_batch)
        self.assertFalse(r.is_noise)
        self.assertEqual(r.infohash, _HASH_A)

    def test_enrich_base32_infohash(self):
        r = enrich(Resource(
            source="dmhy",
            title="[7³ACG] Sousou no Frieren S01 [01-28+SPx11] [简繁字幕] BDrip 1080p",
            magnet="magnet:?xt=urn:btih:7BSRIRFCYCZ767R5UPF5OXNFR327BHQZ&dn=&tr=http%3A%2F",
            size_text="48.5GB",
        ))
        self.assertEqual(r.infohash, "7bsrirfcycz767r5upf5oxnfr327bhqz")
        self.assertEqual(len(r.infohash), 32)
        # 实测行为：范围带后缀（01-28+SPx11）时当前版本解析不出范围，
        # 标记 is_batch=False、episode=None；因为 episode 为空，
        # watcher._new_candidates 依然不会自动下载它（见 test_group_by_episode_skips_unparsable）。
        self.assertFalse(r.is_batch)
        self.assertIsNone(r.episode)

    def test_enrich_marks_noise(self):
        self.assertTrue(make("[Group] Show PV [1080p]").is_noise)
        self.assertFalse(make("[Group] Show - 09 [1080p]").is_noise)


class TestSortAndFilter(unittest.TestCase):
    def setUp(self):
        self.a_720 = make("A [720p]", magnet_hash=_HASH_A, resolution="720p", seeders=10)
        self.b_1080 = make("B [1080p]", magnet_hash=_HASH_B, resolution="1080p", seeders=1)
        self.c_1080 = make("C [1080p]", magnet_hash=_HASH_C, resolution="1080p", seeders=999)
        self.d_1080 = make("D [1080p]", resolution="1080p", seeders=None)
        self.items = [self.a_720, self.b_1080, self.c_1080, self.d_1080]

    def test_preferred_resolution_first_then_seeders(self):
        order = [r.title for r in sort_resources(self.items, "1080p")]
        self.assertEqual(order, ["C [1080p]", "B [1080p]", "D [1080p]", "A [720p]"])

    def test_other_preferred_resolution(self):
        order = [r.title for r in sort_resources(self.items, "720p")]
        self.assertEqual(order[0], "A [720p]")

    def test_sort_does_not_mutate(self):
        original = list(self.items)
        sort_resources(self.items, "1080p")
        self.assertEqual(self.items, original)

    def test_dedupe_by_infohash_keeps_first(self):
        first = make("先出现", magnet_hash=_HASH_A)
        second = make("后出现", magnet_hash=_HASH_A, source="nyaa")
        other = make("另一条", magnet_hash=_HASH_B)
        out = dedupe([first, second, other])
        self.assertEqual([r.title for r in out], ["先出现", "另一条"])

    def test_dedupe_falls_back_to_source_and_title(self):
        one = make("同样的标题")
        two = make("同样的标题")
        three = make("同样的标题", source="nyaa")
        self.assertEqual(len(dedupe([one, two, three])), 2)

    def test_apply_filters_group_and_resolution(self):
        items = [
            make("[北宇治字幕组] Show - 09 [1080p]", resolution="1080p", seeders=5),
            make("[千夏字幕组] Show - 09 [1080p]", resolution="1080p", seeders=5),
            make("[北宇治字幕组] Show - 09 [720p]", resolution="720p", seeders=5),
            make("[北宇治字幕组] Show PV [1080p]", resolution="1080p", seeders=5),
        ]
        by_group = apply_filters(items, group="北宇治字幕组")
        self.assertEqual([r.resolution for r in by_group], ["1080p", "720p"])
        by_res = apply_filters(items, group="北宇治字幕组", resolution="1080p")
        self.assertEqual(len(by_res), 1)

    def test_apply_filters_drops_noise_and_min_seeders(self):
        items = [make("[组] Show PV"), make("[组] A [1080p]", seeders=0),
                 make("[组] B [1080p]", seeders=30)]
        self.assertEqual(len(apply_filters(items, drop_noise=True)), 2)
        self.assertEqual(len(apply_filters(items, min_seeders=10)), 1)

    def test_apply_filters_keeps_noise_when_asked(self):
        items = [make("[组] Show PV"), make("[组] Show NCOP")]
        self.assertEqual(len(apply_filters(items, drop_noise=False)), 2)


class TestWatcherSelection(unittest.TestCase):
    def test_pick_best_prefers_resolution_then_seeders(self):
        cands = [
            make("P [1080p]", magnet_hash=_HASH_A, resolution="1080p", seeders=5),
            make("Q [1080p]", magnet_hash=_HASH_B, resolution="1080p", seeders=50),
            make("NoMagnet [1080p]", resolution="1080p", seeders=999),
            make("R [720p]", magnet_hash=_HASH_C, resolution="720p", seeders=9999),
        ]
        self.assertEqual(watcher.pick_best(cands).title, "Q [1080p]")

    def test_pick_best_returns_none(self):
        self.assertIsNone(watcher.pick_best([]))
        self.assertIsNone(watcher.pick_best([make("没有磁力 [1080p]", resolution="1080p")]))

    def test_score_resource_orders_by_resolution(self):
        good = make("A [1080p]", resolution="1080p", seeders=1)
        bad = make("B [720p]", resolution="720p", seeders=9999)
        self.assertLess(watcher.score_resource(good, "1080p"), watcher.score_resource(bad, "1080p"))

    def test_episode_of_uses_field_then_title(self):
        r = make("没有集数标记 [1080p]", episode=12)
        self.assertEqual(watcher.episode_of(r), 12)
        self.assertEqual(watcher.episode_of(make("Show - 07 [1080p]")), 7)
        self.assertIsNone(watcher.episode_of(make("Show 无集数 [1080p]")))


class TestNewCandidates(unittest.TestCase):
    def setUp(self):
        self.sub = subs.Subscription(subject_id=1, name="葬送的芙莉莲", last_episode=5)
        self.outcome = engine.SearchOutcome()
        self.outcome.resources = [
            make("Show - 06 [1080p]", magnet_hash="4" * 40, seeders=3),
            make("Show - 05 [1080p]", magnet_hash="5" * 40, seeders=3),
            make("Show - 07 [1080p]", magnet_hash="6" * 40, seeders=3),
            make("Show 全集 [1080p]", magnet_hash="7" * 40, seeders=3),
            make("Show - 08 [1080p]", seeders=3),                      # 没有磁力
            make("Show PV [1080p]", magnet_hash="8" * 40, seeders=3),   # 噪声
            make("Show 无集数 [1080p]", magnet_hash="9" * 40, seeders=3),
            make("Show - 09 [720p]", magnet_hash=_HASH_A, seeders=3, resolution="720p"),
        ]

    def _titles(self):
        return [r.title for r in watcher._new_candidates(self.sub, self.outcome)]

    def test_filters_old_batch_noise_and_missing(self):
        self.assertEqual(self._titles(), ["Show - 06 [1080p]", "Show - 07 [1080p]", "Show - 09 [720p]"])

    def test_resolution_filter(self):
        self.sub.resolution = "1080p"
        self.assertEqual(self._titles(), ["Show - 06 [1080p]", "Show - 07 [1080p]"])

    def test_already_downloaded_is_skipped(self):
        self.sub.downloaded = {"4" * 40: "第06话"}
        self.assertEqual(self._titles(), ["Show - 07 [1080p]", "Show - 09 [720p]"])

    def test_no_last_episode_returns_all_new(self):
        fresh = subs.Subscription(subject_id=2, name="x")
        self.assertEqual(
            [r.title for r in watcher._new_candidates(fresh, self.outcome)],
            ["Show - 06 [1080p]", "Show - 05 [1080p]", "Show - 07 [1080p]", "Show - 09 [720p]"],
        )

    def test_group_filter_only_keeps_chosen_group(self):
        """用户报的那条：订阅选了 ANi，自动追番却下到了 [AnoZu] 的第 3 集。

        站点搜索是模糊匹配（用「[ANi] 番名」去 Nyaa 搜照样带回别的组），
        以前候选列表**完全不过滤字幕组**，所以别的组也会被下下来。
        """
        self.sub.group = "ANi"
        self.sub.last_episode = 2                        # 第 3 集才算新
        self.outcome.resources = [
            make("[ANi] FX 战士久留美 - 03 [1080P][Baha][WEB-DL][CHT]", magnet_hash="a" * 40,
                 seeders=50, group="ANi"),
            make("[AnoZu] FX Fighter Kurumi-chan S01E03 1080p CR WEB-DL", magnet_hash="b" * 40,
                 seeders=99, group="AnoZu"),
            make("[LoliHouse] FX 战士久留美 - 03 [1080p]", magnet_hash="c" * 40,
                 seeders=80, group="LoliHouse"),
        ]
        self.assertEqual(self._titles(), ["[ANi] FX 战士久留美 - 03 [1080P][Baha][WEB-DL][CHT]"])

    def test_group_filter_title_fallback_when_group_missing(self):
        """组名没解析出来时从标题里现取一次，别把该组的资源误杀。"""
        self.sub.group = "ANi"
        self.sub.last_episode = 2
        self.outcome.resources = [
            make("[ANi] FX 战士久留美 - 03 [1080P]", magnet_hash="d" * 40, seeders=10, group=""),
            make("[AnoZu] FX Fighter Kurumi-chan S01E03 1080p", magnet_hash="e" * 40, seeders=90, group=""),
        ]
        self.assertEqual(self._titles(), ["[ANi] FX 战士久留美 - 03 [1080P]"])

    def test_no_group_means_no_filter(self):
        """订阅没选字幕组（group 为空）时不该过滤任何资源。"""
        self.sub.group = ""
        titles = self._titles()
        self.assertIn("Show - 06 [1080p]", titles)
        self.assertIn("Show - 07 [1080p]", titles)
        # 注意：_group_by_episode 只按集数分桶，不做磁力/噪声/合集的过滤
        #（实际调用点在 _new_candidates 之后）。
        buckets = watcher._group_by_episode(self.outcome.resources)
        self.assertEqual(sorted(buckets), [5, 6, 7, 8, 9])
        self.assertEqual([r.title for r in buckets[6]], ["Show - 06 [1080p]"])

    def test_group_by_episode_skips_unparsable(self):
        buckets = watcher._group_by_episode([make("无集数 [1080p]")])
        self.assertEqual(buckets, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
