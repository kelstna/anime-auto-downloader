"""诊断自绘下拉的白色箭头方块：量测 .sel-chevron / .sel-display 的实际盒子与继承样式。"""
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

JS = r"""
(() => {
  const out = {items: [], svg: [], inlineSheets: []};
  // 列出内联 <style> 块，看看 fixture/页面里有没有别的东西在干扰
  document.querySelectorAll('style').forEach((s, i) => out.inlineSheets.push(
    {i, len: s.textContent.length, head: s.textContent.trim().slice(0, 120)}));
  const rows = [...document.querySelectorAll('.sel')].slice(0, 6);
  rows.forEach((w, wi) => {
    const d = w.querySelector('.sel-display');
    const c = w.querySelector('.sel-chevron');
    const svg = w.querySelector('.sel-chevron svg');
    const b = el => { const r = el.getBoundingClientRect();
      return {w: +r.width.toFixed(1), h: +r.height.toFixed(1), t: +r.top.toFixed(1), l: +r.left.toFixed(1)}; };
    const cs = el => { const s = getComputedStyle(el); return {
      display: s.display, w: s.width, h: s.height, minW: s.minWidth, minH: s.minHeight,
      maxW: s.maxWidth, maxH: s.maxHeight, flex: s.flex, align: s.alignItems,
      box: s.boxSizing, bg: s.backgroundColor, radius: s.borderRadius, pad: s.padding,
      fontSize: s.fontSize, appearance: s.appearance }; };
    out.items.push({
      i: wi, selId: (w.previousElementSibling || {}).id || '',
      wrap: { box: b(w), css: cs(w) },
      display: d ? { box: b(d), css: cs(d), text: (d.textContent || '').trim().slice(0, 20) } : null,
      chevron: c ? { box: b(c), css: cs(c) } : null,
      svg: svg ? { box: b(svg), css: cs(svg), outer: svg.outerHTML.slice(0, 90) } : null,
    });
  });
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
    profile = os.path.join(tempfile.gettempdir(), f"chev-{int(time.time())}")
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
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/_probe/ui_fixture.html"})
        time.sleep(4.0)
        # 打开弹窗并切到订阅页，让那几个下拉可见
        ws.call("Runtime.evaluate", {"expression":
                "(()=>{const c=document.getElementById('only-airing');if(c&&c.checked){c.checked=false;c.dispatchEvent(new Event('change'));}})()"})
        time.sleep(0.6)
        ws.call("Runtime.evaluate", {"expression": "window.__probe.openModal(498378)"})
        time.sleep(2.0)
        ws.call("Runtime.evaluate", {"expression": "window.__probe.switchTab('sub')"})
        time.sleep(1.0)
        d = ws.call("Runtime.evaluate", {"expression": JS, "returnByValue": True})["result"]["value"]

        print("=== 内联 <style> 块 ===")
        for s in d["inlineSheets"]:
            print(f"  #{s['i']} len={s['len']} {s['head'][:100]!r}")
        print("\n=== 每个自绘下拉的盒子 ===")
        for it in d["items"]:
            print(f"\n  [{it['i']}] select#{it['selId']}")
            for part in ("wrap", "display", "chevron", "svg"):
                v = it.get(part)
                if not v:
                    print(f"    {part:8s} 缺失")
                    continue
                b, c = v["box"], v["css"]
                print(f"    {part:8s} 实测 {b['w']}x{b['h']} @({b['l']},{b['t']})  "
                      f"css={c['w']}x{c['h']} display={c['display']} flex={c['flex']}")
                print(f"             min={c['minW']}/{c['minH']} max={c['maxW']}/{c['maxH']} "
                      f"bg={c['bg']} radius={c['radius']} pad={c['pad']}")
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
