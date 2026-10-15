"""复现：打开弹窗后，不切任何 tab，「限定字幕组」下拉里应当已经有字幕组。"""
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


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def ev(ws, expr, timeout=60):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                timeout=timeout)
    return r.get("result", {}).get("value")


def main() -> int:
    port, cdp = free_port(), free_port()
    handler = lambda *a, **kw: Quiet(*a, directory=ROOT, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    profile = os.path.join(tempfile.gettempdir(), f"repro-{int(time.time())}")
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
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/_probe/ui_fixture.html"})
        time.sleep(3.5)
        print("appReady:", ev(ws, "document.body.classList.contains('app-ready')"))

        # 关掉「仅显示在播」（间谍过家家在 mock 里算已完结，会被隐藏）
        ev(ws, "(()=>{const c=document.getElementById('only-airing');"
               "if(c&&c.checked){c.checked=false;c.dispatchEvent(new Event('change'));}})()")
        time.sleep(0.6)
        print("可见卡片:", ev(ws, "document.querySelectorAll('#anime-grid .card').length"))

        # 打开弹窗（不切任何 tab）
        opened = ev(ws, "window.__probe.openModal(498378)")
        print("打开弹窗:", opened)
        for wait in (1, 2, 3, 4, 6):
            time.sleep(1.2 if wait == 1 else 1.0)
            n = ev(ws, "document.getElementById('s-group').options.length")
            grp = ev(ws, "document.querySelectorAll('#group-list > *').length")
            print(f"  t≈{wait}s  字幕组下拉选项={n}  字幕组tab卡片={grp}")

        opts = json.loads(ev(ws, "JSON.stringify(window.__probe.options('s-group'))") or "[]")
        print("\n下拉内容:")
        for o in opts:
            print(f"   value={o['v']!r:22s} text={o['t'][:48]}")

        active = ev(ws, "document.querySelector('#m-tabs .tab.is-active')?.dataset.tab")
        print("\n当前激活 tab:", active, "（应保持 res，未切到字幕组页）")
        print("modal.groups 有数据:", ev(ws, "(window.__probe && true) ? "
                                        "(document.querySelectorAll('#group-list > *').length > 0) : false"))
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
