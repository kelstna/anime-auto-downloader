"""验证：网络不通时不会「假死」；代理开启后一切正常。

场景 A 直连（预期现在是超时）→ 拉取应在短时间内返回（熔断生效），而不是卡几分钟
场景 B 代理 7890 → 完整拉取 + 详情补齐
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["ANIME_DATA_DIR"] = tempfile.mkdtemp(prefix="netcheck-")

from app.core import bangumi, cache, config, logger   # noqa: E402

logger.set_console(True)
config.update({"bangumi_token": os.environ.get("BGM_TOKEN", "")})

print("=" * 74)
print("A. 直连（当前网络下会超时）—— 验证熔断让拉取快速返回")
print("=" * 74)
config.update({"proxy": {"enabled": False}})
cache.clear()
t0 = time.time()
try:
    subs = bangumi.get_collections(force=True)
    dt = time.time() - t0
    print(f"  用时 {dt:.1f}s，拿到 {len(subs)} 部")
    with_detail = sum(1 for s in subs if s.eps or s.total_episodes)
    print(f"  其中有话数信息的（说明详情补齐成功）：{with_detail}/{len(subs)}")
    ok = dt < 120
    print(f"  [{'通过' if ok else '失败'}] 熔断生效：没有卡到几分钟（{dt:.1f}s < 120s）")
except Exception as e:
    dt = time.time() - t0
    print(f"  用时 {dt:.1f}s 后抛错：{type(e).__name__}: {e}")
    print(f"  [{'通过' if dt < 120 else '失败'}] 失败也算快速返回（{dt:.1f}s）")

print()
print("=" * 74)
print("B. 启用代理 7890 —— 验证完整链路")
print("=" * 74)
config.update({"proxy": {"enabled": True, "url": "http://127.0.0.1:7890",
                         "for_bangumi": True, "for_sources": True}})
cache.clear()
t0 = time.time()
subs = bangumi.get_collections(force=True)
dt = time.time() - t0
print(f"  用时 {dt:.1f}s，拿到 {len(subs)} 部")
detail_ok = sum(1 for s in subs if s.total_episodes or s.eps)
print(f"  有完整详情的：{detail_ok}/{len(subs)}")
print(f"  [{'通过' if len(subs) >= 30 else '失败'}] 代理下能拉到在看列表（{len(subs)} 部）")
print(f"  [{'通过' if detail_ok >= len(subs) * 0.8 else '失败'}] 详情补齐成功率高（{detail_ok}/{len(subs)}）")
if subs:
    s = subs[0]
    print(f"  示例：[{s.id}] {s.display_name} 话数={s.total_episodes} 别名={len(s.aliases)}")

# 代理 vs 不代理 qBittorrent：qB 必须直连
from app.core import qbittorrent   # noqa: E402
print()
print("=" * 74)
print("C. 代理开启时 qBittorrent 仍必须直连")
print("=" * 74)
info = qbittorrent.test_connection()
print(f"  qB 连接：ok={info.get('ok')} 版本={info.get('version')} 错误={info.get('error', '无')}")
print(f"  [{'通过' if info.get('ok') else '失败'}] 代理开启后 qBittorrent 仍可直连访问")
