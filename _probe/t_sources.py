"""联调测试：三个站点适配器 + 搜索调度（真实网络）。配置写入临时目录。"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP_DATA = tempfile.mkdtemp(prefix="anime-src-")
os.environ["ANIME_DATA_DIR"] = TMP_DATA

from app.core import config, bangumi, logger          # noqa: E402
from app.sources import engine                        # noqa: E402

TOKEN = os.environ.get("BGM_TOKEN", "")
config.update({"bangumi_token": TOKEN})
logger.set_console(False)


def line(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


line("1. Bangumi：token 校验")
me = bangumi.get_me()
print("用户:", me.get("nickname"), "id:", me.get("id"))

line("2. Bangumi：拉取在看番剧")
subs = bangumi.get_collections()
print(f"共 {len(subs)} 部")
for s in subs[:5]:
    print(f"  [{s.id}] {s.display_name} | eps={s.eps} total={s.total_episodes} | date={s.date}")
    print(f"        别名: {s.search_aliases()[:6]}")
    print(f"        cover: {s.cover[:70]}")

target = None
for s in subs:
    if "芙莉莲" in (s.name_cn or "") or "Frieren" in (s.name or ""):
        target = s
        break
if target is None:
    target = subs[0]
print(f"\n选定测试番剧: [{target.id}] {target.display_name}")
print("  aliases:", target.search_aliases())
for sid in ("dmhy", "kisssub", "nyaa"):
    print(f"  {sid:8s} 关键词:", bangumi.aliases_for_source(target, sid)[:4])

line("3. 单站点直连测试")
from app.sources.dmhy import DmhyAdapter      # noqa: E402
from app.sources.kisssub import KisssubAdapter  # noqa: E402
from app.sources.nyaa import NyaaAdapter      # noqa: E402

for cls in (DmhyAdapter, KisssubAdapter, NyaaAdapter):
    ad = cls()
    kws = bangumi.aliases_for_source(target, ad.id)[:2]
    for kw in kws:
        t0 = time.time()
        try:
            items = ad.search(kw)
            print(f"\n[{ad.id}] 关键词={kw!r} -> {len(items)} 条  用时 {time.time()-t0:.1f}s")
            for r in items[:6]:
                print(f"   组={r.group!r:22s} 分辨率={r.resolution:6s} 大小={r.size_text:9s} "
                      f"种子={r.seeders} 集={r.episode} 合集={r.is_batch} 噪声={r.is_noise}")
                print(f"      {r.title[:95]}")
                print(f"      magnet={(r.magnet or '')[:60]}... team_id={getattr(r,'team_id','')}")
            if items:
                break
        except Exception as e:
            print(f"\n[{ad.id}] 关键词={kw!r} 失败: {type(e).__name__}: {e}")

line("4. 字幕组枚举")
try:
    t0 = time.time()
    r = engine.collect_groups(target)
    print(f"{len(r['groups'])} 个字幕组，用时 {time.time()-t0:.1f}s")
    for g in r["groups"][:15]:
        print(f"   {g['name'][:36]:38s} {g['sources']} count={g['count']} team_id={g['team_id']}")
except Exception as e:
    print("失败:", type(e).__name__, e)

line("5. 完整搜索调度（无字幕组）")
try:
    t0 = time.time()
    out = engine.search_by_subject(target)
    print(f"策略={out.strategy} 资源={len(out.resources)} 用时={out.elapsed:.1f}s")
    print("站点状态:", {k: (v['ok'], v['count'], v['error'][:60]) for k, v in out.source_status.items()})
    for r in out.resources[:12]:
        print(f"   [{r.source_name}] {r.group[:20]:22s} {r.resolution:6s} {r.size_text:9s} 集{r.episode} | {r.title[:70]}")
except Exception as e:
    import traceback
    traceback.print_exc()

line("6. 带字幕组搜索（自动解析 team_id）")
try:
    gname = None
    for g in r["groups"]:
        if g["team_id"]:
            gname = g["name"]
            break
    if gname:
        t0 = time.time()
        out2 = engine.search_by_subject(target, group=gname)
        print(f"字幕组={gname} 策略={out2.strategy} 资源={len(out2.resources)} 用时={out2.elapsed:.1f}s")
        for x in out2.resources[:10]:
            print(f"   [{x.source_name}] {x.group[:22]:24s} {x.resolution:6s} {x.size_text:9s} 集{x.episode} | {x.title[:65]}")
    else:
        print("未从搜索结果中解析到 team_id")
except Exception as e:
    import traceback
    traceback.print_exc()
