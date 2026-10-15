"""真实服务可视化验收：字幕语言 + 手动搜索（自定义关键词）。

跑之前服务要在 127.0.0.1:7788 运行（start.bat）。产物：
  _probe/shots/23_lang_group_filter.png   按字幕组「绿茶字幕组」筛选后的资源表（语言列）
  _probe/shots/24_lang_filter_chs.png     语言筛「简体」后的结果
  _probe/shots/25_manual_keyword.png      手动搜索关键词后的资源表 + 订阅设置里的搜索词
不点「加入订阅」（避免动用户真实订阅），只验证到「关键词已填进订阅设置」这一步。
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
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


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


def shoot(ws, name, full=False):
    r = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": bool(full)}, timeout=90)
    p = os.path.join(SHOTS, f"{name}.png")
    open(p, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {p}")


SET_SELECT = """(function(id, value){
  const s = document.getElementById(id);
  s.value = value;
  s.dispatchEvent(new Event('change', {bubbles:true}));
  if (window.__ui && window.__ui.enhanceAll) window.__ui.enhanceAll(document);
  return s.value;
})"""
SET_INPUT = """(function(id, value){
  const el = document.getElementById(id);
  el.value = value;
  el.dispatchEvent(new Event('input', {bubbles:true}));
  return el.value;
})"""
ROWS = """JSON.stringify([...document.querySelectorAll('#res-body tr.res-row')].map(tr => ({
  src: (tr.querySelector('.col-src')||{}).innerText || '',
  group: (tr.querySelector('.col-group')||{}).innerText || '',
  title: (tr.querySelector('.col-title')||{}).innerText || '',
  lang: (tr.querySelector('.col-lang .lang-pill')||{}).innerText || '',
  cls: ((tr.querySelector('.col-lang .lang-pill')||{}).className || '').split(' ').pop()
})))"""


def wait_rows(ws, minimum=1, seconds=60):
    for _ in range(seconds):
        n = ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0
        if n >= minimum:
            return n
        time.sleep(1.0)
    return ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0


try:
    wait_cdp(cdp)
    ws = WS(open_page(cdp, "about:blank"))
    ws.call("Runtime.enable")
    ws.call("Page.enable")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    ws.call("Page.navigate", {"url": URL})
    for _ in range(60):
        # 刚导航完 document.body 可能还是 null，先等文档就绪
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    check("页面初始化完成（app-ready）", bool(ev(ws, "!!document.body && document.body.classList.contains('app-ready')")))

    titles = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#anime-grid .card')].map(c => (c.querySelector('.card-title')||{}).innerText || ''))") or "[]")
    idx = next((i for i, t in enumerate(titles) if "久留美" in t), None)
    check("找到「FX战士久留美」卡片", idx is not None, titles[idx] if idx is not None else str(titles[:3]))

    print("\n【1】打开弹窗，等资源列表加载")
    ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx}].click()")
    rows_n = wait_rows(ws, 1, 60)
    check("资源列表已加载出来", rows_n > 0, f"{rows_n} 行")
    check("手动搜索框存在", bool(ev(ws, "!!document.getElementById('f-keyword')")))
    check("手动搜索按钮存在", bool(ev(ws, "!!document.getElementById('btn-keyword-search')")))

    print("\n【2】字幕组筛「绿茶字幕组」：语言列必须识别出来（用户截图里的那一屏）")
    opts = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#f-group option')].map(o => o.value))") or "[]")
    want = next((o for o in opts if "绿茶字幕组" in o), "")
    check("字幕组下拉里有「绿茶字幕组」", bool(want), f"共 {len(opts)} 个选项")
    check("下拉里没有语言标注混进来的脏选项",
          not any(x in ("简繁内封字幕", "简体内封字幕", "簡日內嵌", "繁日內嵌") for x in opts), str(opts))
    ev(ws, f"({SET_SELECT})('f-group', {json.dumps(want)})")
    time.sleep(1.2)
    rows = json.loads(ev(ws, ROWS) or "[]")
    lang_texts = [r["lang"] for r in rows]
    check("筛选后仍有资源行", len(rows) > 0, f"{len(rows)} 行")
    check("语言列全部识别出来（没有「未标注」）",
          len(rows) > 0 and all(t != "未标注" for t in lang_texts), str(lang_texts))
    check("有简体行", any(t == "简体" for t in lang_texts), str(lang_texts))
    check("有繁体行", any(t == "繁体" for t in lang_texts), str(lang_texts))
    check("语言胶囊 class 与文案一致",
          all(r["cls"] in ("lang-chs", "lang-cht", "lang-both", "lang-jp", "lang-none") for r in rows),
          str(sorted({r["cls"] for r in rows})))
    for r in rows:
        print(f"    {r['lang']:4s} | {r['group']:8s} | {r['title'][:66]}")
    shoot(ws, "23_lang_group_filter")

    print("\n【3】语言筛「简体」")
    ev(ws, f"({SET_SELECT})('f-lang', 'chs')")
    time.sleep(1.2)
    rows_chs = json.loads(ev(ws, ROWS) or "[]")
    check("只剩简体行（简繁不再混进来）",
          len(rows_chs) > 0 and all(r["lang"] == "简体" for r in rows_chs),
          str([r["lang"] for r in rows_chs]))
    ev(ws, f"({SET_SELECT})('f-lang', 'both')")
    time.sleep(1.2)
    rows_both = json.loads(ev(ws, ROWS) or "[]")
    check("选「简繁/双语」时只剩简繁行",
          all(r["lang"] == "简繁" for r in rows_both), str([r["lang"] for r in rows_both][:12]))
    shoot(ws, "24_lang_filter_chs")
    ev(ws, f"({SET_SELECT})('f-lang', '')")
    ev(ws, f"({SET_SELECT})('f-group', '')")
    time.sleep(1.0)

    print("\n【4】手动搜索：输入关键词 → 搜索 → 订阅设置里自动带出这个词")
    KW = "FX Senshi Kurumi-chan"
    ev(ws, f"({SET_INPUT})('f-keyword', {json.dumps(KW)})")
    check("关键词非空时出现「恢复自动搜索」按钮",
          bool(ev(ws, "!document.getElementById('btn-keyword-reset').hidden")))
    ev(ws, "document.getElementById('btn-keyword-search').click()")
    time.sleep(1.5)
    rows_kw = wait_rows(ws, 1, 90)
    check("手动搜索有结果", rows_kw > 0, f"{rows_kw} 行")
    state = ev(ws, "document.getElementById('search-state').innerText.replace(/\\n/g, ' | ')") or ""
    check("搜索状态里写明「手动关键词」", "手动关键词" in state, state[:140])
    check("关键词已自动填进订阅设置", (ev(ws, "document.getElementById('s-keyword').value") or "").strip() == KW,
          repr(ev(ws, "document.getElementById('s-keyword').value")))
    ev(ws, "document.querySelector('#m-tabs .tab[data-tab=sub]').click()")
    time.sleep(0.8)
    preview = ev(ws, "document.getElementById('s-preview').innerText.replace(/\\n/g, ' | ')") or ""
    check("订阅预览里显示搜索词", "搜索词" in preview, preview[:160])
    tip = ev(ws, "document.getElementById('s-keyword-tip').innerText") or ""
    check("提示文案说明会一直用这个词", "一直用" in tip, tip)
    ev(ws, "document.querySelector('#m-tabs .tab[data-tab=res]').click()")
    time.sleep(0.6)
    shoot(ws, "25_manual_keyword")

    print("\n【5】恢复自动搜索")
    ev(ws, "document.getElementById('btn-keyword-reset').click()")
    time.sleep(2.0)
    rows_back = wait_rows(ws, 1, 60)
    check("恢复自动搜索后仍有结果", rows_back > 0, f"{rows_back} 行")
    check("关键词输入框已清空", not (ev(ws, "document.getElementById('f-keyword').value") or "").strip())
    check("订阅设置的搜索词也清空", not (ev(ws, "document.getElementById('s-keyword').value") or "").strip())
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
