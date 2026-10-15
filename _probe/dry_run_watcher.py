"""只读预演：真实订阅在「自动追番」这一步会挑哪一集（绝不下载、绝不改动订阅文件）。

用法：python _probe\\dry_run_watcher.py
它只做「搜索 → 候选筛选 → 挑最优」，不会调用 download_resource / check_subscription。
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core import subs, watcher                       # noqa: E402
from app.core.util import resolve_episode_offset, season_of  # noqa: E402

subs_list = subs.all_subs(force=True)
if not subs_list:
    print("没有订阅，无需预演。")
    sys.exit(0)

for sub in subs_list:
    print("=" * 78)
    print(f"订阅：{sub.display_name}（subject {sub.subject_id}）")
    print(f"  组={sub.group or '不限'} 分辨率={sub.resolution or '不限'} "
          f"总话数={sub.total_episodes} 已下载到第 {sub.last_episode} 集 "
          f"已下载 {len(sub.downloaded)} 条 首次检查完成={sub.primed} "
          f"自定义搜索词={sub.custom_keyword or '无'}")
    try:
        outcome = watcher.search_for(sub)
    except Exception as e:                                # noqa: BLE001
        print(f"  搜索失败：{e}")
        continue
    season = season_of(sub.display_name) or season_of(sub.name_original)
    offset, season_min = resolve_episode_offset(outcome.resources, sub.total_episodes, season)
    print(f"  搜到 {len(outcome.resources)} 条 | 本季={season or '未标注'} | "
          f"连续编号换算：偏移={offset} 本季起点={season_min or '未判定'}")
    candidates = watcher._new_candidates(sub, outcome)
    buckets = watcher._group_by_episode(candidates)
    print(f"  候选 {len(candidates)} 条，覆盖集号 {sorted(buckets)[:12]}{' …' if len(buckets) > 12 else ''}")
    for ep in sorted(buckets)[:6]:
        best = watcher.pick_best(buckets[ep], sub.resolution or "1080p")
        if best is None:
            continue
        print(f"    第 {ep} 集 -> [{best.group or best.source_name}] {best.title[:78]}")
    early = [r.title for r in candidates
             if season_min and (watcher.episode_of(r) or 0) < season_min]
    print(f"  更早季的候选（应为 0）：{len(early)}")
    if early:
        print("   ", early[:3])
print()
print("（只读预演结束：没有下载任何东西，也没有改动 data/subscriptions.json）")
