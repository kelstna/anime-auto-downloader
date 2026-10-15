# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
待下载队列的界面验收（mock 页面，不碰真实数据）。

检查点：
  ① 侧栏「待下载」行：qBittorrent 掉线期间攒了 2 集时自动出现，显示集数、悬浮说明列出番名与集号
  ② 订阅卡片上一条提示：「待下载 2 集（第 14 / 15 集）：qBittorrent 恢复后自动补下载」+「立即重试」
  ③ 订阅页汇总条多一个「待下载 2 集」统计 + 「立即补下载 2 集」按钮
  ④ 点侧栏那一行 → 补下载成功 → 提示「已补下载 2 集」、该行自动消失（队列清空）
  ⑤ 布局不溢出

产物：_probe/shots/42_queue_sidebar.png、43_queue_card.png
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_probe"))
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


def ev(ws, expr, timeout=120):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                timeout=timeout)
    res = r.get("result", {})
    if res.get("subtype") == "error":
        raise RuntimeError(res.get("description"))
    return res.get("value")


def shoot(ws, name, clip=None):
    args = {"format": "png"}
    if clip:
        args["clip"] = clip
    p = os.path.join(SHOTS, f"{name}.png")
    r = ws.call("Page.captureScreenshot", args, timeout=90)
    open(p, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {p}")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):   # noqa: D401 - 静音
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", free_port()), lambda *a, **kw: Quiet(*a, directory=ROOT, **kw))
threading_port = httpd.server_address[1]
import threading   # noqa: E402
threading.Thread(target=httpd.serve_forever, daemon=True).start()

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"queueui-{int(time.time())}")
proc = subprocess.Popen(
    [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
     "--no-first-run", "--force-device-scale-factor=1", f"--user-data-dir={profile}",
     f"--remote-debugging-port={cdp}", "--window-size=1600,1000", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    wait_cdp(cdp)
    ws = WS(open_page(cdp, "about:blank"))
    ws.call("Runtime.enable")
    ws.call("Page.enable")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    ws.call("Page.navigate", {"url": f"http://127.0.0.1:{threading_port}/_probe/ui_fixture.html"})
    for _ in range(60):
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    time.sleep(1.2)

    print()
    print("=" * 74)
    print("① 侧栏「待下载」行")
    print("=" * 74)
    info = json.loads(ev(ws, """JSON.stringify((()=>{
      const row = document.getElementById('row-pending');
      return { hidden: !row || row.hidden, text: row ? row.innerText.replace(/\\n/g, ' ') : '',
               title: row ? (row.getAttribute('title') || '') : '',
               dot: (document.getElementById('dot-pending')||{}).className || '',
               overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    })())""") or "{}")
    print(f"    行文本：{info.get('text')!r}")
    print(f"    悬浮：{(info.get('title') or '')[:110]}")
    check("有排队时「待下载」行自动出现", info.get("hidden") is False, str(info.get("hidden")))
    check("显示集数「2 集」", "2 集" in (info.get("text") or ""), repr(info.get("text")))
    check("悬浮说明列出番名与集号", "间谍过家家" in (info.get("title") or "") and "第 14 集" in (info.get("title") or ""),
          (info.get("title") or "")[:80])
    check("用黄色警示点", "dot-warn" in (info.get("dot") or ""), info.get("dot"))
    check("页面没有横向溢出", (info.get("overflowX") or 0) <= 1, f"{info.get('overflowX')}px")
    shoot(ws, "42_queue_sidebar")

    print()
    print("=" * 74)
    print("② 订阅卡片提示 + ③ 汇总条")
    print("=" * 74)
    ev(ws, "document.querySelector('.nav-item[data-view=subs]').click()")
    time.sleep(1.5)
    card = json.loads(ev(ws, """JSON.stringify((()=>{
      const it = document.querySelector('#sub-list .sub-item');
      const hint = it ? it.querySelector('.sub-pending') : null;
      const summary = document.getElementById('sub-summary');
      return { hint: hint ? hint.innerText.replace(/\\n/g, ' ') : '',
               hintTip: hint ? (hint.getAttribute('title') || '') : '',
               summary: summary ? summary.innerText.replace(/\\n/g, ' ') : '',
               buttons: [...(summary ? summary.querySelectorAll('button') : [])].map(b => b.innerText.trim()) };
    })())""") or "{}")
    print(f"    卡片提示：{card.get('hint')!r}")
    print(f"    汇总条：{(card.get('summary') or '')[:120]}")
    check("卡片上有「待下载 N 集」提示", "待下载 2 集" in (card.get("hint") or ""), repr(card.get("hint")))
    check("提示里写了集号与「恢复后自动补下载」",
          "14" in (card.get("hint") or "") and "自动补下载" in (card.get("hint") or ""), repr(card.get("hint")))
    check("卡片提示带「立即重试」按钮", "立即重试" in (card.get("hint") or ""), repr(card.get("hint")))
    check("汇总条显示待下载统计", "待下载" in (card.get("summary") or "") and "2 集" in (card.get("summary") or ""),
          (card.get("summary") or "")[:100])
    check("汇总条有「立即补下载」按钮",
          any("补下载" in b for b in (card.get("buttons") or [])), str(card.get("buttons")))
    shoot(ws, "43_queue_card")

    print()
    print("=" * 74)
    print("④ 点侧栏那一行 → 补下载 → 提示 + 行消失")
    print("=" * 74)
    ev(ws, "document.getElementById('row-pending').click()")
    time.sleep(2.0)
    after = json.loads(ev(ws, """JSON.stringify((()=>{
      const row = document.getElementById('row-pending');
      const toasts = [...document.querySelectorAll('.toast, .toasts .toast, [class*=toast]')]
        .map(n => (n.innerText || '').replace(/\\n/g, ' ').trim()).filter(Boolean);
      const calls = (window.__calls || []).filter(c => c.path.startsWith('/api/queue'));
      return { hidden: !row || row.hidden, toasts, calls: calls.map(c => c.path + ' ' + c.method) };
    })())""") or "{}")
    print(f"    提示：{after.get('toasts')}")
    print(f"    请求：{after.get('calls')}")
    check("点击后调用了 /api/queue/flush", any("flush" in c for c in (after.get("calls") or [])),
          str(after.get("calls")))
    check("有「已补下载 2 集」提示",
          any("补下载" in t and "2" in t for t in (after.get("toasts") or [])), str(after.get("toasts"))[:120])
    check("队列清空后「待下载」行自动消失", after.get("hidden") is True, str(after.get("hidden")))
    shoot(ws, "44_queue_recovered")

    ws.close()
finally:
    try:
        proc.terminate(); proc.wait(timeout=10)
    except Exception:   # noqa: BLE001
        proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    httpd.shutdown()

print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
