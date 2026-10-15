"""诊断：fixed 布局下表格实际宽度与各列实测宽度；以及 app-ready 标记。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

from app.core import config, logger                       # noqa: E402
from app.web import server                                # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
logger.set_console(False)
PORT = 7861
httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

JS = r"""
(() => {
  const out = {body: document.body.className, table: null, cols: [], act: null, wrap: null};
  const t = document.querySelector('#res-table');
  const w = document.querySelector('.table-wrap');
  if (w) { const r = w.getBoundingClientRect();
    out.wrap = {w: Math.round(r.width), scrollW: w.scrollWidth, clientW: w.clientWidth}; }
  if (t) {
    const tr = t.getBoundingClientRect();
    out.table = {w: Math.round(tr.width), cssW: getComputedStyle(t).width,
                 layout: getComputedStyle(t).tableLayout};
    const ths = [...t.querySelectorAll('thead th')];
    out.cols = ths.map(th => ({cls: th.className, declared: null,
                               actual: Math.round(th.getBoundingClientRect().width)}));
    // 声明宽度
    ths.forEach((th, i) => {
      const cs = getComputedStyle(th);
      out.cols[i].declared = cs.width;
    });
    const act = t.querySelector('tbody td.col-act');
    if (act) {
      const buttons = [...act.querySelectorAll('button')];
      out.act = {w: Math.round(act.getBoundingClientRect().width),
                 need: Math.round(buttons.reduce((a, b) => a + b.getBoundingClientRect().width, 0)
                                  + (buttons.length - 1) * 8),
                 texts: buttons.map(b => b.textContent.trim())};
    }
  }
  out.appReady = document.body.classList.contains('app-ready');
  out.uiReady = document.body.classList.contains('ui-ready');
  out.cards = document.querySelectorAll('#anime-grid .card').length;
  return out;
})()
"""


class Quiet:
    pass


try:
    cdp = free_port()
    profile = os.path.join(tempfile.gettempdir(), f"tbl-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--force-device-scale-factor=1", f"--user-data-dir={profile}",
         f"--remote-debugging-port={cdp}", "--window-size=1600,1100", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_cdp(cdp)
    ws = WS(open_page(cdp, "about:blank"))
    ws.call("Runtime.enable")
    ws.call("Page.enable")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1100, "deviceScaleFactor": 1, "mobile": False})
    ws.call("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
    for _ in range(90):
        v = ws.call("Runtime.evaluate", {"expression": "document.body.classList.contains('app-ready')",
                                         "returnByValue": True})["result"].get("value")
        if v:
            break
        time.sleep(1.0)
    # 打开一部番剧
    ws.call("Runtime.evaluate", {"expression":
            "(()=>{const c=document.getElementById('only-airing');if(c&&c.checked){c.checked=false;c.dispatchEvent(new Event('change'));}})()"})
    time.sleep(0.8)
    ws.call("Runtime.evaluate", {"expression": "document.querySelector('#anime-grid .card').click()"})
    time.sleep(3.0)
    d = ws.call("Runtime.evaluate", {"expression": JS, "returnByValue": True})["result"]["value"]
    print(f"body.class = {d['body']!r}  app-ready={d['appReady']} ui-ready={d['uiReady']} 卡片={d['cards']}")
    print(f"表格容器 .table-wrap = {d['wrap']}")
    print(f"表格 = {d['table']}")
    print("列实测宽度（声明 -> 实际）：")
    for c in d["cols"]:
        print(f"  {c['cls']:18s} {c['declared']:>10s} -> {c['actual']:>5d}px")
    print(f"操作列 = {d['act']}")
    ws.close()
finally:
    try:
        proc.terminate(); proc.wait(timeout=10)
    except Exception:      # noqa: BLE001
        proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    httpd.shutdown()
