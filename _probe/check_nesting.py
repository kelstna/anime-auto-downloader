"""查看本工具创建的 qBittorrent 任务的实际落盘结构（确认多余文件夹层）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.core import qbittorrent   # noqa: E402

print("=== 分类 / 标签 ===")
cats = qbittorrent.categories()
print("  已定义分类:", list(cats.keys()))
for k, v in cats.items():
    print(f"    {k}: savePath={v.get('savePath')!r}")

ts = qbittorrent.torrents()
mine = [t for t in ts if (t.get("category") or "") == "Bangumi" or "自动追番" in (t.get("tags") or "")]
print(f"\n=== 本工具创建的任务：{len(mine)} 个（qB 总任务 {len(ts)}）===")
for t in mine:
    print(f"\n  [{t.get('state')}] {round(float(t.get('progress') or 0)*100,1)}%  {t.get('name')[:70]}")
    print(f"    save_path    = {t.get('save_path')}")
    print(f"    content_path = {t.get('content_path')}")
    print(f"    category={t.get('category')!r} tags={t.get('tags')!r}")
    # 检查落盘结构：save_path 下是否多了一层与种子同名的文件夹
    sp = t.get("save_path") or ""
    if os.path.isdir(sp):
        try:
            sub = [d for d in os.listdir(sp) if os.path.isdir(os.path.join(sp, d))]
            files = [f for f in os.listdir(sp) if os.path.isfile(os.path.join(sp, f))]
            print(f"    子目录: {sub[:3]}")
            print(f"    直接文件: {len(files)} 个")
        except OSError as e:
            print(f"    读取失败: {e}")
    else:
        print("    目录不存在（尚未开始下载或已移动）")

print("\n=== 当前 create_subfolder 配置 ===")
from app.core import config   # noqa: E402
print("  config.create_subfolder =", config.get("qbittorrent.create_subfolder"))

print("\n=== 发一个 add 请求看 qB 收到的参数（干跑：不发真实磁链）===")
print("  add_magnet 里的 contentLayout 逻辑:")
import inspect   # noqa: E402
src = inspect.getsource(qbittorrent.add_magnet)
for line in src.splitlines():
    if "contentLayout" in line or "subfolder" in line:
        print("   ", line.strip())
