# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
UI 改版用的截图脚本（mock 页面，不碰真实数据）。

一次把这几个界面截齐，方便每改一轮都对比同一批画面：
    anime / subs / config / logs / modal-资源 / modal-订阅设置 / 最近更新弹窗 / 浅色主题 / 800px 窄视口

用法：
    python -X utf8 _probe/shoot_design.py [--out _probe/design/after] [--tag 01]
"""
import argparse
import base64
import io
import os
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "_probe"))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("_probe", "design", "after"))
    ap.add_argument("--tag", default="")
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    outdir = os.path.join(ROOT, args.out)
    os.makedirs(outdir, exist_ok=True)

    port = args.port or free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), lambda *a, **kw: Quiet(*a, directory=ROOT, **kw))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/_probe/ui_fixture.html?v={int(time.time())}"

    cdp = free_port()
    import subprocess
    import tempfile
    import shutil
    prof = tempfile.mkdtemp(prefix="design-")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--user-data-dir={prof}", f"--remote-debugging-port={cdp}",
         "--window-size=1600,1000", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def ev(ws, expr, timeout=120):
        r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                    timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(res.get("description"))
        return res.get("value")

    def shot(ws, name, clip=None):
        a = {"format": "png"}
        if clip:
            a["clip"] = clip
        r = ws.call("Page.captureScreenshot", a, timeout=90)
        p = os.path.join(outdir, f"{name}.png")
        open(p, "wb").write(base64.b64decode(r["data"]))
        print(f"  {os.path.relpath(p, ROOT)}")

    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": url})
        for _ in range(60):
            if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
                break
            time.sleep(0.5)
        time.sleep(1.4)
        tag = f"{args.tag}-" if args.tag else ""

        ev(ws, "window.__probe.switchView('anime')")
        time.sleep(0.6)
        shot(ws, f"{tag}01-anime")

        ev(ws, "window.__probe.switchView('subs')")
        time.sleep(0.9)
        shot(ws, f"{tag}02-subs")

        ev(ws, "window.__probe.switchView('config')")
        time.sleep(0.9)
        shot(ws, f"{tag}03-config")

        ev(ws, "window.__probe.switchView('logs')")
        time.sleep(0.9)
        shot(ws, f"{tag}04-logs")

        ev(ws, "window.__probe.switchView('anime')")
        time.sleep(0.5)
        ev(ws, "window.__probe.openModal('498378')")
        time.sleep(1.6)
        shot(ws, f"{tag}05-modal-res")
        ev(ws, "document.querySelector('#m-tabs .tab[data-tab=sub]').click()")
        time.sleep(0.9)
        shot(ws, f"{tag}06-modal-sub")
        ev(ws, "document.getElementById('m-close').click()")
        time.sleep(0.5)

        if ev(ws, "!document.getElementById('side-updates').hidden"):
            ev(ws, "document.getElementById('btn-side-updates').click()")
            time.sleep(0.9)
            shot(ws, f"{tag}07-updates")
            ev(ws, "document.getElementById('updates-close').click()")
            time.sleep(0.4)

        # 浅色主题
        ev(ws, "document.documentElement.dataset.theme='light'")
        time.sleep(0.8)
        shot(ws, f"{tag}08-anime-light")
        ev(ws, "window.__probe.switchView('subs')")
        time.sleep(0.8)
        shot(ws, f"{tag}09-subs-light")
        ev(ws, "document.documentElement.dataset.theme='dark'")
        ev(ws, "window.__probe.switchView('anime')")
        time.sleep(0.6)

        # 800×500 视口（≈ 浏览器 200% 缩放时的重排结果）
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 800, "height": 500, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.9)
        shot(ws, f"{tag}10-anime-800")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.4)
        shot(ws, f"{tag}11-anime-clip", clip={"x": 232, "y": 0, "width": 900, "height": 620, "scale": 1})
        ws.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:   # noqa: BLE001
            proc.kill()
        shutil.rmtree(prof, ignore_errors=True)
        httpd.shutdown()
    print(f"\n截图目录：{os.path.relpath(outdir, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
