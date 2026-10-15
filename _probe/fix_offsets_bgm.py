# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
用 **Bangumi 的章节表** 重算每条订阅的集号偏移。

原理：
    Bangumi 章节接口里
        sort = 系列累计编号（凡人第五季 = 177…228）  ← 发布组标题用的就是它
        ep   = 本季序号（1…52）
    所以    偏移 = sort(第一集) - 1      例：177 - 1 = 176
    显示    第几集 = 标题编号 - 偏移      例：196 - 176 = 第 20 集

这一版**不再看资源标题**，完全由 Bangumi 数据决定；资源标题只在算区间时用到。

用法：
    python -X utf8 _probe\fix_offsets_bgm.py [--data-dir DIR] [--only A,B] [--apply]
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.data_dir:
        os.environ["ANIME_DATA_DIR"] = args.data_dir

    from app.core import config, meta, subs as subs_store, util

    data_dir = os.environ.get("ANIME_DATA_DIR") or os.path.join(os.path.dirname(__file__), "..", "data")
    subs_path = os.path.join(data_dir, "subscriptions.json")
    token = config.bangumi_token()
    only = [x for x in (args.only or "").split(",") if x.strip()]

    plan = []
    for sub in subs_store.all_subs():
        if only and not any(k in (sub.display_name or "") for k in only):
            continue
        item = meta.get(sub.subject_id)
        start = (item or {}).get("start_ep")
        if not start:
            try:
                eps = meta.fetch_episodes(sub.subject_id, token=token)
                start = eps[0]["sort"] if eps else None
            except Exception as e:                      # noqa: BLE001
                print(f"  [跳过] {sub.display_name[:20]}：拉章节失败 {e}")
                continue
        if not start:
            print(f"  [跳过] {sub.display_name[:20]}：Bangumi 没有章节数据")
            continue
        offset = max(0, int(start) - 1)
        status = "不变" if offset == int(sub.episode_offset or 0) else f"{sub.episode_offset} → {offset}"
        print(f"  {sub.display_name[:22]:<24} BGM 起点={start:<5} 偏移 {status}")
        if offset != int(sub.episode_offset or 0):
            plan.append((sub, offset))

    if not args.apply:
        print(f"\n[预演] 将修订 {len(plan)} 条。加 --apply 写入。")
        return 0
    if not plan:
        print("\n没有需要修订的订阅。")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{subs_path}.before-bgmoffset-{stamp}.bak"
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
