"""直接转储 ui.js 生成的自绘下拉 DOM 结构 + 截图，看清白色箭头方块到底是什么。"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")

JS = r"""
(() => {
  const out = {html: [], sizes: [], big: []};
  // 1) 前几个 .sel 的 outerHTML（截断）
  [...document.querySelectorAll('.sel')].slice(0, 4).forEach((w, i) => {
    out.html.push({i, selId: (w.previousElementSibling || {}).id || '', html: w.outerHTML.slice(0, 700)});
  });
  // 2) 所有 svg 的尺寸与父链
  [...document.querySelectorAll('svg')].forEach((s, i) => {
    const r = s.getBoundingClientRect();
    if (out.sizes.length < 12) {
      let chain = [], p = s.parentElement, n = 0;
      while (p && n++ < 5) { chain.push(p.tagName + (p.className ? '.' + String(p.className).split(' ')[0] : '')); p = p.parentElement; }
      out.sizes.push({i, w: +r.width.toFixed(1), h: +r.height.toFixed(1),
        cls: s.getAttribute('class'), parent: chain.join(' < ')});
    }
  });
  // 3) 找出页面上异常大的浅色块（宽高 > 40 且背景很亮）
  document.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width > 40 && r.height > 40) {
      const cs = getComputedStyle(el);
      const m = cs.backgroundColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (m) {
        const [_, R, G, B] = m.map(Number);
        if (R > 200 && G > 200 && B > 200) {
          out.big.push({tag: el.tagName, cls: String(el.className || '').slice(0, 40),
            w: Math.round(r.width), h: Math.round(r.height), bg: cs.backgroundColor});
        }
      }
    }
  });
  out.big = out.big.slice(0, 10);
  return out;
})()
"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main() -> int:
    port, cdp = free_port(), free_port()
    handler = lambda *a, **kw: Quiet(*a, directory=ROOT, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    profile = os.path.join(tempfile.gettempdir(), f"dump-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--force-device-scale-factor=1", "--window-size=1600,1200",
         f"--user-data-dir={profile}", f"--remote-debugging-port={cdp}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1200, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/_probe/ui_fixture.html"})
        time.sleep(4.0)
        ws.call("Runtime.evaluate", {"expression":
                "(()=>{const c=document.getElementById('only-airing');if(c&&c.checked){c.checked=false;c.dispatchEvent(new Event('change'));}})()"})
        time.sleep(0.5)
        ws.call("Runtime.evaluate", {"expression": "window.__probe.openModal(498378)"})
        time.sleep(2.0)
        ws.call("Runtime.evaluate", {"expression": "window.__probe.switchTab('sub')"})
        time.sleep(1.0)

        d = ws.call("Runtime.evaluate", {"expression": JS, "returnByValue": True})["result"]["value"]
        print("=== .sel 的 outerHTML（前 3 个）===")
        for h in d["html"][:3]:
            print(f"\n--- select#{h['selId']} ---")
            print(h["html"])
        print("\n=== 页面里所有 svg 的尺寸 ===")
        for s in d["sizes"]:
            print(f"  #{s['i']} {s['w']}x{s['h']} cls={s['cls']!r} parent-chain={s['parent']}")
        print("\n=== 异常大的浅色块（白方块嫌疑）===")
        if not d["big"]:
            print("  无")
        for b in d["big"]:
            print(f"  {b['tag']:8s} {b['w']}x{b['h']} bg={b['bg']} cls={b['cls']}")

        shot = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=60)
        p = os.path.join(SHOTS, "11_dump_modal.png")
        open(p, "wb").write(base64.b64decode(shot["data"]))
        print(f"\n截图 -> {p}")
        ws.close()
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:   # noqa: BLE001
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
