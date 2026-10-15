"""「下次更新（北京时间）」在真实页面上的验收：
  ① 在看番剧卡片：显示「下次更新：10-12 00:20（周一）· 北京时间」，悬浮说明含日本时间/电视台/数据来源
  ② 我的订阅卡片：同样的文案（作为一条 fact 混在那一行里）
  ③ 后端 /api/status 的 airtime 缓存状态：每天刷新、条数、更新时间
  ④ 卡片高度仍然整齐（没有数据的卡片用隐藏占位行）

产物：_probe/shots/35_airtime_anime.png、36_airtime_subs.png
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


def get_json(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


print("=" * 74)
print("1. 后端：更新时刻缓存（data/airtimes.json，每天刷新）")
print("=" * 74)
st = get_json(BASE + "/api/status")
air = st.get("airtime") or {}
print(f"    {json.dumps({k: air.get(k) for k in ('enabled', 'count', 'updated_text', 'stale', 'refreshing')}, ensure_ascii=False)}")
check("更新时刻功能已启用", air.get("enabled") is True, str(air.get("enabled")))
check("缓存里有一批番剧（来自 bangumi-data）", int(air.get("count") or 0) > 1000, f"{air.get('count')} 部")
check("缓存没过期（每天刷新一次）", air.get("stale") is False, f"stale={air.get('stale')}")
check("缓存文件路径就是 data/airtimes.json", str(air.get("path") or "").endswith("airtimes.json"), str(air.get("path")))

subs_payload = get_json(BASE + "/api/subscriptions")
with_air = [s for s in (subs_payload.get("items") or []) if (s.get("airtime") or {}).get("next_text")]
print(f"    订阅 {len(subs_payload.get('items') or [])} 条，其中 {len(with_air)} 条有下次更新时间")
for s in with_air[:4]:
    a = s["airtime"]
    print(f"      {s.get('name', '')[:16]:<18} {a['next_text']} · 北京时间 | {a.get('station') or '?'} | 日本时间 {a['jst_text']}")
check("订阅接口带回下次更新时间", bool(with_air), f"{len(with_air)} 条")
check("时间文案是「MM-DD HH:MM（周X）」格式",
      bool(with_air) and all(len(a["airtime"]["next_text"]) >= 15 and "（周" in a["airtime"]["next_text"]
                             for a in with_air[:5]),
      str(with_air[0]["airtime"]["next_text"]) if with_air else "-")

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"air-{int(time.time())}")
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


CARD_JS = """JSON.stringify((()=>{
  return [...document.querySelectorAll('#anime-grid .card')].map(c=>{
    const n = c.querySelector('.card-air');
    return { title: (c.querySelector('.card-title')||{}).textContent || '',
             text: n ? n.textContent.trim() : '', empty: !!(n && n.classList.contains('is-empty')),
             soon: !!(n && n.classList.contains('is-soon')),
             finished: !!(n && n.classList.contains('is-finished')),
             fits: n ? (n.scrollWidth <= n.clientWidth + 1) : true,
             tip: n ? (n.getAttribute('title') || '') : '',
             h: n ? Math.round(n.getBoundingClientRect().height) : 0 };
  });})())"""

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

    print()
    print("=" * 74)
    print("2. 在看番剧卡片（含已完结）")
    print("=" * 74)
    # 先取消「仅显示在播/未完结」，把已完结的番也显示出来一起看
    ev(ws, "(()=>{const c=document.getElementById('only-airing');if(c.checked){c.checked=false;"
           "c.dispatchEvent(new Event('change'));}return true;})()")
    time.sleep(1.2)
    cards = json.loads(ev(ws, CARD_JS) or "[]")
    shown = [c for c in cards if c["text"] and not c["finished"]]
    finished = [c for c in cards if c["finished"]]
    print(f"    在播 {len(shown)} 张、已完结 {len(finished)} 张；例：")
    for c in shown[:3]:
        print(f"      {c['title'][:18]:<20} {c['text']}")
    for c in finished[:3]:
        print(f"      {c['title'][:18]:<20} {c['text']}  ← {c['tip'].splitlines()[0][:46]}")
    check("卡片显示「下次更新 MM-DD HH:MM」（不带周几 / 北京时间）",
          bool(shown) and all("下次更新" in c["text"] and "（周" not in c["text"]
                              and "北京时间" not in c["text"] for c in shown),
          str(shown[0]["text"]) if shown else "-")
    check("已完结的番显示「已完结」而不是假的更新时间",
          bool(finished) and all(c["text"].strip() == "已完结" for c in finished),
          f"{len(finished)} 张：{str([c['text'] for c in finished][:3])}")
    check("已完结的悬浮说明含「最后一集」/电视台/数据来源",
          bool(finished) and all(("已完结" in c["tip"] and "电视台" in c["tip"] and "bangumi-data" in c["tip"])
                                 for c in finished),
          (finished[0]["tip"] if finished else "").replace("\n", " ｜ ")[:120])
    check("卡片这行没被截断", bool(shown) and all(c["fits"] for c in shown), str([c["fits"] for c in shown]))
    check("悬浮说明是完整那句（含 · 北京时间）+ 日本时间 / 电视台 / 数据来源",
          bool(shown) and all(("· 北京时间" in c["tip"] and "日本时间" in c["tip"]
                               and "电视台" in c["tip"] and "bangumi-data" in c["tip"]) for c in shown),
          (shown[0]["tip"] if shown else "").replace("\n", " ｜ ")[:150])
    check("同行卡片高度一致（没有更新时刻的用隐藏占位）",
          len({c["h"] for c in cards}) == 1 or max(c["h"] for c in cards) - min(c["h"] for c in cards) <= 1,
          str(sorted({c["h"] for c in cards})))
    shoot(ws, "35_airtime_anime")
    # 恢复默认状态（默认不勾选「只看在播」：在看里的番全部显示）
    ev(ws, "(()=>{const c=document.getElementById('only-airing');c.checked=false;"
           "c.dispatchEvent(new Event('change'));return true;})()")
    time.sleep(1.0)

    print()
    print("=" * 74)
    print("2b. 详情弹窗（点开卡片）也要显示更新时刻")
    print("=" * 74)
    ev(ws, "document.querySelector('#anime-grid .card').click()")
    time.sleep(2.5)
    modal_air = json.loads(ev(ws, """JSON.stringify((()=>{
      const n = document.querySelector('#m-sub .m-air');
      return { head: (document.getElementById('m-sub')||{}).innerText || '',
               text: n ? n.innerText.replace(/\\n/g, ' ') : '', tip: n ? (n.getAttribute('title')||'') : '',
               soon: !!(n && n.classList.contains('is-soon')) };
    })())""") or "{}")
    print(f"    标题行：{modal_air.get('head', '').replace(chr(10), ' ')[:110]}")
    print(f"    悬浮说明：{(modal_air.get('tip') or '').replace(chr(10), ' ｜ ')[:130]}")
    check("详情弹窗标题行里有「下次更新：… · 北京时间」",
          "下次更新：" in (modal_air.get("text") or "") and "北京时间" in (modal_air.get("text") or ""),
          str(modal_air.get("text")))
    check("弹窗里的悬浮说明同样含日本时间 / 电视台 / 数据来源",
          all(k in (modal_air.get("tip") or "") for k in ("日本时间", "电视台", "bangumi-data")),
          str(modal_air.get("tip"))[:80])
    shoot(ws, "37_airtime_modal")
    ev(ws, "document.getElementById('m-close').click()")
    time.sleep(0.8)
    # 切到「我的订阅」并等卡片渲染出来（最多 15 秒；顺便打印当前视图，失败时好定位）
    ev(ws, "document.querySelector('.nav-item[data-view=subs]').click()")
    sub_count = 0
    for _ in range(15):
        time.sleep(1.0)
        sub_count = ev(ws, "document.querySelectorAll('#sub-list .sub-item').length") or 0
        if sub_count:
            break
    view = ev(ws, "document.body.dataset.view")
    print(f"    当前视图={view}，订阅卡片 {sub_count} 张")
    check("订阅页渲染出卡片（切页后 15 秒内）", sub_count > 0, f"view={view} count={sub_count}")
    print()
    print("=" * 74)
    print("3. 我的订阅卡片")
    print("=" * 74)
    subs_ui = json.loads(ev(ws, """JSON.stringify((()=>{
      return [...document.querySelectorAll('#sub-list .sub-item')].map(it=>{
        const n = it.querySelector('.sub-fact-air');
        return { title: (it.querySelector('.sub-title')||{}).textContent || '',
                 text: n ? n.textContent.trim() : '', tip: n ? (n.getAttribute('title')||'') : '',
                 soon: !!(n && n.classList.contains('is-soon')) };
      });})())""") or "[]")
    ok_subs = [s for s in subs_ui if s["text"]]
    print(f"    {len(ok_subs)}/{len(subs_ui)} 张订阅卡片显示下次更新；例：")
    for s in ok_subs[:4]:
        print(f"      {s['title'][:18]:<20} {s['text']}")
    check("订阅卡片显示「下次更新：… · 北京时间」",
          bool(ok_subs) and all("下次更新：" in s["text"] and "北京时间" in s["text"] for s in ok_subs),
          str(ok_subs[0]["text"]) if ok_subs else "-")
    check("订阅卡片悬浮说明同样含日本时间 / 电视台 / 数据来源",
          bool(ok_subs) and all(all(k in s["tip"] for k in ("日本时间", "电视台", "bangumi-data")) for s in ok_subs),
          (ok_subs[0]["tip"] if ok_subs else "").replace("\n", " ｜ ")[:140])
    check("界面文案与接口给的一致",
          bool(ok_subs) and bool(with_air) and ok_subs[0]["text"].replace("下次更新：", "") in
          [a["airtime"]["next_text"] + " · 北京时间" for a in with_air][0],
          f"界面 {ok_subs[0]['text'] if ok_subs else '-'} vs 接口 {with_air[0]['airtime']['next_text'] if with_air else '-'}")
    shoot(ws, "36_airtime_subs")
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
