"""关键词问题的现场回归（真实服务 + 真实站点）。

用户反馈的场景：`黑暗召唤师在地下恋爱中`（subject 630160）只搜到 1 条，
因为能搜到资源的关键词 `Dark Summoner to Dekiteiru` 排在候选表第 5 位、被上限截断了。

本探针验证三件事：
  ① 这个关键词现在会被搜到 → 命中条数明显变多（>1，实测 21 条）
  ② 搜索后写进学习记录（data/keyword_stats.json），下次它排第一（不再被预算截断）
  ③ 学习结果进缓存键 → 学习变了旧缓存自动失效、再搜一次就稳定命中缓存
产物：_probe/shots/32_keyword_fix.png
"""
import base64
import io
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("ANIME_BASE", "http://127.0.0.1:7788")
SUBJECT_ID = 630160
GOOD = "Dark Summoner to Dekiteiru"
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


def post(path, body, timeout=420):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def words_of(data):
    return {site: list(kws or []) for site, kws in (data.get("keywords_used") or {}).items()}


print("=" * 74)
print("1. 强制重搜：能搜到资源的罗马字有没有被用上")
print("=" * 74)
t0 = time.time()
d1 = post("/api/search", {"subject_id": SUBJECT_ID, "force": True})
elapsed = time.time() - t0
w1 = words_of(d1)
print(f"    命中 {d1.get('total')} 条（{elapsed:.1f}s）；各站："
      f"{[(k, v.get('count')) for k, v in (d1.get('source_status') or {}).items()]}")
for site, kws in w1.items():
    print(f"    {site}: {kws}")
used_any = any(GOOD in kws for kws in w1.values())
check(f"「{GOOD}」被搜到了", used_any, str(w1))
check("命中条数明显多于 1 条（修复前只有 1 条）", (d1.get("total") or 0) > 1, f"{d1.get('total')} 条")
check("第三种语言（英文组）用的是这条罗马字，而不是机器生拼的串",
      all(not kws or kws[0] in (GOOD, "黑暗召唤师在地下恋爱中") for kws in w1.values()), str(w1))

print()
print("=" * 74)
print("2. 学习记录：下一个关键词排第一 + 缓存键跟着变")
print("=" * 74)
with urllib.request.urlopen(BASE + "/api/status", timeout=30) as r:
    status = json.loads(r.read().decode("utf-8"))
path = ((status.get("keyword_learning") or {}).get("path") or "")   # 服务自己报告存哪了
learned = {}
if path and os.path.exists(path):
    raw = json.load(open(path, encoding="utf-8"))
    learned = (raw.get(str(SUBJECT_ID)) or {}).get("kw") or {}
print(f"    学到：{ {k: v.get('hits') for k, v in learned.items()} }（{path}）")
check("学习记录里记下了这条关键词", GOOD in learned, str(list(learned)))
if GOOD in learned:
    check("按命中数排序时它最靠前（下次第一个试）",
          max(learned.items(), key=lambda kv: kv[1].get("hits", 0))[0] == GOOD,
          str({k: v.get("hits") for k, v in learned.items()}))

d2 = post("/api/search", {"subject_id": SUBJECT_ID})           # 不强制：应当带学习结果重搜一次
w2 = words_of(d2)
print(f"    第二次：cached={d2.get('cached')} 命中 {d2.get('total')} 条")
for site, kws in w2.items():
    print(f"    {site}: {kws}")
check("学到的关键词排在各站候选表第一位",
      all(kws and kws[0] == GOOD for kws in w2.values() if kws), str(w2))

d3 = post("/api/search", {"subject_id": SUBJECT_ID})           # 第三次：学习结果入缓存键后应命中缓存
print(f"    第三次：cached={d3.get('cached')} 命中 {d3.get('total')} 条")
check("第三次命中缓存（学习结果进了缓存键，不会再反复联网）", d3.get("cached") is True, str(d3.get("cached")))
check("缓存里的条数与联网结果一致", (d3.get("total") or 0) == (d2.get("total") or 0),
      f"{d3.get('total')} vs {d2.get('total')}")

print()
print("=" * 74)
print("3. 界面上长什么样（截图）")
print("=" * 74)
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"kw-{int(time.time())}")
proc = subprocess.Popen([BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                         "--no-first-run", "--force-device-scale-factor=1", f"--user-data-dir={profile}",
                         f"--remote-debugging-port={cdp}", "--window-size=1600,1000", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ev(ws, expr, timeout=180):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
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
    ws.call("Page.navigate", {"url": BASE + "/"})
    for _ in range(60):
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    titles = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#anime-grid .card')].map(c => (c.querySelector('.card-title')||{}).innerText || ''))") or "[]")
    idx = next((i for i, t in enumerate(titles) if "黑暗召唤师" in t), None)
    check("番剧卡片能找到", idx is not None, titles[idx] if idx is not None else str(titles[:5]))
    if idx is not None:
        ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx}].click()")
        for _ in range(90):
            if (ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0) > 0:
                break
            time.sleep(1.0)
        time.sleep(1.5)
        rows = ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0
        state = ev(ws, "document.getElementById('search-state').innerText") or ""
        print(f"    界面行数：{rows}；关键词行：{state.split('本次关键词')[-1].strip()[:130] if '本次关键词' in state else '-'}")
        check("界面列出的资源行数 > 1", rows > 1, f"{rows} 行")
        check("界面关键词里能看到这条罗马字", GOOD in state, "OK" if GOOD in state else state[:120])
        r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
        shot = os.path.join(SHOTS, "32_keyword_fix.png")
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
