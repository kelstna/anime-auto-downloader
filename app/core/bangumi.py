# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
Bangumi API 客户端（api.bgm.tv v0）。
- Bearer Token 认证（配合 https://next.bgm.tv/demo/access-token 获取的令牌）
- 拉取「在看」收藏、番剧详情、章节列表、多语言别名
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from . import config, http, logger, meta
from ..core.util import clean_keyword, to_simplified, has_traditional, uniq_keep_order
from ..sources import romaji
from . import cache

API_BASE = "https://api.bgm.tv"
SITE_BASE = "https://bgm.tv"
TOKEN_URL = "https://next.bgm.tv/demo/access-token"

SUBJECT_TYPE_ANIME = 2
COLLECT_WISH, COLLECT_DONE, COLLECT_DOING, COLLECT_ON_HOLD, COLLECT_DROPPED = 1, 2, 3, 4, 5

_cache_lock = threading.RLock()
_subject_cache: dict[int, "Subject"] = {}
_episode_cache: dict[int, tuple[float, list[dict]]] = {}


class BangumiError(Exception):
    pass


@dataclass
class Subject:
    id: int
    name: str = ""                 # 日文原名
    name_cn: str = ""              # 简体中文名
    summary: str = ""
    cover: str = ""                # 视觉图（大图）
    cover_medium: str = ""
    date: str = ""
    eps: int = 0                   # 本篇话数
    total_episodes: int = 0
    rank: int = 0
    score: float = 0.0
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    infobox: dict[str, Any] = field(default_factory=dict)
    collect_type: int = COLLECT_DOING
    ep_status: int = 0
    folder_name: str = ""

    # ---------------------------------------------------------------- #
    @property
    def display_name(self) -> str:
        """界面展示名：优先简体中文名。"""
        return (self.name_cn or self.name or f"subject-{self.id}").strip()

    @property
    def traditional_name(self) -> str:
        return to_traditional(self.name_cn or self.name)

    @property
    def english_name(self) -> str:
        return (self.infobox.get("英文名") or "").strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["display_name"] = self.display_name
        d["traditional_name"] = self.traditional_name
        d["english_name"] = self.english_name
        return d

    def search_aliases(self) -> list[str]:
        """所有可用于搜索的名字（按可信度排序，已去重）。"""
        return build_aliases(self)


# --------------------------------------------------------------------------- #
# 简繁互转（繁体方向，仅覆盖常用字）
# --------------------------------------------------------------------------- #
_S2T_PAIRS = (
    "万萬与與东東车車马馬鸟鳥鱼魚龙龍龟龜齿齒页頁风風飞飛见見贝貝长長门門问問间間"
    "开開关關阳陽阴陰队隊际際随隨隐隱难難云雲电電话話语語说說读讀谁誰课課诸諸让讓"
    "认認识識记記讨討论論设設访訪诉訴评評词詞译譯试試诗詩诚誠误誤调調谈談请請诺諾"
    "谋謀讲講谢謝证證议議护護誉譽变變恋戀湾灣欢歡欧歐岁歲历歷归歸残殘杀殺气氣爱愛"
    "为為无無烟煙热熱营營灯燈烧燒争爭尔爾墙牆独獨奖獎现現环環产產画畫当當发發尽盡"
    "监監盘盤众眾礼禮种種积積称稱稳穩穷窮竞競笔筆节節范範筑築简簡篮籃签籤纪紀红紅"
    "纯純纸紙级級纷紛细細终終组組结結绝絕统統丝丝经經绿綠网網紧紧绪緒线線缘緣编編"
    "缓缓练練缩縮总總织織继繼续續缠纏罚罰罗羅义義习習联聯聪聰声聲听聽肃肅脑腦脸臉"
    "临臨举舉旧舊华華盖蓋蓝藍艺藝药藥处處号號虫蟲术術卫衛冲衝补補装裝复複观觀规規"
    "视視觉覺览覽计計训訓讯訊注註周週游遊递遞远遠适適选選遗遺乡鄉医醫释釋银銀钱錢"
    "针針录錄钟鐘鉴鑑闭閉闲閒陈陳陆陸阶階险險虽雖双雙杂雜鸡雞静静顶頂项項顺順须須"
    "预預领領头頭颈頸颜顏愿願类類顾顧显顯饥飢饭飯饮飲饰飾养養馆館驻駐验驗体體发髮"
    "斗鬥鲁魯鲜鮮鸣鳴鸦鴉鹅鵝鹰鷹咸鹹丽麗麦麥黄黃点點齐齊党黨"
)
_S2T: dict[int, str] = {}
for _i in range(0, len(_S2T_PAIRS) - 1, 2):
    _s, _t = _S2T_PAIRS[_i], _S2T_PAIRS[_i + 1]
    if _s != _t:
        _S2T[ord(_s)] = _t
del _i, _s, _t, _S2T_PAIRS


def to_traditional(text: str) -> str:
    return text.translate(_S2T) if text else ""


# --------------------------------------------------------------------------- #
# 别名构建
# --------------------------------------------------------------------------- #
_ROMAN_TAG = re.compile(r"^[\x00-\x7F]+$")
_TRAILING_SEASON = re.compile(r"\s*(?:第\s*[0-9一二三四五六七八九十]+\s*[季期部]|Season\s*\d+|S\d{1,2}|II|III|IV)$", re.I)
_CJK_ONLY = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f]+$")


def build_aliases(subject: Subject) -> list[str]:
    """
    汇总一个番剧所有**可用于搜索**的名字，排序按用户要求：**先简体 → 再繁体 → 再英文**。

    两条硬规则（都是踩坑换来的）：
    1. **不含日文原名**：含假名的名字在三个站点基本搜不到东西
       （动漫花园/爱恋动漫是中文标题，Nyaa 用罗马字），而且用户明确要求「不要用日文标题」。
       日文原名只用来生成罗马字（罗马字算「英文」这一类）。
    2. 每个名字都会展开成「清洗过的关键词」变体（去标点、多段用空格、去掉第几季），
       清洗后的排在前、原样的排在后兜底 —— 见 util.clean_keyword 里的实测对比：
       「野生的大魔王出现了！第二季」只搜到 2 条，「野生的大魔王出现了」能搜到 11 条。
    """
    info = subject.infobox or {}
    cn_src: list[str] = []       # 中文（简/繁都可能）
    en_src: list[str] = []       # 英文 / 罗马字
    other: list[str] = []        # 其它（纯汉字的外文名等）

    def push(v, bucket: list[str]):
        if isinstance(v, list):
            for x in v:
                push(x.get("v") if isinstance(x, dict) else x, bucket)
        elif isinstance(v, str) and v.strip():
            bucket.append(v.strip())

    push(subject.name_cn, cn_src)
    push(subject.name, other if romaji.has_kana(subject.name) else cn_src)
    for key in ("中文名", "别名", "别名（中文）", "別名", "其它译名", "其他译名", "日文名"):
        if key in info:
            push(info[key], cn_src)
    # 订阅里存下来的别名（订阅模式下没有 infobox，这些别名就是唯一的补充来源）
    for a in (subject.aliases or []):
        if not isinstance(a, str) or not a.strip():
            continue
        if _ROMAN_TAG.match(a.strip()):
            en_src.append(a.strip())
        elif not romaji.has_kana(a):
            cn_src.append(a.strip())
    push(info.get("英文名"), en_src)
    push(info.get("罗马字"), en_src)
    # 日文原名（含假名）→ 罗马字，作为「英文」关键词
    for base in (subject.name, subject.name_cn):
        if base and romaji.has_kana(base):
            en_src.extend(romaji.romaji_variants(base))

    def clean(a: str) -> str:
        a = re.sub(r"\s+", " ", a).strip(" 　/")
        return a if a and len(a) <= 90 else ""

    simp: list[str] = []
    trad: list[str] = []
    for a in cn_src:
        a = clean(a)
        if not a or romaji.has_kana(a):        # 日文别名不参与搜索
            continue
        if _ROMAN_TAG.match(a):                # 中文别名字段里的纯英文
            en_src.append(a)
            continue
        s = to_simplified(a)
        simp.append(s)
        t = to_traditional(s)
        if t != s:
            trad.append(t)
    for a in other:
        a = clean(a)
        if a:
            other[other.index(a)] = a

    english: list[str] = []
    for a in en_src:
        a = clean(a)
        if a:
            english.append(a)
    for a in (subject.name, subject.name_cn):
        a = clean(a or "")
        if a and _ROMAN_TAG.match(a):
            english.append(a)

def build_aliases(subject: Subject) -> list[str]:
    """
    汇总一个番剧所有**可用于搜索**的名字（简体 → 繁体 → 英文交错排列）。

    两条硬规则（都是踩坑换来的）：
    1. **不含日文原名**：含假名的名字在三个站点基本搜不到东西
       （动漫花园/爱恋动漫是中文标题，Nyaa 用罗马字），而且用户明确要求「不要用日文标题」。
       日文原名只用来生成罗马字（罗马字算「英文」这一类）。
    2. 每个名字都会展开成「清洗过的关键词」变体（去标点、多段用空格、去掉第几季），
       清洗后的排在前、原样的排在后兜底 —— 见 util.clean_keyword 里的实测对比：
       「野生的大魔王出现了！第二季」只搜到 2 条，「野生的大魔王出现了」能搜到 11 条。
    分组细节见 alias_groups()。
    """
    return aliases_for_source(subject, "")


def _usable_alias(a: str) -> bool:
    """过滤掉纯符号 / 过短的名字。"""
    if len(a) < 2:
        return False
    return bool(re.search(r"[\w\u4e00-\u9fff]", a))


def alias_groups(subject: Subject) -> dict[str, list[str]]:
    """
    把搜索名按语言分组：`{"chs": [简体…], "cht": [繁体…], "en": [罗马字 / 英文…]}`。

    为什么要分组：用户要求「三种搜索词（简体/繁体/英文）每种的结果都显示」——
    引擎必须保证每组至少搜一次，不能因为简体那组已经搜到东西就跳过繁体/英文。

    en 组内部顺序（用户要求「英文名搜索改成罗马音搜索」）：
      ① 罗马字：日文原名转写出来的、别名里「像罗马音」的（`Kusuriya no Hitorigoto`）、infobox 罗马字
      ② 英文名/其它拉丁别名：**短英文名**才用；一长串英文句子（`There is also a hole in the
         student organization!`）站内搜索一条都搜不到，直接丢掉
    组内都按「清洗版优先」（去标点、去第几季），清洗后的排前、原样写法兜底。
    """
    info = subject.infobox or {}
    cn_src: list[str] = []           # 中文（简/繁都可能）
    romaji_src: list[str] = []       # 罗马字（优先生成/挑出来）
    en_src: list[str] = []           # 英文名 / 其它拉丁别名
    other: list[str] = []            # 其它（纯汉字的外文名等）

    def push(v, bucket: list[str]):
        if isinstance(v, list):
            for x in v:
                push(x.get("v") if isinstance(x, dict) else x, bucket)
        elif isinstance(v, str) and v.strip():
            bucket.append(v.strip())

    def push_latin(v):
        """拉丁字符的名字：像罗马音的进 romaji 组，其余进英文组。"""
        for a in (v if isinstance(v, list) else [v]):
            if isinstance(a, dict):
                a = a.get("v")
            if not isinstance(a, str) or not a.strip():
                continue
            a = a.strip()
            (romaji_src if romaji.looks_like_romaji(a) else en_src).append(a)

    push(subject.name_cn, cn_src)
    push(subject.name, other if romaji.has_kana(subject.name) else cn_src)
    for key in ("中文名", "别名", "别名（中文）", "別名", "其它译名", "其他译名", "日文名"):
        if key in info:
            push(info[key], cn_src)
    # 订阅里存下来的别名（订阅模式下没有 infobox，这些别名就是唯一的补充来源）
    for a in (subject.aliases or []):
        if not isinstance(a, str) or not a.strip():
            continue
        if _ROMAN_TAG.match(a.strip()):
            push_latin(a.strip())
        elif not romaji.has_kana(a):
            cn_src.append(a.strip())
    push_latin(info.get("英文名"))
    push(info.get("罗马字"), romaji_src)
    # 日文原名（含假名）→ 罗马字
    for base in (subject.name, subject.name_cn):
        if base and romaji.has_kana(base):
            romaji_src.extend(romaji.romaji_variants(base))

    def clean(a: str) -> str:
        a = re.sub(r"\s+", " ", a).strip(" 　/")
        return a if a and len(a) <= 90 else ""

    simp: list[str] = []
    trad: list[str] = []
    for a in cn_src:
        a = clean(a)
        if not a or romaji.has_kana(a):        # 日文别名不参与搜索
            continue
        if _ROMAN_TAG.match(a):                # 中文别名字段里的纯英文
            push_latin(a)
            continue
        s = to_simplified(a)
        simp.append(s)
        t = to_traditional(s)
        if t != s:
            trad.append(t)

    def latin_ok(a: str) -> bool:
        """英文名只留「短名」：一长串英文句子（There is also a hole in…）站内搜索一条都搜不到。"""
        a = clean(clean_keyword(a))       # 先去标点/去第几季，再判断长短
        if not a:
            return False
        if len(a) > 42:
            return False
        return len(a.split()) <= 4

    english: list[str] = []
    # ① 罗马字优先（用户要求：英文名搜索改成罗马音搜索），越像罗马音的排越前
    romaji_ranked = sorted(uniq_keep_order([clean(a) for a in romaji_src if clean(a)]),
                           key=lambda a: -romaji.romaji_score(a))
    for a in romaji_ranked:
        if _usable_alias(a):
            english.append(a)
    # ② 再放短英文名当兜底
    for a in en_src:
        a = clean(a)
        if a and latin_ok(a):
            english.append(a)
    for a in (subject.name, subject.name_cn):
        a = clean(a or "")
        if a and _ROMAN_TAG.match(a) and latin_ok(a):
            english.append(a)

    def keywords(names: list[str], *, aggressive_first: bool) -> list[str]:
        """
        把「名字列表」展开成关键词候选，**按清洗级别分层、层内保持名字顺序**：

            第 1 层：每个名字的清洗版（去标点、多段用空格、去掉第几季）
            第 2 层：每个名字的激进清洗版（连 ASCII 标点也去掉 / 英文去标点优先）
            第 3 层：原样名字兜底

        分层（而不是一个名字一口气展开 3 个变体）的原因：关键词有预算上限，
        必须保证**每个不同的名字都能轮到一次**，否则第 3 个名字可能因为前两个名字
        占了 6 个槽位而永远搜不到（用户实测：能搜到资源的 `Dark Summoner to Dekiteiru`
        是第 5 个候选，被上限截断了）。
        """
        names = uniq_keep_order([n for n in names if _usable_alias(n)])
        clean = [clean_keyword(n) for n in names]
        aggressive = [clean_keyword(n, cjk_only=True) for n in names]
        levels = ([aggressive, clean, list(names)] if aggressive_first
                  else [clean, aggressive, list(names)])
        out = [k for level in levels for k in level]
        return uniq_keep_order([k for k in out if _usable_alias(k)])

    # 跨语言组去重：繁体名跟简体名一模一样（没用到繁体字）时不必再搜一遍，
    # 省下来的预算留给真正不同的名字（实测同一部番的简/繁名常常完全相同）。
    seen: set[str] = set()
    simp = [s for s in uniq_keep_order(simp) if not (s.lower() in seen or seen.add(s.lower()))]
    trad = [t for t in uniq_keep_order(trad) if not (t.lower() in seen or seen.add(t.lower()))]
    english = [e for e in uniq_keep_order(english) if not (e.lower() in seen or seen.add(e.lower()))]

    return {
        "chs": keywords(simp, aggressive_first=False)[:10],
        "cht": keywords(trad, aggressive_first=False)[:10],
        "en": keywords(english, aggressive_first=True)[:10],
    }


def alias_groups_for_source(subject: Subject, source_id: str) -> dict[str, list[str]]:
    """按资源站给出分组关键词（顺序统一，站点差异只体现在取几个）。"""
    groups = alias_groups(subject)
    limit = 6 if source_id == "nyaa" else 8
    return {k: v[:limit] for k, v in groups.items()}


def aliases_for_source(subject: Subject, source_id: str) -> list[str]:
    """
    按资源站给出搜索名（顺序统一为**简体 → 繁体 → 英文**，各组交错排列）。

    交错的意义：引擎按这个顺序逐个搜，前三个就覆盖了三种语言
    （用户要求「每种搜索词的结果都显示」），不会因为简体先搜到就漏掉繁体/英文。
    """
    groups = alias_groups_for_source(subject, source_id)
    order = ("chs", "cht", "en")
    out: list[str] = []
    for i in range(max((len(groups.get(k) or []) for k in order), default=0)):
        for k in order:
            items = groups.get(k) or []
            if i < len(items):
                out.append(items[i])
    return uniq_keep_order(out)


def alias_group_map(subject: Subject, source_id: str) -> dict[str, str]:
    """关键词 → 语言分组（引擎用来判断「三种语言是否都搜过了」）。"""
    mapping: dict[str, str] = {}
    for group, items in (alias_groups_for_source(subject, source_id) or {}).items():
        for kw in items or []:
            mapping.setdefault(kw, group)
    return mapping# --------------------------------------------------------------------------- #
# API 调用
# --------------------------------------------------------------------------- #
def _headers(token: Optional[str] = None) -> dict:
    h = {"User-Agent": "DSH-AnimeAutoDownloader/1.0 (local)", "Accept": "application/json"}
    tok = (token or config.bangumi_token()).strip()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _paged(url: str, params: dict, token: Optional[str] = None, max_pages: int = 20) -> list[dict]:
    out: list[dict] = []
    offset = int(params.get("offset", 0))
    limit = int(params.get("limit", 50))
    for _ in range(max_pages):
        p = dict(params)
        p["offset"] = offset
        p["limit"] = limit
        data = http.get_json(
            url, params=p, headers=_headers(token),
            proxy=config.proxy_for("bangumi"), timeout=config.get("search.timeout_seconds", 20) + 5,
        )
        items = (data or {}).get("data") or []
        out.extend(items)
        total = (data or {}).get("total", 0)
        offset += limit
        if not items or offset >= total:
            break
    return out


def get_me(token: Optional[str] = None) -> dict:
    """校验 token 并返回当前用户信息（带缓存，避免每次启动都打接口）。"""
    tok = (token or config.bangumi_token()).strip()
    key = f"{cache.ME_KEY}:{cache.token_fingerprint(tok)}"

    def fetch() -> dict:
        return _get_me_raw(tok)

    try:
        data, from_cache, age = cache.cached(
            key, cache.collections_ttl(), fetch, background_refresh=True)
        if isinstance(data, dict) and data.get("id"):
            if from_cache:
                logger.debug("用户信息命中缓存（%.0f 秒前）", age)
            return data
    except (http.HttpError, OSError, ValueError) as e:
        # 接口不可用时尝试用过期缓存兜底，保证界面仍可用
        stale, ts = cache.get_stale(key)
        if isinstance(stale, dict) and stale.get("id"):
            logger.warn("Bangumi 接口不可用，使用过期缓存（%.0f 秒前）：%s", time.time() - ts, e)
            return stale
        raise
    return _get_me_raw(tok)


def _get_me_raw(token: str) -> dict:
    try:
        return http.get_json(f"{API_BASE}/v0/me", headers=_headers(token),
                            proxy=config.proxy_for("bangumi"), timeout=20)
    except http.HttpError as e:
        if e.status == 401:
            raise BangumiError("Access Token 无效或已过期，请重新获取") from None
        raise BangumiError(f"Bangumi 接口返回 HTTP {e.status}") from None
    except OSError as e:
        raise BangumiError(f"无法连接 Bangumi：{e}") from None


def cached_subject(subject_id: int) -> Optional[Subject]:
    """
    只读内存缓存，**绝不联网**。

    给「列表接口顺手补点信息」这种场景用（比如取「播放电视台」）：Bangumi 抽风时
    一次 /api/subscriptions 里 13 个详情接口各超时几秒，能把整个请求拖到一分钟，
    所以列表接口只能读缓存，缺的以后再补（见 warm_subjects）。
    """
    with _cache_lock:
        return _subject_cache.get(int(subject_id))


def warm_subjects(subject_ids: Iterable[int]) -> list[int]:
    """
    后台把还没有缓存的番剧详情补起来（下次列表接口就能读到「播放电视台」等信息）。
    返回这次真正补齐的 id 列表；任何失败都吞掉，绝不影响调用方。
    """
    done = []
    for sid in subject_ids:
        sid = int(sid)
        if cached_subject(sid):
            continue
        try:
            get_subject(sid)
            done.append(sid)
        except Exception:                     # noqa: BLE001 - 补详情失败不算错误
            break                             # 连续失败（多半是网络/站点问题）就别继续了
    return done


def get_subject(subject_id: int, token: Optional[str] = None, use_cache: bool = True,
                force: bool = False) -> Subject:
    """取番剧详情。force=True 时跳过本地缓存强制联网（别名/首播日等会跟着更新）。"""
    cached = None if force else meta.get(subject_id, allow_stale=False)
    if cached and cached.get("total_episodes") is not None and cached.get("date"):
        # 只填 Subject 真正有的字段（airtime / 章节表这些走 meta 直接取，不进 Subject）
        s = Subject(
            id=int(cached["subject_id"]),
            name=cached.get("name") or "",
            name_cn=cached.get("name_cn") or "",
            cover=cached.get("cover") or "",
            date=cached.get("date") or "",
            total_episodes=int(cached.get("total_episodes") or 0),
            score=float(cached.get("score") or 0) or 0.0,
            rank=int(cached.get("rank") or 0) or 0,
        )
        # 缓存里存过别名（含 Bangumi infobox 的「别名」，如「凡人修仙传 慕兰之战篇」）就带上，
        # 否则季判定拿不到篇章名，动漫花园那种按篇章名+本季编号发的资源会被当成上一季
        s.aliases = [a for a in (cached.get("aliases") or []) if isinstance(a, str) and a]
        return s
    with _cache_lock:
        if use_cache and subject_id in _subject_cache:
            return _subject_cache[subject_id]

    data = http.get_json(f"{API_BASE}/v0/subjects/{subject_id}", headers=_headers(token),
                         proxy=config.proxy_for("bangumi"), timeout=25)
    imgs = data.get("images") or {}
    info: dict[str, Any] = {}
    for item in data.get("infobox") or []:
        k = item.get("key")
        if k:
            info[k] = item.get("value")

    s = Subject(
        id=int(data.get("id") or subject_id),
        name=data.get("name") or "",
        name_cn=data.get("name_cn") or "",
        summary=(data.get("summary") or "").strip(),
        cover=imgs.get("large") or imgs.get("common") or imgs.get("medium") or "",
        cover_medium=imgs.get("common") or imgs.get("medium") or imgs.get("large") or "",
        date=data.get("date") or "",
        eps=int(data.get("eps") or 0),
        total_episodes=int(data.get("total_episodes") or data.get("eps") or 0),
        rank=int((data.get("rating") or {}).get("rank") or 0),
        score=float((data.get("rating") or {}).get("score") or 0.0),
        tags=[t.get("name", "") for t in (data.get("tags") or [])[:12] if t.get("name")],
        infobox=info,
    )
    s.aliases = build_aliases(s)
    s.folder_name = s.display_name
    with _cache_lock:
        _subject_cache[subject_id] = s
    try:
        meta.save_many([s])
    except Exception as e:                  # noqa: BLE001 - 缓存失败不影响主流程
        logger.debug("番剧 %s 元数据写缓存失败：%s", subject_id, e)
    return s


def get_collections(token: Optional[str] = None, collect_type: int = COLLECT_DOING,
                    subject_type: int = SUBJECT_TYPE_ANIME, force: bool = False) -> list[Subject]:
    """
    拉取指定收藏状态的番剧列表（默认「在看」）。

    缓存策略（用户要求：token 没变就用缓存，并自动更新）：
    - 缓存键包含 token 指纹，token 变了自然失效
    - 15 分钟内直接命中缓存（秒回）
    - 超过 15 分钟：先用旧数据返回，同时后台线程去 Bangumi 拉最新并写回缓存
    - force=True 时强制同步拉取（UI 上的「刷新」按钮）
    """
    tok = (token or config.bangumi_token()).strip()
    if not tok:
        raise BangumiError("请先填写 Bangumi Access Token")
    key = f"{cache.COLLECTIONS_KEY}:{cache.token_fingerprint(tok)}:{collect_type}:{subject_type}"

    def fetch() -> list:
        return _fetch_collections(tok, collect_type, subject_type)

    def to_subjects(raw: list) -> list[Subject]:
        return _raw_to_subjects(raw)

    if force:
        raw = fetch()
        cache.set(key, raw)
        return to_subjects(raw)

    cached_raw, from_cache, age = cache.cached(
        key, cache.collections_ttl(), fetch, background_refresh=True)
    if from_cache:
        logger.info("在看列表命中缓存（%.0f 秒前，可在设置里强制刷新）", age)
    return to_subjects(cached_raw or [])


def _fetch_collections(token: str, collect_type: int, subject_type: int) -> list:
    """真正打接口：user id + 分页收藏列表（返回可 JSON 序列化的原始数据）。"""
    me = get_me(token)
    uid = me.get("id") or me.get("username")
    if not uid:
        raise BangumiError("无法获取用户 ID")

    raw = _paged(
        f"{API_BASE}/v0/users/{uid}/collections",
        {"subject_type": subject_type, "type": collect_type, "limit": 50},
        token=token,
    )
    slim: list[dict] = []
    for item in raw:
        sub = item.get("subject") or {}
        images = sub.get("images") or {}
        slim.append({
            "subject_id": item.get("subject_id") or sub.get("id"),
            "type": item.get("type") or collect_type,
            "ep_status": item.get("ep_status") or 0,
            "vol_status": item.get("vol_status") or 0,
            "updated_at": item.get("updated_at") or "",
            "subject": {
                "id": sub.get("id"),
                "name": sub.get("name") or "",
                "name_cn": sub.get("name_cn") or "",
                "short_summary": sub.get("short_summary") or "",
                "date": sub.get("date") or "",
                "images": {
                    "large": images.get("large") or "",
                    "common": images.get("common") or "",
                    "medium": images.get("medium") or "",
                },
            },
        })
    return slim


def _raw_to_subjects(raw: list) -> list[Subject]:
    """
    缓存的原始数据 -> Subject 列表，并补齐详情（话数/别名），并发加速。

    熔断：网络不通时（例如没开代理），每部番剧的详情请求要等 25 秒超时并重试，
    36 部并发 8 路会让「拉取在看」看起来卡死好几分钟。所以这里连续失败若干次就
    停止补详情，直接用收藏列表里的数据（列表本身已含名称/封面/日期），
    并把原因记到日志与返回值里，界面仍然可用。
    """
    subjects: list[Subject] = []
    for item in raw or []:
        sub = item.get("subject") or {}
        images = sub.get("images") or {}
        s = Subject(
            id=int(item.get("subject_id") or sub.get("id") or 0),
            name=sub.get("name") or "",
            name_cn=sub.get("name_cn") or "",
            summary=(sub.get("short_summary") or "").strip(),
            cover=images.get("large") or images.get("common") or images.get("medium") or "",
            cover_medium=images.get("common") or images.get("medium") or images.get("large") or "",
            date=sub.get("date") or "",
            collect_type=int(item.get("type") or COLLECT_DOING),
            ep_status=int(item.get("ep_status") or 0),
        )
        s.aliases = build_aliases(s)
        s.folder_name = s.display_name
        subjects.append(s)

    todo = [s for s in subjects if s.id]
    if not todo:
        with _cache_lock:
            return []

    # 熔断阈值：连续失败这么多次就认为「详情接口整体不可用」，不再逐部等超时
    fail_limit = max(2, int(config.get("bangumi.detail_fail_limit", 3)))
    workers = max(2, min(8, len(todo)))
    consecutive_fail = 0
    stop = threading.Event()

    def fetch_one(subject: Subject):
        nonlocal consecutive_fail
        if stop.is_set():
            return None
        detail = _safe_detail(subject.id, None)
        if detail is None:
            consecutive_fail += 1
            if consecutive_fail >= fail_limit and not stop.is_set():
                stop.set()
                logger.warn(
                    "已连续 %d 部番剧详情获取失败，停止补齐详情（列表数据仍可用）"
                    "——若这是网络问题，请在「设置 → 代理设置」里启用代理后重试", consecutive_fail)
        else:
            consecutive_fail = 0
        return detail

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bgm-detail") as pool:
        futs = {pool.submit(fetch_one, s): s for s in todo}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                detail = fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warn("获取番剧 %s 详情失败：%s", s.id, e)
                continue
            if detail is not None:
                detail.collect_type = s.collect_type
                detail.ep_status = s.ep_status

    if stop.is_set():
        total = len(todo)
        logger.warn("本次只拿到部分番剧详情（%d/%d）", len(_subject_cache), total)

    with _cache_lock:
        return [_subject_cache.get(s.id, s) for s in subjects]


def _safe_detail(subject_id: int, token: Optional[str]) -> Optional[Subject]:
    try:
        return get_subject(subject_id, token=token)
    except (http.HttpError, OSError, ValueError) as e:
        logger.warn("番剧 %s 详情接口异常：%s", subject_id, e)
        return None


def get_episodes(subject_id: int, token: Optional[str] = None, ttl: float = 6 * 3600) -> list[dict]:
    """获取本篇章节列表（带缓存）。"""
    now = time.time()
    with _cache_lock:
        hit = _episode_cache.get(subject_id)
        if hit and now - hit[0] < ttl:
            return hit[1]

    eps: list[dict] = []
    offset, limit = 0, 100
    for _ in range(10):
        data = http.get_json(
            f"{API_BASE}/v0/episodes",
            params={"subject_id": subject_id, "type": 0, "limit": limit, "offset": offset},
            headers=_headers(token), proxy=config.proxy_for("bangumi"), timeout=25,
        )
        items = (data or {}).get("data") or []
        for e in items:
            eps.append({
                "id": e.get("id"),
                "ep": e.get("ep"),
                "sort": e.get("sort"),
                "name": e.get("name") or "",
                "name_cn": e.get("name_cn") or "",
                "airdate": e.get("airdate") or "",
                "comment": e.get("comment") or 0,
            })
        total = (data or {}).get("total", 0)
        offset += limit
        if not items or offset >= total:
            break
    eps.sort(key=lambda x: (x.get("sort") or 0))
    with _cache_lock:
        _episode_cache[subject_id] = (now, eps)
    return eps


def total_episodes(subject: Subject, token: Optional[str] = None) -> int:
    """番剧总话数：优先 subject 信息，其次章节列表。"""
    if subject.total_episodes:
        return subject.total_episodes
    if subject.eps:
        return subject.eps
    try:
        eps = get_episodes(subject.id, token=token)
        nums = [e.get("sort") or e.get("ep") or 0 for e in eps]
        return int(max(nums)) if nums else 0
    except (http.HttpError, OSError, ValueError) as e:
        logger.warn("获取 %s 章节失败：%s", subject.id, e)
        return 0


def search_subjects(keyword: str, limit: int = 12) -> list[dict]:
    """搜索 Bangumi 条目（用于手动添加番剧）。"""
    try:
        data = http.request(
            f"{API_BASE}/v0/search/subjects",
            method="POST",
            data=__import__("json").dumps({"keyword": keyword, "filter": {"type": [SUBJECT_TYPE_ANIME]}}).encode(),
            headers={**_headers(), "Content-Type": "application/json"},
            proxy=config.proxy_for("bangumi"), timeout=25,
        )[1]
        import json as _json
        items = (_json.loads(data) or {}).get("data") or []
        return items[:limit]
    except (http.HttpError, OSError, ValueError) as e:
        logger.warn("Bangumi 搜索失败：%s", e)
        return []


def clear_cache() -> None:
    with _cache_lock:
        _subject_cache.clear()
        _episode_cache.clear()
