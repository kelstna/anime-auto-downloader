"""「跳 Bangumi 详情页」按钮验收（真实页面）：
  ① 在看番剧卡片：封面右上角有外链按钮，href 指向 https://bgm.tv/subject/<id>，新标签打开
  ② 我的订阅卡片：同一个按钮（同一套视觉），href 用订阅的 subject_id
  ③ 点它不会顺带打开详情弹窗（卡片整体有点击事件，必须阻止冒泡）
  ④ 位置/尺寸：卡片按钮在封面内右上角、与左上角复选框对称；订阅卡片按钮贴封面右上角

产物：_probe/shots/33_bgm_link_anime.png、34_bgm_link_subs.png
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

BASE = os.environ.get("ANIME_BASE", "http://127.0.0.1:7788")
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


CARD_INFO = """JSON.stringify((() => {
  const card = document.querySelector('#anime-grid .card');
  const a = card && card.querySelector('.card-bgm');
  const cover = card && card.querySelector('.card-cover');
  const box = card && card.querySelector('.card-check');
  if (!a || !cover) return null;
  const ra = a.getBoundingClientRect(), rc = cover.getBoundingClientRect();
  const rb = box ? box.getBoundingClientRect() : null;
  return {
    id: card.dataset.id, href: a.getAttribute('href'), target: a.getAttribute('target'),
    rel: a.getAttribute('rel'), title: a.getAttribute('title'),
    w: Math.round(ra.width), h: Math.round(ra.height),
    insetRight: Math.round(rc.right - ra.right), insetTop: Math.round(ra.top - rc.top),
    sameTopAsCheck: rb ? Math.abs(rb.top - ra.top) <= 1 : null,
    insideCover: ra.left >= rc.left && ra.right <= rc.right && ra.top >= rc.top && ra.bottom <= rc.bottom,
    svg: !!a.querySelector('svg'),
  };
})())"""

SUB_INFO = """JSON.stringify((() => {
  const item = document.querySelector('#sub-list .sub-item');
  const a = item && item.querySelector('.sub-bgm');
  const wrap = item && item.querySelector('.sub-cover-wrap');
  const img = item && item.querySelector('.sub-cover');
  if (!a || !wrap) return null;
  const ra = a.getBoundingClientRect(), rw = wrap.getBoundingClientRect(), ri = img ? img.getBoundingClientRect() : null;
  return {
    id: item.dataset.id, href: a.getAttribute('href'), target: a.getAttribute('target'),
    rel: a.getAttribute('rel'), title: a.getAttribute('title'),
    w: Math.round(ra.width), h: Math.round(ra.height),
    insideWrap: ra.left >= rw.left && ra.right <= rw.right && ra.top >= rw.top && ra.bottom <= rw.bottom,
    imgFills: ri ? Math.abs(ri.width - rw.width) <= 1 && Math.abs(ri.height - rw.height) <= 1 : null,
    svg: !!a.querySelector('svg'),
    actionsWidth: Math.round((item.querySelector('.sub-actions') || {}).getBoundingClientRect ? item.querySelector('.sub-actions').getBoundingClientRect().width : 0),
  };
})())"""

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"bgm-{int(time.time())}")
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


def shoot(ws, name):
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
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
    ws.call("Page.navigate", {"url": BASE + "/"})
    for _ in range(60):
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)

    print("\n【① 在看番剧卡片】")
    info = json.loads(ev(ws, CARD_INFO) or "null")
    check("卡片上有 Bangumi 跳转按钮", bool(info), str(info))
    if info:
        sid = info["id"]
        check("href 指向 Bangumi 条目页", info["href"] == f"https://bgm.tv/subject/{sid}",
              f"{info['href']}（卡片的 id={sid}）")
        check("新标签页打开且带 noopener", info["target"] == "_blank" and "noopener" in (info["rel"] or ""),
              f"target={info['target']} rel={info['rel']}")
        check("有悬浮说明（title）", "Bangumi" in (info["title"] or ""), str(info["title"]))
        check("图标是内联 SVG（不是方框乱码）", info["svg"] is True)
        check("按钮在封面内、右上角留白 8px", info["insideCover"] and info["insetRight"] == 8 and info["insetTop"] == 8,
              f"inside={info['insideCover']} right={info['insetRight']} top={info['insetTop']}")
        check("与左上角复选框同一水平线（对称）", info["sameTopAsCheck"] is True, str(info["sameTopAsCheck"]))
        check("尺寸与复选框一致（24×24）", (info["w"], info["h"]) == (24, 24), f"{info['w']}×{info['h']}")
        # 点它不应该打开详情弹窗
        ev(ws, "document.querySelector('#anime-grid .card .card-bgm').click()")
        time.sleep(0.6)
        modal = ev(ws, "document.getElementById('modal').hidden !== true")
        check("点按钮不会顺带打开详情弹窗", modal is False, f"modal open={modal}")
    shoot(ws, "33_bgm_link_anime")

    print("\n【② 我的订阅卡片】")
    ev(ws, "document.querySelector('.nav-item[data-view=subs]').click()")
    time.sleep(2.2)
    sinfo = json.loads(ev(ws, SUB_INFO) or "null")
    check("订阅卡片上有 Bangumi 跳转按钮", bool(sinfo), str(sinfo))
    if sinfo:
        check("href 用订阅的 subject_id",
              sinfo["href"] == f"https://bgm.tv/subject/{sinfo['id']}", f"{sinfo['href']}（id={sinfo['id']}）")
        check("新标签页打开且带 noopener", sinfo["target"] == "_blank" and "noopener" in (sinfo["rel"] or ""),
              f"target={sinfo['target']} rel={sinfo['rel']}")
        check("按钮贴在封面右上角内（不越界）", sinfo["insideWrap"] is True, str(sinfo["insideWrap"]))
        check("封面图仍铺满容器（加了一层包裹没破坏布局）", sinfo["imgFills"] is True, str(sinfo["imgFills"]))
        check("尺寸比卡片上的小一号（20×20，不抢戏）", (sinfo["w"], sinfo["h"]) == (20, 20),
              f"{sinfo['w']}×{sinfo['h']}")
        check("图标是内联 SVG", sinfo["svg"] is True)
        row = ev(ws, "document.querySelectorAll('#sub-list .sub-item .btn-row .btn').length") or 0
        check("操作区按钮数没变（跳转按钮放在封面上，没挤进按钮行）", row >= 4, f"{row} 个按钮")
    shoot(ws, "34_bgm_link_subs")
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
