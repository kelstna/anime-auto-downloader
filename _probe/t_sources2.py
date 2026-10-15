"""联调测试 v2：用正在更新的番剧验证搜索解析。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import config, bangumi, logger          # noqa: E402
from app.sources import engine                        # noqa: E402
from app.sources.dmhy import DmhyAdapter              # noqa: E402
from app.sources.kisssub import KisssubAdapter        # noqa: E402
from app.sources.nyaa import NyaaAdapter              # noqa: E402

config.update({"bangumi_token": os.environ.get("BGM_TOKEN", "")})
logger.set_console(False)

print("=== romaji 自检 ===")
from app.sources import romaji  # noqa: E402
for t in ["ゾンビさがしてます", "葬送のフリーレン", "戦車椅子", "カウボーイビバップ",
          "どうも、好きな人に惚れ薬を依頼された魔女です。", "ワンピース", "SPY×FAMILY"]:
    print(f"  {t!r:44s} -> {romaji.romaji_variants(t)}")

subs = bangumi.get_collections()
print(f"\n=== 在看 {len(subs)} 部，寻找有活跃资源的番剧 ===")
for s in subs:
    print(f"  [{s.id}] {s.display_name[:44]:46s} total={s.total_episodes or s.eps}")

# 优先用「尼古喵喵」这类正在播的
cands = [s for s in subs if any(k in (s.name_cn or "") for k in ("尼古喵喵", "僵尸搜寻中", "战车椅子"))]
if not cands:
    cands = subs[:3]

for target in cands[:3]:
    print("\n" + "=" * 78)
    print(f"测试番剧: [{target.id}] {target.display_name}")
    for sid in ("dmhy", "kisssub", "nyaa"):
        print(f"  {sid:8s}: {bangumi.aliases_for_source(target, sid)[:4]}")
    print("=" * 78)

    for cls in (DmhyAdapter, KisssubAdapter, NyaaAdapter):
        ad = cls()
        for kw in bangumi.aliases_for_source(target, ad.id)[:3]:
            t0 = time.time()
            try:
                items = ad.search(kw)
            except Exception as e:
                print(f"  [{ad.id}] {kw!r} 失败 {type(e).__name__}: {e}")
                continue
            print(f"  [{ad.id}] kw={kw!r} -> {len(items)} 条 ({time.time()-t0:.1f}s)")
            for r in items[:4]:
                print(f"     组={r.group!r:20s} {r.resolution:6s} {r.size_text:9s} 种子={r.seeders} "
                      f"集={r.episode}-{r.episode_end} 合集={r.is_batch} 噪声={r.is_noise} team={r.team_id}")
                print(f"       {r.title[:88]}")
                print(f"       magnet={(r.magnet or 'NONE')[:64]}")
            if items:
                break

    t0 = time.time()
    try:
        g = engine.collect_groups(target)
        print(f"\n  字幕组枚举: {len(g['groups'])} 个 ({time.time()-t0:.1f}s)")
        for x in g["groups"][:10]:
            print(f"     {x['name'][:34]:36s} {x['sources']} n={x['count']} team_id={x['team_id']}")
    except Exception as e:
        print("  字幕组枚举失败:", type(e).__name__, e)
