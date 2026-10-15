"""一次性数据修正：把订阅里记录错了的「已下载集号」换算成本季集号。

背景：发布组用「系列连续编号」时（药屋少女的呢喃第三季的 49 = 本季第 1 集），
订阅里存的是标题里的编号，订阅卡片就会显示「进度 49 / 12 集」。
现在同一套判断（开播日期 → 季数标记 → 连续编号）会把老数据换算回来，并且可重复执行（幂等）。

只读搜索 + 只改 subscriptions.json（改前自动备份）。用法：
    python _probe\\fix_episode_numbers.py            # 预演，只打印不改
    python _probe\\fix_episode_numbers.py --apply    # 真正写入
"""
import io
import json
import os
import shutil
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.core import subs, watcher                       # noqa: E402
from app.core.util import resolve_episode_offset         # noqa: E402

APPLY = "--apply" in sys.argv
def _history_fix(entry: dict, offset: int, total: int, base: int) -> tuple:
    """
    按标题重新读一次原始集号（和参考项目一样：解析文件名，而不是信旧字段），
    再换算成本季集号。返回 (原始集号, 修正后的集号)；不需要改时第二个值为 None。
    """
    from app.core.util import parse_episode
    title = str(entry.get("title") or "")
    raw = parse_episode(title) or 0
    if not raw:
        raw = int(entry.get("episode") or 0)
    if raw <= 0 or not offset:
        return raw, None
    fixed = raw - offset
    if not (1 <= fixed <= (total or 9999)) or raw == fixed:
        return raw, None
    if entry.get("episode") == fixed:
        return raw, None
    return raw, fixed


subs_list = subs.all_subs(force=True)
if not subs_list:
    print("没有订阅。")
    sys.exit(0)

PLAN = []
for sub in subs_list:
    air_date, total, season = watcher._season_context(sub)
    try:
        outcome = watcher.search_for(sub)
    except Exception as e:                                # noqa: BLE001
        print(f"{sub.display_name}: 搜索失败，跳过（{e}）")
        continue
    # 只看本订阅关心的那个字幕组的结果（自动追番也只从这些里挑）
    rows = [r for r in outcome.resources if not sub.group or r.group == sub.group] or outcome.resources
    offset, base = resolve_episode_offset(rows, total, season, air_date)
    before = int(sub.last_episode or 0)
    after = before
    if offset and base and before >= base:
        after = before - offset
    # 历史记录里的集号也按同一套换算（「管理已下载」列表显示的就是它）
    hist_fix = 0
    for h in (sub.history or []):
        raw_ep, fixed_ep = _history_fix(h, offset, total, base)
        if fixed_ep is not None and fixed_ep != raw_ep:
            hist_fix += 1
    PLAN.append((sub, total, season, offset, base, before, after, hist_fix))

print("=" * 96)
print(f"{'番剧':<26}{'本季':>4}{'话数':>5}{'偏移':>6}{'起点':>6}{'旧集号':>7}{'新集号':>7}   说明")
print("-" * 96)
for sub, total, season, offset, base, before, after, hist_fix in PLAN:
    note = "无需修正" if before == after else f"{before}（标题编号）→ 第 {after} 集"
    if offset == 0:
        note = "没判出连续编号，保持原样"
    elif hist_fix:
        note += f"；历史记录修正 {hist_fix} 条"
    print(f"{sub.display_name[:24]:<26}{season:>4}{total:>5}{offset:>6}{base:>6}{before:>7}{after:>7}   {note}")

changed = [p for p in PLAN if p[5] != p[6] or p[7] or (p[3] and p[0].episode_offset != p[3])]
if not APPLY:
    print()
    print(f"[预演] 需要写入的订阅：{len(changed)} 条。加 --apply 才会真正修改。")
    sys.exit(0)

path = subs._SUBS_PATH
if os.path.exists(path):
    shutil.copyfile(path, path + ".bak")
    print(f"\n已备份：{path}.bak")
for sub, total, season, offset, base, before, after, _hist in PLAN:
    if total and not sub.total_episodes:
        sub.total_episodes = total
    sub.episode_offset = offset
    if before != after:
        sub.last_episode = after
    # 历史记录：episode 换成本季集号，原始编号留在 episode_absolute（可重复执行）
    if offset:
        for h in (sub.history or []):
            _raw, fixed_ep = _history_fix(h, offset, total, base)
            if fixed_ep is None:
                continue
            h.setdefault("episode_absolute", _raw)
            h["episode"] = fixed_ep
subs.save_all(subs_list)
print(f"[完成] 已更新 {len(PLAN)} 条订阅，其中修正集号 {len([p for p in PLAN if p[5] != p[6]])} 条。")
