# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""集数识别的离线测试：季数标记不能当集号 + 系列连续编号换算成本季集号。

对应用户反馈：「这里识别的集数也错了，这里是第二季第一集」
—— 标题 `[ANi] Season 2 - 171 …`（黑色五叶草第二季，系列连续编号）被识别成第 2 集。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core.util import (  # noqa: E402
    episode_offset_for, in_current_season, parse_episode, parse_episode_range,
    resolve_episode_offset,
)


class ParseEpisodeTest(unittest.TestCase):
    def test_season_number_is_not_episode(self):
        """用户报的那条：Season 2 - 171 是第 171 集，不是第 2 集。"""
        self.assertEqual(parse_episode("[ANi] Season 2 - 171 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]黑色五葉草"), 171)
        self.assertEqual(parse_episode("[ANi] Black Clover Season 2 - 171 [1080P][Baha]"), 171)
        self.assertEqual(parse_episode("[黒ネズミたち] Season 2 / Black Clover 2nd Season - 171 (Baha 1920x1080)"), 171)
        self.assertEqual(parse_episode("[Group] Anime Season 2 - 05 [1080p]"), 5)

    def test_hash_like_token_not_episode(self):
        """[E6AB6CBC] 这种种子名里的 E+数字不是集号（以前会解析成第 6 集）。"""
        self.assertEqual(parse_episode("[SubsPlease] Black Clover - 171 (480p) [E6AB6CBC].mkv"), 171)
        self.assertEqual(parse_episode("[Group] Anime - 12 [A1B2C3D4].mkv"), 12)

    def test_sxxexx_still_works(self):
        self.assertEqual(parse_episode("[Group] Anime S02E05 [1080p]"), 5)
        self.assertEqual(parse_episode("[Group] Anime S2E12v2 [1080p]"), 12)

    def test_chinese_season_and_episode(self):
        self.assertEqual(parse_episode("[Group] Anime 第2季 第5话 [1080p]"), 5)
        self.assertEqual(parse_episode("[Group] Anime 第2期 09 [1080p]"), 9)
        self.assertEqual(parse_episode("[Group] Anime 第09集 [1080p]"), 9)

    def test_bare_season_has_no_episode(self):
        self.assertIsNone(parse_episode("[Group] Anime Season 2 [1080p]"))
        self.assertIsNone(parse_episode("[Group] Anime 2nd Season [1080p]"))
        self.assertIsNone(parse_episode("[Group] Anime 第二季 [1080p]"))

    def test_bracket_and_dash_forms(self):
        self.assertEqual(parse_episode("[Group] Anime [02][1080p]"), 2)
        self.assertEqual(parse_episode("[Group] Anime - 09v2 [1080p]"), 9)
        self.assertEqual(parse_episode("[LoliHouse] Anime - 14 [WebRip 1080p HEVC-10bit AAC][简繁内封字幕]"), 14)

    def test_ranges_unchanged(self):
        self.assertEqual(parse_episode_range("[Group] Anime [01-12][1080p]"), (1, 12, True))
        self.assertEqual(parse_episode("[Group] Anime [01-12][1080p]"), 12)
        self.assertEqual(parse_episode("[Group] Anime Season 2 [01-13 Fin]"), 13)


class EpisodeOffsetTest(unittest.TestCase):
    def test_black_clover_case(self):
        """黑色五叶草第二季（13 话）发布组用 171~183：偏移 170 → 本季第 1~13 集。"""
        self.assertEqual(episode_offset_for(range(171, 184), 13), 170)
        self.assertEqual(episode_offset_for([171], 13), 170)

    def test_relative_numbering_needs_no_offset(self):
        self.assertEqual(episode_offset_for(range(1, 14), 13), 0)
        # 混着本季编号（1、2）和系列连续编号（171+）时，只看超过本季话数的那批
        self.assertEqual(episode_offset_for([1, 2, 3, 171, 172], 13), 170)

    def test_conservative_when_unknown_or_spread(self):
        self.assertEqual(episode_offset_for([171, 172], 0), 0, "本季话数未知不换算")
        self.assertEqual(episode_offset_for([5], 12), 0, "集号不超过本季话数不换算")
        self.assertEqual(episode_offset_for([20, 40, 72, 171], 13), 0, "连续编号那批跨度太大就放弃")
        self.assertEqual(episode_offset_for([], 13), 0)


class EpisodeNormalizeTest(unittest.TestCase):
    """订阅记账里的集号换算（进度不能出现「50 / 12 集」这种）。"""

    def test_normalize_episode_number(self):
        from app.core.watcher import normalize_episode_number
        # 有偏移量且集号在偏移量之上 → 换算（药屋第三季 50 → 第 2 集）
        self.assertEqual(normalize_episode_number(50, 48, 12), 2)
        self.assertEqual(normalize_episode_number(15, 14, 12), 1, "冰之城墙第二季 [15] = 本季第 1 集")
        # 已经是本季集号 / 没有偏移量 / 空值 → 原样
        self.assertEqual(normalize_episode_number(2, 48, 12), 2)
        self.assertEqual(normalize_episode_number(3, 0, 12), 3)
        self.assertIsNone(normalize_episode_number(None, 48, 12))

    def test_fix_stale_last_episode(self):
        from app.core.watcher import _normalize_last_episode

        class S:
            last_episode = 0

        cases = [
            # (订阅里记的, 当前偏移, 旧偏移, 总话数, 期望)
            (50, 48, 49, 12, 2),      # 药屋第三季：手动下载记了标题原始编号
            (15, 14, 13, 12, 1),      # 冰之城墙第二季：[15] = 本季第 1 集
            (2, 48, 48, 12, None),    # 已经是本季集号，不动
            (12, 0, 0, 12, None),
            (1, 48, 48, 12, None),
            (0, 48, 48, 12, None),
            (50, 0, 49, 12, 1),       # 当前偏移量没算出来 → 用订阅里存过的旧偏移量
        ]
        for cur, off, old, total, want in cases:
            s = S()
            s.last_episode = cur
            got = _normalize_last_episode(s, off, total, old)
            self.assertEqual(got, want, f"last={cur} 偏移={off}/{old} 总话数={total} → 期望 {want}，实际 {got}")


class SeasonScopeTest(unittest.TestCase):
    def test_date_rule_beats_others(self):
        """按开播日期圈本季资源：药屋第三季（12 话，开播 2026-10-02）是 49~。"""
        items = [
            {"title": "[喵萌奶茶屋] 药屋少女的呢喃 [48][1080p]", "episode": 48, "published": "2025/10/23 19:55"},
            {"title": "[天月搬運組] 药师少女的独语 - 49 (NetFlix)", "episode": 49, "published": "2026/10/02"},
            {"title": "【喵萌奶茶屋】[药师少女的独语 / 药屋少女的呢喃][49][1080p]", "episode": 49, "published": "2026/10/05 10:53"},
        ]
        self.assertEqual(resolve_episode_offset(items, 12, 3, "2026-10-02"), (48, 49))

    def test_preair_included(self):
        """大魔王第二季电视开播 10-03，先行配信的 13（=本季第 1 集）09-27 就发了。"""
        items = [
            {"title": "[LoliHouse] 野生的大魔王出现了！ - 12 [合集]", "episode": 12, "published": "2025/12/26"},
            {"title": "[黒ネズミたち] 野生的大魔王出现了！第二季 - 13", "episode": 13, "published": "2026/09/27 01:10"},
            {"title": "[LoliHouse] 野生的大魔王出现了！ - 14 [WebRip]", "episode": 14, "published": "2026/10/04 00:03"},
        ]
        self.assertEqual(resolve_episode_offset(items, 12, 2, "2026-10-03"), (12, 13))

    def test_in_current_season(self):
        # 本季区间 = [起点, 起点+总话数-1]；写明本季季数的一律保留；写明别的季一律排除
        self.assertTrue(in_current_season({"title": "x [177]", "episode": 177}, base=177, total_episodes=52, sub_season=5))
        self.assertTrue(in_current_season({"title": "x [228]", "episode": 228}, base=177, total_episodes=52, sub_season=5))
        self.assertFalse(in_current_season({"title": "x [176]", "episode": 176}, base=177, total_episodes=52, sub_season=5))
        self.assertFalse(in_current_season({"title": "x [229]", "episode": 229}, base=177, total_episodes=52, sub_season=5))
        self.assertTrue(in_current_season({"title": "x 第五季 - 01", "episode": 1}, base=177, total_episodes=52, sub_season=5))
        self.assertFalse(in_current_season({"title": "x 第二季 [12]", "episode": 12}, base=177, total_episodes=52, sub_season=5))
        self.assertTrue(in_current_season({"title": "x [7]", "episode": 7}, base=0, total_episodes=52, sub_season=5))

    def test_franchise_mixed_results(self):
        # 黑色五叶草第二季的搜索结果混着第 1 季（20/40/72）和本季（171+）
        items = [
            {"title": "[ANi] 黑色五葉草 Season 2 - 171 [1080P]", "episode": 171},
            {"title": "[黒ネズミたち] Season 2 / Black Clover 2nd Season - 172 (Baha)", "episode": 172},
            {"title": "[SubsPlease] Black Clover - 173 (1080p) [XX].mkv", "episode": 173},
            {"title": "[LoliHouse] Black Clover - 20 [WebRip]", "episode": 20},
            {"title": "[LoliHouse] Black Clover - 72 [WebRip]", "episode": 72},
        ]
        self.assertEqual(resolve_episode_offset(items, 13, 2), (170, 171))

    def test_falls_back_to_whole_batch(self):
        items = [{"title": "X - 171", "episode": 171}, {"title": "X - 172", "episode": 172}]
        self.assertEqual(resolve_episode_offset(items, 13, 0), (170, 171))

    def test_no_offset_for_relative_numbering(self):
        items = [{"title": "X - 01", "episode": 1}, {"title": "X - 02", "episode": 2}]
        self.assertEqual(resolve_episode_offset(items, 12, 1), (0, 0))


class SeasonTokenRuleTest(unittest.TestCase):
    """用户定的规则 1：本季标识从「番剧名 + 别名」两处搜集，命中任意一个就算本季。"""

    def test_tokens_from_name_and_alias(self):
        from app.core.util import season_tokens
        # 「…篇」→ 取「篇」前面最后一个空格之后的字符，并保留带「篇」的写法
        self.assertEqual(season_tokens(["凡人修仙传 慕兰之战篇"]), ["慕兰之战篇", "慕兰之战"])
        self.assertEqual(season_tokens(["凡人修仙传 第五季"]), ["第五季"])
        self.assertEqual(season_tokens(["Kusuriya no Hitorigoto 3rd Season"]), ["3rd Season"])
        self.assertEqual(season_tokens(["X Season 2"]), ["Season 2"])
        # 裸番名不是标识，否则整部系列都会被当成本季
        self.assertEqual(season_tokens(["凡人修仙传"]), [])
        # 「篇」前面没有空格的连写，切不出篇章边界 → 整条不用（避免把番名也切进来）
        self.assertEqual(season_tokens(["凡人慕兰之战篇"]), [])

    def test_hit(self):
        from app.core.util import season_hit, season_tokens
        tokens = season_tokens(["凡人修仙传 第五季", "凡人修仙传 慕兰之战篇"])
        self.assertTrue(season_hit("[LoliHouse] 凡人修仙传 慕兰之战 - 05 [1080p]", tokens))
        self.assertTrue(season_hit("[LoliHouse] 凡人修仙传 第五季 - 03 [1080p]", tokens))
        self.assertFalse(season_hit("[LoliHouse] 凡人修仙传 星海飞驰 - 120 [1080p]", tokens))
        self.assertTrue(season_hit("X season 2 - 01", ["Season 2"]))
        # ASCII 字边界：「Season 2」不能命中「Season 20」
        self.assertFalse(season_hit("X Season 20 - 01", ["Season 2"]))

    def test_apply_rules_token_kept(self):
        from app.core.util import apply_season_rules
        items = [
            {"title": "[LoliHouse] 凡人修仙传 慕兰之战 - 05 [1080p]", "episode": 5},
            {"title": "[LoliHouse] 凡人修仙传 星海飞驰 - 120 [1080p]", "episode": 120},
            {"title": "[LoliHouse] 凡人修仙传 - 177 [1080p]", "episode": 177},
            {"title": "[LoliHouse] 凡人修仙传 第二季 - 30 [1080p]", "episode": 30},
        ]
        keep, offset, hidden = apply_season_rules(
            items, total_episodes=52, sub_season=5, start_ep=177,
            names=["凡人修仙传 第五季"], aliases=["凡人修仙传 慕兰之战篇"])
        self.assertEqual(keep, [0, 2], "别名片段 慕兰之战 命中、177 落在本季区间")
        self.assertEqual(offset, 176)
        self.assertEqual(hidden, 2, "星海飞驰 120 和 第二季 都要排除")



    """server._prepare_episodes：接口层做「季判定 + 集号换算」，其它季直接不返回。"""

    def setUp(self):
        from app.web import server
        self.server = server

    def test_offsets_items(self):
        items = [{"episode": 171, "episode_end": 171}, {"episode": 172, "episode_end": 172},
                 {"episode": 183, "episode_end": 183}]
        out, offset, hidden = self.server._prepare_episodes(items, {"total_episodes": 13})
        self.assertEqual(offset, 170)
        self.assertEqual(hidden, 0)
        self.assertEqual([it["episode"] for it in out], [1, 2, 13])
        self.assertEqual([it["episode_absolute"] for it in out], [171, 172, 183])
        self.assertEqual(items[0]["episode"], 171, "不应改动入参")

    def test_episode_range_is_not_filtered(self):
        """只按「集号 < 本季起点」排除上季；标题写明本季的保留（集号上限不再参与判断）。"""
        items = [
            {"title": "[ANi] 黑色五葉草 Season 2 - 171 [1080P]", "episode": 171},
            {"title": "[LoliHouse] Black Clover - 20 [WebRip]", "episode": 20},
            {"title": "[LoliHouse] Black Clover - 72 [WebRip]", "episode": 72},
        ]
        out, offset, hidden = self.server._prepare_episodes(
            items, {"total_episodes": 13, "display_name": "黑色五叶草 第二季"})
        self.assertEqual(offset, 170)
        self.assertEqual(hidden, 2, "上季的 20/72 要被排除，本季 171 保留")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["episode"], 1)
        self.assertEqual(out[0]["episode_absolute"], 171)


    def test_keeps_items_when_no_offset(self):
        items = [{"episode": 1}, {"episode": 2}]
        out, offset, hidden = self.server._prepare_episodes(items, {"total_episodes": 13})
        self.assertEqual((offset, hidden), (0, 0))
        self.assertNotIn("episode_absolute", out[0])

    def test_handles_missing_episode(self):
        items = [{"episode": None}, {}, {"episode": 0}]
        out, offset, hidden = self.server._prepare_episodes(items, {"total_episodes": 13})
        self.assertEqual((offset, hidden), (0, 0))
        self.assertEqual(len(out), 3)


if __name__ == "__main__":
    unittest.main()
