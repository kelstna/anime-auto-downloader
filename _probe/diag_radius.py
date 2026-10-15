"""量测：哪些元素是直角（border-radius 0）或圆角过小；控件间距是否过窄。"""
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
  const out = { zero: [], small: [], gaps: {}, viewport: null };
  const seen = new Set();
  document.querySelectorAll('*').forEach(el => {
    if (!el.offsetParent && el.tagName !== 'BODY') return;
    const cs = getComputedStyle(el);
    const r = cs.borderTopLeftRadius;
    const w = el.getBoundingClientRect().width, h = el.getBoundingClientRect().height;
    if (w < 6 || h < 6) return;
    const key = el.tagName + '.' + (el.className || '') + '|' + r;
    if (seen.has(key)) return;
    seen.add(key);
    const px = parseFloat(r) || 0;
    const item = { tag: el.tagName, cls: String(el.className || '').slice(0, 42),
                   radius: r, w: Math.round(w), h: Math.round(h),
                   bg: cs.backgroundColor };
    // 只关心有可见背景/边框的块
    const visible = cs.backgroundColor !== 'rgba(0, 0, 0, 0)' || parseFloat(cs.borderTopWidth) > 0;
    if (!visible) return;
    if (px === 0) out.zero.push(item);
    else if (px < 6) out.small.push(item);
  });
  const box = el => el ? el.getBoundingClientRect() : null;
  const gapBetween = (a, b) => {
    const A = box(a), B = box(b);
    return (A && B) ? { v: Math.round(B.top - A.bottom), h: Math.round(B.left - A.right) } : null;
  };
  const q = s => document.querySelector(s);
  out.gaps = {
    表单行间距: (() => {
      const cells = [...document.querySelectorAll('#view-config .form-cell')].filter(c => c.offsetParent);
      if (cells.length < 3) return null;
      const g = Math.round(box(cells[1]).top - box(cells[0]).bottom);
      const g2 = Math.round(box(cells[2]).top - box(cells[1]).bottom);
      return { rowGap: g, rowGap2: g2 };
    })(),
    标签到控件: (() => {
      const c = [...document.querySelectorAll('#view-config .form-cell')].find(x => x.offsetParent);
      if (!c) return null;
      const lab = c.querySelector('label'), ctl = c.querySelector('input, select');
      return lab && ctl ? Math.round(box(ctl).top - box(lab).bottom) : null;
    })(),
    面板间距: (() => {
      const ps = [...document.querySelectorAll('#view-config .panel')].filter(p => p.offsetParent);
      const g = [];
      for (let i = 1; i < Math.min(ps.length, 4); i++) g.push(Math.round(box(ps[i]).top - box(ps[i - 1]).bottom));
      return g;
    })(),
    弹窗按钮间距: (() => {
      const a = q('#btn-sub-add'), b = q('#btn-goto-res');
      return (a && b && a.offsetParent) ? Math.round(box(b).left - box(a).right) : null;
    })(),
    弹窗标签到控件: (() => {
      const c = [...document.querySelectorAll('#tab-sub .form-cell')].find(x => x.offsetParent);
      if (!c) return null;
      const lab = c.querySelector('label'), ctl = c.querySelector('select, input');
      return lab && ctl ? Math.round(box(ctl).top - box(lab).bottom) : null;
    })(),
    控件高度: [...new Set([...document.querySelectorAll('.form-cell > input, .form-cell > select')]
      .filter(e => e.offsetParent).map(e => Math.round(box(e).height)))],
  };
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
    profile = os.path.join(tempfile.gettempdir(), f"rad-{int(time.time())}")
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
        time.sleep(1.6)
        d = ws.call("Runtime.evaluate", {"expression": JS, "returnByValue": True})["result"]["value"]
        print("=== 直角元素（border-radius: 0，且有可见背景/边框）===")
        real = []
        for it in d["zero"]:
            if it["tag"] == "BODY":
                continue
            # 表格 th/td、卡片内部块等由带圆角的父容器裁剪，视觉上是圆角，不算直角
            if it["tag"] in ("TH", "TD") or it["cls"].split(" ")[0] in (
                    "card-meta", "card-body", "card-title", "card-sub", "sub-actions",
                    "sub-item-actions", "sub-facts", "sub-meta", "filters", "toolbar"):
                continue
            real.append(it)
        if not real:
            print("  无（表格单元格等由圆角父容器裁剪，视觉上已是圆角）")
        for it in real[:25]:
            print(f"  {it['tag']:8s} r={it['radius']:6s} {it['w']}x{it['h']:<5} bg={it['bg']:22s} {it['cls']}")
        d["realZero"] = real
        print(f"\n=== 小圆角（<6px）{len(d['small'])} 个 ===")
        for it in d["small"][:20]:
            print(f"  {it['tag']:8s} r={it['radius']:6s} {it['w']}x{it['h']:<5} {it['cls']}")
        print("\n=== 间距量测（px）===")
        for k, v in (d.get("gaps") or {}).items():
            print(f"  {k}: {v}")
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
