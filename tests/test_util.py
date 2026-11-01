# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""app.core.util 的离线单元测试：文件名净化 / 集数解析 / 大小 / 简繁转换。"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import util  # noqa: E402


class TestSanitizeName(unittest.TestCase):
    """Windows 文件名净化。"""

    def test_remove_forbidden_chars(self):
        self.assertEqual(util.sanitize_name('a<b>c:d"e/f\\g|h?i*j'), "abcdefghij")

    def test_strip_trailing_dot_and_space(self):
        self.assertEqual(util.sanitize_name("结尾点..."), "结尾点")
        self.assertEqual(util.sanitize_name("结尾空格   "), "结尾空格")
        self.assertEqual(util.sanitize_name("点.空格 . "), "点.空格")

    def test_reserved_names_get_prefixed(self):
        self.assertEqual(util.sanitize_name("CON"), "_CON")
        self.assertEqual(util.sanitize_name("con"), "_con")
        self.assertEqual(util.sanitize_name("nul.txt"), "_nul.txt")
        self.assertEqual(util.sanitize_name("com1"), "_com1")
        self.assertEqual(util.sanitize_name("LPT9"), "_LPT9")
        # COM10 不在 Windows 保留名之列，应原样保留
        self.assertEqual(util.sanitize_name("COM10"), "COM10")

    def test_max_len(self):
        self.assertEqual(len(util.sanitize_name("A" * 200)), 120)
        self.assertEqual(util.sanitize_name("A" * 200, max_len=10), "A" * 10)
        # 截断后再去掉结尾的点/空格
        self.assertEqual(util.sanitize_name("A" * 9 + ". " + "B" * 5, max_len=10), "A" * 9)

    def test_fallback(self):
        self.assertEqual(util.sanitize_name(""), "未命名")
        self.assertEqual(util.sanitize_name("   "), "未命名")
        self.assertEqual(util.sanitize_name("", fallback="回退名"), "回退名")
        self.assertEqual(util.sanitize_name("..."), "未命名")

    def test_whitespace_and_control_chars(self):
        self.assertEqual(util.sanitize_name("全角\u3000空格"), "全角 空格")
        self.assertEqual(util.sanitize_name("多    空格"), "多 空格")
        self.assertEqual(util.sanitize_name("a\x00b\x1fc"), "abc")
        self.assertEqual(util.sanitize_name("  首尾空白  "), "首尾空白")

    def test_chinese_and_japanese_kept(self):
        self.assertEqual(util.sanitize_name("葬送的芙莉莲"), "葬送的芙莉莲")
        self.assertEqual(util.sanitize_name("アニメ 第01话"), "アニメ 第01话")
        # 方括号/书名号是字幕组标记，按 sanitize_name 的契约会被清掉，中文日文本身保留
        self.assertEqual(util.sanitize_name("[北宇治字幕组] 葬送的芙莉莲"), "北宇治字幕组 葬送的芙莉莲")
        self.assertEqual(util.sanitize_name("【组】名字"), "组名字")

    def test_usable_as_path_component(self):
        name = util.sanitize_name('葬送的芙莉莲 / 第一季 <1080p>')
        path = os.path.join(r"D:\Anime", name)
        self.assertIn("葬送的芙莉莲", path)
        self.assertNotIn("/", name)
        self.assertNotIn("<", name)


class TestParseEpisodeRange(unittest.TestCase):
    """集数范围与单集编号解析。"""

    def test_bracket_range_is_batch(self):
        self.assertEqual(util.parse_episode_range("[Sakurato] Title [01-12][1080p]"), (1, 12, True))
        self.assertEqual(util.parse_episode("[Sakurato] Title [01-12][1080p]"), 12)

    def test_chinese_episode(self):
        self.assertEqual(util.parse_episode_range("第09话 测试"), (9, 9, False))
        self.assertEqual(util.parse_episode_range("第9集"), (9, 9, False))
        self.assertEqual(util.parse_episode("第09话 测试"), 9)
        self.assertEqual(util.parse_episode_range("Show 第01-12话"), (1, 12, True))

    def test_season_episode(self):
        self.assertEqual(util.parse_episode_range("Show S02E05 1080p"), (5, 5, False))
        self.assertEqual(util.parse_episode("Show S02E05 1080p"), 5)
        self.assertEqual(util.parse_episode("Show S01E12"), 12)

    def test_dash_number_in_brackets_context(self):
        self.assertEqual(util.parse_episode_range("Title - 09 [1080p]"), (9, 9, False))
        self.assertEqual(util.parse_episode("Title - 09 [1080p]"), 9)

    def test_v2_suffix(self):
        self.assertEqual(util.parse_episode_range("Name [12v2][720p]"), (12, 12, False))
        self.assertEqual(util.parse_episode("Name [12v2][720p]"), 12)

    def test_no_episode(self):
        self.assertEqual(util.parse_episode_range("无集数的标题 1080p"), (None, None, False))
        self.assertIsNone(util.parse_episode("无集数的标题 1080p"))
        self.assertIsNone(util.parse_episode(""))
        self.assertEqual(util.parse_episode_range(""), (None, None, False))

    def test_ep_prefix(self):
        self.assertEqual(util.parse_episode("Title EP13"), 13)
        self.assertEqual(util.parse_episode("Title E13"), 13)

    def test_full_width_brackets(self):
        self.assertEqual(util.parse_episode("【07】测试"), 7)

    def test_batch_hint_without_range(self):
        start, end, is_batch = util.parse_episode_range("某番 全集")
        self.assertIsNone(start)
        self.assertIsNone(end)
        self.assertTrue(is_batch)
        # 合集标题即使带集数也标记为合集
        self.assertEqual(util.parse_episode_range("Show 01-12 END"), (1, 12, True))

    def test_end_is_finale_not_batch(self):
        """`Show - 12 END` 是**最终话**，不是合集（以前判成合集 → 自动追番永远漏最后一集）。"""
        self.assertEqual(util.parse_episode_range("Show 12 END"), (12, 12, False))
        self.assertEqual(util.parse_episode_range("[Group] Anime - 12 END [1080p]"), (12, 12, False))
        self.assertEqual(util.parse_episode("Show 12 END"), 12)

    def test_word_boundary_batch_words(self):
        """英文合集词要词边界：Weekend 里的 end、Final 里的 fin 都不算。"""
        self.assertFalse(util.parse_episode_range("Cool Show Weekend Special - 05 [1080p]")[2])
        self.assertFalse(util.parse_episode_range("Some Anime Final Season - 12 [1080p]")[2])
        self.assertTrue(util.parse_episode_range("Show Batch [1080p]")[2])
        self.assertTrue(util.parse_episode_range("Show Complete [1080p]")[2])

    def test_movie_is_not_batch(self):
        """剧场版是单片：不算合集（以前按标题里的 movie 判合集，弹窗默认隐藏了整排）。"""
        title = "[北宇治字幕组] GROTESQQQUE - 夜露死駆★少女 [Movie][WebRip][繁日內嵌]"
        start, end, is_batch = util.parse_episode_range(title)
        self.assertFalse(is_batch)
        self.assertIsNone(start)
        self.assertTrue(util.looks_like_movie(title))
        self.assertFalse(util.looks_like_movie("[Group] Anime - 05 [1080p]"))

    def test_part_number_is_not_episode(self):
        """`(Part 2: …)` 是分段标记，不是第 2 集。"""
        title = "[ToonsHub] Grotesqqque (2026) (Part 2: YOROSHIKU Girl) 1080p WEB-DL"
        self.assertEqual(util.parse_episode_range(title), (None, None, False))
        self.assertIsNone(util.parse_episode(title))

    def test_container_token_is_not_episode(self):
        """aniparse 会把容器格式 `[MP4]` 拆成「MP」+ 集号 4 —— 容器不是集号。"""
        self.assertEqual(
            util.parse_episode_range("[Lilith-Raws] 劇場版 某番 Movie [Baha][1080p][AVC AAC][CHT][MP4]"),
            (None, None, False))
        self.assertEqual(util.parse_episode("[Lilith-Raws] 某番 - 11 [1080p][AVC AAC][MP4]"), 11)

    def test_unbracketed_range_is_batch(self):
        """不带方括号的范围（动漫花园写成 `S01 | 01-12`）也要认成合集。"""
        self.assertEqual(util.parse_episode_range("[7³ACG] 幻想嘉年华 S01 | 01-12 [简繁字幕]"), (1, 12, True))
        self.assertEqual(util.parse_episode_range("Show 1-24v2 [1080p]"), (1, 24, True))
        self.assertIsNone(util.loose_range("2026-10-22"))
        self.assertIsNone(util.loose_range("AAC2.0-5.1"))

    def test_title_with_season_digit_plus_episode_is_not_range(self):
        """`异世界四重奏3 - 11` 是「番名带季数 + 第 11 集」，不是「第 3~11 集」。"""
        self.assertEqual(util.parse_episode_range(
            "[LoliHouse] 异世界四重奏3 / Isekai Quartet 3 - 11 [WebRip 1080p]"), (11, 11, False))
        self.assertEqual(util.parse_episode_range("[Group] 四重奏3-11 [1080p]"), (11, 11, False))
        self.assertEqual(util.parse_episode_range("[Group] Show 1080p-720p test"), (None, None, False))

    def test_category_decides_batch(self):
        """动漫花园分类「季度全集」是权威口径；Nyaa/爱恋的分类和合集无关。"""
        from app.sources.base import Resource, enrich
        quarterly = enrich(Resource(source="dmhy", title="[Group] 某番 [1080p]", category="季度全集"))
        self.assertTrue(quarterly.is_batch, "分类说季度全集 → 合集")
        single = enrich(Resource(source="dmhy", title="[Group] 某番 [1080p]", category="動畫"))
        self.assertFalse(single.is_batch, "分类说動畫 → 不是合集")
        nyaa = enrich(Resource(source="nyaa", title="[Group] 某番 [1080p]",
                               category="Anime - English-translated"))
        self.assertFalse(nyaa.is_batch, "Nyaa 的分类是语言/来源，不是合集")
        movie = enrich(Resource(source="dmhy", title="[Group] 某番 剧场版 [1080p]", category="動畫"))
        self.assertTrue(movie.is_movie)
        self.assertFalse(movie.is_batch, "剧场版即使分类是動畫也不是合集")

    def test_resolution_is_not_episode(self):
        self.assertIsNone(util.parse_episode("Show 1080p"))
        self.assertIsNone(util.parse_episode("Show HEVC 10bit"))


class TestParseResolution(unittest.TestCase):
    def test_common_tokens(self):
        self.assertEqual(util.parse_resolution("[Group] Title [1080p]"), "1080p")
        self.assertEqual(util.parse_resolution("Title 2160p"), "2160p")
        self.assertEqual(util.parse_resolution("Title 4K"), "2160p")
        self.assertEqual(util.parse_resolution("Title 720p"), "720p")
        self.assertEqual(util.parse_resolution(""), "")
        self.assertEqual(util.parse_resolution("Title 1920x1080"), "")
        self.assertEqual(util.parse_resolution("Title 1080i"), "1080i")

    def test_case_insensitive(self):
        self.assertEqual(util.parse_resolution("title 1080P"), "1080p")


class TestParseSize(unittest.TestCase):
    def test_binary_and_decimal_units(self):
        self.assertEqual(util.parse_size("1.4 GiB"), 1503238553)
        self.assertEqual(util.parse_size("48.5GB"), 52076478464)
        self.assertEqual(util.parse_size("700 MB"), 734003200)
        self.assertEqual(util.parse_size("12 KB"), 12288)
        self.assertEqual(util.parse_size("2.5 TB"), 2748779069440)
        self.assertEqual(util.parse_size("1.5MiB"), 1572864)

    def test_empty_and_invalid(self):
        self.assertEqual(util.parse_size(""), 0)
        self.assertEqual(util.parse_size("abc"), 0)
        self.assertEqual(util.parse_size("0 B"), 0)

    def test_human_size(self):
        self.assertEqual(util.human_size(0), "-")
        self.assertEqual(util.human_size(1), "1 B")
        self.assertEqual(util.human_size(1024), "1.00 KB")
        self.assertEqual(util.human_size(1536), "1.50 KB")
        self.assertEqual(util.human_size(1048576), "1.00 MB")
        self.assertEqual(util.human_size(1503238553), "1.40 GB")
        self.assertEqual(util.human_size(52076478464), "48.50 GB")

    def test_round_trip(self):
        for text in ("1.4 GiB", "700 MB", "48.5GB"):
            self.assertGreater(util.parse_size(text), 0)


class TestToSimplified(unittest.TestCase):
    """简繁转换（表驱动）。只覆盖表中已收录的常用字。

    注意：该表目前不完整（例如 話/進/蓮 未收录），本文件只断言已收录且映射正确的字。
    """

    def test_common_traditional_to_simplified(self):
        self.assertEqual(util.to_simplified("繁體字與簡體字"), "繁体字与简体字")
        self.assertEqual(util.to_simplified("萬與東車馬龍魚"), "万与东车马龙鱼")
        self.assertEqual(util.to_simplified("說語讀"), "说语读")
        self.assertEqual(util.to_simplified("已經"), "已经")
        self.assertEqual(util.to_simplified("實樣麼戰將過應業動務區單"), "实样么战将过应业动务区单")

    def test_simplified_text_unchanged(self):
        self.assertEqual(util.to_simplified("简体字与繁体字"), "简体字与繁体字")
        self.assertEqual(util.to_simplified("abcABC123"), "abcABC123")
        self.assertEqual(util.to_simplified(""), "")
        self.assertEqual(util.to_simplified("葬送的芙莉莲"), "葬送的芙莉莲")

    def test_idempotent(self):
        once = util.to_simplified("繁體字與簡體字")
        self.assertEqual(util.to_simplified(once), once)

    def test_has_traditional(self):
        self.assertTrue(util.has_traditional("繁體"))
        self.assertFalse(util.has_traditional("简体字"))
        self.assertFalse(util.has_traditional(""))
        self.assertFalse(util.has_traditional("abc123"))


class TestNormalizeTitle(unittest.TestCase):
    def test_full_width_space_and_case(self):
        self.assertEqual(util.normalize_title("【測試】 Title - 09 [1080p]　ＡＢＣ"), "測試title091080pabc")

    def test_empty(self):
        self.assertEqual(util.normalize_title(""), "")
        self.assertEqual(util.normalize_title(" 　-· "), "")


class TestMisc(unittest.TestCase):
    def test_is_noise_title(self):
        self.assertTrue(util.is_noise_title("[Group] Show NCOP"))
        self.assertTrue(util.is_noise_title("[Group] Show PV"))
        self.assertTrue(util.is_noise_title("[Group] Show OST"))
        self.assertFalse(util.is_noise_title("[Group] Show - 09 [1080p]"))

    def test_uniq_keep_order(self):
        self.assertEqual(util.uniq_keep_order(["a", "b", "a", "c", "", "b"]), ["a", "b", "c"])

    def test_join_path(self):
        self.assertEqual(util.join_path(r"D:\Anime", "葬送的芙莉莲"), os.path.normpath(r"D:\Anime\葬送的芙莉莲"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
