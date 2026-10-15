# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
快速重算集号偏移：**不联网**，只看订阅文件夹里的文件名 + 历史标题里的集号。

规则（用户定）：
    起点 = 该订阅已存在的文件/历史里**最小的标题编号**
    偏移 = 起点 - 1
    显示 = 标题编号 - 偏移     →  15 显示第 1 集，17 显示第 3 集

为什么不用搜索：搜索每条订阅要 5~30 秒，16 条要好几分钟；而文件夹里的文件名
本来就有编号，离线就能算，毫秒级完成。

保护：写入前备份；字幕组/语言/站点等字段逐条校验，任何一条会变就整体中止。
用法：
    python -X utf8 _probe\fix_offsets_fast.py [--data-dir DIR] [--apply]
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
VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm", ".rmvb", ".mov")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="", help="只处理名字包含该子串的订阅")
    args = ap.parse_args()
    if args.data_dir:
        os.environ["ANIME_DATA_DIR"] = args.data_dir

    from app.core import config, subs as subs_store, util

    root = config.get("download.root", "")
    data_dir = os.environ.get("ANIME_DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
    subs_path = os.path.join(data_dir, "subscriptions.json")

    only = [x for x in (args.only or '').split(',') if x.strip()]
    plan = []
    for sub in subs_store.all_subs():
        if only and not any(k in (sub.display_name or '') for k in only):
            continue
        folder = str(getattr(sub, "folder", "") or "")
        folder = folder if os.path.isabs(folder) else os.path.join(root, folder)
        nums = []
        try:
            for name in os.listdir(folder):
                if os.path.splitext(name)[1].lower() not in VIDEO_EXTS:
                    continue
                ep = util.parse_episode(name)
                if ep:
                    nums.append(int(ep))
        except OSError:
            pass
        for h in (sub.history or []):
            ep = util.parse_episode(h.get("title") or "")
            if ep:
                nums.append(int(ep))
        if not nums:
            print(f"  [跳过] {sub.display_name[:20]:<22} 没有可用编号")
            continue
        start = min(nums)
        offset = max(0, start - 1)
        if offset == int(getattr(sub, "episode_offset", 0) or 0):
            print(f"  [不变] {sub.display_name[:20]:<22} 起点={start:<5} 偏移={offset}")
            continue
        print(f"  {sub.display_name[:20]:<22} 起点={start:<5} 偏移 {getattr(sub, 'episode_offset', 0)} → {offset}")
        plan.append((sub, offset))

    if not args.apply:
        print(f"\n[预演] 将修订 {len(plan)} 条。加 --apply 写入。")
        return 0
    if not plan:
        print("\n没有需要修订的订阅。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{subs_path}.before-fastoffset-{stamp}.bak"
    shutil.copy2(subs_path, backup)
    print(f"\n已备份：{backup}")

    changed = 0
    for sub, offset in plan:
        before = {k: json.dumps(getattr(sub, k, None), ensure_ascii=False, sort_keys=True, default=str)
                  for k in KEEP_FIELDS}
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
        if last:
            sub.last_episode = last
        if hist_new:
            sub.history = hist_new
        after = {k: json.dumps(getattr(sub, k, None), ensure_ascii=False, sort_keys=True, default=str)
                 for k in KEEP_FIELDS}
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
