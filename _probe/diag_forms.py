"""诊断：为什么某些控件不是 36px？直接看实际生效的 CSS 规则来源。"""
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


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


JS = r"""
(() => {
  const out = {sheets: [], items: [], dumps: [], matches: {}};
  for (const s of document.styleSheets) {
    let n = 0;
    try { n = s.cssRules.length; } catch (e) { n = -1; }
    out.sheets.push({href: s.href ? s.href.split('/').pop() : '(inline)', rules: n});
  }
  // 转储样式表里与 input/select 相关的选择器文本
  for (const s of document.styleSheets) {
    let rules = [];
    try { rules = [...s.cssRules]; } catch (e) { continue; }
    rules.forEach((r, i) => {
      if (r.selectorText && /input|select|textarea/.test(r.selectorText)) {
        out.dumps.push({sheet: s.href ? s.href.split('/').pop() : '(inline)', i,
                        sel: r.selectorText, css: r.style.cssText.slice(0, 120)});
      }
    });
  }
  // 我们的选择器是否匹配这些元素？
  const sel = 'input[type="text"], input[type="password"], input[type="number"], input[type="search"], select, textarea, .input';
  ['#s-folder', '#cfg-qb-url', '#s-total', '#s-group', '#anime-filter'].forEach(q => {
    const el = document.querySelector(q);
    out.matches[q] = el ? {
      matches: el.matches(sel),
      matchesText: el.matches('input[type="text"]'),
      outer: el.outerHTML.slice(0, 120),
      attrs: [...el.attributes].map(a => a.name + '=' + a.value),
    } : null;
  });
  const probes = [
    ['#s-total', 'number in modal'], ['#cfg-sub-interval', 'number in config'],
    ['#s-folder', 'text in modal'], ['#s-group', 'select in modal'],
    ['#cfg-qb-url', 'text in config'], ['#anime-filter', 'search in toolbar'],
  ];
  probes.forEach(([q, label]) => {
    const el = document.querySelector(q);
    if (!el) { out.items.push({q, label, missing: true}); return; }
    const cs = getComputedStyle(el);
    const b = el.getBoundingClientRect();
    out.items.push({q, label, tag: el.tagName, h: +b.height.toFixed(2),
      cssH: cs.height, pad: cs.padding, border: cs.borderWidth,
      fontSize: cs.fontSize, radius: cs.borderRadius, all: cs.all});
  });
  return out;
})()
"""


def main() -> int:
    port, cdp = free_port(), free_port()
    handler = lambda *a, **kw: Quiet(*a, directory=ROOT, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    profile = os.path.join(tempfile.gettempdir(), f"diag-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--force-device-scale-factor=1", "--window-size=1600,1200",
         f"--user-data-dir={profile}", f"--remote-debugging-port={cdp}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, f"http://127.0.0.1:{port}/_probe/ui_components.html"))
        ws.call("Runtime.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1200, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1.5)
        d = ws.call("Runtime.evaluate", {"expression": JS, "returnByValue": True})["result"]["value"]
        print("=== 已加载样式表 ===")
        for s in d["sheets"]:
            print(f"  {s['href']:20s} rules={s['rules']}")
        print("\n=== 样式表里与 input/select 相关的规则 ===")
        for r in d["dumps"]:
            print(f"  [{r['sheet']}#{r['i']}] {r['sel'][:110]}")
            print(f"        {r['css']}")
        print("\n=== 选择器匹配情况 ===")
        for q, v in d["matches"].items():
            print(f"  {q}: matches(整串)={v['matches'] if v else '-'} matches('input[type=\"text\"]')={v['matchesText'] if v else '-'}")
            if v:
                print(f"      attrs={v['attrs']}")
        print("\n=== 控件实际计算样式 ===")
        for it in d["items"]:
            if it.get("missing"):
                print(f"  {it['q']} 不存在")
                continue
            print(f"  {it['q']:20s} {it['tag']:6s} h={it['h']:6.2f} cssH={it['cssH']:8s} "
                  f"pad={it['pad']:14s} border={it['border']:5s} fs={it['fontSize']:5s} r={it['radius']}")

        # 用 CDP CSS 域拿到「实际匹配到的规则」
        print("\n=== CDP: #s-folder / #s-total 实际匹配的规则 ===")
        ws.call("DOM.enable")
        ws.call("CSS.enable")
        doc = ws.call("DOM.getDocument", {"depth": -1})
        root_id = doc["root"]["nodeId"]
        for sel in ("#s-folder", "#s-total", "#anime-filter"):
            node = ws.call("DOM.querySelector", {"nodeId": root_id, "selector": sel})
            nid = node.get("nodeId")
            if not nid:
                print(f"  {sel}: 未找到节点")
                continue
            ms = ws.call("CSS.getMatchedStylesForNode", {"nodeId": nid})
            print(f"\n  --- {sel} 匹配到的规则（按层叠顺序）---")
            for m in ms.get("matchedCSSRules", []):
                rule = m.get("rule", {})
                sel_txt = rule.get("selectorList", {}).get("text", "")
                style = rule.get("style", {})
                props = [f"{p['name']}:{p['value']}" for p in style.get("cssProperties", [])
                         if p["name"] in ("height", "padding", "font-size", "border-radius", "border")]
                origin = rule.get("origin", "")
                print(f"    {sel_txt[:70]:72s} {';'.join(props)[:90]}")
            inline = ms.get("inlineStyle")
            if inline and inline.get("cssProperties"):
                print("    [inline]", [f"{p['name']}:{p['value']}" for p in inline["cssProperties"]])
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
