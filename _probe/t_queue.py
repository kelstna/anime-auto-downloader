# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
待下载队列端到端验收（qBittorrent 掉线 → 恢复 → 自动补下载）。

模拟用户报的场景：
  ① 番剧更新，qBittorrent 没开 → 下载失败，但资源**不能丢**，要进待下载队列
  ② qBittorrent 仍然没开时手动重试 → 报错但队列保留
  ③ qBittorrent 恢复连接 → 巡检线程（不用重启程序、不用等下一轮追番）自动补下载
  ④ HTTP 接口 /api/queue、/api/queue/flush、/api/queue/delete 行为正确
  ⑤ 补下载后：订阅进度前进、下载历史记一条「恢复补下载」、队列清空

全程用临时数据目录（不碰真实 data/）与假的 qBittorrent 客户端。
"""
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from unittest import mock

DATA = tempfile.mkdtemp(prefix="anime-queue-probe-")
os.environ["ANIME_DATA_DIR"] = DATA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.core import config, pending, qbittorrent, subs, watcher   # noqa: E402
from app.sources.base import Resource                              # noqa: E402
from app.web import server                                         # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post(url, body=None, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def make_sub():
    sub = subs.Subscription(subject_id=910001, name="队列测试番", total_episodes=12, last_episode=2,
                            folder=os.path.join(config.get("download.root"), "队列测试番"),
                            group="ANi", primed=True)
    subs.save_all([sub])
    return sub


def make_res(ep=3):
    tag = ("%040d" % ep)
    return Resource(source="dmhy", source_name="动漫花园", title=f"[ANi] 队列测试番 - {ep:02d} [1080P]",
                    group="ANi", resolution="1080p", size_text="400MB",
                    magnet=f"magnet:?xt=urn:btih:{tag}&dn=x", infohash=tag, episode=ep)


class FakeQB:
    """假 qBittorrent：up=False 时所有请求报「无法连接」，up=True 时正常收下。"""

    def __init__(self):
        self.up = False
        self.added = []

    def install(self):
        def version():
            if not self.up:
                raise qbittorrent.QBError("无法连接 qBittorrent（http://127.0.0.1:8080）："
                                          "<urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>")
            return "v5.2.1"

        def ensure_category(name, save_path=""):
            if not self.up:
                raise qbittorrent.QBError("无法连接 qBittorrent（http://127.0.0.1:8080）")

        def add_magnet(magnet, **kw):
            if not self.up:
                raise qbittorrent.QBError(
                    "无法连接 qBittorrent（http://127.0.0.1:8080）：请求失败 "
                    "http://127.0.0.1:8080/api/v2/torrents/add: <urlopen error [WinError 10061] "
                    "由于目标计算机积极拒绝，无法连接。>")
            self.added.append(magnet)

        patches = [mock.patch.object(qbittorrent, "version", version),
                   mock.patch.object(qbittorrent, "ensure_category", ensure_category),
                   mock.patch.object(qbittorrent, "add_magnet", add_magnet),
                   mock.patch.object(qbittorrent, "login", lambda force=False: True)]
        for p in patches:
            p.start()
        return patches


print("=" * 78)
print("待下载队列端到端验收（临时数据目录）")
print("=" * 78)
print(f"数据目录：{DATA}")

pending.reset_cache()
pending.clear()
subs.save_all([])
sub = make_sub()
fake = FakeQB()
patches = fake.install()
port = free_port()
httpd = server.serve_forever("127.0.0.1", port)
threading.Thread(target=httpd.serve_forever, name="probe-http", daemon=True).start()
time.sleep(0.8)
base = f"http://127.0.0.1:{port}"

try:
    # ---------------------------------------------------------------- ①
    print("\n① 番剧更新，但 qBittorrent 没开 → 下载失败要入队（不能丢）")
    res = make_res(3)
    try:
        watcher.download_resource(sub, res, reason="自动追番")
        check("qB 掉线时下载会抛错", False, "居然成功了？")
    except Exception as e:
        check("qB 掉线时下载会抛错", "无法连接" in str(e), str(e)[:60])
    queued = watcher._queue_failed(sub, res, 3, "无法连接 qBittorrent")
    subs.save_all([sub])
    s = pending.summary()
    print(f"    队列：count={s['count']} subjects={s['subjects']} 最近错误={s['last_error'][:40]}")
    check("失败的那一集进了待下载队列", bool(queued) and s["count"] == 1, f"count={s['count']}")
    check("队列里存的是磁力链（不是重新搜索）", "magnet:?xt=urn:btih:" in pending.items()[0]["magnet"])
    check("界面接口不会泄露磁力链", all("magnet" not in it for it in s["items"]))
    check("订阅进度没有前进（没下成功就不算）", subs.get(910001).last_episode == 2,
          f"last_episode={subs.get(910001).last_episode}")

    # ---------------------------------------------------------------- ②
    print("\n② qBittorrent 仍然没开：手动重试要报错，但队列必须留着")
    code, data = post(base + "/api/queue/flush")
    print(f"    POST /api/queue/flush -> HTTP {code} ok={data.get('ok')} error={str(data.get('error'))[:60]}")
    check("qB 没起来时重试返回失败", data.get("ok") is False and "仍未连接" in (data.get("error") or ""),
          str(data.get("error"))[:70])
    check("重试失败后队列没被清空", pending.count() == 1, f"count={pending.count()}")

    # ---------------------------------------------------------------- ③
    print("\n③ 打开 qBittorrent（恢复连接）→ 巡检线程自动补下载，不用等下一轮追番")
    cfg = config.load()
    cfg.setdefault("queue", {})["retry_seconds"] = 10
    config._cache = cfg
    watcher._stop.clear()
    threading.Thread(target=watcher._pending_loop, name="probe-pending", daemon=True).start()
    fake.up = True                      # 用户打开了 qBittorrent
    started = time.time()
    while time.time() - started < 30 and pending.count():
        time.sleep(0.5)
    waited = time.time() - started
    print(f"    等待 {waited:.1f}s 后：队列剩余 {pending.count()} 条，qB 收到 {len(fake.added)} 个磁力")
    check("qBittorrent 恢复后自动补下载（无需重启程序）", pending.count() == 0 and len(fake.added) == 1,
          f"remaining={pending.count()} added={len(fake.added)}")
    check("补下载很快（巡检间隔 10s 内完成）", waited <= 25, f"{waited:.1f}s")
    cur = subs.get(910001)
    check("订阅进度前进了", cur.last_episode == 3, f"last_episode={cur.last_episode}")
    check("下载历史记了一条「恢复补下载」",
          any(h.get("reason") == "恢复补下载" for h in cur.history), str([h.get("reason") for h in cur.history]))
    st = pending.summary()
    check("恢复时刻/累计补下载数已记录",
          st["recovered_at"] > 0 and st["flushed_total"] >= 1, f"recovered_at={st['recovered_at']:.0f}")
    check("恢复后错误信息清空", st["last_error"] == "", repr(st["last_error"]))

    # ---------------------------------------------------------------- ④
    print("\n④ HTTP 接口：查询 / 删除 / 再补下载")
    watcher._queue_failed(sub, make_res(4), 4, "无法连接 qBittorrent")
    watcher._queue_failed(sub, make_res(5), 5, "无法连接 qBittorrent")
    data = get(base + "/api/queue")
    print(f"    GET /api/queue -> count={data.get('count')} items={[i['episode'] for i in data.get('items', [])]}")
    check("GET /api/queue 列出待下载集数", data.get("count") == 2, f"count={data.get('count')}")
    check("GET /api/queue 带番名与集号",
          all(i.get("name") and i.get("episode") for i in data.get("items", [])), str(data.get("items"))[:90])
    status = get(base + "/api/status")
    check("/api/status 暴露队列数量", (status.get("queue") or {}).get("count") == 2,
          str((status.get("queue") or {}).get("count")))
    subs_payload = get(base + "/api/subscriptions")
    card = (subs_payload.get("items") or [{}])[0]
    check("订阅接口带 pending_count（卡片上能提示）", card.get("pending_count") == 2,
          str(card.get("pending_count")))

    first_id = data["items"][0]["id"]
    code, out = post(base + "/api/queue/delete", {"id": first_id})
    check("POST /api/queue/delete 能删单条", out.get("removed") == 1 and pending.count() == 1,
          f"removed={out.get('removed')} left={pending.count()}")

    code, out = post(base + "/api/queue/flush")
    print(f"    POST /api/queue/flush（qB 已恢复）-> ok={out.get('ok')} flushed={out.get('flushed')}")
    check("qB 在线时补下载返回成功", out.get("ok") is True and out.get("flushed") == 1,
          f"flushed={out.get('flushed')}")
    check("补下载后队列清空", pending.count() == 0, f"count={pending.count()}")

    # ---------------------------------------------------------------- ⑤
    print("\n⑤ 边界：番剧已取消订阅 / 队列关闭")
    watcher._queue_failed(sub, make_res(6), 6, "无法连接 qBittorrent")
    subs.save_all([])                    # 用户取消订阅
    out = watcher.flush_pending()
    check("番剧不在订阅里时这条被丢弃", pending.count() == 0 and out.get("flushed") == 0,
          f"remaining={pending.count()}")
    pending.clear()
finally:
    for p in patches:
        p.stop()
    watcher._stop.set()
    try:
        httpd.shutdown()
    except Exception:   # noqa: BLE001
        pass
    pending.reset_cache()

print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
