"""验证：字幕组按资源站分开返回（不再跨站合并同名组）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["ANIME_DATA_DIR"] = tempfile.mkdtemp(prefix="grp-")

from app.core import bangumi, config, logger   # noqa: E402
from app.sources import engine                 # noqa: E402

logger.set_console(False)
config.update({"bangumi_token": os.environ.get("BGM_TOKEN", "")})

SID = 622288   # FX战士久留美
subject = bangumi.get_subject(SID)
print(f"番剧: [{SID}] {subject.display_name}\n")

print("=" * 74)
print("A. by_source=True（默认，用户要求：按资源站分开）")
print("=" * 74)
r = engine.collect_groups(subject, by_source=True)
print(f"  共 {len(r['groups'])} 条（按站点分组）")
by_src = {}
for g in r["groups"]:
    by_src.setdefault(g["source_name"], []).append(g)
for src, items in by_src.items():
    print(f"\n  【{src}】{len(items)} 个字幕组")
    for g in items[:8]:
        tid = f" team_id={g['team_id']}" if g.get("team_id") else ""
        print(f"    {g['name'][:30]:32s} {g['count']:>3} 条  value={g['value'][:44]}{tid}")

print()
print("=" * 74)
print("B. by_source=False（旧行为：跨站合并）")
print("=" * 74)
r2 = engine.collect_groups(subject, by_source=False)
print(f"  共 {len(r2['groups'])} 条（合并）")
for g in r2["groups"][:6]:
    print(f"    {g['name'][:30]:32s} {g['count']:>3} 条  sources={g['sources']}")

print()
print("=" * 74)
print("C. 关键验证：同名组在不同站点是否分开")
print("=" * 74)
name_counts = {}
for g in r["groups"]:
    name_counts.setdefault(g["name"], []).append(g["source_name"])
dupes = {k: v for k, v in name_counts.items() if len(v) > 1}
print(f"  出现在多个站点的同名组：{dupes if dupes else '（本番剧没有重名组）'}")
keys = [g["value"] for g in r["groups"]]
print(f"  value 唯一性: {len(keys)} 条 / 去重后 {len(set(keys))} 条 -> {'OK' if len(keys) == len(set(keys)) else '有重复！'}")
print(f"  所有条目都有 source 字段: {all(g.get('source') for g in r['groups'])}")
print(f"  站点顺序（按配置优先级）: {[s for s in dict.fromkeys(g['source_name'] for g in r['groups'])]}")
