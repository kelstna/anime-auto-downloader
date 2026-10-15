# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
按「本季第一集的标题编号」重算每条订阅的集号偏移。

规则（用户定）：
    起点 = 本季第一集在资源标题里的编号（如凡人修仙传第五季 = 177）
    偏移 = 起点 - 1
    显示 = 标题里的编号 - 偏移     →  177 显示第 1 集，178 显示第 2 集
    「从 1 开始」的番，起点就是 1，偏移自然是 0，不动。

起点怎么取：把该订阅搜一遍，只在**属于本季**的结果里找最小的标题编号
（标题写明别的季的、以及小到不可能的编号都排除）。

保护：
  - 写入前备份 subscriptions.json
  - 逐条校验 group / sub_group / lang / source_ids / resolution / team_id / custom_keyword 未变，
    任何一条会变就整体中止
用法：
    python -X utf8 _probe/fix_all_offsets.py [--data-dir DIR] [--only A,B] [--apply]
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
    if isinstance(data, dict):
        return data.get("items") or [], True
    return data or [], False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.data_dir:
        os.environ["ANIME_DATA_DIR"] = args.data_dir

    from app.core import logger, subs as subs_store, util
    from app.sources import engine
    from app.core import watcher

    data_dir = os.environ.get("ANIME_DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
    subs_path = os.path.join(data_dir, "subscriptions.json")
    raw, wrapped = load_subs(subs_path)
    only = [x.strip() for x in (args.only or "").split(",") if x.strip()]

    plan = []
    for sub in subs_store.all_subs():
        if only and not any(k in (sub.name or "") for k in only):
            continue
        air_date, total, season = watcher._season_context(sub)
        try:
            outcome = engine.search_by_subject(
                watcher.make_subject(sub), source_ids=sub.source_ids or None,
                group=sub.group or "", group_first=bool(sub.group) or None,
                lang=(sub.lang or ""), keyword=(sub.custom_keyword or ""))
        except Exception as e:                       # noqa: BLE001
            print(f"  [跳过] {sub.display_name}：搜索失败 {e}")
            continue
        items = [r.to_dict() for r in outcome.resources]
        keep, _old_offset, _hidden = util.apply_season_rules(
            items, total_episodes=total, sub_season=season, air_date=air_date)
        eps = []
        for idx in keep:
            ep = items[idx].get("episode")
            if isinstance(ep, int) and ep > 0:
                eps.append(ep)
        if not eps:
            print(f"  [跳过] {sub.display_name}：本季结果里没有可用集号")
            continue
        start = min(eps)
        offset = max(0, start - 1)
        print(f"  {sub.display_name[:22]:<24} 起点={start:<5} 偏移={offset:<5} 总话数={total:<4} 本季命中={len(eps)}")
        plan.append((sub, offset))

    if not args.apply:
        print(f"\n[预演] 将修订 {len(plan)} 条订阅。加 --apply 才会写入。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{subs_path}.before-alloffsets-{stamp}.bak"
    shutil.copy2(subs_path, backup)
    print(f"\n已备份：{backup}")

    changed = 0
    for sub, offset in plan:
        before = {k: json.dumps(getattr(sub, k, None), ensure_ascii=False, sort_keys=True,
                                default=str) for k in KEEP_FIELDS}
        hist_new = []
        for h in (sub.history or []):
            abs_ep = util.parse_episode(h.get("title") or "")
            if not abs_ep:
                hist_new.append(h)
                continue
            rel = int(abs_ep) - offset
            if rel < 1:
                continue
            row = dict(h)
            row["episode_absolute"] = int(abs_ep)
            row["episode"] = rel
            hist_new.append(row)
        last = max([h.get("episode") for h in hist_new if isinstance(h.get("episode"), int)] or [0])
        sub.episode_offset = offset
        sub.last_episode = last or sub.last_episode
        if hist_new:
            sub.history = hist_new
        after = {k: json.dumps(getattr(sub, k, None), ensure_ascii=False, sort_keys=True,
                               default=str) for k in KEEP_FIELDS}
        guard = [k for k in KEEP_FIELDS if before[k] != after[k]]
        if guard:
            print(f"[中止] {sub.display_name} 的字段会被改动：{guard}")
            return 1
        subs_store.upsert(sub)
        changed += 1

    print(f"[完成] 已修订 {changed} 条订阅（字幕组/语言/站点等字段逐条校验未变）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
