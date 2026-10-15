# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""搜索缓存的选择规则（变体 vs 基础）的离线测试。

对应用户反馈：「点了立即预热全部番剧，预热完弹窗还是显示 4 天前（已过期）」。
原因：弹窗请求带「关键词学习签名」变体（lk=），预热只刷新基础缓存，
变体缓存永远停在几天前 —— 现在两者取更新的那份。
"""
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.web import server  # noqa: E402

_BASE = {"items": [{"title": "base"}], "total": 1}
_LK = {"items": [{"title": "lk"}], "total": 1}
_KW = {"items": [{"title": "kw"}], "total": 1}


def _fake_ages(mapping):
    """mapping: {variant: (value, age)}"""
    def fake(subject_id, variant=""):
        return mapping.get(variant, (None, 0.0))
    return fake


class PickSearchCacheTest(unittest.TestCase):
    def _pick(self, variant, mapping):
        with mock.patch.object(server.warmup, "search_any_age",
                               side_effect=_fake_ages(mapping)):
            return server._pick_search_cache(554779, variant)

    def test_base_when_no_variant(self):
        got, age = self._pick("", {"": (_BASE, 60.0)})
        self.assertIs(got, _BASE)
        self.assertEqual(age, 60.0)

    def test_lk_variant_loses_to_fresher_base(self):
        """预热刷新基础缓存后，旧的 lk 变体不能再顶在前面（这就是「还是过期」的原因）。"""
        got, age = self._pick("lk=e29f0a8bfb", {
            "lk=e29f0a8bfb": (_LK, 4 * 24 * 3600.0),
            "": (_BASE, 300.0),
        })
        self.assertIs(got, _BASE)
        self.assertEqual(age, 300.0)

    def test_fresher_lk_variant_wins(self):
        got, age = self._pick("lk=e29f0a8bfb", {
            "lk=e29f0a8bfb": (_LK, 120.0),
            "": (_BASE, 9000.0),
        })
        self.assertIs(got, _LK)
        self.assertEqual(age, 120.0)

    def test_keyword_variant_is_not_replaced_by_base(self):
        """手动关键词的口径不能拿全量缓存顶替，否则会显示成没搜过关键词的结果。"""
        got, age = self._pick("kw=脑洞学生会", {
            "kw=脑洞学生会": (_KW, 5 * 24 * 3600.0),
            "": (_BASE, 60.0),
        })
        self.assertIs(got, _KW)

    def test_missing_variant_falls_back_to_base(self):
        got, age = self._pick("d动漫花园::ANi", {"": (_BASE, 120.0)})
        self.assertIs(got, _BASE)
        self.assertEqual(age, 120.0)

    def test_nothing_cached(self):
        got, age = self._pick("lk=abc", {})
        self.assertIsNone(got)
        self.assertEqual(age, 0.0)


if __name__ == "__main__":
    unittest.main()
