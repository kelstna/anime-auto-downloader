"""解析与排序逻辑自测（离线）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sources.base import (Resource, normalize_resolution, resolution_matches,
                              sort_resources, dedupe, apply_filters, extract_group, enrich)
from app.sources import engine
from app.core import watcher

print("=== 分辨率归一化 ===")
for x in ["4K", "1080", "1080p", "720P", "2160P", "", "abc"]:
    print(f"  {x!r:8s} -> {normalize_resolution(x)!r}")
print("  匹配测试:", resolution_matches("1080p", "1080p"), resolution_matches("2160p", "1080p"),
      resolution_matches("", "1080p"), resolution_matches("1080p", ""))

print("\n=== 排序（优先分辨率 -> 做种 -> 站点顺序）===")
rs = [
    Resource(source="dmhy", title="A", resolution="1080p", seeders=1, magnet="magnet:?xt=urn:btih:A"),
    Resource(source="nyaa", title="B", resolution="1080p", seeders=99, magnet="magnet:?xt=urn:btih:B"),
    Resource(source="dmhy", title="C", resolution="2160p", seeders=500, magnet="magnet:?xt=urn:btih:C"),
    Resource(source="kisssub", title="D", resolution="1080p", seeders=50, magnet="magnet:?xt=urn:btih:D"),
]
for r in sort_resources(rs, "1080p"):
    print(f"  {r.source:8s} {r.resolution:6s} 种={r.seeders} {r.title}")
print("  pick_best ->", watcher.pick_best(rs, "1080p").title)

print("\n=== 剧集编号解析 ===")
titles = [
    "[Skymoon-Raws] - 01 [CHS][AVC AAC]僵屍搜尋中",
    "[SubsPlease] Zombie Sagashitemasu - 01 (1080p) [15F667B4].mkv",
    "[桜都字幕组] / Spy x Family (2025) [13][1080p][简体内嵌]间谍过家家第三季",
    "[7³ACG] 葬送的芙莉莲/Sousou no Frieren S01 | 01-28+SPx11 [简繁字幕] BDrip 1080p",
    "[Group] Title 第09话 [1080p]",
    "[Group] Title S02E05 [1080p]",
    "[Group] Title - 12v2 [1080p]",
    "[VCB-Studio] Fullmetal Alchemist Brotherhood [Ma10p_1080p]",
]
for t in titles:
    r = enrich(Resource(source="t", title=t))
    print(f"  集={str(r.episode):>4s} 区间={r.episode_end} 合集={str(r.is_batch):5s} "
          f"噪声={str(r.is_noise):5s} 组={r.group!r:16s} 分辨率={r.resolution or '-':6s} | {t[:52]}")

print("\n=== 字幕组提取 ===")
for t in ["[Erai-raws] Sousou no Frieren - 09 [1080p][MultiSub][15B7C196]",
          "SPY x FAMILY S03E13 1080p NF WEB-DL AAC2.0 H.264",
          "[7³ACG] 葬送的芙莉莲 [简繁字幕] BDrip 1080p",
          "标题 [Ma10p_1080p]",
          "标题 [15B7C196]"]:
    print(f"  {extract_group(t)!r:22s} <- {t[:60]}")

print("\n=== 跨站去重 ===")
a = Resource(source="dmhy", title="X", infohash="abc123")
b = Resource(source="kisssub", title="X2", infohash="abc123")
c = Resource(source="nyaa", title="X3", infohash="def456")
print("  去重后:", [(r.source, r.infohash) for r in dedupe([a, b, c])])

print("\n=== 字幕组匹配 ===")
for g, want in [("天月動漫&發佈組", "天月动漫"), ("桜都字幕组", "桜都字幕组"),
                ("SubsPlease", "subsplease"), ("", "abc"), ("ABC", "")]:
    print(f"  {g!r:20s} vs {want!r:16s} -> {engine._group_match(g, want)}")

print("\n=== 关键词过滤 ===")
print(" ", engine.usable_keywords(["僵尸搜寻中", "#ゾンビさがしてます", "a", "", "SPY x FAMILY"], 4))
