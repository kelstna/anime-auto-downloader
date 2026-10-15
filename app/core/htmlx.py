# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
极简 HTML 解析器（标准库 html.parser 封装）。
提供按 id / class / 标签 / 属性 查询与文本提取，足够解析资源站点的列表页。
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from typing import Iterable, Optional

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "_content")

    def __init__(self, tag: str, attrs: Optional[dict] = None, parent: Optional["Node"] = None):
        self.tag = tag
        self.attrs: dict[str, str] = attrs or {}
        self.children: list[Node] = []
        self.parent = parent
        # 文档顺序的内容表：字符串（文本）与子节点混排。
        # 以前只存「本节点的所有文本段」，取全文时会把子元素的文本排到后面，
        # 于是动漫花园高亮的标题 `[组] <span class="keyword">关键词</span>！/ 其它名 - 14`
        # 会被拼成「[组] ！/ 其它名 - 14关键词」—— 关键词跑到标题尾部（用户会看到标题少一段）。
        self._content: list = []

    # ------------------------------------------------------------------ #
    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def has_class(self, name: str) -> bool:
        return name in self.classes

    def append(self, node: "Node") -> None:
        node.parent = self
        self.children.append(node)
        self._content.append(node)

    # ------------------------------------------------------------------ #
    def iter(self) -> Iterable["Node"]:
        """深度优先遍历自身及所有后代。"""
        stack = [self]
        while stack:
            cur = stack.pop()
            yield cur
            stack.extend(reversed(cur.children))

    def find(self, tag: Optional[str] = None, **kw) -> Optional["Node"]:
        for n in self.iter():
            if n is self:
                continue
            if _match(n, tag, kw):
                return n
        return None

    def find_all(self, tag: Optional[str] = None, **kw) -> list["Node"]:
        out = []
        for n in self.iter():
            if n is self and tag is not None:
                continue
            if _match(n, tag, kw):
                out.append(n)
        return out

    def children_by_tag(self, tag: str) -> list["Node"]:
        return [c for c in self.children if c.tag == tag]

    def first_child(self, tag: str) -> Optional["Node"]:
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    # ------------------------------------------------------------------ #
    @property
    def text(self) -> str:
        """包含所有后代文本，**按文档顺序**拼接（文本与子元素交错），压缩空白。"""
        parts: list[str] = []
        stack: list = [self]
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                parts.append(item)
                continue
            for child in reversed(item._content):
                stack.append(child)
        return re.sub(r"\s+", " ", "".join(parts)).strip()

    @property
    def own_text(self) -> str:
        """仅自身直接文本（不含子元素），压缩空白。"""
        return re.sub(r"\s+", " ", "".join(x for x in self._content if isinstance(x, str))).strip()

    def attr_text(self, name: str) -> str:
        return self.attrs.get(name, "")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Node {self.tag} attrs={self.attrs} children={len(self.children)}>"


def _match(node: Node, tag: Optional[str], kw: dict) -> bool:
    if tag is not None and node.tag != tag:
        return False
    for k, v in kw.items():
        if k == "class_":
            if not node.has_class(v):
                return False
        elif k == "class_contains":
            if v not in (node.attrs.get("class") or ""):
                return False
        # 注意：attr_contains_* 必须排在 attr_* 之前，否则永远匹配不到
        elif k.startswith("attr_contains_"):
            if v not in (node.attrs.get(k[len("attr_contains_"):]) or ""):
                return False
        elif k.startswith("attr_"):
            if node.attrs.get(k[5:]) != v:
                return False
        else:
            return False
    return True


class _Builder(HTMLParser):
    _SKIP_CONTENT = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].append(node)
        if tag in self._SKIP_CONTENT:
            self._skip_depth += 1
        elif tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        node = Node(tag, {k.lower(): (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].append(node)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self._SKIP_CONTENT and self._skip_depth:
            self._skip_depth -= 1
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._skip_depth:
            return
        if data:
            self.stack[-1]._content.append(data)


def parse(html_text: str) -> Node:
    b = _Builder()
    try:
        b.feed(html_text)
        b.close()
    except Exception:  # 容错：解析异常时返回已有部分
        pass
    return b.root


def strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def unescape(text: str) -> str:
    return _html.unescape(text or "")


def find_by_id(root: Node, node_id: str) -> Optional[Node]:
    for n in root.iter():
        if n.attrs.get("id") == node_id:
            return n
    return None


def direct_rows(table: Node) -> list[Node]:
    """取表格的 <tr> 行列表（兼容 tbody）。"""
    rows: list[Node] = []
    for child in table.children:
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in ("tbody", "thead", "tfoot"):
            rows.extend(c for c in child.children if c.tag == "tr")
    return rows


def cells(row: Node) -> list[Node]:
    """取行内 <td>/<th> 单元格。"""
    return [c for c in row.children if c.tag in ("td", "th")]
