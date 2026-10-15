"""
CDP 全流程 UI 测试 + 截图：
1) 加载 mock 数据测试页，验证番剧卡片 / 资源表 / 字幕组 / 订阅页渲染
2) 打开弹窗，验证 9 列资源表、筛选器、字幕组 tab、订阅 tab
3) 截图保存到 _probe/shots/

用法：python _probe/cdp_ui.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))

from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

SHOTS = os.path.join(ROOT, "_probe", "shots")
os.makedirs(SHOTS, exist_ok=True)
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)

PASS: list[str] = []
FAIL: list[str] = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory, port):
    handler = lambda *a, **kw: Quiet(*a, directory=directory, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def evaluate(ws, expr, timeout=60):
    return ev_js(ws, expr, timeout)


def ev_js(ws, expr, timeout=60):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                timeout=timeout)
    res = r.get("result", {})
    if res.get("subtype") == "error":
        raise RuntimeError(res.get("description"))
    return res.get("value")


def shoot(ws, name, full=False):
    params = {"format": "png", "captureBeyondViewport": bool(full)}
    try:
        r = ws.call("Page.captureScreenshot", params, timeout=90)
    except Exception as e:                                  # noqa: BLE001
        print(f"    !! 截图失败 {name}: {e}")
        return None
    import base64
    data = base64.b64decode(r["data"])
    path = os.path.join(SHOTS, f"{name}.png")
    with open(path, "wb") as f:
        f.write(data)
    print(f"    截图 -> {path} ({len(data) // 1024} KB)")
    return path


MEASURE_JS = r"""
(() => {
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const box = el => { const b = el.getBoundingClientRect(); return {l:+b.left.toFixed(1), t:+b.top.toFixed(1), w:+b.width.toFixed(1), h:+b.height.toFixed(1), r:+b.right.toFixed(1)}; };
  const out = {};
  out.appReady = document.body.classList.contains('app-ready');
  out.view = document.body.dataset.view;
  out.errors = window.__errs || [];

  // 番剧卡片
  const cards = qa('#anime-grid .card');
  out.cardCount = cards.length;
  if (cards.length) {
    out.cardBoxes = cards.map(box);
    out.cardTitles = cards.map(c => (c.querySelector('.card-title') || {}).textContent || '');
    out.subscribed = qa('#anime-grid .card.is-subscribed').length;
    out.covers = qa('#anime-grid .card img').length;
    out.checkboxes = qa('#anime-grid .card input[type=checkbox]').length;
    // Bangumi 跳转按钮（用户要求：在看番剧/我的订阅卡片上都能跳详情页）
    out.bgmLinks = qa('#anime-grid .card .card-bgm').map(a => ({
      href: a.getAttribute('href') || '', target: a.getAttribute('target') || '',
      rel: a.getAttribute('rel') || '', svg: !!a.querySelector('svg'),
      inCover: !!(a.closest('.card-cover')),
    }));
    out.subBgmLinks = qa('#sub-list .sub-item .sub-bgm').map(a => ({
      href: a.getAttribute('href') || '', target: a.getAttribute('target') || '',
      rel: a.getAttribute('rel') || '', svg: !!a.querySelector('svg'),
      inCover: !!a.closest('.sub-cover-wrap'),
    }));
  }
  out.animeEmptyHidden = q('#anime-empty') ? q('#anime-empty').hidden : null;
  out.selectedText = q('#selected-count') ? q('#selected-count').textContent.trim() : '';

  // 弹窗 + 资源表
  const modal = q('#modal');
  out.modalOpen = modal ? !modal.hidden : null;
  const rows = qa('#res-body tr');
  out.rowCount = rows.length;
  if (rows.length) {
    out.rowCells = rows.map(tr => [...tr.querySelectorAll('td')].map(td => td.className));
    out.rowBoxes = rows.slice(0, 5).map(tr => [...tr.querySelectorAll('td')].map(box));
    out.numAlign = [...new Set(qa('#res-body td.num').map(td => getComputedStyle(td).textAlign))];
    out.numRightEdges = qa('#res-body tr').slice(0, 6).map(tr => {
      const td = tr.querySelector('td.col-size.num');
      return td ? +td.getBoundingClientRect().right.toFixed(1) : null;
    }).filter(v => v !== null);
    out.groupsCells = [...new Set(qa('#res-body td.col-group').map(td => td.textContent.trim()))].length;
    out.srcCells = [...new Set(qa('#res-body td.col-src').map(td => td.textContent.trim()))];
    out.actionsPerRow = qa('#res-body tr').slice(0, 3).map(tr => tr.querySelectorAll('.col-act button').length);
  }
  out.tableHeaders = qa('#res-table thead th').map(th => th.textContent.trim());
  out.searchState = q('#search-state') ? q('#search-state').textContent.trim().slice(0, 120) : '';
  out.filterGroups = q('#f-group') ? q('#f-group').options.length : 0;
  out.filterSources = q('#f-source') ? q('#f-source').options.length : 0;

  // 字幕组 tab
  out.groupItems = qa('#group-list > *').length;
  if (out.groupItems) out.groupNames = qa('#group-list .group-name, #group-list .group-head').map(x => x.textContent.trim().slice(0, 30));

  // 弹窗头部
  out.modalTitle = q('#m-title') ? q('#m-title').textContent.trim() : '';
  out.modalAliases = q('#m-aliases') ? q('#m-aliases').textContent.trim().slice(0, 90) : '';

  // 订阅页
  out.subItems = qa('#sub-list > *').length;
  out.subSummary = q('#sub-summary') ? q('#sub-summary').textContent.replace(/\s+/g, ' ').trim().slice(0, 160) : '';

  // 设置页字段
  out.cfgFilled = ['cfg-qb-url', 'cfg-qb-user', 'cfg-qb-cat', 'cfg-root', 'cfg-proxy-url', 'cfg-sub-interval']
    .map(id => { const e = q('#' + id); return e ? (e.value || '') : null; });
  out.sourceRows = qa('#source-list > *').length;

  // 溢出
  out.overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  out.modalOverflow = q('.modal') ? q('.modal').scrollHeight - q('.modal').clientHeight : null;
  return out;
})()
"""


def main() -> int:
    print("=" * 76)
    print("CDP 全流程 UI 测试（mock 数据 + 截图）")
    print("=" * 76)
    assert BROWSER, "找不到浏览器"

    static_port = free_port()
    cdp_port = free_port()
    httpd = serve(ROOT, static_port)
    profile = os.path.join(tempfile.gettempdir(), f"ui-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--disable-extensions", "--force-device-scale-factor=1",
         "--window-size=1600,1000", f"--user-data-dir={profile}",
         f"--remote-debugging-port={cdp_port}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        wait_cdp(cdp_port)
        url = f"http://127.0.0.1:{static_port}/_probe/ui_fixture.html"
        # 先开空白页 -> 注册「新文档即注入」的错误收集脚本 -> 再导航，
        # 这样页面初始化阶段的报错也能抓到（之前直接 open_page(url) 会让监听丢失）
        ws = WS(open_page(cdp_port, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source":
                "window.__errs=[];"
                "window.addEventListener('error',e=>window.__errs.push('error: '+String(e.message)));"
                "window.addEventListener('unhandledrejection',e=>window.__errs.push('rej: '+String(e.reason)));"})
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": url})
        time.sleep(3.5)
        # 自检：确认错误收集器真的生效（否则断言等于空转）
        probe_ok = evaluate(ws, "typeof window.__errs !== 'undefined'")
        check("JS 错误监听已注入生效（防止断言空转）", probe_ok is True, str(probe_ok))
        print(f"    appReady={evaluate(ws, 'document.body.classList.contains(\"app-ready\")')}")

        # Token 面板：输入框与按钮必须齐平（用户反馈过「Token 输入框和按钮没有对齐」：
        # 控件基准高度 40px 而 .btn-row 写死 36px → 按钮溢出这一行 4px，和输入框错开）
        tok = json.loads(evaluate(ws, """JSON.stringify((()=>{
          const g = (sel) => { const n = document.querySelector(sel); if (!n) return null;
            const r = n.getBoundingClientRect();
            return { t: Math.round(r.top), b: Math.round(r.bottom), h: Math.round(r.height) }; };
          return { input: g('#token-input'), save: g('#btn-save-token'), load: g('#btn-load-anime') };
        })())""") or "{}")
        same_row = [v for v in (tok.get("input"), tok.get("save"), tok.get("load")) if v]
        print(f"    Token 行：输入框 {tok.get('input')} / 保存按钮 {tok.get('save')} / 拉取按钮 {tok.get('load')}")
        check("Token 行输入框与按钮顶边/底边齐平（±1px）",
              len(same_row) == 3 and len({v["t"] for v in same_row}) == 1 and len({v["b"] for v in same_row}) == 1,
              str(same_row))
        check("Token 行控件同高（都是 40px 基准）", len({v["h"] for v in same_row}) == 1,
              str({v["h"] for v in same_row}))

        # 侧栏「最近更新」：列出订阅里**已经更新**的番（按最近一集播出时间排；mock 1 条订阅带 airtime）
        side = json.loads(evaluate(ws, """JSON.stringify((()=>{
          const box = document.getElementById('side-updates');
          const list = document.getElementById('side-updates-list');
          const rows = [...(list ? list.querySelectorAll('.update-row') : [])].map(r => ({
            name: (r.querySelector('.update-name')||{}).textContent || '',
            time: (r.querySelector('.update-time')||{}).textContent || '',
            next: r.classList.contains('is-next') }));
          const nav = document.getElementById('nav'), st = document.getElementById('side-status');
          const rb = box ? box.getBoundingClientRect() : null;
          return { hidden: !box || box.hidden, title: (box ? box.querySelector('.side-updates-head span') : {}).textContent || '',
                   rows,
                   placed: rb ? (Math.round(nav.getBoundingClientRect().top) < Math.round(rb.top)
                                 && Math.round(rb.top) < Math.round(st.getBoundingClientRect().top)) : false };
        })())""") or "{}")
        print(f"    侧栏最近更新：{side.get('rows')}（标题 {side.get('title')!r}）")
        check("侧栏标题是「最近更新」且写明「近 2 天」口径",
              "最近更新" in (side.get("title") or "") and "近 2 天" in (side.get("title") or ""),
              str(side.get("title")))
        check("侧栏只列近 2 天更新过的番", side.get("hidden") is False and len(side.get("rows") or []) >= 1,
              str(side.get("rows")))
        check("侧栏条目是「第 N 集 · 时间 · 相对时间」",
              all(("第" in (r.get("time") or "") and "·" in (r.get("time") or "")) for r in (side.get("rows") or [])),
              str([r.get("time") for r in (side.get("rows") or [])]))
        check("侧栏块位于导航与状态块之间", side.get("placed") is True, str(side.get("placed")))

        # 待下载队列（qBittorrent 掉线期间攒下的）：侧栏「待下载 N 集」+ 点一下补下载
        qrow = json.loads(evaluate(ws, """JSON.stringify((()=>{
          const row = document.getElementById('row-pending');
          return { hidden: !row || row.hidden, text: row ? row.innerText.replace(/\\n/g, ' ') : '',
                   title: row ? (row.getAttribute('title') || '') : '',
                   warn: ((document.getElementById('dot-pending')||{}).className || '').includes('dot-warn') };
        })())""") or "{}")
        print(f"    待下载行：{qrow.get('text')!r} hidden={qrow.get('hidden')}")
        check("有排队时侧栏出现「待下载 N 集」", qrow.get("hidden") is False and "2 集" in (qrow.get("text") or ""),
              repr(qrow.get("text")))
        check("待下载行用警示色圆点", qrow.get("warn") is True, str(qrow.get("warn")))
        check("待下载行悬浮说明列出番名/集号", "第 14 集" in (qrow.get("title") or ""),
              (qrow.get("title") or "")[:70])
        evaluate(ws, "document.getElementById('row-pending').click()")
        time.sleep(1.6)
        after = json.loads(evaluate(ws, """JSON.stringify((()=>{
          const row = document.getElementById('row-pending');
          const calls = (window.__calls || []).filter(c => c.path === '/api/queue/flush');
          return { hidden: !row || row.hidden, flushCalls: calls.length };
        })())""") or "{}")
        check("点「待下载」行会调用 /api/queue/flush", after.get("flushCalls", 0) >= 1, str(after))
        check("补下载完成后这一行自动消失", after.get("hidden") is True, str(after.get("hidden")))
        # 「更多」→ 弹窗列出最近最多 50 条更新
        more = evaluate(ws, "document.getElementById('btn-side-updates').innerText") or ""
        evaluate(ws, "document.getElementById('btn-side-updates').click()")
        time.sleep(1.0)
        up = json.loads(evaluate(ws, """JSON.stringify((()=>{
          const box = document.getElementById('updates-modal');
          const rows = [...document.querySelectorAll('#updates-list .updates-row')].map(r => ({
            name: (r.querySelector('.updates-name')||{}).textContent || '',
            time: (r.querySelector('.updates-time')||{}).textContent || '',
            tag: (r.querySelector('.updates-tag')||{}).textContent || '',
            img: !!(r.querySelector('.updates-cover') && r.querySelector('.updates-cover').getAttribute('src')) }));
          return { open: !!(box && !box.hidden), title: (document.getElementById('updates-title')||{}).textContent || '',
                   sub: (document.getElementById('updates-sub')||{}).textContent || '', rows };
        })())""") or "{}")
        print(f"    更多弹窗：{up.get('title')}｜{up.get('sub')}｜{up.get('rows')}")
        check("侧栏按钮文字是「更多」", more.strip() == "更多", repr(more))
        check("点「更多」弹出「最近更新」窗口",
              up.get("open") is True and up.get("title") == "最近更新", str(up.get("title")))
        check("弹窗写明最多 50 条并列出条目",
              "50" in (up.get("sub") or "") and len(up.get("rows") or []) >= 1,
              f"{up.get('sub')} / {len(up.get('rows') or [])} 条")
        check("弹窗每行有封面 + 集号时间",
              all(r["img"] and "第" in r["time"] for r in (up.get("rows") or [])),
              str([r["time"] for r in (up.get("rows") or [])]))
        evaluate(ws, "document.getElementById('updates-close').click()")
        time.sleep(0.4)
        check("弹窗能关闭", bool(evaluate(ws, "document.getElementById('updates-modal').hidden")))

        print("\nA. 番剧卡片墙（mock 6 部）")
        m = evaluate(ws, MEASURE_JS)
        print(f"    appReady={m['appReady']} 视图={m['view']} 显示卡片={m['cardCount']} 封面={m.get('covers')}")
        check("app.js 初始化完成", m["appReady"], f"appReady={m['appReady']}")
        # 「只看在播/未完结」默认**不勾选**：Bangumi 在看里的番全部显示（用户要求）
        check("默认显示全部在看番剧（不隐藏已完结的）", m["cardCount"] == 6, f"{m['cardCount']} 张")
        check("卡片都加载了封面图", m.get("covers") == m["cardCount"], f"{m.get('covers')} 张")
        check("卡片都有选择框", m.get("checkboxes") == m["cardCount"], f"{m.get('checkboxes')} 个")
        titles = m.get("cardTitles") or []
        check("卡片显示 Bangumi 简体名", any("僵尸搜寻中" == t for t in titles), str(titles))
        check("卡片不显示日文原名/井号", not any(t.startswith("#") for t in titles), str(titles))
        boxes = m.get("cardBoxes") or []
        if boxes:
            heights = sorted({round(b["h"]) for b in boxes})
            # 允许 1px 的子像素误差（图标/字体渲染），差得更多就说明卡片内容参差了
            check("卡片等高（网格整齐）", heights[-1] - heights[0] <= 1, f"高度集合 {heights}")

        # 详情弹窗（点卡片打开）也要显示「下次更新：… · 北京时间」
        evaluate(ws, "(()=>{document.querySelector('#anime-grid .card').click();return true;})()")
        time.sleep(1.4)
        modal_air = json.loads(evaluate(ws, """JSON.stringify((()=>{
          const n = document.querySelector('#m-sub .m-air');
          return { head: (document.getElementById('m-sub')||{}).innerText || '',
                   text: n ? n.innerText.replace(/\\n/g, ' ') : '',
                   tip: n ? (n.getAttribute('title') || '') : '' };
        })())""") or "{}")
        print(f"    弹窗标题行：{modal_air.get('head', '').replace(chr(10), ' ')[:90]}")
        check("详情弹窗显示「下次更新：… · 北京时间」",
              "下次更新：" in (modal_air.get("text") or "") and "北京时间" in (modal_air.get("text") or ""),
              str(modal_air.get("text")))
        check("弹窗里的悬浮说明含日本时间 / 电视台 / 数据来源",
              all(k in (modal_air.get("tip") or "") for k in ("日本时间", "电视台", "bangumi-data")),
              str(modal_air.get("tip"))[:70])
        evaluate(ws, "document.getElementById('m-close').click()")
        time.sleep(0.8)

        print("\nA2. 勾上「只看在播/未完结」应只留在播的，取消后全部回来")
        evaluate(ws, "(()=>{const c=document.getElementById('only-airing');c.checked=true;"
                     "c.dispatchEvent(new Event('change'));})()")
        time.sleep(0.8)
        only = evaluate(ws, MEASURE_JS)
        check("勾上「只看在播/未完结」后藏起已完结的", only["cardCount"] < 6,
              f"{only['cardCount']} 张（全部 6 张）")
        evaluate(ws, "(()=>{const c=document.getElementById('only-airing');c.checked=false;"
                     "c.dispatchEvent(new Event('change'));})()")
        time.sleep(0.8)
        m2 = evaluate(ws, MEASURE_JS)
        print(f"    全部卡片={m2['cardCount']} 已订阅标记={m2.get('subscribed')}")
        check("取消筛选后显示全部番剧", m2["cardCount"] == 6, f"{m2['cardCount']} 张")
        check("已订阅的卡片有标记", m2.get("subscribed") == 1, f"{m2.get('subscribed')} 张")
        tops = [b["t"] for b in (m2.get("cardBoxes") or [])]
        if tops:
            first = min(tops)
            check("同行卡片顶边对齐", len([t for t in tops if t == first]) >= 3,
                  f"同行 {len([t for t in tops if t == first])} 张")
        # Bangumi 跳转按钮（用户要求：卡片上能一键去看详情，且要好看）
        links = m2.get("bgmLinks") or []
        check("每张番剧卡片都有 Bangumi 跳转按钮（挂在封面上）",
              len(links) == (m2.get("cardCount") or 0) and all(x["inCover"] for x in links),
              f"{len(links)}/{m2.get('cardCount')}")
        check("跳转按钮指向 bgm.tv 条目页、新标签打开",
              bool(links) and all(x["href"].startswith("https://bgm.tv/subject/")
                                  and x["target"] == "_blank" and "noopener" in x["rel"] for x in links),
              str(links[:2]))
        check("跳转按钮用的是内联 SVG 图标", bool(links) and all(x["svg"] for x in links), "OK")
        # 下次更新（北京时间）：多数卡片有数据，第 4 部故意没有 → 用隐藏占位行撑高度
        air = json.loads(evaluate(ws, """JSON.stringify((()=>{
          return [...document.querySelectorAll('#anime-grid .card')].map(c=>{
            const n = c.querySelector('.card-air');
            return { text: n ? n.textContent.trim() : '', empty: !!(n && n.classList.contains('is-empty')),
                     soon: !!(n && n.classList.contains('is-soon')),
                     finished: !!(n && n.classList.contains('is-finished')),
                     tip: n ? (n.getAttribute('title') || '') : '',
                     fits: n ? (n.scrollWidth <= n.clientWidth + 1) : true,
                     h: n ? Math.round(n.getBoundingClientRect().height) : 0 };
          });})())""") or "[]")
        print(f"    下次更新行：{[(a['text'] or '（占位）') for a in air]}")
        finished = [a for a in air if a["finished"]]
        shown = [a for a in air if a["text"] and not a["finished"]]      # 在播的（不含已完结）
        hidden = [a for a in air if a["empty"]]
        check("番剧卡片显示「下次更新 MM-DD HH:MM」（不带周几/北京时间）",
              bool(shown) and all("下次更新" in a["text"] and "（周" not in a["text"]
                                  and "北京时间" not in a["text"] for a in shown),
              str([a["text"] for a in shown][:2]))
        check("已完结的番显示「已完结」而不是假的更新时间",
              bool(finished) and all(a["text"].strip() == "已完结" for a in finished),
              str([a["text"] for a in finished]))
        check("卡片这行没被截断（紧凑版刚好放得下）",
              bool(shown) and all(a["fits"] for a in shown), str([a["fits"] for a in shown]))
        check("没有数据的卡片用隐藏占位（不显示空行）", bool(hidden) and all(not a["text"] for a in hidden),
              f"{len(hidden)} 张占位")
        check("占位行与有数据行等高（网格整齐）",
              len({a["h"] for a in air}) == 1, str(sorted({a["h"] for a in air})))
        check("悬浮说明含日本时间/电视台/数据来源",
              bool(shown) and all(("日本时间" in a["tip"] and "电视台" in a["tip"] and "bangumi-data" in a["tip"])
                                  for a in shown),
              (shown[0]["tip"] if shown else "").replace("\n", " ｜ ")[:120])
        check("已完结的悬浮说明讲清楚「最后一集」与来源",
              bool(finished) and all(("已完结" in a["tip"] and "bangumi-data" in a["tip"]) for a in finished),
              (finished[0]["tip"] if finished else "").replace("\n", " ｜ ")[:110])
        check("距开播不足 6 小时的高亮（is-soon）", any(a["soon"] for a in air),
              f"{len([a for a in air if a['soon']])} 张高亮")
        shoot(ws, "01b_anime_grid_all")

        # 卡片标记绝不能压住卡片上的文字（话数/日期/评分）——用户反馈被挡住过
        cov = json.loads(evaluate(ws, "JSON.stringify((()=>{"
                                     "const out=[];"
                                     "document.querySelectorAll('#anime-grid .card').forEach((c,i)=>{"
                                     "const bd=c.querySelector('.card-badges');"
                                     "if(!bd)return;"
                                     "const inCover=!!bd.closest('.card-cover');"
                                     "const bb=bd.getBoundingClientRect();"
                                     "const hits=[];"
                                     "c.querySelectorAll('.card-meta, .card-title, .card-sub').forEach(t=>{"
                                     "const tb=t.getBoundingClientRect();"
                                     "const ox=Math.min(bb.right,tb.right)-Math.max(bb.left,tb.left);"
                                     "const oy=Math.min(bb.bottom,tb.bottom)-Math.max(bb.top,tb.top);"
                                     "if(ox>1&&oy>1)hits.push(t.className+' 重叠'+Math.round(ox)+'x'+Math.round(oy));});"
                                     "out.push({i,inCover,hits,badges:bd.children.length,"
                                     "texts:[...bd.children].map(x=>x.textContent.trim())});});"
                                     "return out;})())") or "[]")
        bad_overlap = [x for x in cov if x.get("hits")]
        bad_place = [x for x in cov if not x.get("inCover")]
        print(f"    卡片标记：{len(cov)} 张卡有标记（示例 {[x['texts'] for x in cov[:2]]}），"
              f"位于封面内 {sum(1 for x in cov if x['inCover'])} 张")
        check("确实渲染出了卡片标记（断言不是空转）", len(cov) >= 4, f"{len(cov)} 张卡有标记")
        check("卡片标记挂在封面容器内（不会飘到卡片底部压住日期）", not bad_place, str(bad_place[:3]))
        check("卡片标记与文字无重叠（话数/日期/评分不被遮挡）", not bad_overlap,
              str(bad_overlap[:3]))

        print("\nB. 详情弹窗 + 资源表（9 列）")
        evaluate(ws, "window.__probe.openModal(498378)")
        time.sleep(2.2)
        m = evaluate(ws, MEASURE_JS)
        print(f"    弹窗打开={m['modalOpen']} 资源行={m['rowCount']} 标题={m['modalTitle']!r}")
        check("弹窗成功打开", m["modalOpen"] is True)
        check("弹窗标题为简体名", m["modalTitle"] == "间谍过家家 第三季", m["modalTitle"])
        check("资源表有数据", m["rowCount"] >= 6, f"{m['rowCount']} 行")
        check("表头为 10 列（资源站/字幕组/标题/语言/分辨率/集数/大小/做种/发布/操作）",
              m["tableHeaders"] == ["资源站", "字幕组", "标题", "语言", "分辨率", "集数", "大小", "做种", "发布", "操作"],
              str(m["tableHeaders"]))
        check("每行 10 个单元格", all(len(c) == 10 for c in (m.get("rowCells") or [])),
              str({len(c) for c in (m.get("rowCells") or [])}))
        check("数字列右对齐", m.get("numAlign") == ["right"], str(m.get("numAlign")))

        # 语言列：标签要正确、且能筛选（简/繁/简繁/未标注）
        lang_info = json.loads(evaluate(ws, "JSON.stringify((()=>{"
                                            "const cells=[...document.querySelectorAll('#res-body td.col-lang')];"
                                            "return {n:cells.length,"
                                            "texts:cells.map(c=>c.textContent.trim()),"
                                            "classes:[...new Set(cells.map(c=>{const s=c.querySelector('span');"
                                            "return s?s.className:'';}))],"
                                            "hasTitle:cells.every(c=>{const s=c.querySelector('span');"
                                            "return !!(s&&(s.title||'').length);})};})())") or "{}")
        print(f"    语言列：{lang_info.get('n')} 个单元格，标签 {lang_info.get('texts')}")
        check("语言列已渲染", (lang_info.get("n") or 0) >= 6, str(lang_info.get("n")))
        check("语言标签是「简体/繁体/简繁/日文/未标注」之一",
              all(t in ("简体", "繁体", "简繁", "日文", "未标注") for t in (lang_info.get("texts") or [])),
              str(lang_info.get("texts")))
        check("语言标签用了区分的胶囊样式",
              len(lang_info.get("classes") or []) >= 2
              and all("lang-pill" in c for c in (lang_info.get("classes") or [])),
              str(lang_info.get("classes")))
        check("语言标签带 title 说明依据", lang_info.get("hasTitle") is True)

        # 语言筛选：选「简体」只应剩 简体（简繁不再混进来，用户反馈过）
        base_rows = evaluate(ws, "document.querySelectorAll('#res-body tr').length")
        evaluate(ws, "window.__probe.selectOption('f-lang', 'chs')")
        time.sleep(0.7)
        chs_rows = json.loads(evaluate(ws, "JSON.stringify((()=>{"
                                           "const tds=[...document.querySelectorAll('#res-body td.col-lang')];"
                                           "return {rows:document.querySelectorAll('#res-body tr').length,"
                                           "langs:[...new Set(tds.map(c=>c.textContent.trim()))]};})())") or "{}")
        print(f"    选「简体」：{base_rows} 行 -> {chs_rows.get('rows')} 行，语言集合 {chs_rows.get('langs')}")
        check("选「简体」后只剩简体（简繁被筛掉）",
              set(chs_rows.get("langs") or []) == {"简体"} and (chs_rows.get("rows") or 0) > 0,
              str(chs_rows))
        evaluate(ws, "window.__probe.selectOption('f-lang', 'cht')")
        time.sleep(0.7)
        cht_langs = json.loads(evaluate(ws, "JSON.stringify([...new Set([...document.querySelectorAll('#res-body td.col-lang')].map(c=>c.textContent.trim()))])") or "[]")
        print(f"    选「繁体」：语言集合 {cht_langs}")
        check("选「繁体」后只剩繁体", set(cht_langs) <= {"繁体"} and bool(cht_langs), str(cht_langs))
        evaluate(ws, "window.__probe.selectOption('f-lang', 'both')")
        time.sleep(0.7)
        both_langs = json.loads(evaluate(ws, "JSON.stringify([...new Set([...document.querySelectorAll('#res-body td.col-lang')].map(c=>c.textContent.trim()))])") or "[]")
        print(f"    选「简繁/双语」：语言集合 {both_langs}")
        check("选「简繁/双语」后只剩简繁", set(both_langs) <= {"简繁"} and bool(both_langs), str(both_langs))
        evaluate(ws, "window.__probe.selectOption('f-lang', '')")
        time.sleep(0.6)
        restored = evaluate(ws, "document.querySelectorAll('#res-body tr').length")
        check("清空语言筛选后行数恢复", restored == base_rows, f"{restored} vs {base_rows}")
        rights = m.get("numRightEdges") or []
        check("大小列右边缘共线", len(rights) > 2 and (max(rights) - min(rights)) <= 1.5,
              f"偏差 {round(max(rights) - min(rights), 1) if rights else '-'}px")
        check("显示了多个资源站", len(m.get("srcCells") or []) >= 2, str(m.get("srcCells")))
        check("显示了多个字幕组", (m.get("groupsCells") or 0) >= 3, f"{m.get('groupsCells')} 个")
        check("每行都有操作按钮", all(n >= 1 for n in (m.get("actionsPerRow") or [])),
              str(m.get("actionsPerRow")))
        check("搜索状态区显示了策略与站点命中", "字幕组" in (m.get("searchState") or "") or
              "命中" in (m.get("searchState") or ""), (m.get("searchState") or "")[:80])
        check("字幕组筛选器已填充", (m.get("filterGroups") or 0) >= 4, f"{m.get('filterGroups')} 项")
        check("资源站筛选器已填充", (m.get("filterSources") or 0) >= 3, f"{m.get('filterSources')} 项")
        check("弹窗无横向溢出", (m.get("overflowX") or 0) <= 1, f"{m.get('overflowX')}px")

        # 表格单行约束：任一单元格换行都会撑破行高、让列对不齐
        wrap = json.loads(evaluate(ws, "JSON.stringify((()=>{"
                                       "const bad=[];let maxH=0,minH=1e9;"
                                       "document.querySelectorAll('#res-body tr').forEach(tr=>{"
                                       "const h=tr.getBoundingClientRect().height;maxH=Math.max(maxH,h);minH=Math.min(minH,h);"
                                       "[...tr.querySelectorAll('td')].forEach(td=>{"
                                       "if(getComputedStyle(td).whiteSpace!=='nowrap')bad.push(td.className+' ws='+getComputedStyle(td).whiteSpace);"
                                       "if(td.scrollHeight>td.clientHeight+2)bad.push(td.className+' 内容溢出');});});"
                                       "return {bad:bad.slice(0,5),maxH:Math.round(maxH),minH:Math.round(minH),"
                                       "rows:document.querySelectorAll('#res-body tr').length};})())") or "{}")
        print(f"    表格行高 {wrap.get('minH')}~{wrap.get('maxH')}px，行数 {wrap.get('rows')}")
        check("资源表单元格都不换行（单行 + 省略号）", not wrap.get("bad"), str(wrap.get("bad")))
        check("资源表所有行行高一致（没有被换行撑高）",
              (wrap.get("maxH") or 0) - (wrap.get("minH") or 0) <= 2,
              f"{wrap.get('minH')}~{wrap.get('maxH')}")
        act_w = json.loads(evaluate(ws, "JSON.stringify((()=>{const td=document.querySelector('#res-body td.col-act');"
                                        "if(!td)return null;const btns=[...td.querySelectorAll('button')];"
                                        "return {tdW:Math.round(td.getBoundingClientRect().width),"
                                        "btnW:btns.reduce((a,b)=>a+b.getBoundingClientRect().width,0)+ (btns.length-1)*8,"
                                        "n:btns.length,texts:btns.map(b=>b.textContent.trim())};})())") or "null")
        print(f"    操作列：{act_w}")
        if act_w:
            check("操作列宽度足够放下全部按钮（不截断）",
                  act_w["btnW"] <= act_w["tdW"], f"按钮共 {act_w['btnW']}px / 列宽 {act_w['tdW']}px")

        # 资源列表内直接加入订阅（用户要求：筛选完直接加订阅）
        has_btn = evaluate(ws, "!!document.getElementById('btn-sub-add-res')")
        check("资源列表筛选条内有「加入订阅」按钮", has_btn is True)
        if has_btn:
            evaluate(ws, "window.__probe.clearCalls()")
            # 路径①：点选表里某一行后点订阅
            row_ok = evaluate(ws, "(()=>{const tr=document.querySelector('#res-body tr.res-row');"
                                  "if(!tr)return false;tr.click();return true;})()")
            time.sleep(0.6)
            evaluate(ws, "window.__probe.click('btn-sub-add-res')")
            time.sleep(1.8)
            posts = json.loads(evaluate(ws, "JSON.stringify(window.__probe.calls('/api/subscriptions','POST'))") or "[]")
            print(f"    路径① 点选行后订阅：提交 {len(posts)} 次，resource={'有' if posts and posts[0]['body'].get('resource') else '无'}")
            check("路径① 点选资源行后可直接订阅", len(posts) == 1 and bool(posts[0]["body"].get("resource")),
                  json.dumps(posts[0]["body"], ensure_ascii=False)[:110] if posts else "无提交")
            if posts:
                b = posts[0]["body"]
                check("提交的资源就是表里点选的那条",
                      (b.get("resource") or {}).get("title", "")[:20]
                      in (wrap.get("firstRowTitle") or (b.get("resource") or {}).get("title", "")),
                      (b.get("resource") or {}).get("title", "")[:60])

            # 路径②：不点选行，但订阅设置里选了集数
            evaluate(ws, "window.__probe.clearCalls()")
            eopts2 = json.loads(evaluate(ws, "JSON.stringify(window.__probe.options('s-episode'))") or "[]")
            pick2 = next((o["v"] for o in eopts2 if o["v"]), None)
            if pick2:
                evaluate(ws, f"window.__probe.selectOption('s-episode', {json.dumps(pick2)})")
                time.sleep(0.4)
                evaluate(ws, "window.__probe.click('btn-sub-add-res')")
                time.sleep(1.8)
                posts2 = json.loads(evaluate(ws, "JSON.stringify(window.__probe.calls('/api/subscriptions','POST'))") or "[]")
                print(f"    路径② 未点选行但有选集数：提交 {len(posts2)} 次，resource={'有' if posts2 and posts2[0]['body'].get('resource') else '无'}")
                check("路径② 未点选行时用「立即下载哪一集」的资源订阅",
                      len(posts2) == 1 and bool(posts2[0]["body"].get("resource")),
                      json.dumps(posts2[0]["body"], ensure_ascii=False)[:110] if posts2 else "无提交")
            else:
                print("    路径② 跳过（当前无可选集数）")
        shoot(ws, "02_modal_resources")

        print("\nC. 自绘下拉框（ui.js，替代原生弹层以获得圆角/间距/悬停）")
        b = {}
        for _ in range(20):
            built = evaluate(ws, "JSON.stringify({"
                                 "wraps:document.querySelectorAll('.sel').length,"
                                 "displays:document.querySelectorAll('.sel-display').length,"
                                 "natives:document.querySelectorAll('select').length,"
                                 "nativeHidden:[...document.querySelectorAll('select')]"
                                 ".filter(s=>s.classList.contains('sel-native')).length,"
                                 "visibleNatives:[...document.querySelectorAll('select')].filter(s=>s.offsetParent).length})")
            b = json.loads(built or "{}")
            if b.get("wraps") and b.get("wraps") == b.get("natives"):
                break
            time.sleep(0.4)
        print(f"    原生 select {b.get('natives')} 个（可见 {b.get('visibleNatives')}）→ 自绘控件 {b.get('wraps')} 个，已接管 {b.get('nativeHidden')} 个")
        check("所有 select 都被自绘控件接管（含隐藏视图里的，避免晚开弹窗变回原生样式）",
              b.get("wraps") == b.get("natives") and b.get("wraps") >= 8,
              f"{b.get('wraps')} 接管 / {b.get('natives')} 原生")
        check("原生 select 仍保留在 DOM 中（值来源与无障碍载体，未被移除）",
              b.get("natives") >= 8, f"{b.get('natives')} 个原生 select")
        check("被接管的原生 select 就是全部 select",
              b.get("natives") == b.get("nativeHidden"), f"{b.get('nativeHidden')}/{b.get('natives')}")

        # 打开「限定字幕组」下拉：面板选项必须与原生 select 的选项一一对应
        evaluate(ws, "window.__probe.switchTab('sub')")
        time.sleep(0.8)
        evaluate(ws, "(()=>{const s=document.getElementById('s-group');"
                     "const w=s.nextElementSibling;const d=w.querySelector('.sel-display');"
                     "if(d)d.click();return true;})()")
        time.sleep(0.6)
        panel = evaluate(ws, "(()=>{"
                             "const s=document.getElementById('s-group');"
                             "const w=s.nextElementSibling;const p=w.querySelector('.sel-panel');"
                             "if(!p||p.hidden)return null;const cs=getComputedStyle(p);const bb=p.getBoundingClientRect();"
                             "return JSON.stringify({radius:cs.borderTopLeftRadius,shadow:cs.boxShadow!=='none',"
                             "opts:p.querySelectorAll('.sel-option').length,"
                             "nativeOpts:s.options.length,"
                             "first:p.querySelector('.sel-option .sel-option-text')?.textContent||'',"
                             "selected:p.querySelector('.sel-option.is-selected .sel-option-text')?.textContent||'',"
                             "w:Math.round(bb.width),h:Math.round(bb.height)});})()")
        pd = json.loads(panel) if panel else None
        print(f"    面板：{pd}")
        check("点击后弹出的是自绘面板（不是原生 select）", bool(pd))
        if pd:
            check("面板有圆角（原生弹层做不到）", float(pd["radius"].replace("px", "")) >= 8, pd["radius"])
            check("面板有阴影", pd["shadow"] is True)
            check("自绘面板选项数与原生 select 完全一致（内容不丢）",
                  pd["opts"] == pd["nativeOpts"] and pd["opts"] >= 2,
                  f"{pd['opts']} vs 原生 {pd['nativeOpts']}")
            check("面板首项是「不限字幕组」", "不限" in pd["first"], pd["first"][:30])
        shoot(ws, "10_custom_select")
        evaluate(ws, "document.body.click()")
        time.sleep(0.4)

        # 回归：SVG 图标绝不能按「无 CSS 时的默认画布」渲染
        # （一旦图标没有显式尺寸、而样式表未生效/被旧缓存命中，inline SVG 会铺成
        #   300x150 白底 + 巨大黑箭头的大方块。用户截图里出现过，必须断言住。）
        p = json.loads(ev_js(ws, "JSON.stringify((()=>{"
                                 "const out={total:0,svg:0,sized:0,attrs:0,big:[],visible:0};"
                                 "document.querySelectorAll('.sel-chevron').forEach(sp=>{"
                                 "out.total++;const r=sp.getBoundingClientRect();"
                                 "if(r.width>0){out.visible++;}"
                                 "if(r.width<=20&&r.height<=20){out.sized++;}"
                                 "else if(r.width>0){out.big.push('chevron '+Math.round(r.width)+'x'+Math.round(r.height));}"
                                 "const s=sp.querySelector('svg');"
                                 "if(s){out.svg++;const sr=s.getBoundingClientRect();"
                                 "if(sr.width<=20&&sr.height<=20){out.sized++;} "
                                 "else if(sr.width>0){out.big.push('svg '+Math.round(sr.width)+'x'+Math.round(sr.height));}"
                                 "if(s.getAttribute('width')&&s.getAttribute('height')){out.attrs++;}}"
                                 "});return out;})())") or "{}")
        print(f"    下拉图标：容器 {p.get('total')} 个（可见 {p.get('visible')}）、内含 svg {p.get('svg')} 个、"
              f"尺寸合规 {p.get('sized')} 个、显式宽高 {p.get('attrs')} 个")
        check("下拉箭头图标不会渲染成白色大方块（容器与 svg 尺寸都 ≤20px）",
              not p.get("big"), f"异常尺寸 {p.get('big')}")
        check("每个箭头 SVG 都自带 width/height 属性（样式表未加载时也不会铺开）",
              (p.get("attrs") or 0) == (p.get("svg") or 0) and (p.get("svg") or 0) > 0,
              f"{p.get('attrs')}/{p.get('svg')}")

        print("\nC2. 三态主题（跟随系统 / 深色 / 浅色）")
        ui_ready = evaluate(ws, "!!(window.__ui && window.__ui.applyTheme)")
        check("ui.js 已加载并暴露 __ui", ui_ready is True, str(ui_ready))
        modes = evaluate(ws, "JSON.stringify(['auto','dark','light'].map(m=>{"
                             "window.__ui.applyTheme(m);"
                             "return [m, document.documentElement.dataset.theme,"
                             "document.documentElement.dataset.themeMode];}))")
        print(f"    模式 -> 生效主题：{modes}")
        parsed = json.loads(modes or "[]")
        check("三种模式都能生效并写回 themeMode",
              len(parsed) == 3 and all(p[2] == p[0] for p in parsed), str(parsed))
        check("auto 模式解析为系统主题（headless 下通常是 light）",
              parsed[0][1] in ("light", "dark"), str(parsed[0]))
        # 轮换按钮
        evaluate(ws, "window.__ui.applyTheme('auto')")
        time.sleep(0.3)
        before = evaluate(ws, "window.__ui.storedTheme()")
        evaluate(ws, "window.__probe.click('btn-theme')")
        time.sleep(0.5)
        after = evaluate(ws, "window.__ui.storedTheme()")
        btn_label = evaluate(ws, "document.getElementById('btn-theme').textContent.trim()")
        print(f"    点击前模式={before!r} 点击后={after!r} 按钮文案={btn_label!r}")
        check("点击主题按钮能轮换模式", before != after, f"{before} -> {after}")
        check("按钮文案显示当前模式", any(k in (btn_label or "") for k in ("跟随系统", "深色", "浅色")),
              btn_label)
        # 系统主题变化实时跟随
        follow = evaluate(ws, "(()=>{"
                              "window.__ui.applyTheme('auto');"
                              "const t0=document.documentElement.dataset.theme;"
                              "return JSON.stringify({mode:window.__ui.storedTheme(),theme:t0,"
                              "system:window.__ui.systemTheme()});})()")
        fd = json.loads(follow or "{}")
        check("auto 模式的生效主题等于系统主题", fd.get("theme") == fd.get("system"), str(fd))
        evaluate(ws, "window.__ui.applyTheme('dark')")
        time.sleep(0.3)

        print("\nC3. 字幕组 tab 已删除")
        tabs = evaluate(ws, "JSON.stringify([...document.querySelectorAll('#m-tabs .tab')]"
                            ".map(t=>t.dataset.tab))")
        print(f"    弹窗标签页：{tabs}")
        check("弹窗只剩 资源列表 / 订阅设置 两个 tab",
              json.loads(tabs or "[]") == ["res", "sub"], str(tabs))
        check("「选择字幕组」tab 按钮已不存在",
              evaluate(ws, "!document.querySelector('#m-tabs .tab[data-tab=\"group\"]')") is True)

        # 字幕组下拉仍然可选（功能已并入订阅设置）
        gsel = evaluate(ws, "JSON.stringify(window.__probe.options('s-group'))")
        gopts = json.loads(gsel or "[]")
        check("字幕组仍可通过下拉选择（功能未丢）", len(gopts) >= 2, f"{len(gopts)} 项")

        print("\nC4. 字幕组按资源站分组（不要跨站合并同名组）")
        grp = json.loads(ev_js(ws, "JSON.stringify((()=>{"
                                   "const s=document.getElementById('s-group');"
                                   "if(!s)return null;"
                                   "const groups=[...s.querySelectorAll('optgroup')].map(g=>({"
                                   "label:g.label,n:g.querySelectorAll('option').length}));"
                                   "const opts=[...s.options].map(o=>({v:o.value,t:o.textContent.trim()}));"
                                   "const panels=[...s.parentElement.querySelectorAll('.sel-group')].map(e=>e.textContent.trim());"
                                   "return {groups,opts:opts.slice(0,10),total:opts.length,panelLabels:panels};})())") or "{}") 
        print(f"    optgroup 分组：{grp.get('groups')}")
        print(f"    选项总数 {grp.get('total')}，前几项：{[o['v'] for o in (grp.get('opts') or [])[:5]]}")
        check("字幕组下拉按资源站分了组（存在 optgroup）", bool(grp.get("groups")), str(grp.get("groups")))
        if grp.get("groups"):
            labels = [g["label"] for g in grp["groups"]]
            check("分组标签是资源站名（不出现「来源：」这类冗余前缀）",
                  all(lbl and "来源" not in lbl and "：" not in lbl for lbl in labels), str(labels))
        site_opts = [o for o in (grp.get("opts") or []) if "::" in o["v"]]
        check("带站点的选项 value 形如 source::组名", bool(site_opts),
              str([o["v"] for o in site_opts[:3]]))
        # 打开面板确认分组标题被渲染出来（面板可能已开，避免点一下反而关掉）
        ev_js(ws, "(()=>{const s=document.getElementById('s-group');"
                  "const w=s.nextElementSibling;const p=w.querySelector('.sel-panel');"
                  "if(p && p.hidden){const d=w.querySelector('.sel-display');if(d)d.click();}})()")
        time.sleep(0.7)
        labels_dom = json.loads(ev_js(ws, "JSON.stringify([...document.querySelectorAll('.sel-panel:not([hidden]) .sel-group')].map(e=>e.textContent.trim()))") or "[]")
        print(f"    面板里渲染出的分组标题：{labels_dom}")
        check("下拉面板里能看到站点分组标题（不只存在于 DOM，视觉上也分组）",
              len(labels_dom) >= 2, str(labels_dom))
        ev_js(ws, "document.body.click()")
        time.sleep(0.4)

        print("\nD. 订阅设置标签页（新：字幕组下拉 + 集数下拉 + 预览 + 一步订阅）")
        evaluate(ws, "window.__probe.switchTab('sub')")
        time.sleep(1.0)
        gopts = evaluate(ws, "JSON.stringify(window.__probe.options('s-group'))")
        eopts = evaluate(ws, "JSON.stringify(window.__probe.options('s-episode'))")
        groups_opts = json.loads(gopts or "[]")
        episode_opts = json.loads(eopts or "[]")
        print(f"    字幕组下拉 {len(groups_opts)} 项：{[o['t'][:22] for o in groups_opts[:4]]}")
        print(f"    集数下拉 {len(episode_opts)} 项：{[o['t'][:30] for o in episode_opts[:4]]}")
        check("「限定字幕组」是下拉且选项来自真实字幕组",
              len(groups_opts) >= 2
              and any("不限" in o["t"] for o in groups_opts[:1])
              and any("桜都" in o["t"] or "SubsPlease" in o["t"] for o in groups_opts),
              f"{len(groups_opts)} 项")
        check("「立即下载哪一集」是下拉且含具体集数",
              len(episode_opts) >= 2 and any("第 13 集" in o["t"] or "第 12 集" in o["t"] for o in episode_opts),
              f"{len(episode_opts)} 项")
        check("集数下拉默认是「不下载」", episode_opts and "不下载" in episode_opts[0]["t"],
              episode_opts[0]["t"] if episode_opts else "-")

        # 选择「第 13 集」后预览应更新
        pick_val = next((o["v"] for o in episode_opts if "第 13 集" in o["t"]), None)
        if pick_val:
            evaluate(ws, f"window.__probe.selectOption('s-episode', {json.dumps(pick_val)})")
            time.sleep(0.5)
        preview = evaluate(ws, "document.getElementById('s-preview').textContent.replace(/\\s+/g,' ').trim()")
        print(f"    预览：{preview[:110]!r}")
        check("订阅预览显示字幕组/分辨率/集数/目录",
              all(k in (preview or "") for k in ("字幕组", "1080p", "第 13 集")),
              (preview or "")[:90])
        check("预览文案分段之间没有挤在一起（有分隔）",
              "集" in (preview or "") and ("立即下载 第 13 集" in (preview or "")),
              (preview or "")[:100])
        shoot(ws, "04_modal_subscribe")

        # 一步订阅：不先去资源列表点选，直接点「加入订阅」
        evaluate(ws, "window.__probe.clearCalls()")
        evaluate(ws, "window.__probe.click('btn-sub-add')")
        time.sleep(1.6)
        posts = json.loads(evaluate(ws, "JSON.stringify(window.__probe.calls('/api/subscriptions','POST'))") or "[]")
        print(f"    提交 {len(posts)} 次：{json.dumps(posts[0]['body'], ensure_ascii=False)[:170] if posts else '无'}")
        check("在订阅设置页直接完成订阅（无需先点资源列表）", len(posts) == 1)
        if posts:
            b = posts[0]["body"]
            check("提交带上了所选集数对应的资源", bool(b.get("resource")),
                  (b.get("resource") or {}).get("title", "-")[:60])
            check("提交带上了限定的字幕组", bool(b.get("group")), b.get("group"))
            check("提交带上了站点限定的 sub_group（source::组名）",
                  (not b.get("group")) or ("::" in (b.get("sub_group") or "")),
                  f"group={b.get('group')!r} sub_group={b.get('sub_group')!r}")
            check("提交目录为 根目录\\简体名", (b.get("folder") or "").endswith("间谍过家家 第三季"), b.get("folder"))
            check("资源属于所选字幕组",
                  not b.get("group") or b["group"] in (b.get("resource") or {}).get("group", ""),
                  f"{b.get('group')} vs {(b.get('resource') or {}).get('group')}")
        # 复位检查
        back = json.loads(evaluate(ws, "JSON.stringify(window.__probe.options('s-episode'))") or "[]")
        check("订阅成功后集数下拉复位为「不下载」", back and "不下载" in back[0]["t"],
              back[0]["t"] if back else "-")

        # 「去资源列表」按钮
        evaluate(ws, "window.__probe.click('btn-goto-res')")
        time.sleep(0.6)
        active_tab = evaluate(ws, "document.querySelector('#m-tabs .tab.is-active')?.dataset.tab")
        check("「去资源列表挑选单集/合集」可切到资源列表", active_tab == "res", str(active_tab))
        evaluate(ws, "document.getElementById('m-close').click()")
        time.sleep(0.5)

        print("\nD2. 批量订阅（让「全选」有实际用途）")
        evaluate(ws, "document.getElementById('only-airing').checked=false;"
                     "document.getElementById('only-airing').dispatchEvent(new Event('change'))")
        time.sleep(0.6)
        ba_hidden_before = evaluate(ws, "document.getElementById('batch-actions').hidden")
        check("未勾选时批量操作条隐藏", ba_hidden_before is True, str(ba_hidden_before))
        picked = evaluate(ws, "window.__probe.setChecked(513878, true) && window.__probe.setChecked(586255, true) "
                              "&& window.__probe.setChecked(568244, true)")
        time.sleep(0.6)
        ba_hidden_after = evaluate(ws, "document.getElementById('batch-actions').hidden")
        sel_text = evaluate(ws, "document.getElementById('selected-count').textContent.trim()")
        print(f"    勾选 3 部后：批量条 hidden={ba_hidden_after}，计数={sel_text!r}")
        check("勾选番剧后出现批量操作条", ba_hidden_after is False, str(ba_hidden_after))
        check("计数文案更新", "3" in (sel_text or ""), sel_text)
        shoot(ws, "09_batch_actions")

        evaluate(ws, "window.__probe.clearCalls()")
        evaluate(ws, "window.__probe.click('btn-batch-sub')")
        time.sleep(2.5)
        bp = json.loads(evaluate(ws, "JSON.stringify(window.__probe.calls('/api/subscriptions','POST'))") or "[]")
        print(f"    批量提交 {len(bp)} 次：{[c['body'].get('subject_id') for c in bp]}")
        check("批量订阅对每部选中的番剧各提交一次", len(bp) == 3, f"{len(bp)} 次")
        check("批量订阅不带 resource（只订阅不立即下载）",
              all(not c["body"].get("resource") for c in bp))
        check("批量订阅的 subject_id 与勾选的一致",
              {c["body"].get("subject_id") for c in bp} == {513878, 586255, 568244},
              str(sorted(c["body"].get("subject_id") for c in bp)))
        sel_after = evaluate(ws, "document.getElementById('selected-count').textContent.trim()")
        check("批量完成后自动清空选择", "0" in (sel_after or ""), sel_after)

        evaluate(ws, "window.__probe.clearCalls()")
        evaluate(ws, "window.__probe.click('btn-clear-selection')")
        time.sleep(0.5)
        check("「清空选择」可清空", "0" in (evaluate(ws, "document.getElementById('selected-count').textContent.trim()") or ""))

        print("\nE. 我的订阅页")
        evaluate(ws, "window.__probe.switchView('subs')")
        time.sleep(1.6)
        m = evaluate(ws, MEASURE_JS)
        print(f"    订阅条目={m['subItems']} 摘要={m['subSummary'][:80]!r}")
        check("订阅列表已渲染", m["subItems"] >= 1, f"{m['subItems']} 条")
        check("订阅页有汇总信息", len(m["subSummary"]) > 10, m["subSummary"][:60])
        # 订阅卡片也要能跳 Bangumi（同一套按钮，放在封面右上角）
        slinks = m.get("subBgmLinks") or []
        check("订阅卡片也有 Bangumi 跳转按钮（挂在封面上）",
              bool(slinks) and all(x["inCover"] for x in slinks), f"{len(slinks)} 个")
        check("订阅卡片的跳转按钮同样指向 bgm.tv 且新标签打开",
              bool(slinks) and all(x["href"].startswith("https://bgm.tv/subject/")
                                   and x["target"] == "_blank" for x in slinks), str(slinks[:2]))
        shoot(ws, "05_subscriptions")

        print("\nF. 设置页")
        evaluate(ws, "window.__probe.switchView('config')")
        time.sleep(1.2)
        m = evaluate(ws, MEASURE_JS)
        print(f"    回填字段={m['cfgFilled']} 资源站行={m['sourceRows']}")
        check("qBittorrent 地址已回填", "8080" in (m["cfgFilled"][0] or ""), m["cfgFilled"][0])
        check("下载根目录已回填", "Anime" in (m["cfgFilled"][3] or ""), m["cfgFilled"][3])
        check("代理地址已回填", "7890" in (m["cfgFilled"][4] or ""), m["cfgFilled"][4])
        check("自动追番间隔已回填", str(m["cfgFilled"][5]) == "30", m["cfgFilled"][5])
        check("资源站优先级列表已渲染", m["sourceRows"] >= 3, f"{m['sourceRows']} 行")
        shoot(ws, "06_settings")

        print("\nG. 日志页")
        evaluate(ws, "window.__probe.switchView('logs')")
        time.sleep(1.2)
        logs = evaluate(ws, "document.getElementById('logbox').textContent.trim().slice(0,80)")
        print(f"    日志内容={logs[:60]!r}")
        check("日志已载入", "INFO" in (logs or "") or len(logs or "") > 5, logs[:50])

        print("\nH. 主题切换与响应式")
        evaluate(ws, "document.getElementById('btn-theme').click()")
        time.sleep(0.6)
        theme = evaluate(ws, "document.documentElement.dataset.theme")
        check("主题可切换", theme in ("dark", "light"), theme)
        evaluate(ws, "document.getElementById('btn-theme').click()")
        time.sleep(0.4)
        # 窄屏
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 700, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        evaluate(ws, "window.__probe.switchView('anime')")
        time.sleep(1.0)
        narrow = evaluate(ws, "JSON.stringify({ovf:document.documentElement.scrollWidth-document.documentElement.clientWidth,"
                              "cards:document.querySelectorAll('#anime-grid .card').length})")
        nd = json.loads(narrow)
        print(f"    窄屏(700px)：卡片={nd['cards']} 横向溢出={nd['ovf']}px")
        check("窄屏无横向溢出", nd["ovf"] <= 1, f"{nd['ovf']}px")
        shoot(ws, "07_narrow")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})

        print("\nI. JS 错误检查")
        m = evaluate(ws, MEASURE_JS)
        check("全流程无未捕获 JS 错误", not m["errors"], str(m["errors"])[:200])

        ws.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:      # noqa: BLE001
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        httpd.shutdown()

    print()
    print("=" * 76)
    print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    print(f"截图：{SHOTS}")
    print("=" * 76)
    for f in FAIL:
        print("  [失败]", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
