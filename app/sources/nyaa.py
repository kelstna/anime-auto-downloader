# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
Nyaa（nyaa.si）适配器 —— 第三优先级（兜底，主要覆盖罗马字标题资源）。
分类：c=1_0 全部动画；排序：s=seeders&o=desc。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from ..core import htmlx
from .base import Resource, SourceAdapter, enrich
from .romaji import romanize

_GROUP_NOISE = re.compile(
    r"^(?:\d{3,4}[pi]|4k|8k|web-?dl|web-?rip|bd|bdrip|hevc|avc|av1|x26[45]|10bit|8bit|aac|flac|opus|"
    r"multi-?sub|vostfr|raw|batch|complete|repack|dual-?audio|amzn|cr|nf|baha|b-global)$",
    re.I,
)


def _clean(node: htmlx.Node) -> str:
    return re.sub(r"\s+", " ", node.text).strip()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class NyaaAdapter(SourceAdapter):
    id = "nyaa"
    name = "Nyaa"
    default_base = "https://nyaa.si"
    native_group_field = False
    supports_group_in_query = True      # 用 "[字幕组] 番剧名" 作为关键词近似实现

    def search(self, keyword: str, *, group: str = "", page: int = 1, limit: Optional[int] = None,
               lang: str = "") -> list[Resource]:
        # lang 仅用于「有没有中文字幕」的本地识别，Nyaa 站内没有语言筛选参数，这里忽略
        kw = (keyword or "").strip()
        group_name = (group or "").split("|")[0].strip()
        if group_name:
            kw = f"[{group_name}] {kw}".strip()

        html = self._get(
            f"{self.base}/",
            params={"q": kw, "c": "1_0", "f": "0", "s": "seeders", "o": "desc", "p": max(1, page)},
            session="nyaa",
        )
        resources = self.parse_list(html)
        if group_name:
            g = group_name.lower()
            matched = [r for r in resources if g in (r.group or "").lower() or g in r.title.lower()]
            if matched:
                resources = matched
        if limit:
            resources = resources[:limit]
        return resources

    # ------------------------------------------------------------------ #
    def parse_list(self, html: str) -> list[Resource]:
        root = htmlx.parse(html)
        tables = root.find_all("table", class_contains="torrent-list")
        table = tables[0] if tables else None
        if table is None:
            table = root.find("table")
        if table is None:
            return []

        out: list[Resource] = []
        for row in htmlx.direct_rows(table):
            tds = htmlx.cells(row)
            if len(tds) < 6:
                continue

            # 标题链接：/view/<id>，排除 /view/<id>#comments 的评论链接
            title, page_url = "", ""
            for a in row.find_all("a"):
                href = a.get("href", "")
                if not href.startswith("/view/"):
                    continue
                if "#comments" in href:
                    continue
                text = _clean(a)
                if not text:
                    continue
                title = a.get("title") or text
                title = _clean_text(title)
                page_url = urllib.parse.urljoin(self.base + "/", href)
                break
            if not title:
                continue

            magnet = ""
            torrent_url = ""
            for a in row.find_all("a"):
                href = htmlx.unescape(a.get("href", ""))
                if href.startswith("magnet:"):
                    magnet = href
                elif href.startswith("/download/"):
                    torrent_url = urllib.parse.urljoin(self.base + "/", href)

            size_text = ""
            date_text = ""
            nums: list[int] = []
            cat = ""
            for td in tds:
                # 分类列只有图标链接、没有文本，必须在文本判空之前先探测
                if not cat:
                    a = td.find("a")
                    if a is not None and a.get("href", "").startswith("/?c="):
                        cat = (a.get("title") or a.get("alt") or "").strip()
                txt = _clean(td)
                if not txt:
                    continue
                if re.fullmatch(r"[\d.]+\s*[KMGT]i?B", txt, re.I) and not size_text:
                    size_text = txt
                    continue
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}[\s\d:]*", txt) and not date_text:
                    date_text = txt.strip()
                    continue
                if txt.isdigit():
                    nums.append(int(txt))

            res = Resource(
                source=self.id,
                source_name=self.name,
                title=title,
                size_text=size_text,
                magnet=magnet,
                page_url=page_url,
                torrent_url=torrent_url,
                published=date_text,
                category=cat,
                seeders=nums[0] if len(nums) > 0 else None,
                leechers=nums[1] if len(nums) > 1 else None,
            )
            enrich(res)
            if res.group and _GROUP_NOISE.match(res.group):
                res.group = ""
            out.append(res)
        return out

    def groups_from(self, resources: list[Resource]) -> list[str]:
        seen, out = set(), []
        for r in resources:
            g = (r.group or "").strip()
            if g and g not in seen and not _GROUP_NOISE.match(g) and len(g) <= 30:
                seen.add(g)
                out.append(g)
        return out
