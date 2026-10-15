# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""三个站点适配器的离线解析测试。

夹具是真实抓取快照，放在 tests\\fixtures\\ 下；本文件不联网。
联网冒烟测试用环境变量 ANIME_ONLINE=1 控制：

    set ANIME_ONLINE=1
    python -m unittest tests.test_parsers -v
"""
import os
import re
import string
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import http  # noqa: E402
from app.sources.dmhy import DmhyAdapter  # noqa: E402
from app.sources.kisssub import KisssubAdapter  # noqa: E402
from app.sources.nyaa import NyaaAdapter  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ONLINE = os.environ.get("ANIME_ONLINE") == "1"

_BASE32 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
_HEX = set(string.hexdigits)


def load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def valid_infohash(value: str) -> bool:
    """40 位十六进制，或 32 位 base32（动漫花园/部分站点用 base32）。"""
    if len(value) == 40:
        return all(c in _HEX for c in value)
    if len(value) == 32:
        return all(c in _BASE32 for c in value.upper())
    return False


class ParserCaseMixin:
    """公共部分：加载夹具 + 三个站点共用的不变量断言。

    注意：这里故意不继承 unittest.TestCase，避免基类被 unittest 当成用例收集。
    """

    fixture = ""
    adapter_cls = None
    source_id = ""
    min_items = 1

    @classmethod
    def setUpClass(cls):
        path = os.path.join(FIXTURES, cls.fixture)
        if not os.path.exists(path):
            raise unittest.SkipTest(f"缺少夹具 {cls.fixture}，跳过该站点用例")
        cls.res = cls.adapter_cls().parse_list(load_fixture(cls.fixture))

    def test_has_items(self):
        self.assertGreaterEqual(len(self.res), self.min_items,
                                f"{self.source_id} 解析条目数过少：{len(self.res)}")
        self.assertLess(len(self.res), 500, "条目数异常，可能解析到了整页噪声")

    def test_every_item_has_title(self):
        for r in self.res:
            self.assertTrue(r.title.strip(), f"{self.source_id} 有标题为空的条目：{r!r}")

    def test_group_or_resolution_extracted(self):
        for r in self.res:
            self.assertTrue(
                r.group.strip() or r.resolution.strip(),
                f"既没有字幕组也没有分辨率：{r.title!r}",
            )

    def test_magnet_is_usable(self):
        for r in self.res:
            self.assertTrue(
                r.magnet.startswith("magnet:?xt=urn:btih:"),
                f"磁力链接不合法：{r.magnet[:60]!r}",
            )

    def test_size_parsed(self):
        for r in self.res:
            self.assertGreater(r.size_bytes, 0, f"大小未解析出来：{r.size_text!r} / {r.title!r}")

    def test_infohash_shape(self):
        for r in self.res:
            self.assertTrue(valid_infohash(r.infohash),
                            f"infohash 格式异常：{r.infohash!r}（{r.title!r}）")
            self.assertIn(r.infohash.lower(), r.magnet.lower())

    def test_source_fields(self):
        for r in self.res:
            self.assertEqual(r.source, self.source_id)
            self.assertTrue(r.source_name.strip())

    def test_resolution_values_normalized(self):
        for r in self.res:
            if r.resolution:
                self.assertIn(r.resolution, {"2160p", "1440p", "1080p", "1080i", "720p", "576p", "480p"})


class DmhyParserTest(ParserCaseMixin, unittest.TestCase):
    fixture = "dmhy_search.html"
    adapter_cls = DmhyAdapter
    source_id = "dmhy"
    min_items = 40

    def test_group_extraction_ratio(self):
        with_group = [r for r in self.res if r.group.strip()]
        self.assertGreaterEqual(len(with_group), len(self.res) * 0.75)

    def test_team_id_extraction(self):
        with_team = [r for r in self.res if r.team_id]
        self.assertGreaterEqual(len(with_team), 20, "动漫花园应能解析出 team_id 链接")

    def test_page_url(self):
        for r in self.res:
            self.assertIn("/topics/view/", r.page_url)
            self.assertTrue(r.page_url.startswith("https://share.dmhy.org/"))

    def test_published_date(self):
        for r in self.res:
            self.assertRegex(r.published, r"^\d{4}/\d{2}/\d{2}")

    def test_seeders_are_integers(self):
        rows = [r for r in self.res if r.seeders is not None]
        self.assertGreaterEqual(len(rows), 10)
        for r in rows:
            self.assertIsInstance(r.seeders, int)
            if r.leechers is not None:
                self.assertIsInstance(r.leechers, int)

    def test_infohash_is_base32(self):
        for r in self.res:
            self.assertEqual(len(r.infohash), 32)
            self.assertTrue(all(c in _BASE32 for c in r.infohash.upper()))

    def test_category_filled(self):
        self.assertGreaterEqual(sum(1 for r in self.res if r.category.strip()), 10)


class KisssubParserTest(ParserCaseMixin, unittest.TestCase):
    fixture = "kisssub_search.html"
    adapter_cls = KisssubAdapter
    source_id = "kisssub"
    min_items = 25

    def test_group_extraction_ratio(self):
        with_group = [r for r in self.res if r.group.strip()]
        self.assertEqual(len(with_group), len(self.res), "爱恋动漫的 UP主/代号 列应全部解析出来")

    def test_page_url_matches_infohash(self):
        for r in self.res:
            m = re.search(r"show-([0-9a-fA-F]{40})\.html$", r.page_url)
            self.assertIsNotNone(m, f"页面地址不是 show-<infohash>.html：{r.page_url}")
            self.assertEqual(m.group(1).lower(), r.infohash)

    def test_magnet_uses_page_infohash(self):
        for r in self.res:
            self.assertEqual(r.magnet, f"magnet:?xt=urn:btih:{r.infohash}")

    def test_published_date(self):
        for r in self.res:
            self.assertRegex(r.published, r"^\d{4}/\d{2}/\d{2}$")

    def test_resolution_ratio(self):
        with_res = [r for r in self.res if r.resolution]
        self.assertGreaterEqual(len(with_res), len(self.res) * 0.5)

    def test_no_seeders_column(self):
        # 爱恋动漫列表页没有做种数字段，应保持 None 而不是 0
        for r in self.res:
            self.assertIsNone(r.seeders, f"不应解析出做种数：{r.title!r}")


class NyaaParserTest(ParserCaseMixin, unittest.TestCase):
    fixture = "nyaa_search.html"
    adapter_cls = NyaaAdapter
    source_id = "nyaa"
    min_items = 30

    def test_page_url_and_torrent_url(self):
        for r in self.res:
            self.assertTrue(r.page_url.startswith("https://nyaa.si/view/"), r.page_url)
            self.assertIn("/download/", r.torrent_url)
            # 评论链接不应被当成标题
            self.assertNotIn("#comments", r.page_url)

    def test_all_have_resolution(self):
        for r in self.res:
            self.assertTrue(r.resolution, f"未解析出分辨率：{r.title!r}")

    def test_seeders_sorted_desc(self):
        seeds = [r.seeders for r in self.res if r.seeders is not None]
        self.assertEqual(len(seeds), len(self.res), "Nyaa 列表应有全部做种数")
        self.assertEqual(seeds, sorted(seeds, reverse=True), "Nyaa 按做种数倒序，解析后应保持有序")

    def test_group_ratio(self):
        with_group = [r for r in self.res if r.group.strip()]
        self.assertGreaterEqual(len(with_group), len(self.res) * 0.8)

    def test_episode_parsed_ratio(self):
        with_ep = [r for r in self.res if r.episode is not None]
        self.assertGreaterEqual(len(with_ep), len(self.res) * 0.6)

    def test_published_datetime(self):
        for r in self.res:
            self.assertRegex(r.published, r"^\d{4}-\d{2}-\d{2}")

    def test_title_key_attribute_used(self):
        # Nyaa 的 <a title="完整标题"> 比锚文本更完整
        longest = max(self.res, key=lambda r: len(r.title))
        self.assertGreater(len(longest.title), 30)

    def test_noise_titles_not_marked(self):
        self.assertEqual(sum(1 for r in self.res if r.is_noise), 0,
                         "该夹具内不应有 PV/音乐类噪声标题")


@unittest.skipUnless(ONLINE, "需要联网：设置 ANIME_ONLINE=1 后运行")
class OnlineSmokeTest(unittest.TestCase):
    """联网冒烟测试：真实请求三个站点各一次，确认解析仍然有效。"""

    def _search(self, adapter, keyword, **kw):
        try:
            return adapter.search(keyword, **kw)
        except (OSError, ValueError, http.HttpError) as e:
            self.skipTest(f"联网失败，跳过：{e}")

    def test_dmhy_online(self):
        res = self._search(DmhyAdapter(), "葬送的芙莉莲")
        self.assertTrue(res, "动漫花园在线搜索没有解析出任何条目")

    def test_kisssub_online(self):
        res = self._search(KisssubAdapter(), "葬送的芙莉莲")
        self.assertTrue(res, "爱恋动漫在线搜索没有解析出任何条目")

    def test_nyaa_online(self):
        res = self._search(NyaaAdapter(), "Sousou no Frieren")
        self.assertTrue(res, "Nyaa 在线搜索没有解析出任何条目")


if __name__ == "__main__":
    unittest.main(verbosity=2)
