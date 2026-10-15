"""语言筛选回归（用户反馈：选「简体」时「简繁」资源没被筛掉）。

做法：真实页面打开一部有简繁资源的番剧（默认「冰之城墙 第二季」），
先把语言列全部读出来，再逐档切换筛选，断言每一档**只剩那一类**。
产物：_probe/shots/30_lang_filter_strict.png
"""
import base64
import json
import os
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
KEYWORD = os.environ.get("ANIME_NAME", "冰之城")
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


ROWS = """JSON.stringify([...document.querySelectorAll('#res-body tr.res-row')].map(tr => ({
  lang: (tr.querySelector('.col-lang .lang-pill')||{}).innerText || '',
  title: (tr.querySelector('.col-title')||{}).innerText || ''})))"""

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"lang-{int(time.time())}")
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


SET_SELECT = """(function(id, value){
  const s = document.getElementById(id);
  s.value = value;
  s.dispatchEvent(new Event('change', {bubbles:true}));
  if (window.__ui && window.__ui.enhanceAll) window.__ui.enhanceAll(document);
  return s.value;
})"""


def set_lang(ws, value):
    """设置 #f-lang（原生 select 是自绘控件的真值来源，改它 + 派发 change 即可）。"""
    got = ev(ws, f"({SET_SELECT})('f-lang', {json.dumps(value)})")
    time.sleep(1.0)
    return got == value


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
    check("页面初始化完成（连的是 127.0.0.1:7788 上的实例）",
          bool(ev(ws, "!!document.body && document.body.classList.contains('app-ready')")))

    titles = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#anime-grid .card')].map(c => (c.querySelector('.card-title')||{}).innerText || ''))") or "[]")
    idx = next((i for i, t in enumerate(titles) if KEYWORD in t), None)
    check(f"找到「{KEYWORD}」卡片", idx is not None, titles[idx] if idx is not None else str(titles[:6]))
    if idx is None:
        raise SystemExit(1)
    print(f"    打开：{titles[idx]}")
    ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx}].click()")
    for _ in range(90):
        if (ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0) > 0:
            break
        time.sleep(1.0)
    time.sleep(1.5)

    all_rows = json.loads(ev(ws, ROWS) or "[]")
    langs = [r["lang"] for r in all_rows]
    print(f"    未筛选：{len(all_rows)} 行，语言分布 { {k: langs.count(k) for k in sorted(set(langs))} }")
    check("这部番同时有简体与简繁资源（否则测不出问题）",
          "简体" in langs and "简繁" in langs, str(sorted(set(langs))))

    # ① 选「简体」：只允许简体
    set_lang(ws, "chs")
    rows = json.loads(ev(ws, ROWS) or "[]")
    got = [r["lang"] for r in rows]
    print(f"    选「简体」：{len(rows)} 行 { {k: got.count(k) for k in sorted(set(got))} }")
    check("选「简体」后只剩简体（简繁被筛掉）", got and set(got) == {"简体"}, str(sorted(set(got))))
    check("简体行数与未筛选时的简体条数一致", len(rows) == langs.count("简体"),
          f"{len(rows)} vs {langs.count('简体')}")
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
    shot = os.path.join(SHOTS, "30_lang_filter_strict.png")
    open(shot, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {shot}")

    # ② 选「简繁/双语」：只允许简繁
    set_lang(ws, "both")
    rows = json.loads(ev(ws, ROWS) or "[]")
    got = [r["lang"] for r in rows]
    print(f"    选「简繁/双语」：{len(rows)} 行 { {k: got.count(k) for k in sorted(set(got))} }")
    check("选「简繁/双语」后只剩简繁", got and set(got) == {"简繁"}, str(sorted(set(got))))

    # ③ 选「繁体」：只允许繁体（可能为空，为空不算错）
    set_lang(ws, "cht")
    got = [r["lang"] for r in json.loads(ev(ws, ROWS) or "[]")]
    check("选「繁体」后只剩繁体", set(got) <= {"繁体"}, str(sorted(set(got))))

    # ④ 回到「全部」：行数恢复
    set_lang(ws, "")
    back = json.loads(ev(ws, ROWS) or "[]")
    check("切回「全部」后行数恢复", len(back) == len(all_rows), f"{len(back)} vs {len(all_rows)}")
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
