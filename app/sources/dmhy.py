# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
动漫花园（share.dmhy.org）适配器 —— 最高优先级。
支持原生字幕组精确搜索：/topics/list?keyword=<番剧名>+team_id:<id>
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from ..core import htmlx
from ..core.util import uniq_keep_order
from .base import Resource, SourceAdapter, enrich

_IDX_DATE, _IDX_CAT, _IDX_TITLE = 0, 1, 2

# 搜索结果里可能出现的、不应视为字幕组的噪声文本
_GROUP_NOISE = re.compile(
    r"^(?:\d{3,4}[pi]|4k|8k|web-?dl|web-?rip|bd|bdrip|bluray|hevc|avc|av1|x26[45]|10bit|8bit|aac|flac|opus|mp4|mkv|"
    r"简|繁|简繁|简日|繁日|中日|双语|合集|全集|季度全集|剧场版|movie|ova|oad|sp|raw|sub|字幕|内嵌|内封|外挂|"
    r"vostfr|multi-?sub|hi10p|ma10p|fin|end)$",
    re.I,
)


def _clean_text(node: htmlx.Node) -> str:
    return re.sub(r"\s+", " ", node.text).strip()


class DmhyAdapter(SourceAdapter):
    id = "dmhy"
    name = "动漫花园"
    default_base = "https://share.dmhy.org"
    native_group_field = True
    supports_group_in_query = True

    def search(self, keyword: str, *, group: str = "", page: int = 1, limit: Optional[int] = None,
               lang: str = "") -> list[Resource]:
        """
        动漫花园搜索。

        lang 会作为站内关键词附加（该站搜索结果支持「关键字 简体/繁体」这类过滤词），
        dmhy 的标题本身就大量标注了 [简繁内封]/[简体内嵌]/[繁日內嵌]，所以
        站内后缀 + 我们自己的 detect_language 双重保证。
        """
        kw = (keyword or "").strip()
        team_id = ""
        if group:
            m = re.search(r"team_id:(\d+)", group)
            if m:
                team_id = m.group(1)
                group = group.split("|")[0].strip()
            else:
                team_id = self.resolve_team_id(group) or ""
        if team_id:
            kw = f"{kw} team_id:{team_id}" if kw else f"team_id:{team_id}"
        suffix = {"chs": "简体", "cht": "繁体", "both": "简繁"}.get((lang or "").lower(), "")
        if suffix and suffix not in kw:
            kw = f"{kw} {suffix}".strip()

        html = self._get(
            f"{self.base}/topics/list",
            params={"keyword": kw, "sort_id": 2, "page": max(1, page)},
            session="dmhy",
        )
        resources = self.parse_list(html, group_hint=group if team_id else "")
        if limit:
            resources = resources[:limit]
        return resources

    # ------------------------------------------------------------------ #
    def parse_list(self, html: str, group_hint: str = "") -> list[Resource]:
        root = htmlx.parse(html)
        table = htmlx.find_by_id(root, "topic_list")
        if table is None:
            # 兜底：任意含 topic_list class 的表格
            table = root.find("table", attr_contains_class="topic_list")
        if table is None:
            return []

        out: list[Resource] = []
        for row in htmlx.direct_rows(table):
            tds = htmlx.cells(row)
            if len(tds) < 6:
                continue
            title_td = tds[_IDX_TITLE] if len(tds) > _IDX_TITLE else None
            if title_td is None:
                continue
            link = None
            for a in title_td.find_all("a"):
                href = a.get("href", "")
                if "/topics/view/" in href:
                    link = a
                    break
            if link is None:
                link = title_td.find("a")
            if link is None:
                continue

            # 字幕组：优先 <span class="tag"><a href="/topics/list/team_id/N">组名</a></span>
            group_name, team_id = "", ""
            tag_span = title_td.find("span", class_="tag")
            if tag_span is not None:
                for a in tag_span.find_all("a"):
                    href = a.get("href", "")
                    m = re.search(r"/team_id/(\d+)", href)
                    if m:
                        team_id = m.group(1)
                        group_name = _clean_text(a)
                        break

            # 磁力鏈
            magnet = ""
            for a in row.find_all("a"):
                href = a.get("href", "")
                if href.startswith("magnet:"):
                    magnet = htmlx.unescape(href)
                    break
            if not magnet:
                a = row.find("a", class_contains="download-xl")
                if a is not None:
                    magnet = htmlx.unescape(a.get("data-magnet", ""))

            date_text = _clean_text(tds[_IDX_DATE])[:10]
            # 日期单元格文本为 "2026/08/28 05:32 2026/08/28 05:32"，取第一个日期
            m = re.search(r"\d{4}/\d{2}/\d{2}(?:\s+\d{2}:\d{2})?", _clean_text(tds[_IDX_DATE]))
            if m:
                date_text = m.group(0)

            size_text = ""
            seeders = leechers = None
            for i, td in enumerate(tds):
                txt = _clean_text(td)
                if re.fullmatch(r"[\d.]+\s*[KMGT]i?B", txt, re.I):
                    size_text = txt
                    if i + 1 < len(tds):
                        try:
                            seeders = int(_clean_text(tds[i + 1]) or -1)
                        except ValueError:
                            seeders = None
                        if i + 2 < len(tds):
                            try:
                                leechers = int(_clean_text(tds[i + 2]) or -1)
                            except ValueError:
                                leechers = None
                    break

            res = Resource(
                source=self.id,
                source_name=self.name,
                title=link.text or "",
                group=group_name or "",
                team_id=team_id,
                size_text=size_text,
                magnet=magnet,
                page_url=urllib.parse.urljoin(self.base + "/", link.get("href", "")),
                seeders=seeders,
                leechers=leechers,
                published=date_text,
                category=_clean_text(tds[_IDX_CAT]) if len(tds) > _IDX_CAT else "",
            )
            enrich(res)
            if team_id and not res.group:
                res.group = group_hint
            if res.group and _GROUP_NOISE.match(res.group):
                res.group = ""
            out.append(res)
        return out

    # ------------------------------------------------------------------ #
    def resolve_team_id(self, group_name: str) -> str:
        """通过搜索「字幕组名」找到对应的 team_id，用于精确过滤。"""
        name = (group_name or "").strip()
        if not name or len(name) > 30:
            return ""
        try:
            html = self._get(f"{self.base}/topics/list", params={"keyword": name, "sort_id": 2},
                             session="dmhy")
        except OSError:
            return ""
        # 统计出现次数最多的 team_id，且组名需与查询一致
        counts: dict[str, int] = {}
        names: dict[str, str] = {}
        for m in re.finditer(r'/topics/list/team_id/(\d+)"[^>]*>\s*([^<]{1,40})', html):
            tid, tname = m.group(1), htmlx.unescape(m.group(2)).strip()
            if not tname:
                continue
            if name.lower() not in tname.lower() and tname.lower() not in name.lower():
                continue
            counts[tid] = counts.get(tid, 0) + 1
            names[tid] = tname
        if not counts:
            return ""
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def groups_from(self, resources: list[Resource]) -> list[str]:
        seen, out = set(), []
        for r in resources:
            g = (r.group or "").strip()
            if g and g not in seen and not _GROUP_NOISE.match(g):
                seen.add(g)
                out.append(g)
        return out


def group_query_hint(group_name: str, team_id: str = "") -> str:
    """构造传给适配器的 group 参数（动漫花园可携带 team_id）。"""
    if team_id:
        return f"{group_name}|team_id:{team_id}"
    return group_name


__all__ = ["DmhyAdapter", "group_query_hint"]
