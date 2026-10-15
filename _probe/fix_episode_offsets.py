# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
修订阅里的「集号」三件套：episode_offset / 历史记录集号 / last_episode。

为什么需要：连续编号的番（野生的大魔王 13~16 = 本季 1~4、黑色五叶草 171~173 = 本季 1~3），
一旦 offset 被写成 0 或者历史里的集号被别的算法写过一遍，就会出现
「qB 里是 13~16、历史里是 1~12」两套编号对不上，「管理已下载」一条都匹配不到。

做法（只碰集号相关字段，绝不碰字幕组/语言/站点）：
  1. 用历史标题里的**绝对集号** + 总话数，反推本季起点与偏移（复用 core.util.resolve_episode_offset）
  2. 每条历史：episode_absolute = 标题里的编号；episode = 绝对 - 偏移
  3. 同一集号 + 同一标题的重复记录只留最新一条
  4. last_episode = 历史里最大的本季集号

保护：写入前逐条比对 group / sub_group / lang / source_ids / resolution，
只要有任何一条会在写入后变化，整次运行直接中止（不做写入）。

用法：
    python -X utf8 _probe/fix_episode_offsets.py [--data-dir DIR] [--apply]
不带 --apply 只打印预演结果。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


KEEP_FIELDS = ("group", "sub_group", "lang", "source_ids", "resolution", "team_id", "custom_keyword")


def load_subs(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):          # 兼容 {"items": [...]} 的老格式
        return data.get("items") or [], data
    return data or [], data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="", help="只处理名字包含该子串的订阅（逗号分隔可多个）")
    args = ap.parse_args()

    if args.data_dir:
        os.environ["ANIME_DATA_DIR"] = args.data_dir

    from app.core import util              # noqa: E402  必须在设置环境变量之后导入

    data_dir = os.environ.get("ANIME_DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
    subs_path = os.path.join(data_dir, "subscriptions.json")
    subs, wrapped = load_subs(subs_path)

    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]
    changed = 0
    plan = []
    for sub in subs:
        if only and not any(k in (sub.get('name') or '') for k in only):
            continue
        hist = sub.get("history") or []
        if not hist:
            continue
        total = int(sub.get("total_episodes") or 0)
        season = util.season_of(sub.get("name") or "") or util.season_of(sub.get("name_original") or "")
        # 历史标题里的绝对集号
        abs_eps = []
        for h in hist:
            ep = util.parse_episode(h.get("title") or "")
            if ep:
                abs_eps.append(int(ep))
        if not abs_eps:
            continue
        probe = [{"title": h.get("title") or "", "episode": util.parse_episode(h.get("title") or "")}
                 for h in hist]
        offset, base = util.resolve_episode_offset(probe, total, season, sub.get("airdate") or "")
        if not offset or not base:
            continue

        new_hist = []
        seen = set()
        for h in sorted(hist, key=lambda x: -(x.get("time") or 0)):
            abs_ep = util.parse_episode(h.get("title") or "")
            if not abs_ep:
                new_hist.append(h)
                continue
            rel = int(abs_ep) - offset
            if rel < 1:
                continue                    # 上季的，直接不进本季历史
            key = (rel, (h.get("title") or "").strip())
            if key in seen:
                continue                    # 同一集同一发布只留最新
            seen.add(key)
            row = dict(h)
            row["episode_absolute"] = int(abs_ep)
            row["episode"] = rel
            new_hist.append(row)

        new_hist.sort(key=lambda x: -(x.get("time") or 0))
        last_ep = max([h.get("episode") for h in new_hist if isinstance(h.get("episode"), int)] or [0])
        if (sub.get("episode_offset"), sub.get("last_episode"), len(hist)) != (offset, last_ep, len(new_hist)) \
                or any(h.get("episode") is None for h in hist):
            plan.append((sub, offset, base, last_ep, hist, new_hist))

    print("=" * 100)
    print(f"{'番剧':<24}{'旧偏移':>8}{'新偏移':>8}{'旧集号':>26}{'新集号':>22}{'last':>6}")
    print("-" * 100)
    for sub, offset, base, last_ep, hist, new_hist in plan:
        old_eps = ",".join(str(h.get("episode")) for h in hist[:8])
        new_eps = ",".join(str(h.get("episode")) for h in new_hist[:8])
        print(f"{sub.get('name', '')[:22]:<24}{sub.get('episode_offset', 0):>8}{offset:>8}"
              f"  {old_eps[:24]:>24}  {new_eps[:20]:>20}{last_ep:>6}")

    if not args.apply:
        print(f"\n[预演] 需要写入 {len(plan)} 条订阅。加 --apply 才会真正修改。")
        return 0
    if not plan:
        print("\n没有需要修改的订阅。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{subs_path}.before-offsetfix-{stamp}.bak"
    shutil.copy2(subs_path, backup)
    print(f"\n已备份：{backup}")

    for sub, offset, base, last_ep, hist, new_hist in plan:
        before = {k: json.dumps(sub.get(k), ensure_ascii=False, sort_keys=True) for k in KEEP_FIELDS}
        candidate = dict(sub)
        candidate["episode_offset"] = offset
        candidate["last_episode"] = last_ep
        candidate["history"] = new_hist
        after = {k: json.dumps(candidate.get(k), ensure_ascii=False, sort_keys=True) for k in KEEP_FIELDS}
        guard = [k for k in KEEP_FIELDS if before[k] != after[k]]
        if guard:
            print(f"[中止] {sub.get('name')} 的字段会被改动：{guard}（不做任何写入）")
            return 1
        sub.clear()
        sub.update(candidate)
        changed += 1

    payload = {"items": subs} if isinstance(wrapped, dict) else subs
    with open(subs_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[完成] 已更新 {changed} 条订阅（字幕组/语言/站点等字段已逐条校验未变）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
