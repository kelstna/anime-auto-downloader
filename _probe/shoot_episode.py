"""真实服务截图 + 断言：集数换算（用户报的「这里是第二季第一集」那一屏）。

产物：_probe/shots/27_episode_offset.png
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

URL = "http://127.0.0.1:7788/"
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
TARGET = "黑色五叶草"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"ep-{int(time.time())}")
proc = subprocess.Popen(
    [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
     "--no-first-run", "--force-device-scale-factor=1", f"--user-data-dir={profile}",
     f"--remote-debugging-port={cdp}", "--window-size=1600,1000", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ev(ws, expr, timeout=180):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                timeout=timeout)
    res = r.get("result", {})
    if res.get("subtype") == "error":
        raise RuntimeError(res.get("description"))
    return res.get("value")


ROWS = """JSON.stringify([...document.querySelectorAll('#res-body tr.res-row')].map(tr => ({
  src: (tr.querySelector('.col-src')||{}).innerText || '',
  group: (tr.querySelector('.col-group')||{}).innerText || '',
  title: (tr.querySelector('.col-title')||{}).innerText || '',
  ep: (tr.querySelector('.col-ep')||{}).innerText || '',
  epTitle: (tr.querySelector('.col-ep')||{}).title || ''
})))"""

SET_SELECT = """(function(id, value){
  const s = document.getElementById(id);
  s.value = value;
  s.dispatchEvent(new Event('change', {bubbles:true}));
  if (window.__ui && window.__ui.enhanceAll) window.__ui.enhanceAll(document);
  return s.value;
})"""

try:
    wait_cdp(cdp)
    ws = WS(open_page(cdp, "about:blank"))
    ws.call("Runtime.enable")
    ws.call("Page.enable")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    ws.call("Page.navigate", {"url": URL})
    for _ in range(60):
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    check("页面初始化完成", bool(ev(ws, "!!document.body && document.body.classList.contains('app-ready')")))

    titles = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#anime-grid .card')].map(c => (c.querySelector('.card-title')||{}).innerText || ''))") or "[]")
    idx = next((i for i, t in enumerate(titles) if TARGET in t and "第二季" in t), None)
    check(f"找到「{TARGET} 第二季」卡片", idx is not None, titles[idx] if idx is not None else str(titles[:5]))
    ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx}].click()")
    for _ in range(90):
        if (ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0) > 0:
            break
        time.sleep(1.0)
    time.sleep(1.5)

    # 按用户截图那样：资源站选动漫花园、字幕组选 ANi
    opts = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#f-source option')].map(o => o.value))") or "[]")
    if "dmhy" in opts:
        ev(ws, f"({SET_SELECT})('f-source', 'dmhy')")
        time.sleep(1.0)
    groups = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#f-group option')].map(o => o.value))") or "[]")
    ani = next((g for g in groups if "ANi" == g or "ANI" in g.upper()), "")
    if ani:
        ev(ws, f"({SET_SELECT})('f-group', {json.dumps(ani)})")
        time.sleep(1.2)

    state = ev(ws, "document.getElementById('search-state').innerText.replace(/\\n/g, ' | ')") or ""
    print(f"    搜索状态：{state[:190]}")
    check("搜索状态里给出集数换算说明", "集数按本季显示" in state, state[:190])
    check("提示里写明标题编号起点", re.search(r"标题编号从 \d+ 起", state) is not None, state[:190])

    rows = json.loads(ev(ws, ROWS) or "[]")
    check("筛选后仍有资源行", len(rows) > 0, f"{len(rows)} 行")
    target = [r for r in rows if "Season 2 - 171" in r["title"]]
    check("找到用户报的那一行（Season 2 - 171）", bool(target), target[0]["title"][:70] if target else str([r["title"][:40] for r in rows[:3]]))
    if target:
        row = target[0]
        check("集数显示为本季第 1 集（不再是 2）", row["ep"] == "1", f"集数列={row['ep']!r}")
        check("鼠标提示里能看到标题原始编号 171", "171" in row["epTitle"], row["epTitle"])
    others = [r for r in rows if r["ep"] not in ("", "–")]
    print(f"    本屏集数：{[(r['group'][:8], r['ep']) for r in others[:8]]}")
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
    p = os.path.join(SHOTS, "27_episode_offset.png")
    open(p, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {p}")
    ws.close()
finally:
    try:
        proc.terminate(); proc.wait(timeout=10)
    except Exception:   # noqa: BLE001
        proc.kill()
    shutil.rmtree(profile, ignore_errors=True)

print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
