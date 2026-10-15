# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
爱恋动漫（www.kisssub.org）适配器 —— 第二优先级。
站点有「访客验证」反爬页，需先 POST 一次 visitor-test 建立 cookie。
列表页的标题链接形如 show-<infohash>.html，可据此直接构造磁力链接。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Optional

from ..core import htmlx, http, logger
from ..core.http import HttpError
from .base import Resource, SourceAdapter, enrich

_SHOW_LINK = re.compile(r"show-([0-9a-fA-F]{40})\.html")
_VISITOR_PATH = "/addon.php?r=document/view&page=visitor-test"
_SESSION = "kisssub"

_GROUP_NOISE = re.compile(
    r"^(?:\d{3,4}[pi]|4k|8k|web-?dl|web-?rip|bd|bdrip|hevc|avc|av1|x26[45]|10bit|8bit|aac|flac|opus|"
    r"简|繁|简繁|简日|繁日|中日|双语|合集|全集|季度全集|raw|字幕|内嵌|内封|外挂|搬运|转载|我是搬运工)$",
    re.I,
)


def _clean(node: htmlx.Node) -> str:
    return re.sub(r"\s+", " ", node.text).strip()


class KisssubAdapter(SourceAdapter):
    id = "kisssub"
    name = "爱恋动漫"
    default_base = "https://www.kisssub.org"
    native_group_field = True          # 列表自带「UP主 / 代号」列
    supports_group_in_query = False    # 站内搜索无独立字幕组参数，用关键词包含组名近似实现

    # ------------------------------------------------------------------ #
    def _ensure_visitor(self) -> None:
        """通过访客验证，拿到可用的 cookie。"""
        try:
            html = self._get(f"{self.base}/", session=_SESSION)
        except OSError as e:
            raise OSError(f"爱恋动漫首页访问失败：{e}") from None
        if "visitor-test" not in html:
            return
        logger.info("爱恋动漫：正在通过访客验证…")
        try:
            http.request(
                self.base + _VISITOR_PATH,
                method="POST",
                data={"visitor_test": "human"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                referer=self.base + "/",
                session=_SESSION,
                proxy=self._proxy(),
                timeout=self._timeout(),
            )
        except (http.HttpError, OSError) as e:
            raise OSError(f"爱恋动漫访客验证失败：{e}") from None
        logger.info("爱恋动漫：访客验证通过")

    def _search_page(self, keyword: str, page: int = 1) -> str:
        for attempt in (1, 2):
            url = f"{self.base}/search.php"
            params = {"keyword": keyword}
            if page > 1:
                params = {"keyword": f"{keyword} order-{page}"}
            html = self._get(url, params=params, session=_SESSION, referer=self.base + "/")
            if "visitor-test" in html or len(html) < 3000:
                if attempt == 1:
                    http.clear_session(_SESSION)
                    self._ensure_visitor()
                    continue
            return html
        return html

    def search(self, keyword: str, *, group: str = "", page: int = 1, limit: Optional[int] = None,
               lang: str = "") -> list[Resource]:
        """
        爱恋动漫搜索。

        lang 会作为站内原生搜索后缀附加（该站支持「关键词 简体 / 繁体 / 简繁」这类后缀，
        比我们自己按标题猜语言更准）。lang: 'chs' | 'cht' | 'both' | ''。
        """
        kw = (keyword or "").strip()
        if group:
            g = group.split("|")[0].strip()
            if g:
                kw = f"{kw} {g}".strip()
        suffix = {"chs": "简体", "cht": "繁体", "both": "简繁"}.get((lang or "").lower(), "")
        if suffix and suffix not in kw:
            kw = f"{kw} {suffix}"
        html = self._search_page(kw, page=page)
        resources = self.parse_list(html)
        if group:
            # 站内为模糊匹配，这里做一次精确的组名收敛
            g = group.split("|")[0].strip().lower()
            matched = [r for r in resources if g in (r.group or "").lower()]
            if matched:
                resources = matched
        if limit:
            resources = resources[:limit]
        return resources

    # ------------------------------------------------------------------ #
    def parse_list(self, html: str) -> list[Resource]:
        root = htmlx.parse(html)
        tables = root.find_all("table", class_contains="table_fixed")
        target = None
        for t in tables:
            if t.find("tbody", attr_id="data_list") is not None:
                target = t
                break
        if target is None:
            for t in tables:
                if t.find("a", attr_contains_href="show-") is not None:
                    target = t
                    break
        if target is None:
            return []

        out: list[Resource] = []
        for row in htmlx.direct_rows(target):
            tds = htmlx.cells(row)
            if len(tds) < 4:
                continue
            # 标题列：找 show-<hash>.html 链接
            link = None
            infohash = ""
            for td in tds:
                for a in td.find_all("a"):
                    m = _SHOW_LINK.search(a.get("href", ""))
                    if m:
                        link, infohash = a, m.group(1).lower()
                        break
                if link is not None:
                    break
            if link is None:
                continue

            group = ""
            for td in reversed(tds):
                a = td.find("a")
                if a is not None and "search.php?keyword=" in a.get("href", ""):
                    txt = _clean(a)
                    if txt and not _GROUP_NOISE.match(txt):
                        group = txt
                    break

            size_text = ""
            for td in tds:
                txt = _clean(td)
                if re.fullmatch(r"[\d.]+\s*[KMGT]i?B", txt, re.I):
                    size_text = txt
                    break

            date_text = ""
            m = re.search(r"\d{4}/\d{2}/\d{2}", _clean(tds[0]))
            if m:
                date_text = m.group(0)

            magnet = f"magnet:?xt=urn:btih:{infohash}" if infohash else ""
            res = Resource(
                source=self.id,
                source_name=self.name,
                title=_clean(link),
                group=group,
                size_text=size_text,
                magnet=magnet,
                page_url=urllib.parse.urljoin(self.base + "/", link.get("href", "")),
                published=date_text,
                category=_clean(tds[1]) if len(tds) > 1 else "",
                infohash=infohash,
            )
            enrich(res)
            out.append(res)
        return out

    def groups_from(self, resources: list[Resource]) -> list[str]:
        seen, out = set(), []
        for r in resources:
            g = (r.group or "").strip()
            if g and g not in seen and not _GROUP_NOISE.match(g):
                seen.add(g)
                out.append(g)
        return out
