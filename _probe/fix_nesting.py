"""验证：新添加的任务不再多包一层文件夹；并检查已有任务的实际落盘结构。

只做只读检查，不删除任何文件（删除交给用户确认）。
"""
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["ANIME_DATA_DIR"] = tempfile.mkdtemp(prefix="nestcheck-")

from app.core import config, logger, qbittorrent   # noqa: E402

logger.set_console(False)

print("=" * 74)
print("1. 配置与请求参数")
print("=" * 74)
print(f"  config.qbittorrent.create_subfolder = {config.get('qbittorrent.create_subfolder')}")

# 用假的磁力链接探测实际发出的 payload（不真正添加：用不存在的 info hash 让 qB 受理但不下载？
#   —— 不做这种脏操作，改为直接检查函数行为）
import inspect   # noqa: E402
sig = inspect.signature(qbittorrent.add_magnet)
print(f"  add_magnet 默认参数 subfolder = {sig.parameters['subfolder'].default!r}")
src = inspect.getsource(qbittorrent.add_magnet)
line = next(l.strip() for l in src.splitlines() if "contentLayout" in l)
print(f"  payload 逻辑: {line}")

from app.core import watcher   # noqa: E402
wsrc = inspect.getsource(watcher.download_resource)
for l in wsrc.splitlines():
    if "subfolder" in l and "=" in l:
        print(f"  watcher: {l.strip()}")

print()
print("=" * 74)
print("2. 已有任务的实际落盘结构")
print("=" * 74)
ts = qbittorrent.torrents()
mine = [t for t in ts if (t.get("category") or "") == "Bangumi" or "自动追番" in (t.get("tags") or "")]
print(f"  本工具创建的任务：{len(mine)} 个")
for t in mine:
    sp = t.get("save_path") or ""
    cp = t.get("content_path") or ""
    name = (t.get("name") or "").strip()
    print(f"\n  {name[:72]}")
    print(f"    save_path    = {sp}")
    print(f"    content_path = {cp}")
    # 多余嵌套的判定：save_path 下唯一的子目录名 == 种子名（qB 加了 Subfolder 层）
    extra = ""
    if os.path.isdir(sp):
        subs = [d for d in os.listdir(sp) if os.path.isdir(os.path.join(sp, d))]
        files = [f for f in os.listdir(sp) if os.path.isfile(os.path.join(sp, f))]
        same_name = [d for d in subs if d.strip() == name or name.startswith(d.strip())]
        print(f"    子目录 {subs} / 直属文件 {len(files)} 个")
        if same_name and not files:
            extra = os.path.join(sp, same_name[0])
            print(f"    ⚠ 检测到多余嵌套层：{extra}")
        elif files:
            print("    ✓ 文件直接落在番剧目录里（符合预期）")
    if extra:
        keep = input(f"    -> 是否把该目录内的文件上移到 {sp} 并删除空目录？(y/N) ").strip().lower()
        if keep == "y":
            moved = 0
            for entry in os.listdir(extra):
                src = os.path.join(extra, entry)
                dst = os.path.join(sp, entry)
                if os.path.exists(dst):
                    print(f"       跳过（已存在）：{entry}")
                    continue
                shutil.move(src, dst)
                moved += 1
            try:
                os.rmdir(extra)
                print(f"       ✓ 已上移 {moved} 项并删除空目录 {extra}")
            except OSError as e:
                print(f"       ! 目录非空或无法删除：{e}")
        else:
            print("       （未改动；可手动移动，或在 qBittorrent 里删除任务后重新添加）")
