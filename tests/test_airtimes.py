# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""番剧更新时刻（app/core/airtimes.py）的离线测试：不联网。

覆盖：
- bangumi-data 的 `broadcast` RFC5545 周期解析（P7D / P2W / P1D / 乱写）
- 由 `begin` + 周期算「下一次更新」（北京时间精确到分钟 + 日本时间）
- 界面文案与悬浮说明（含日本时间 / 电视台 / 数据来源）
- 缓存新鲜期（每天刷新）与「没有数据就返回 None」
对应用户要求：「缓存到 data/airtimes.json 每天刷新一次；卡片显示下次更新：10-12 00:20（周一）· 北京时间」
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import airtimes  # noqa: E402

CST = timezone(timedelta(hours=8))
JST = timezone(timedelta(hours=9))


class RruleTest(unittest.TestCase):
    def test_period_parsing(self):
        self.assertEqual(airtimes.parse_period("R/2026-10-04T16:20:00.000Z/P7D"), 7 * 86400)
        self.assertEqual(airtimes.parse_period("R/2026-10-04T16:20:00.000Z/P1D"), 86400)
        self.assertEqual(airtimes.parse_period("R/2026-10-04T16:20:00.000Z/P2W"), 14 * 86400)
        self.assertEqual(airtimes.parse_period(""), 7 * 86400, "解析不出来按每周算")
        self.assertEqual(airtimes.parse_period("每周日 24:30"), 7 * 86400)

    def test_next_airing(self):
        begin = datetime(2026, 10, 4, 16, 20, tzinfo=timezone.utc).timestamp()
        period = 7 * 86400
        # 首播前 → 就是首播
        before = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
        self.assertEqual(airtimes.next_airing(begin, period, before), begin)
        # 首播后一周内 → 下一周
        after = datetime(2026, 10, 6, tzinfo=timezone.utc).timestamp()
        self.assertEqual(airtimes.next_airing(begin, period, after), begin + period)
        # 正好踩在首播时刻 → 下一周（不返回过去）
        self.assertEqual(airtimes.next_airing(begin, period, begin), begin + period)
        self.assertIsNone(airtimes.next_airing(0, period, after))


class DescribeTest(unittest.TestCase):
    """用户要的文案：`下次更新：10-12 00:20（周一）· 北京时间`（悬浮看日本时间/电视台/来源）。"""

    def setUp(self):
        self._saved_cache = airtimes._cache
        self._saved_path = airtimes.CACHE_PATH
        tmp = tempfile.mkdtemp(prefix="airtime-")
        self._tmp = tmp
        airtimes.CACHE_PATH = os.path.join(tmp, "airtimes.json")
        # 2026-10-04 16:20 UTC = 北京时间 10-05 00:20（周一）／日本时间 10-05 01:20
        begin = datetime(2026, 10, 4, 16, 20, tzinfo=timezone.utc).timestamp()
        airtimes._cache = {
            "schema": airtimes.SCHEMA, "updated": int(time.time()), "source": "test",
            "count": 1,
            "items": {"630160": {"title": "ダークサモナーとデキている", "title_cn": "黑暗召唤师在地下恋爱中",
                                 "begin": int(begin), "period": 7 * 86400, "sites": {}, "site": ""}},
        }

    def tearDown(self):
        airtimes._cache = self._saved_cache
        airtimes.CACHE_PATH = self._saved_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_next_text_timezone(self):
        info = airtimes.for_subject(630160)
        self.assertTrue(info, "应该能查到数据")
        # 把「现在」拨到首播之后，验算下一集
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc).timestamp()
        item = (airtimes.load() or {}).get("items", {}).get("630160")
        d = airtimes.describe(item, now)
        self.assertEqual(d["next_text"], "10-12 00:20（周一）", f"北京时间：{d}")
        self.assertEqual(d["cst_text"], "10-12 00:20（周一）· 北京时间")
        self.assertEqual(d["jst_text"], "10-12 01:20（周一）· 日本时间", "日本时间比北京时间早 1 小时")
        self.assertEqual(d["next_full"], "2026-10-12 00:20（周一）")
        self.assertEqual(d["begin_text"], "首播 10-05 00:20（周一）")
        self.assertTrue(d["weekly"])

    def test_attach_tooltip(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc).timestamp()
        item = (airtimes.load() or {}).get("items", {}).get("630160")
        airtimes._cache["items"]["630160"]["begin"] = int(item["begin"])
        info = airtimes.attach(630160, "TOKYO MX")
        self.assertIn("下次更新：", info["tip"])
        self.assertIn("北京时间", info["tip"])
        self.assertIn("日本时间：", info["tip"])
        self.assertIn("电视台：TOKYO MX", info["tip"])
        self.assertIn("bangumi-data", info["tip"])
        self.assertEqual(info["station"], "TOKYO MX")
        self.assertEqual(info["source"], "bangumi-data")

    def test_missing_subject(self):
        self.assertIsNone(airtimes.for_subject(999999))
        self.assertEqual(airtimes.attach(999999, "X"), {})

    def test_not_blocking_when_no_data(self):
        """缓存为空时也不能抛异常（接口路径上必须安全）。"""
        airtimes._cache = None
        airtimes.CACHE_PATH = os.path.join(self._tmp, "missing.json")
        self.assertIsNone(airtimes.for_subject(630160))
        self.assertEqual(airtimes.status()["count"], 0)


class FinishedTest(unittest.TestCase):
    """已完结判断：完结的番不能再显示编造的「下次更新」。"""

    def setUp(self):
        self._saved = airtimes._cache
        airtimes._cache = None

    def tearDown(self):
        airtimes._cache = self._saved

    @staticmethod
    def _item(y, m, d, hh=20, mm=0):
        begin = datetime(y, m, d, hh, mm, tzinfo=timezone.utc).timestamp()
        return {"begin": int(begin), "period": 7 * 86400, "end": 0, "title": "x"}

    def test_finished_when_all_episodes_aired(self):
        # 2026-07-09 首播、12 话周更 → 最后一集 2026-09-24，现在（10-10）已经播完
        item = self._item(2026, 7, 9)
        now = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
        d = airtimes.describe(item, now=now, total_episodes=12)
        self.assertTrue(d["finished"], "12 话播完应判为已完结")
        self.assertEqual(d["finished_text"], "已完结")
        self.assertIn("最后一集", d["end_text"])

    def test_ongoing_not_finished(self):
        # 当季在播：2026-10-02 首播、12 话 → 最后一集还没到
        item = self._item(2026, 10, 2, 22, 0)
        now = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
        d = airtimes.describe(item, now=now, total_episodes=12)
        self.assertFalse(d["finished"], "还在播的不能判完结")
        self.assertIn("（周", d["next_text"])

    def test_unknown_total_not_finished(self):
        """总话数未知又没有 end 字段 → 不敢下结论（宁可不判）。"""
        item = self._item(2026, 7, 9)
        now = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
        self.assertFalse(airtimes.describe(item, now=now, total_episodes=0)["finished"])

    def test_end_field_wins(self):
        item = self._item(2026, 7, 9)
        item["end"] = int(datetime(2026, 9, 25, tzinfo=timezone.utc).timestamp())
        now = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
        self.assertTrue(airtimes.describe(item, now=now, total_episodes=0)["finished"])

    def test_not_yet_aired(self):
        item = self._item(2026, 11, 1)
        now = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
        d = airtimes.describe(item, now=now, total_episodes=12)
        self.assertFalse(d["finished"])
        self.assertTrue(d["next_full"].startswith("2026-11"), f"还没开播就显示首播时间：{d['next_full']}")

    def test_aired_episode_and_time(self):
        """「已经更新到哪一集」：侧栏「最近更新」按这个排序。"""
        # 药屋第三季：2026-10-02 22:00（北京时间）首播、每周；站在 10-11 中午看 → 已播第 2 集（10-09）
        item = {"begin": int(datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc).timestamp()),
                "period": 7 * 86400, "end": 0, "title": "x"}
        now = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc).timestamp()
        d = airtimes.describe(item, now=now, total_episodes=12)
        self.assertEqual(d["aired_text"], "10-09 22:00", f"北京时间：{d['aired_text']}")
        self.assertEqual(d["episode_no"], 2)
        self.assertIn("2026-10-09", d["aired_full"])
        self.assertFalse(d["finished"])
        # 还没开播 → 没有「已更新」
        future = {"begin": int(datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc).timestamp()),
                  "period": 7 * 86400, "end": 0}
        d2 = airtimes.describe(future, now=now, total_episodes=12)
        self.assertEqual(d2["aired_ts"], 0)
        self.assertEqual(d2["aired_text"], "")

    def test_aired_capped_for_finished(self):
        """已完结的番，「已更新」要停在最后一集（不能一直往后滚）。"""
        item = {"begin": int(datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc).timestamp()),
                "period": 7 * 86400, "end": 0, "title": "x"}
        now = datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp()
        d = airtimes.describe(item, now=now, total_episodes=12)
        self.assertTrue(d["finished"])
        self.assertEqual(d["episode_no"], 12, "最后一集就是第 12 集")
        self.assertLess(d["aired_ts"], now - 7 * 86400, "已完结的不会显示成刚更新")

    def test_attach_tip_for_finished(self):
        item = self._item(2026, 7, 9)
        now = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
        info = airtimes.describe(item, now=now, total_episodes=12)
        info.update({"station": "TOKYO MX", "updated": int(now), "stale": False})
        # 复用 attach 的文案拼装逻辑（直接调内部拼接不方便，这里手工核对字段）
        self.assertEqual(info["finished_text"], "已完结")
        self.assertIn("北京时间", info["end_text"])


class CacheTest(unittest.TestCase):
    def test_stale_after_24h(self):
        fresh = {"updated": int(time.time())}
        old = {"updated": int(time.time()) - 25 * 3600}
        self.assertFalse(airtimes.is_stale(fresh))
        self.assertTrue(airtimes.is_stale(old), "超过 24 小时就该刷新")
        self.assertTrue(airtimes.is_stale(None), "没有缓存当然要刷")
        self.assertFalse(airtimes.is_stale(fresh, hours=48))

    def test_index_building(self):
        payload = json.dumps({
            "items": [
                {"title": "A", "begin": "2026-10-04T16:20:00.000Z",
                 "broadcast": "R/2026-10-04T16:20:00.000Z/P7D",
                 "sites": [{"site": "bangumi", "id": "1"}, {"site": "aniList", "id": "99"}],
                 "titleTranslate": {"zh-Hans": ["甲"]}},
                {"title": "没有 bangumi id", "begin": "2026-10-05T00:00:00.000Z", "sites": []},
                {"title": "没有 begin", "sites": [{"site": "bangumi", "id": "2"}]},
            ]
        }, ensure_ascii=False).encode("utf-8")
        data = airtimes._index(payload)
        self.assertEqual(data["count"], 1, "缺 begin / 缺 bangumi id 的条目要跳过")
        item = data["items"]["1"]
        self.assertEqual(item["title_cn"], "甲")
        self.assertEqual(item["period"], 7 * 86400)
        self.assertEqual(item["sites"]["aniList"], "99")


if __name__ == "__main__":
    unittest.main()
