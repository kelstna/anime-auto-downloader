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
        self.assertEqual(util.parse_episode_range("Show 12 END"), (12, 12, True))

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
