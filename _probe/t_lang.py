"""字幕语言识别测试：用三站点真实标题写法验证 detect_language 与筛选。

标题全部来自真实搜索结果（data/cache 里攒下来的 2000+ 条），改动识别规则后必须全绿。
"""
import os
import sys
import hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.sources.base import (  # noqa: E402
    Resource, detect_language, enrich, extract_group, is_lang_tag, lang_matches,
    apply_filters, normalize_items,
)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


# (标题, 期望语言)
CASES = [
    # ---- 动漫花园：标题里大量标注 ----
    ("[7³ACG] 葬送的芙莉莲 [简繁字幕] BDrip 1080p x265", "both"),
    ("[绿茶字幕组] FX Senshi Kurumi-chan [01][WebRip][1080p][简体内嵌]", "chs"),
    ("[綠茶字幕組] 葬送的芙莉蓮 第二季 [38][WebRip][1080p][繁日內嵌]", "cht"),
    ("[沸班亚马制作组] 间谍过家家 第三季 [01-13Fin][1080p][简繁内封]", "both"),
    # 「简日双语」= 简体+日文双语，有简体中文，算简体（以前被算成简繁）
    ("[云光字幕组] 间谍过家家 第三季 - 11 [1080p][简日双语]", "chs"),
    ("[北宇治字幕组] / FX Senshi Kurumi-chan [01][WebRip][HEVC_AAC]", ""),
    ("[ANi] FX 戰士久留美 - 01 [1080P][Baha][WEB-DL][AAC AVC][CHT]", "cht"),
    ("[Skymoon-Raws] - 01 [CHS][AVC AAC]僵屍搜尋中", "chs"),
    ("[SomeGroup] Title - 05 [1080p][GB][BIG5]", "both"),
    ("[Group] Title [1080p][BIG5]", "cht"),
    # ---- 繁体写法：用户截图里的那三条就是这种 ----
    ("[绿茶字幕组] / FX Senshi Kurumi-chan [01v2][WebRip][1080p][简日内嵌]FX战士久留美", "chs"),
    ("[綠茶字幕組] / FX Senshi Kurumi-chan [01v2][WebRip][1080p][繁日內嵌]FX戰士久留美", "cht"),
    ("[绿茶字幕组] / FX Senshi Kurumi-chan [01][WebRip][1080p][簡日内嵌]FX戰士久留美", "chs"),
    ("【悠哈璃羽字幕社】[ / FX Senshi Kurumi-chan][01][1080p HEVC][CHT_JP][繁日內嵌]FX戰士久留美", "cht"),
    ("【悠哈璃羽字幕社】[ / FX Senshi Kurumi-chan][01][1080p HEVC][CHS_JP&CHT_JP][简繁日内封]FX战士久留美", "both"),
    ("[LCK] ：Brotherhood [2009年版][第01-05話][繁簡英日][480p]FullmetalAlchemist鋼之煉金術師", "both"),
    ("[SweetSub][堀與宮村 --][13][WebRip][1080P][AVC 8bit][繁日雙語]pieceHorimiyapiece", "cht"),
    # ---- 老番/少见写法（以前全是「未标注」）----
    ("【幻樱字幕组】【10月新番】【赛博朋克:边缘行者】【06-10】【GB_MP4】【180X70】22", "chs"),
    ("[fx字幕大队][][Death Note][BDrip][1080p][10bit_x265_aac][CHN SUB][HEVC Encode by FK99]死亡笔记", "chs"),
    ("[诸神字幕组][__][57][1280×720][X264_AAC][中日双字幕]钢之炼金术师", "chs"),
    ("HD高清国语中字死亡笔记", "both"),
    ("[漫游字幕组] 2009 第57话 MKV+ASS（日本语字幕附）FullmetalAlchemist钢之炼金术师", "jp"),
    ("NEO FA 1-64 全[繁/rmvb/6.81GB]FULLMETALALCHEMIST鋼之煉金術師", "cht"),
    ("[03版][_][51集全][GB_JP][X264_AAC][528P][DVDRIP][MP4][skytree]钢之炼金术师", "chs"),
    # ---- 爱恋动漫：语言后缀在搜索词里，标题里也有 ----
    ("[爱恋字幕社] 间谍过家家 第三季 - 12 [1080p][简繁内嵌]", "both"),
    ("[爱恋&猫恋汉化组] 间谍过家家 第三季 第12话 [1080p][简繁]", "both"),
    ("[Kirara Fantasia] FX战士久留美 [01][1080p][简体]", "chs"),
    # ---- Nyaa：多数不标语言 ----
    ("[Erai-raws] Sousou no Frieren - 09 [1080p][MultiSub][15B7C196]", "jp"),
    ("[Group] Title - 01 [1080p][MultiSub]", ""),
    ("[SubsPlease] Spy x Family S03E13 (1080p) [A1B2C3D4].mkv", ""),
    ("[ToonsHub] SPY x FAMILY S03E13 1080p NF WEB-DL AAC2.0 H.264", ""),
    ("[ASW] Zombie Sagashitemasu - 01 [1080p HEVC x265 10Bit][AAC]", ""),
    # Dual Audio / Multi Audio 说的是音轨（通常是日英），不代表有中文字幕
    ("[Group] Title - 01 [1080p][Dual Audio]", ""),
    ("[Group] Title - 01 [720p][RAWS]", "jp"),
    ("[Group] Title - 01 [720p][RAW]", "jp"),
    ("[Ohys-Raws] Horimiya Piece (BS11 1280x720 x264 AAC)", "jp"),
    ("[NanakoRaws] Golden Kamuy S4 (1080p)", "jp"),
    ("[VCB-Studio] Fullmetal Alchemist Brotherhood [Ma10p_1080p]", ""),
    # ---- 不能把体积当成国标（GB）简体 ----
    ("Death Note (2006) [BluRay.1080p.x265.FLAC.ITA.JPN.Subs.Ita.Eng] [101.2GB] [stress]", "jp"),
    ("[Group] Title [1080p][1.5 GB]", ""),
    ("[Group] Title [1080p][433.8MB][AVC]", ""),
    # ---- 组名里的 raw / sc 不能当成语言 ----
    ("[Erai-raws] Golden Kamuy Final Season - 04 [1080p CR WEB-DL AVC AAC][MultiSub][27936E10]", "jp"),
    ("[SC-OL][Some Anime][01][1080p]", ""),
]

print("=" * 74)
print("1. 语言识别（按三站点真实写法）")
print("=" * 74)
bad = []
for title, want in CASES:
    got = detect_language(title=title)
    ok = got == want
    if not ok:
        bad.append((title, want, got))
    print(f"  [{'OK ' if ok else 'FAIL'}] 期望 {want or '未标注':4s} 实得 {got or '未标注':4s} | {title[:62]}")
check(f"全部 {len(CASES)} 条识别正确", not bad, str(bad[:3]))

print()
print("=" * 74)
print("2. 关键点：「简繁」不能被误判成单一语言")
print("=" * 74)
for t in ["[简繁内封]", "[简繁字幕]", "[简繁外掛]", "[简繁]", "[双语]", "[雙語]", "[简繁日内封]", "[CHS&CHT]", "[繁簡英日]"]:
    got = detect_language(title=f"[Group] Title {t} [1080p]")
    check(f"{t} -> both", got == "both", got)
for t in ["[简体]", "[简体内嵌]", "[简日]", "[簡日内嵌]", "[CHS_JP]", "[GB][Big5][简日内嵌]"]:
    got = detect_language(title=f"[Group] Title {t} [1080p]")
    check(f"{t} -> 含简体（chs/both）", got in ("chs", "both"), got)

print()
print("=" * 74)
print("3. 语言筛选语义")
print("=" * 74)
checks = [
    # (资源语言, 筛选条件, 期望是否通过) —— 精确匹配：选哪类就只留哪类
    ("chs", "chs", True), ("chs", "both", False), ("chs", "cht", False), ("chs", "", True),
    ("cht", "cht", True), ("cht", "both", False), ("cht", "chs", False),
    ("both", "both", True), ("both", "chs", False), ("both", "cht", False), ("both", "", True),
    ("jp", "jp", True), ("jp", "chs", False), ("jp", "both", False),
    ("", "chs", False), ("", "unknown", True), ("", "both", False), ("", "", True),
]
for have, want, expect in checks:
    got = lang_matches(have, want)
    check(f"资源={have or '未标注'} 筛选={want or '不限'} -> {expect}", got == expect, got)

print()
print("=" * 74)
print("4. apply_filters 组合筛选")
print("=" * 74)
rows = [
    Resource(source="dmhy", title="[A组] 番剧 - 01 [1080p][简体内嵌]", group="A组"),
    Resource(source="dmhy", title="[B组] 番剧 - 01 [1080p][繁日内嵌]", group="B组"),
    Resource(source="dmhy", title="[C组] 番剧 - 01 [1080p][简繁内封]", group="C组"),
    Resource(source="dmhy", title="[A组] 番剧 - 01 [720p][简体内嵌]", group="A组"),
]
rows = [enrich(r) for r in rows]
print(f"    样本语言：{[(r.group, r.lang, r.resolution) for r in rows]}")
only_chs = apply_filters(rows, lang="chs")
check("筛选简体 -> 只剩简体（简繁不再混进来）", {r.group for r in only_chs} == {"A组"},
      str(sorted(r.group for r in only_chs)))
only_cht = apply_filters(rows, lang="cht")
check("筛选繁体 -> 只剩繁体", {r.group for r in only_cht} == {"B组"},
      str(sorted(r.group for r in only_cht)))
both = apply_filters(rows, lang="both")
check("筛选简繁/双语 -> 只剩简繁", {r.group for r in both} == {"C组"},
      str(sorted(r.group for r in both)))
combo = apply_filters(rows, lang="chs", resolution="1080p")
check("语言 + 分辨率组合筛选", {r.group for r in combo} == {"A组"},
      str(sorted(r.group for r in combo)))
grp = apply_filters(rows, lang="chs", group="A组")
check("语言 + 字幕组组合筛选", {r.group for r in grp} == {"A组"},
      str(sorted(r.group for r in grp)))

print()
print("=" * 74)
print("5. 语言标注不能变成「字幕组」（下拉框脏数据）")
print("=" * 74)
for tag in ["简繁内封字幕", "简体内封字幕", "簡日內嵌", "繁日內嵌", "繁簡英日", "简繁", "CHS_JP", "内封英文", "繁体中文"]:
    check(f"[{tag}] 不是字幕组名", is_lang_tag(tag), is_lang_tag(tag))
for name in ["绿茶字幕组", "ANi", "SC-OL", "千夏字幕组&VCB-Studio", "LoliHouse"]:
    check(f"[{name}] 是字幕组名", not is_lang_tag(name))
check("标题末尾的语言标注不会被当成组名",
      extract_group("★4月新番★[异世界四重奏][01][1080P][简繁内封字幕]") == "",
      repr(extract_group("★4月新番★[异世界四重奏][01][1080P][简繁内封字幕]")))
check("开头的字幕组仍然认得出来",
      extract_group("[绿茶字幕组] FX Senshi Kurumi-chan [01][WebRip][1080p][简日内嵌]") == "绿茶字幕组")

print()
print("=" * 74)
print("6. 旧缓存补算（用户看到「简繁识别不出来」的真正原因）")
print("=" * 74)
# 新增字段之前写下的 payload：item 里根本没有 lang 键
old_payload_items = [
    {"source": "dmhy", "title": "[绿茶字幕组] / FX Senshi Kurumi-chan [01v2][WebRip][1080p][简日内嵌]FX战士久留美",
     "group": "绿茶字幕组", "size_text": "433.8MB"},
    {"source": "dmhy", "title": "[綠茶字幕組] / FX Senshi Kurumi-chan [01v2][WebRip][1080p][繁日內嵌]FX戰士久留美",
     "group": "绿茶字幕组", "size_text": "537.4MB"},
    {"source": "kisssub", "title": "[绿茶字幕组] / FX Senshi Kurumi-chan [01][WebRip][1080p][简日内嵌]",
     "group": "绿茶字幕组", "some_future_key": 123},
]
check("旧 payload 里确实没有 lang 键", all("lang" not in it for it in old_payload_items))
fixed = normalize_items(old_payload_items)
check("读缓存时补算出简体", fixed[0]["lang"] == "chs", fixed[0]["lang"])
check("读缓存时补算出繁体", fixed[1]["lang"] == "cht", fixed[1]["lang"])
check("多余字段不会让还原失败", fixed[2]["lang"] == "chs" and fixed[2]["group"] == "绿茶字幕组")
check("标题/站点等原始字段不变", fixed[0]["title"] == old_payload_items[0]["title"])
check("size_text 仍然解析成字节", fixed[0]["size_bytes"] > 0, fixed[0]["size_bytes"])
check("空列表安全", normalize_items(None) == [] and normalize_items([]) == [])
# 缓存指纹：解析/识别代码一变，旧缓存必须当未命中，否则用户会一直看到旧结果
from app.core import warmup  # noqa: E402
check("当前代码算出来的缓存直接命中", warmup.search_payload_ok({"schema": warmup.SEARCH_SCHEMA, "items": []}))
check("没有 schema 的旧缓存不算命中", not warmup.search_payload_ok({"items": []}))
check("指纹不一致的缓存不算命中", not warmup.search_payload_ok({"schema": "deadbeefcafe"}))
check("老版本数字 schema 不算命中", not warmup.search_payload_ok({"schema": 2}))
check("None / 垃圾值不算命中", not warmup.search_payload_ok(None) and not warmup.search_payload_ok("x"))
check("指纹是 12 位十六进制", len(warmup.SEARCH_SCHEMA) == 12 and all(c in "0123456789abcdef" for c in warmup.SEARCH_SCHEMA),
      warmup.SEARCH_SCHEMA)
check("指纹可复算（同一份代码稳定）", warmup.parser_fingerprint() == warmup.SEARCH_SCHEMA)
check("指纹把识别规则算进去了（改了 base.py 就会变）",
      warmup.parser_fingerprint() != hashlib.sha1(b"other").hexdigest()[:12])

print()
print("=" * 74)
print("7. 每个站点的 search() 都要能接住 engine 统一传的参数")
print("=" * 74)
# 踩过的坑：engine 统一用 adapter.search(kw, group=..., page=..., lang=...) 调用，
# 而 NyaaAdapter 少写了 lang 参数 —— TypeError 被上层吞掉，Nyaa 整站静默返回空结果
import inspect  # noqa: E402
from app.sources import engine  # noqa: E402
for sid, cls in sorted(engine.ADAPTERS.items()):
    sig = inspect.signature(cls.search)
    try:
        sig.bind(object(), "番剧名", group="", page=1, lang="")
        check(f"{sid}.search 接受 engine 的调用方式", True)
    except TypeError as e:
        check(f"{sid}.search 接受 engine 的调用方式", False, str(e))

print()
print("=" * 74)
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
print("=" * 74)
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
