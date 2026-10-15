# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""HTTP 层的离线测试：429 冷却与 Retry-After 解析（不联网）。

为什么单独测：爱恋动漫（kisssub）在批量预热时会返回 429，
被限流后还继续重试只会被继续拦、而且每个请求都要等好几秒才失败。
现在会记住「这个站点到什么时候为止别再打」，冷却期内快速失败。
"""
import os
import sys
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import http  # noqa: E402


class RetryAfterTest(unittest.TestCase):
    def test_seconds_form(self):
        self.assertEqual(http._retry_after({"Retry-After": "7"}), 7.0)
        self.assertEqual(http._retry_after({"Retry-After": " 12.5 "}), 12.5)

    def test_missing_or_garbage(self):
        for headers in ({}, None, {"Retry-After": ""}, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}, {"Retry-After": "-3"}):
            self.assertEqual(http._retry_after(headers), 0.0)

    def test_negative_clamped(self):
        self.assertEqual(http._retry_after({"Retry-After": "-10"}), 0.0)


class CooldownTest(unittest.TestCase):
    def setUp(self):
        http.clear_cooldown()

    def tearDown(self):
        http.clear_cooldown()

    def test_mark_and_read(self):
        self.assertEqual(http.cooldown_left("https://www.kisssub.org/search.php"), 0.0)
        http.mark_cooldown("https://www.kisssub.org/search.php", 30)
        left = http.cooldown_left("https://www.kisssub.org/search.php?keyword=x")
        self.assertTrue(25 <= left <= 30, left)

    def test_cooldown_is_per_host(self):
        http.mark_cooldown("https://www.kisssub.org/search.php", 30)
        self.assertEqual(http.cooldown_left("https://share.dmhy.org/topics/list"), 0.0,
                         "别的站点不该被连带冷却")

    def test_seconds_clamped(self):
        self.assertGreaterEqual(http.mark_cooldown("https://a.example/x", 0.1), 5.0)
        self.assertLessEqual(http.mark_cooldown("https://b.example/x", 99999), 600.0)

    def test_expired_cooldown_is_gone(self):
        http.mark_cooldown("https://c.example/x", 5)
        http._COOLDOWN[http._host_of("https://c.example/x")] = time.time() - 1
        self.assertEqual(http.cooldown_left("https://c.example/x"), 0.0)

    def test_request_fails_fast_while_cooling(self):
        http.mark_cooldown("https://cooling.example/x", 30)
        started = time.time()
        with self.assertRaises(http.HttpError) as ctx:
            http.request("https://cooling.example/x", timeout=5, retries=2)
        self.assertLess(time.time() - started, 1.0, "冷却期内必须立刻失败，不能真的去请求")
        self.assertEqual(ctx.exception.code, 429)
        self.assertIn("限流", str(ctx.exception))

    def test_clear_cooldown(self):
        http.mark_cooldown("https://d.example/x", 30)
        http.clear_cooldown("https://d.example/x")
        self.assertEqual(http.cooldown_left("https://d.example/x"), 0.0)
        http.mark_cooldown("https://e.example/x", 30)
        http.clear_cooldown()
        self.assertEqual(http.cooldown_left("https://e.example/x"), 0.0)


if __name__ == "__main__":
    unittest.main()
