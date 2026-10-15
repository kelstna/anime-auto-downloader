# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
资源站点通用数据结构与基类。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Optional

from ..core import config, http, logger
from ..core.util import (
    is_noise_title, parse_episode, parse_episode_range, parse_resolution, parse_size,
    to_simplified,
)

# 标题开头的 [字幕组] 或 【字幕组】
_BRACKET_GROUP = re.compile(r"^\s*[\[【]([^\]】]{1,30})[\]】]")
# 标题结尾的 [发布组]（Nyaa 等站点常见）
_TAIL_GROUP = re.compile(r"[\[【]([^\]】]{2,24})[\]】]\s*$")
# 形如 [15B7C196]、[Ma10p_1080p]、[1080p]、[简繁内封] 的方括号内容不是组名
_NOT_A_GROUP = re.compile(
    r"^(?:[0-9a-fA-F]{6,10}"
    r"|(?=.*\d)[0-9A-Za-z_\- ]{2,20}"
    r"|(?:简|繁|简繁|简日|繁日|中日|双语|内嵌|内封|外挂|字幕|合集|全集|季度全集|剧场版|合集)"
    r"|(?:batch|complete|repack|multi-?sub|dual-?audio|vostfr|hi10p|ma10p|web-?dl|web-?rip|bd|bdrip|bluray|hevc|avc|av1|x26[45]|aac|flac|opus|mp4|mkv|raw|sub|fin|end)"
    r")$",
    re.I,
)
# 「简体内封字幕」「簡日內嵌」「繁簡英日」这类方括号里是语言/规格标注，不是字幕组名。
# 它们会出现在标题末尾，以前会被 _TAIL_GROUP 当成组名进了「字幕组」下拉框（用户能看到脏数据）
_LANG_TAG_ONLY = re.compile(
    r"^(?:(?:[简繁簡日英中双內内嵌封挂掛字幕版体體语語文]|chs|cht|gb|big5|jpn?|jpsc|jptc|sc|tc|[\d_\-/&+.]+)){1,10}$",
    re.I,
)


def is_lang_tag(text: str) -> bool:
    """方括号内容是不是「语言/规格标注」（不是字幕组名）。"""
    t = (text or "").strip()
    return bool(t) and bool(_LANG_TAG_ONLY.match(t))


@dataclass
class Resource:
    """一条搜索结果（一个种子/磁力）。"""
    source: str                      # 站点 id: dmhy / kisssub / nyaa
    source_name: str = ""            # 站点中文名
    title: str = ""
    group: str = ""                  # 字幕组 / 发布组
    team_id: str = ""                # 站点原生字幕组 ID（动漫花园 team_id）
    resolution: str = ""
    lang: str = ""                   # 字幕语言：chs 简体 / cht 繁体 / both 简繁 / jp 日文 / '' 未标注
    size_text: str = ""
    size_bytes: int = 0
    magnet: str = ""
    page_url: str = ""
    torrent_url: str = ""
    seeders: Optional[int] = None
    leechers: Optional[int] = None
    published: str = ""
    category: str = ""
    episode: Optional[int] = None
    episode_end: Optional[int] = None
    is_batch: bool = False
    is_noise: bool = False
    infohash: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Resource":
        """从 JSON（缓存）还原：多余的键忽略，缺的键用默认值。"""
        if isinstance(data, cls):
            return data
        known = {k: v for k, v in (data or {}).items() if k in _FIELDS}
        return cls(**known)

    @property
    def key(self) -> str:
        """去重键：优先 infohash，其次标题归一化。"""
        if self.infohash:
            return self.infohash.lower()
        return f"{self.source}:{self.title.strip().lower()}"


_FIELDS = frozenset(f.name for f in fields(Resource))


def extract_group(title: str, fallback: str = "") -> str:
    """从标题里提取字幕组/发布组名。"""
    if not title:
        return fallback
    m = _BRACKET_GROUP.match(title)
    if m:
        g = m.group(1).strip()
        if g and not _NOT_A_GROUP.match(g) and not is_lang_tag(g):
            return g
    m = _TAIL_GROUP.search(title)
    if m:
        g = m.group(1).strip()
        if g and not _NOT_A_GROUP.match(g) and not is_lang_tag(g):
            return g
    return fallback


# --------------------------------------------------------------------------- #
# 字幕语言识别
# --------------------------------------------------------------------------- #
# 各站点的标注习惯差别很大，这里把常见写法都覆盖：
#   dmhy   : [简繁内封] [简体内嵌] [繁日內嵌] [簡繁外掛] [中日双字幕] [CHN SUB] CHS CHT BIG5 GB
#   kisssub: [简繁] [简体] [繁体] [简日] [繁日] [双语]（网站搜索还支持追加「简体」等后缀）
#   nyaa   : 多数不标注语言；英文组常写 MultiSub / Multi Audio，日文台标 [JPSC]/[JPN]
#
# 四条踩过的坑（都能在 tests / _probe/t_lang.py 里找到对应标题）：
# 1) 繁体写法必须先转简体再匹配：标题里「[繁簡英日]」「[簡日内嵌]」「[繁體]」很常见，
#    只按简体词表匹配会全部漏成「未标注」（用户反馈「这种的简繁都识别不出来」）。
# 2) 边界不能用 \b：正则里下划线算「词字符」，「[GB_MP4]」「[Ma10p_RAW]」用 \b 匹配不到。
# 3) 「1.5 GB」里的 GB 是体积不是国标简体，匹配前先把体积抠掉。
# 4) Dual Audio / Multi Audio / MultiSub 说的是音轨和多语字幕（通常是英西葡法），
#    不代表有中文字幕，不能算「简繁」，否则用户筛中文会看到一堆英文组资源。
_SIZE_TEXT = re.compile(r"\d+(?:\.\d+)?\s*(?:[KMGT]i?B)(?![A-Za-z])", re.I)
_LEFT = r"(?<![A-Za-z0-9])"           # 左边界：方括号/下划线/连字符/空格都算分隔符
_RIGHT = r"(?![A-Za-z0-9])"
_RIGHT_STRICT = r"(?![A-Za-z0-9-])"   # 用在 sc/tc 上，别把组名「SC-OL」当成简体


def _word(*words: str) -> str:
    """ASCII 语言标记：允许 [_]、[-] 之类作分隔符（\b 会被下划线骗过）。"""
    return _LEFT + "(?:" + "|".join(words) + ")" + _RIGHT


# 真·简繁（同一份资源里简体繁体都有）
_LANG_BOTH = re.compile(
    r"简繁|繁简|简繁日|繁简日|简&繁|" + _word("chs&cht", "sc&tc", "chs_cht", "cht_chs"), re.I)
# 单一语言（含「简日 / 繁日」这种中文+日文双语）
# [繁/rmvb/6.81GB] 这种老番标题里单个「简」「繁」就是语言标注，但只认「方括号 + 分隔符」的写法，
# 免得把「繁花」这种普通词当成繁体
_LANG_SIMP = re.compile(
    r"简体|简中|简体中文|简日|简英|中日|" + _word("chs", "chn", "zh-cn", "zh_hans")
    + r"|[\[【（(]\s*简\s*[/、,，]" + r"|" + _LEFT + r"(?:sc|gb)" + _RIGHT_STRICT, re.I)
_LANG_TRAD = re.compile(
    r"繁体|繁中|繁体中文|繁日|繁化|正体|" + _word("cht", "big5", "zh-tw", "zh_hant")
    + r"|[\[【（(]\s*繁\s*[/、,，]" + r"|" + _LEFT + r"tc" + _RIGHT_STRICT, re.I)
# 有中文但没写死简繁：双语 / 双字幕 / 中字（「国语中字」这类老番标题很多）
_LANG_ZH_ANY = re.compile(r"双语|雙語|双字幕|中字|中文字幕")
# RAW：标题里带 raw/raws 的（[RAW]、[Ma10p_RAW]、[NanakoRaws]、[Ohys-Raws]、nyaa 的「Anime - Raw」分类）
# 基本都是日语生肉，没有中文字幕。不写 \b 边界，因为要同时认「-Raws」「XxxRaws」两种写法
_RAW_TOKEN = r"(?:(?<![A-Za-z0-9])raws?(?![A-Za-z0-9])|raws?(?=[\]】]))"
_LANG_JP = re.compile(
    r"日语|日文|日本语|生肉|无字幕|vostfr|english\s*sub|eng[\s._-]?subs?|"
    + _RAW_TOKEN + "|" + _word("jp", "jpn", "jpsc", "jptc"),
    re.I)


# 「简日 / 繁日」这种中+日双语的标注（[简日双语] [簡日内嵌] [CHS_JP] [GB_JP] [繁日]）
_LANG_SIMP_JP = re.compile(
    r"(?:简|簡|chs?|gb|sc)[\s_&+\-.]*(?:日|jp|jpn|japanese)"
    r"|(?:日|jp|jpn)[\s_&+\-.]*(?:简|簡|chs?|gb|sc)", re.I)
_LANG_TRAD_JP = re.compile(
    r"(?:繁|cht|big5|tc)[\s_&+\-.]*(?:日|jp|jpn|japanese)"
    r"|(?:日|jp|jpn)[\s_&+\-.]*(?:繁|cht|big5|tc)", re.I)


def detect_language(*, title: str = "", category: str = "", extra: str = "") -> str:
    """
    识别资源的字幕语言，返回归一化标签：
      'chs'  简体
      'cht'  繁体
      'chj'  简日（中文简体 + 日文，[简日双语] [CHS_JP]）
      'cjt'  繁日（中文繁体 + 日文，[繁日双语] [CHT_JP]）
      'both' 简繁（简繁都有，或「双语 / 双字幕 / 中字」这类没写死简繁的中文标注）
      'jp'   只有日文（生肉/无字幕/只有英法字幕）
      ''     未标注（很多站点不标，宁可为空也不要猜错）

    判定顺序：真·简繁 > 简+繁同时出现 > 简体 > 繁体 > 双语/中字 > 日文。
    「简繁内封」里简繁都有，必须先判多语言，否则会被误判成单一语言。
    匹配时会把标题按「繁体 -> 简体」再跑一遍，繁体标注（[繁簡英日]、[簡日内嵌]）才不会漏。
    """
    text = " ".join(x for x in (title, category, extra) if x)
    if not text:
        return ""
    text = _SIZE_TEXT.sub(" ", text)                 # 先抠掉「1.5 GB」这种体积
    variants = [text]
    simplified = to_simplified(text)
    if simplified != text:                           # 繁体标题再跑一遍简体词表
        variants.append(simplified)

    def hit(rx: "re.Pattern[str]") -> bool:
        return any(rx.search(v) for v in variants)

    if hit(_LANG_BOTH):
        return "both"
    # 中+日双语：简日 / 繁日 要先于「简体」「繁体」判断，否则会被吞成单语
    if hit(_LANG_SIMP_JP):
        return "chj"                                 # [简日双语] [CHS_JP] [GB_JP]
    if hit(_LANG_TRAD_JP):
        return "cjt"                                 # [繁日双语] [CHT_JP] [BIG5_JP]
    has_simp = hit(_LANG_SIMP)
    has_trad = hit(_LANG_TRAD)
    if has_simp and has_trad:
        return "both"                                # [CHS_JP&CHT_JP] [GB][BIG5]
    if has_simp:
        return "chs"                                 # [简日内嵌] [簡日内嵌] [GB_MP4]
    if has_trad:
        return "cht"                                 # [繁日內嵌] [BIG5]
    if hit(_LANG_ZH_ANY):
        return "both"                                # [双语] [中字]
    if hit(_LANG_JP):
        return "jp"                                  # [RAW] [生肉] [ENG Subs]
    return ""


LANG_LABELS = {"chs": "简体", "cht": "繁体", "chj": "简日", "cjt": "繁日",
               "both": "简繁", "jp": "日文", "": "未标注"}


def lang_matches(resource_lang: str, wanted: str) -> bool:
    """
    语言筛选：**精确匹配**下拉里选的那一类，wanted 为空表示不限。

    用户反馈：选「简体」时「简繁」资源还留在表里（`[枝都字幕组] 冰之城墙 [15][简繁内嵌]`）。
    以前的规则是「选简体时简繁也算符合（里面确实有简体）」，但这样筛完还得自己一条条看，
    等于没筛。现在每个选项只留它自己那一类，「简繁/双语」是单独的选项：
        chs      → 只留 简体
        cht      → 只留 繁体
        both     → 只留 简繁/双语
        jp       → 只留 日文生肉
        unknown  → 只留未标注（站点没标语言的）
    """
    want = (wanted or "").strip().lower()
    if not want:
        return True
    have = (resource_lang or "").strip().lower()
    if want == "unknown":
        return have == ""
    return have == want


def enrich(res: Resource) -> Resource:
    """补全派生字段：分辨率、大小、剧集、字幕语言、噪声标记。"""
    if not res.resolution:
        res.resolution = parse_resolution(res.title)
    if not res.size_bytes and res.size_text:
        res.size_bytes = parse_size(res.size_text)
    a, b, batch = parse_episode_range(res.title)
    if res.episode is None:
        res.episode = parse_episode(res.title)
    res.episode_end = b
    res.is_batch = res.is_batch or batch
    res.is_noise = is_noise_title(res.title)
    if not res.group:
        res.group = extract_group(res.title)
    if not res.lang:
        res.lang = detect_language(title=res.title, category=res.category)
    if res.magnet and not res.infohash:
        m = re.search(r"btih:([0-9a-zA-Z]{32,40})", res.magnet)
        if m:
            res.infohash = m.group(1).lower()
    return res


def normalize_items(items) -> list[dict]:
    """
    读取缓存里的资源列表时重新补全派生字段（分辨率/语言/集数/大小/噪声）。

    为什么必须做：缓存是「上一版程序」写的。新增字段（比如字幕语言 lang）之后，
    旧 payload 里根本没有这个键，照原样返回就会让 UI 把「[简日内嵌]」显示成
    「未标注」（用户反馈过），而且用户看到的一直是旧数据。这里读缓存时统一重算一遍，
    新字段、新解析规则立刻生效，不用等缓存过期。
    """
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(enrich(Resource.from_dict(it)).to_dict())
    return out


class SourceAdapter:
    """资源站点适配器基类。"""

    id: str = ""
    name: str = ""
    default_base: str = ""
    #: 站点搜索结果本身是否带字幕组字段
    native_group_field: bool = False
    #: 站点是否支持「关键词 + 字幕组」组合搜索
    supports_group_in_query: bool = False
    #: 站点是否支持在关键词后面追「简体 / 繁体 / 简繁」做站内筛选
    #: （不支持也要能接住 lang 参数，否则 engine 统一传参会直接 TypeError）
    supports_lang_in_query: bool = False

    def __init__(self, base: Optional[str] = None):
        self.base = (base or self.default_base).rstrip("/")

    # ---------------------------------------------------------------- #
    def _timeout(self) -> float:
        return float(config.get("search.timeout_seconds", 20))

    def _proxy(self) -> Optional[str]:
        return config.proxy_for("sources")

    def _get(self, url: str, *, params: Optional[dict] = None, referer: Optional[str] = None,
             session: Optional[str] = None, timeout: Optional[float] = None,
             retries: int = 1) -> str:
        """
        站内搜索/详情页请求。

        retries 默认只重试 1 次（http.request 的默认是 2）：站点抽风时（动漫花园偶尔整站
        超时）「超时 20s × 3 次 × 10 个关键词」能把一次搜索拖到 10 分钟，页面一直卡在
        「正在搜索资源…」。少重试几次，失败了下一轮追番再试更划算。
        """
        _, text, _ = http.request(
            url, params=params, proxy=self._proxy(), session=session,
            timeout=timeout or self._timeout(), referer=referer, retries=retries,
            headers={"Referer": referer} if referer else None,
        )
        return text

    def search(self, keyword: str, *, group: str = "", page: int = 1,
               limit: Optional[int] = None, lang: str = "") -> list[Resource]:
        """搜索资源。keyword 为番剧名，group 为字幕组（可为空）。

        lang: 'chs' | 'cht' | 'both' | ''，站点不支持的忽略即可（engine 会统一传）。
        """
        raise NotImplementedError

    def groups_from(self, resources: list[Resource]) -> list[str]:
        """从搜索结果中汇总字幕组列表。"""
        seen, out = set(), []
        for r in resources:
            g = (r.group or "").strip()
            if g and g not in seen:
                seen.add(g)
                out.append(g)
        return out


_RES_ALIASES = {
    "4k": "2160p", "8k": "4320p", "uhd": "2160p", "fhd": "1080p", "hd": "720p",
    "2160": "2160p", "1440": "1440p", "1080": "1080p", "720": "720p", "480": "480p",
}


def normalize_resolution(text: str) -> str:
    """把 4K / 1080 / 1080P 之类写法统一成 2160p / 1080p。"""
    t = (text or "").strip().lower()
    if not t:
        return ""
    if t in _RES_ALIASES:
        return _RES_ALIASES[t]
    m = re.match(r"^(\d{3,4})[pi]?$", t)
    if m:
        return _RES_ALIASES.get(m.group(1), t)
    return t


def resolution_matches(resource_resolution: str, wanted: str) -> bool:
    """资源分辨率是否满足要求（要求为空表示不限）。"""
    want = normalize_resolution(wanted)
    if not want:
        return True
    got = normalize_resolution(resource_resolution)
    if not got:
        return True          # 标题里没写分辨率，不因此排除
    return got == want


def sort_resources(resources: list[Resource], preferred_resolution: str = "1080p") -> list[Resource]:
    """排序：分辨率匹配 > 做种数 > 站点优先级（保持入参中的站点顺序）。"""
    order: dict[str, int] = {}
    for r in resources:
        order.setdefault(r.source, len(order))
    want = normalize_resolution(preferred_resolution)

    def score(r: Resource):
        res_ok = 0 if (not want or normalize_resolution(r.resolution) == want) else 1
        seed = -(r.seeders if r.seeders is not None else -1)
        return (res_ok, seed, order.get(r.source, 99))

    return sorted(resources, key=score)


def apply_filters(resources: list[Resource], *, group: str = "", resolution: str = "",
                  min_seeders: int = 0, lang: str = "", drop_noise: bool = True) -> list[Resource]:
    """按字幕组 / 分辨率 / 字幕语言 / 做种数 过滤。"""
    out = []
    want_group = (group or "").strip().lower()
    for r in resources:
        if drop_noise and r.is_noise:
            continue
        if want_group:
            g = (r.group or "").lower()
            if want_group not in g and g not in want_group:
                continue
        if resolution and not resolution_matches(r.resolution, resolution):
            continue
        if lang and not lang_matches(r.lang, lang):
            continue
        if min_seeders and (r.seeders or 0) < min_seeders:
            continue
        out.append(r)
    return out


def dedupe(resources: list[Resource]) -> list[Resource]:
    """跨站点去重：同一 infohash 只保留优先级更高（先出现的）站点。"""
    seen: dict[str, Resource] = {}
    out: list[Resource] = []
    for r in resources:
        k = r.key
        if k in seen:
            continue
        seen[k] = r
        out.append(r)
    return out
