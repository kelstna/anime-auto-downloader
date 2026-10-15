"""对真实服务页面截图（用真实 Bangumi 数据），供人工核对视觉。"""
import base64
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

from app.core import logger                              # noqa: E402
from app.web import server                               # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
logger.set_console(False)
PORT = 7851

print(f"资源版本号：{server._ASSET_VERSION}")
httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"real-{int(time.time())}")
proc = subprocess.Popen(
    [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
     "--no-first-run", "--force-device-scale-factor=1", f"--user-data-dir={profile}",
     f"--remote-debugging-port={cdp}", "--window-size=1600,1000", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ev(ws, expr, timeout=120):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                timeout=timeout)
    return r.get("result", {}).get("value")


def shoot(ws, name, full=False):
    r = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": bool(full)}, timeout=90)
    p = os.path.join(SHOTS, f"{name}.png")
    open(p, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {p}")


try:
    wait_cdp(cdp)
    ws = WS(open_page(cdp, "about:blank"))
    ws.call("Runtime.enable")
    ws.call("Page.enable")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    ws.call("Page.navigate", {"url": f"http://127.0.0.1:{PORT}/"})
    # 等真实数据加载完成（36 部 + 详情）
    for _ in range(90):
        if ev(ws, "document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    print(f"  app-ready={ev(ws, 'document.body.classList.contains(\"app-ready\")')} "
          f"卡片={ev(ws, 'document.querySelectorAll(\"#anime-grid .card\").length')}")
    time.sleep(1.0)
    shoot(ws, "20_real_anime")

    # 设置页
    ev(ws, "document.querySelector('.nav-item[data-view=config]').click()")
    time.sleep(1.2)
    shoot(ws, "21_real_settings", full=True)

    # 打开一部番剧的订阅设置，检查下拉
    ev(ws, "(()=>{const c=document.getElementById('only-airing');if(c&&c.checked){c.checked=false;c.dispatchEvent(new Event('change'));}})()")
    time.sleep(0.6)
    ev(ws, "document.querySelector('#anime-grid .card').click()")
    time.sleep(2.5)
    ev(ws, "document.querySelector('#m-tabs .tab[data-tab=sub]').click()")
    time.sleep(1.0)
    ev(ws, "(()=>{const s=document.getElementById('s-group');const w=s.nextElementSibling;"
           "const d=w.querySelector('.sel-display');if(d)d.click();})()")
    time.sleep(0.8)
    shoot(ws, "22_real_dropdown")
    print(f"  下拉面板尺寸：{ev(ws, 'JSON.stringify((()=>{const p=document.querySelector(\".sel-panel:not([hidden])\");if(!p)return null;const r=p.getBoundingClientRect();const s=p.querySelectorAll(\".sel-option\").length;const ch=document.querySelector(\".sel-chevron svg\").getBoundingClientRect();return {panel:Math.round(r.width)+\"x\"+Math.round(r.height),options:s,chevron:Math.round(ch.width)+\"x\"+Math.round(ch.height)};})())')}")
    ws.close()
finally:
    try:
        proc.terminate(); proc.wait(timeout=10)
    except Exception:   # noqa: BLE001
        proc.kill()
    shutil.rmtree(profile, ignore_errors=True)
    httpd.shutdown()
