# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""app.core.htmlx 的离线单元测试：用内联 HTML 片段验证解析与查询接口。"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import htmlx  # noqa: E402

PAGE = """<!DOCTYPE html>
<html><head><title>页面标题</title>
<style>.a { color: red; }</style>
<script>var secret = "should-not-appear";</script>
</head>
<body>
<div id="main" class="wrap box">
  <p class="a">Hello <b>World</b></p>
  <ul>
    <li>one</li>
    <li>two</li>
  </ul>
  <br><img src="x.png">
</div>
<table id="topic_list" class="topic_list other">
  <thead><tr><th>日期</th><th>分类</th></tr></thead>
  <tbody>
    <tr><td>2026/08/28</td><td>动画</td><td><a href="magnet:?xt=urn:btih:AAAA">标题一</a></td></tr>
    <tr><td>2026/08/27</td><td>动画</td><td><a href="/view/1">标题二</a></td></tr>
  </tbody>
</table>
<table class="plain">
  <tr><td>直接 tr</td><td>第二格</td></tr>
</table>
<p>a&amp;b &lt;tag&gt;</p>
</body></html>
"""


class TestParseAndFind(unittest.TestCase):
    def setUp(self):
        self.root = htmlx.parse(PAGE)

    def test_root_is_document(self):
        self.assertEqual(self.root.tag, "#document")
        self.assertTrue(self.root.children)

    def test_find_by_id(self):
        node = htmlx.find_by_id(self.root, "main")
        self.assertIsNotNone(node)
        self.assertEqual(node.tag, "div")
        self.assertTrue(node.has_class("wrap"))
        self.assertTrue(node.has_class("box"))
        self.assertEqual(node.get("id"), "main")
        self.assertEqual(node.get("data-x", "默认值"), "默认值")

    def test_find_by_id_missing(self):
        self.assertIsNone(htmlx.find_by_id(self.root, "不存在的id"))

    def test_find_all_document_order(self):
        links = self.root.find_all("a")
        self.assertEqual(len(links), 2)
        self.assertEqual(links[0].get("href"), "magnet:?xt=urn:btih:AAAA")
        self.assertEqual(links[1].get("href"), "/view/1")

    def test_find_all_td_count(self):
        self.assertEqual(len(self.root.find_all("td")), 8)

    def test_find_first_match(self):
        p = self.root.find("p", class_="a")
        self.assertIsNotNone(p)
        self.assertEqual(p.own_text, "Hello")

    def test_find_by_tag_and_class_contains(self):
        tables = self.root.find_all("table", class_contains="topic_list")
        self.assertEqual(len(tables), 1)
        self.assertEqual(htmlx.find_by_id(self.root, "topic_list").get("id"), "topic_list")

    def test_find_by_attr(self):
        table = self.root.find("table", attr_id="topic_list")
        self.assertIsNotNone(table)
        self.assertEqual(len(self.root.find_all("table", attr_class="plain")), 1)

    def test_find_returns_none_when_no_match(self):
        self.assertIsNone(self.root.find("video"))
        self.assertIsNone(self.root.find("p", class_="not-exist"))

    def test_subtree_find_excludes_self(self):
        div = htmlx.find_by_id(self.root, "main")
        self.assertEqual(div.find_all("div"), [])
        self.assertEqual(len(div.find_all("li")), 2)

    def test_classes_property(self):
        div = htmlx.find_by_id(self.root, "main")
        self.assertEqual(div.classes, {"wrap", "box"})
        self.assertFalse(div.has_class("nope"))


class TestText(unittest.TestCase):
    def setUp(self):
        self.root = htmlx.parse(PAGE)

    def test_text_compresses_whitespace(self):
        node = htmlx.parse("<div class='x'><p>Hello <b>World</b></p></div>")
        self.assertEqual(node.find("div").text, "Hello World")

    def test_leaf_whitespace_collapsed(self):
        node = htmlx.parse("<table><tr><td>  标题一\n\t第二行  </td></tr></table>")
        self.assertEqual(node.find("td").text, "标题一 第二行")

    def test_text_concatenates_sibling_leaves(self):
        node = htmlx.parse("<div><span>one</span><span>two</span></div>")
        self.assertEqual(node.find("div").text, "onetwo")

    def test_own_text_excludes_children(self):
        p = self.root.find("p", class_="a")
        self.assertEqual(p.own_text, "Hello")
        self.assertEqual(p.text, "Hello World")

    def test_text_collapses_inner_whitespace(self):
        node = htmlx.parse("<p>  a \n\t b </p>")
        self.assertEqual(node.find("p").text, "a b")

    def test_script_and_style_content_skipped(self):
        text = self.root.text
        self.assertNotIn("should-not-appear", text)
        self.assertNotIn("color: red", text)
        self.assertIn("页面标题", text)

    def test_entities_are_decoded(self):
        texts = [n.text for n in self.root.find_all("p")]
        self.assertIn("a&b <tag>", texts)

    def test_unescape_helper(self):
        self.assertEqual(htmlx.unescape("&amp;lt;"), "&lt;")
        self.assertEqual(htmlx.unescape(""), "")

    def test_strip_tags_helper(self):
        self.assertEqual(htmlx.strip_tags("<b>x</b> y"), "x y")
        self.assertEqual(htmlx.strip_tags(""), "")


class TestTables(unittest.TestCase):
    def setUp(self):
        self.root = htmlx.parse(PAGE)

    def test_direct_rows_includes_thead(self):
        # direct_rows 会把 thead/tbody/tfoot 里的 tr 都收集进来
        #（所以适配器用「单元格数量」过滤掉表头行）
        table = htmlx.find_by_id(self.root, "topic_list")
        rows = htmlx.direct_rows(table)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.tag == "tr" for r in rows))
        self.assertEqual(rows[0].first_child("th").text, "日期")

    def test_direct_rows_without_tbody(self):
        table = self.root.find("table", attr_class="plain")
        rows = htmlx.direct_rows(table)
        self.assertEqual(len(rows), 1)

    def test_cells(self):
        table = htmlx.find_by_id(self.root, "topic_list")
        row = htmlx.direct_rows(table)[1]
        tds = htmlx.cells(row)
        self.assertEqual(len(tds), 3)
        self.assertEqual(tds[0].text, "2026/08/28")
        self.assertEqual(tds[2].tag, "td")
        self.assertEqual(tds[2].find("a").text, "标题一")

    def test_cells_include_th(self):
        table = htmlx.find_by_id(self.root, "topic_list")
        thead_row = table.first_child("thead").first_child("tr")
        self.assertEqual([c.tag for c in htmlx.cells(thead_row)], ["th", "th"])

    def test_children_by_tag_and_first_child(self):
        table = htmlx.find_by_id(self.root, "topic_list")
        self.assertEqual(len(table.children_by_tag("thead")), 1)
        self.assertEqual(len(table.children_by_tag("tbody")), 1)
        self.assertIsNone(table.first_child("tfoot"))


class TestStructure(unittest.TestCase):
    def test_void_tags_do_not_nest(self):
        root = htmlx.parse('<div><br><img src="x.png"><span>t</span></div>')
        div = root.find("div")
        self.assertIsNotNone(div.first_child("br"))
        self.assertEqual(len(div.children_by_tag("span")), 1)
        self.assertEqual(div.text, "t")

    def test_self_closing_tag(self):
        root = htmlx.parse('<div><input type="text"/><span>ok</span></div>')
        div = root.find("div")
        self.assertEqual(len(div.children), 2)
        self.assertEqual(div.find("input").get("type"), "text")

    def test_iter_is_depth_first_preorder(self):
        root = htmlx.parse("<a><b><c></c></b><d></d></a>")
        self.assertEqual([n.tag for n in root.iter()], ["#document", "a", "b", "c", "d"])

    def test_attribute_names_lowercased(self):
        root = htmlx.parse('<A HREF="x" DATA-ID="7">t</A>')
        a = root.find("a")
        self.assertEqual(a.get("href"), "x")
        self.assertEqual(a.get("data-id"), "7")

    def test_malformed_html_does_not_raise(self):
        root = htmlx.parse("<div><p>未闭合<span>x")
        self.assertIsNotNone(root.find("span"))
        self.assertEqual(root.find("span").text, "x")

    def test_empty_input(self):
        root = htmlx.parse("")
        self.assertEqual(root.tag, "#document")
        self.assertEqual(root.text, "")
        self.assertIsNone(root.find("div"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
