"""诊断筛选条标签换行：量测 .filter > span 的实际宽度与计算样式。"""
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
  const out = {rules: [], filters: [], bar: null};
  // 1) 样式表里与 .filter / .filters 相关的规则
  for (const s of document.styleSheets) {
    let rules = [];
    try { rules = [...s.cssRules]; } catch (e) { continue; }
    rules.forEach((r, i) => {
      if (r.selectorText && /(^|,)\s*\.filters?[\s,>{:]/.test(r.selectorText)) {
        out.rules.push({sheet: (s.href || 'inline').split('/').pop(), i,
                        sel: r.selectorText, css: r.style.cssText.slice(0, 160)});
      }
    });
  }
  // 2) 每个筛选标签
  const bar = document.querySelector('#tab-res .filters');
  out.bar = bar ? (() => { const b = bar.getBoundingClientRect();
    return {w: Math.round(b.width), h: Math.round(b.height), display: getComputedStyle(bar).display,
            wrap: getComputedStyle(bar).flexWrap}; })() : null;
  [...document.querySelectorAll('#tab-res .filter')].forEach((f, i) => {
    const sp = f.querySelector(':scope > span');
    const sel = f.querySelector('.sel, select');
    const cs = sp ? getComputedStyle(sp) : null;
    out.filters.push({
      i,
      label: sp ? sp.textContent.trim() : '(无 span)',
      spanW: sp ? +sp.getBoundingClientRect().width.toFixed(1) : null,
      spanH: sp ? +sp.getBoundingClientRect().height.toFixed(1) : null,
      lines: sp ? Math.round(sp.getBoundingClientRect().height / parseFloat(cs.lineHeight || '16')) : null,
      whiteSpace: cs ? cs.whiteSpace : null,
      wordBreak: cs ? cs.wordBreak : null,
      minW: cs ? cs.minWidth : null,
      flex: cs ? cs.flex : null,
      selW: sel ? +sel.getBoundingClientRect().width.toFixed(1) : null,
      filterW: +f.getBoundingClientRect().width.toFixed(1),
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
    profile = os.path.join(tempfile.gettempdir(), f"wrap-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--force-device-scale-factor=1", "--window-size=1600,1000",
         f"--user-data-dir={profile}", f"--remote-debugging-port={cdp}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/_probe/ui_fixture.html"})
        time.sleep(4.0)
        ev = lambda e: ws.call("Runtime.evaluate", {"expression": e, "returnByValue": True})["result"].get("value")
        ev("(()=>{const c=document.getElementById('only-airing');if(c&&c.checked){c.checked=false;c.dispatchEvent(new Event('change'));}})()")
        time.sleep(0.5)
        ev("window.__probe.openModal(498378)")
        time.sleep(2.5)
        d = json.loads(ev(f"JSON.stringify({JS})") or "{}")

        print("=== 样式表里 .filter/.filters 相关规则 ===")
        for r in d.get("rules", []):
            print(f"  [{r['sheet']}#{r['i']}] {r['sel']}")
            print(f"        {r['css']}")
        print(f"\n=== 筛选条 ===\n  {d.get('bar')}")
        print("\n=== 各筛选标签 ===")
        for f in d.get("filters", []):
            print(f"  [{f['i']}] {f['label']!r}: span {f['spanW']}x{f['spanH']} "
                  f"折行数≈{f['lines']} white-space={f['whiteSpace']} word-break={f['wordBreak']} "
                  f"min-w={f['minW']} flex={f['flex']}")
            print(f"       下拉宽 {f['selW']} / 整组宽 {f['filterW']}")
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
