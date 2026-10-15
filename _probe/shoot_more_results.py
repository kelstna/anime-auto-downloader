"""真实服务截图：用户报的「搜索结果少了一大堆」那一屏（野生的大魔王出现了！第二季）。

离线断言 + 截图，产物：_probe/shots/26_more_results.png
跑之前服务要在 127.0.0.1:7788 运行（start.bat），且该番剧已有缓存（否则会现场联网搜一次）。
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
PASS, FAIL = [], []
TARGET = "大魔王"


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"kw-{int(time.time())}")
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
    idx = next((i for i, t in enumerate(titles) if TARGET in t), None)
    check(f"找到「{TARGET}」卡片", idx is not None, titles[idx] if idx is not None else str(titles[:5]))
    ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx}].click()")
    for _ in range(90):
        if (ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0) > 0:
            break
        time.sleep(1.0)
    time.sleep(1.5)

    rows = json.loads(ev(ws, """JSON.stringify([...document.querySelectorAll('#res-body tr.res-row')].map(tr => ({
      src: (tr.querySelector('.col-src')||{}).innerText || '',
      title: (tr.querySelector('.col-title')||{}).innerText || '',
      ep: (tr.querySelector('.col-ep')||{}).innerText || '',
      lang: (tr.querySelector('.col-lang .lang-pill')||{}).innerText || ''})))""") or "[]")
    state = ev(ws, "document.getElementById('search-state').innerText.replace(/\\n/g, ' | ')") or ""
    print(f"    搜索状态：{state[:170]}")
    hits = 0
    for m in re.finditer(r"命中 (\d+) 条", state):
        hits = int(m.group(1))
    check("仍有本季资源可挑", hits >= 5, f"命中 {hits} 条")
    kw_part = state.split("本次关键词")[-1] if "本次关键词" in state else ""
    check("搜索关键词已是清洗过的简体名（不带标点、不带第几季）",
          "野生的大魔王出现了" in kw_part and "！" not in kw_part and "第二季" not in kw_part,
          kw_part.strip()[:120])
    # 现在会滤掉同一系列其它季的资源（否则订阅进度会出现 14/12 这种数字）
    check("其它季的资源已被隐藏并提示", "已隐藏" in state, state[:150])
    eps = [r["ep"] for r in rows if r["ep"] and r["ep"] != "–"]
    check("列表里只剩本季集号（1~12）", bool(eps) and all(e.isdigit() and 1 <= int(e) <= 12 for e in eps), str(eps))
    dmhy = [r for r in rows if r["src"] == "动漫花园"]
    check("动漫花园有本季资源", len(dmhy) >= 1, f"{len(dmhy)} 条")
    loli = [r for r in rows if "LoliHouse" in r["title"]]
    check("标题里关键词留在原位（解析器文本顺序回归）",
          bool(loli) and all(re.search(r"野生的大魔王出现了！\s*/\s*野生的最终BOSS出现了！", r["title"]) for r in loli),
          loli[0]["title"][:90] if loli else "(没有 LoliHouse 的行)")
    print("    前几行：")
    for r in rows[:6]:
        print(f"      第{r['ep']:>3}集 {r['lang'] or '未标注':4s} [{r['src']}] {r['title'][:70]}")
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
    p = os.path.join(SHOTS, "26_more_results.png")
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
