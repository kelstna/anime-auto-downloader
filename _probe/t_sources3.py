"""联调 v3：nyaa 罗马字关键词 + 完整调度（含字幕组优先策略）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import config, bangumi, logger          # noqa: E402
from app.sources import engine                        # noqa: E402
from app.sources.nyaa import NyaaAdapter              # noqa: E402
from app.sources.dmhy import DmhyAdapter              # noqa: E402
from app.sources.kisssub import KisssubAdapter        # noqa: E402

config.update({"bangumi_token": os.environ.get("BGM_TOKEN", "")})
logger.set_console(False)

subs = bangumi.get_collections()
by_id = {s.id: s for s in subs}

print("=== 关键词顺序检查（应为拉丁优先 for nyaa）===")
for sid in ("dmhy", "kisssub", "nyaa"):
    for key in (586255, 498378, 568244):
        s = by_id.get(key)
        if s:
            print(f"  [{s.display_name[:20]}] {sid:8s} -> {bangumi.aliases_for_source(s, sid)[:4]}")

print("\n=== nyaa 直连：罗马字 / 英文别名 ===")
ad = NyaaAdapter()
for kw in ["Zonbisagashitemasu", "Zombie Sagashitemasu", "SPY x FAMILY", "Kusuriya no Hitorigoto", "Sousou no Frieren"]:
    try:
        items = ad.search(kw)
        print(f"  {kw!r} -> {len(items)} 条")
        for r in items[:3]:
            print(f"     组={r.group!r:18s} {r.resolution:6s} {r.size_text:9s} 种={r.seeders} 集={r.episode} | {r.title[:70]}")
    except Exception as e:
        print(f"  {kw!r} 失败 {type(e).__name__}: {e}")

print("\n=== 完整调度：僵尸搜寻中（无字幕组）===")
t = by_id[586255]
t0 = time.time()
out = engine.search_by_subject(t)
print(f"策略={out.strategy} 资源={len(out.resources)} 用时={out.elapsed:.1f}s")
print("站点:", {k: v["count"] for k, v in out.source_status.items()})
print("关键词:", out.keywords_used)
for r in out.resources[:10]:
    print(f"   [{r.source_name}] {r.group[:20]:22s} {r.resolution:6s} {r.size_text:9s} 集{r.episode} | {r.title[:60]}")

print("\n=== 带字幕组策略：僵尸搜寻中 + 天月动漫 ===")
out2 = engine.search_by_subject(t, group="天月动漫")
print(f"策略={out2.strategy} 资源={len(out2.resources)} 用时={out2.elapsed:.1f}s")
print("关键词:", out2.keywords_used)
for r in out2.resources[:10]:
    print(f"   [{r.source_name}] {r.group[:20]:22s} {r.resolution:6s} {r.size_text:9s} 集{r.episode} | {r.title[:60]}")

print("\n=== 间谍过家家 第三季（字幕组优先）===")
t2 = by_id.get(498378)
if t2:
    g = engine.collect_groups(t2)
    print(f"字幕组 {len(g['groups'])} 个:", [x["name"] for x in g["groups"][:8]])
    if g["groups"]:
        gn = g["groups"][0]["name"]
        out3 = engine.search_by_subject(t2, group=gn)
        print(f"用字幕组 {gn!r}: 资源={len(out3.resources)} 策略={out3.strategy}")
        for r in out3.resources[:8]:
            print(f"   [{r.source_name}] {r.group[:20]:22s} {r.resolution:6s} {r.size_text:9s} 集{r.episode} | {r.title[:60]}")
