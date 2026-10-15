# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""Bangumi 元数据缓存的离线测试。

对应用户反馈：「动漫花园那 80 条为什么还是被当成上一季」——
缓存里的 aliases 是老的（来自「在看」列表，没有 infobox 的「别名」），
季判定拿不到「凡人修仙传 慕兰之战篇」里的篇章名，于是按篇章名发的资源全被隐藏。
这里保证：缓存被刷新时章节表/别名不被冲掉，force 刷新能真正联网。
"""
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import bangumi, meta  # noqa: E402


class MetaNormalizeTest(unittest.TestCase):
    def test_int_eps_is_not_stored_as_chapter_table(self):
        """Subject.eps 是「话数」（int），不能写进缓存里的 eps（章节表是 list）。"""
        item = meta._normalize({"subject_id": 7, "eps": 52, "name": "x"})
        self.assertEqual(item["eps"], [])

    def test_chapter_table_kept(self):
        eps = [{"sort": 177, "ep": 1}, {"sort": 178, "ep": 2}]
        item = meta._normalize({"subject_id": 7, "eps": eps})
        self.assertEqual(item["eps"], eps)


class MetaSaveManyTest(unittest.TestCase):
    def test_refresh_keeps_chapter_table_and_start_ep(self):
        old = {"7": {"subject_id": 7, "eps": [{"sort": 177}], "start_ep": 177, "end_ep": 228,
                     "aliases": ["凡人修仙传 慕兰之战篇"], "updated_at": 1}}
        with mock.patch.object(meta, "_load", return_value=dict(old)), \
                mock.patch.object(meta, "_save") as save:
            meta.save_many([{"subject_id": 7, "name": "x", "eps": 52, "aliases": []}])
        written = save.call_args[0][0]["7"]
        self.assertEqual(written["start_ep"], 177, "起点不能被刷新冲掉")
        self.assertEqual(written["end_ep"], 228)
        self.assertEqual(written["eps"], [{"sort": 177}], "章节表不能被话数(int)冲掉")
        self.assertEqual(written["aliases"], ["凡人修仙传 慕兰之战篇"], "别名不能变空")

    def test_aliases_are_merged_not_replaced(self):
        """「在看」列表写缓存时只有番名，不能把联网详情里的篇章名别名冲掉。"""
        old = {"7": {"subject_id": 7, "eps": [], "aliases": ["凡人修仙传", "凡人修仙传 慕兰之战篇"]}}
        with mock.patch.object(meta, "_load", return_value=dict(old)), \
                mock.patch.object(meta, "_save") as save:
            meta.save_many([{"subject_id": 7, "name": "x", "aliases": ["凡人修仙传"]}])
        written = save.call_args[0][0]["7"]
        self.assertEqual(written["aliases"], ["凡人修仙传", "凡人修仙传 慕兰之战篇"])


class GetSubjectForceTest(unittest.TestCase):
    def test_force_skips_cache(self):
        """force=True 必须真的联网，否则别名永远刷不出来。"""
        payload = {"id": 9, "name": "n", "name_cn": "", "date": "2026-10-01",
                   "eps": 12, "total_episodes": 12, "infobox": []}
        with mock.patch.object(meta, "get", side_effect=AssertionError("不该读缓存")), \
                mock.patch.object(meta, "save_many", return_value=0), \
                mock.patch.object(bangumi.http, "get_json", return_value=payload) as get_json:
            subject = bangumi.get_subject(9, force=True)
        self.assertTrue(get_json.called)
        self.assertEqual(subject.id, 9)

    def test_fetched_subject_is_written_to_cache(self):
        """联网拿到的详情（含 infobox「别名」）必须写回缓存 —— 以前写的是不存在的变量，
        NameError 被 except 吞掉，缓存里永远只有老别名（这就是动漫花园那批资源被隐藏的原因）。"""
        payload = {"id": 607915, "name": "凡人修仙传 第五季", "name_cn": "凡人修仙传 第五季",
                   "date": "2026-06-13", "eps": 52, "total_episodes": 52,
                   "infobox": [{"key": "别名", "value": [{"v": "凡人修仙传 慕兰之战篇"}]}]}
        with mock.patch.object(meta, "get", return_value=None), \
                mock.patch.object(meta, "save_many", return_value=1) as save_many, \
                mock.patch.object(bangumi.http, "get_json", return_value=payload):
            subject = bangumi.get_subject(607915, force=True)
        self.assertTrue(save_many.called, "取到详情后必须写缓存")
        saved = save_many.call_args[0][0][0]
        self.assertIn("凡人修仙传 慕兰之战篇", saved.aliases)
        self.assertIn("凡人修仙传 慕兰之战篇", subject.aliases)

    def test_cached_branch_carries_aliases(self):
        """走缓存时也要带上别名（否则季判定拿不到篇章名）。"""
        cached = {"subject_id": 9, "name": "n", "total_episodes": 12, "date": "2026-10-01",
                  "aliases": ["凡人修仙传 慕兰之战篇"]}
        with mock.patch.object(meta, "get", return_value=cached):
            subject = bangumi.get_subject(9)
        self.assertEqual(subject.aliases, ["凡人修仙传 慕兰之战篇"])


if __name__ == "__main__":
    unittest.main()
