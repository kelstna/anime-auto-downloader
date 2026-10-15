# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""强制刷新 Bangumi 元数据（别名 / 首播日 / 总话数），保留章节表与起点集号。

为什么要这个脚本：缓存里的 aliases 是「拉取在看列表」时写的，那时只有番名，没有
infobox 里的「别名」（例如「凡人修仙传 慕兰之战篇」）。季判定靠别名里的篇章名才能认
出「凡人修仙传 慕兰之战 — 16」是第五季的资源，否则会被当成上一季隐藏掉。

用法（**在安装目录里跑**，或指定 --root；读写该目录的 data/）：
    python _probe\\refresh_meta.py
    python _probe\\refresh_meta.py --root E:\\アニメ\\anifetch

会先把 data/bangumi_meta.json 备份成 data/bangumi_meta.json.bak-<时间>，
刷新完对比每个条目的 start_ep / 章节表条数，有丢失会直接列出来。
"""
import argparse
import os
import shutil
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getcwd(), help="安装目录（含 app/ 和 data/）")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if not os.path.isdir(os.path.join(root, "app")):
        print(f"不是安装目录：{root}")
        return 2
    sys.path.insert(0, root)
    os.chdir(root)

    from app.core import bangumi, config, meta, subs

    meta_path = os.path.join(root, "data", "bangumi_meta.json")
    if os.path.exists(meta_path):
        bak = f"{meta_path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(meta_path, bak)
        print(f"备份：{bak}")

    before = meta._load()
    ids = {int(k) for k in before}
    try:
        ids |= {int(s.subject_id) for s in subs.all_subs()}
    except Exception as e:                       # noqa: BLE001
        print(f"读取订阅失败（只刷新缓存里已有的）：{e}")
    ids = sorted(i for i in ids if i)
    print(f"待刷新 {len(ids)} 条番剧元数据")

    token = config.bangumi_token() or None
    rows = []
    for sid in ids:
        old = before.get(str(sid)) or {}
        try:
            subject = bangumi.get_subject(sid, token=token, force=True)
        except Exception as e:                   # noqa: BLE001
            print(f"  {sid} 刷新失败：{e}")
            continue
        new = meta.get(sid) or {}
        rows.append((sid, subject.display_name, len(old.get("aliases") or []),
                     len(new.get("aliases") or []), new.get("start_ep"), new.get("end_ep")))
        time.sleep(0.4)                          # 别把 Bangumi 打限流

    after = meta._load()
    lost = []
    for sid, old in before.items():
        new = after.get(sid) or {}
        if old.get("start_ep") and not new.get("start_ep"):
            lost.append(f"{sid}: start_ep")
        if old.get("eps") and not new.get("eps"):
            lost.append(f"{sid}: 章节表")
    print("\n序号  番剧名                          别名  起点   终点")
    for sid, name, old_n, new_n, se, ee in rows:
        flag = "" if new_n >= old_n else f"  (别名 {old_n}->{new_n})"
        print(f"  {sid}  {name[:24]:24s}  {old_n:>2}->{new_n:<2}  {se}   {ee}{flag}")
    print(f"\n章节表/起点丢失：{lost or '无'}")
    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
