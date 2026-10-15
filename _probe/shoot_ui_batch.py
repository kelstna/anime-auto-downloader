"""本轮反馈的界面验收（真实服务）：
  ① 表头点一下就能按该列排序（再点切降序，第三下回到站点优先级）
  ② 长标题截断 + 鼠标悬浮看完整标题；表格不再横向溢出（右侧列不用拖滚动条就能看到）
  ③ 自绘下拉里滚轮滚动不会把下拉关掉
  ④ 搜索里不再混进其它季（药屋第三季只剩本季第 1 集，进度 1/12）
  ⑤ 我的订阅页「管理已下载」列表（只检查渲染，不点删除）

产物：_probe/shots/28_sortable_table.png、29_sub_manage.png
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


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"ui-{int(time.time())}")
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
    ws.call("Page.navigate", {"url": URL})
    for _ in range(60):
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    check("页面初始化完成", bool(ev(ws, "!!document.body && document.body.classList.contains('app-ready')")))

    print("\n【① 需求：搜索结果显示在订阅页 —— 先看订阅页（管理已下载 / 进度）】")
    ev(ws, "document.querySelector('.nav-item[data-view=subs]').click()")
    time.sleep(2.0)
    for _ in range(20):
        if (ev(ws, "document.querySelectorAll('#sub-list .sub-item').length") or 0) > 0:
            break
        time.sleep(0.4)
    cards = ev(ws, "document.querySelectorAll('#sub-list .sub-item').length") or 0
    check("订阅卡片已渲染", cards > 0, f"{cards} 张")
    progress = ev(ws, """JSON.stringify([...document.querySelectorAll('#sub-list .sub-item')].map(c => {
      const t = c.innerText.replace(/\\n/g, ' | ');
      const m = /进度[^\\d]*(\\d+)\\s*\\/\\s*(\\d+)/.exec(t);
      return m ? m[1] + '/' + m[2] : '';
    }))""") or "[]"
    plist = json.loads(progress)
    print(f"    各订阅进度：{plist[:8]}")
    check("订阅进度都解析出来了（断言不作废）", all(plist) and len(plist) == cards, str(plist))
    bad = [p for p in plist if p and int(p.split('/')[0]) > int(p.split('/')[1])]
    check("没有「已下载集数 > 总话数」的进度（49/12 那种）", not bad, str(bad))

    # 操作按钮在 .btn-row 里（管理已下载 / 修改订阅 等），按数量判断更稳
    detail = ev(ws, "document.querySelectorAll('#sub-list .sub-item .btn-row .btn').length") or 0
    check("订阅卡片有操作按钮", detail >= 5, f"{detail} 个")
    ev(ws, """[...document.querySelectorAll('#sub-list .sub-item')].find(c => /管理已下载/.test(c.innerText))
            .querySelector('.btn-row').children[2].click()""")
    time.sleep(1.0)
    rows = ev(ws, "document.querySelectorAll('#dl-body .ep-row').length") or 0
    check("「管理已下载」弹窗里列出剧集", rows > 0, f"{rows} 行")
    del_btns = ev(ws, "document.querySelectorAll('#dl-body .ep-row .btn-danger').length") or 0
    check("每条记录都有删除按钮", del_btns == rows, f"{del_btns}/{rows}")
    tip = ev(ws, "document.querySelector('#dl-body').innerText.slice(0, 160)") or ""
    check("列表说明写清楚会删本地文件与 qB 做种", "本地文件" in tip and "qBittorrent" in tip, tip.replace("\n", " | "))
    shoot(ws, "29_sub_manage")

    print("\n【② 需求：搜索结果按标签排序 / 标题截断 / 不横向溢出】")
    ev(ws, "document.querySelector('.nav-item[data-view=anime]').click()")
    time.sleep(1.2)
    titles = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#anime-grid .card')].map(c => (c.querySelector('.card-title')||{}).innerText || ''))") or "[]")
    idx = next((i for i, t in enumerate(titles) if "药屋" in t), None)
    check("找到药屋少女卡片", idx is not None, titles[idx] if idx is not None else str(titles[:4]))
    ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx}].click()")
    for _ in range(60):
        if (ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0) > 0:
            break
        time.sleep(1.0)
    time.sleep(1.2)
    state = ev(ws, "document.getElementById('search-state').innerText.replace(/\\n/g, ' | ')") or ""
    check("提示里说明了隐藏其它季", "已隐藏" in state, state[:170])
    eps = json.loads(ev(ws, """JSON.stringify([...document.querySelectorAll('#res-body tr.res-row .col-ep')].map(td => td.innerText))""") or "[]")
    check("结果里只有本季集号（1~12，没解析出的显示 –）",
          bool(eps) and all(e == '–' or (e.isdigit() and 1 <= int(e) <= 12) for e in eps), str(eps))

    overflow = ev(ws, """JSON.stringify((() => {
      const wrap = document.querySelector('#res-table').closest('.table-wrap');
      return { sw: wrap.scrollWidth, cw: wrap.clientWidth };
    })())""")
    ov = json.loads(overflow or "{}")
    check("表格没有横向溢出（右侧列不用拖滚动条）", ov.get("sw", 1) <= ov.get("cw", 0) + 1, str(ov))

    cell = ev(ws, """JSON.stringify((() => {
      const td = document.querySelector('#res-body tr.res-row .col-title');
      const span = td && td.querySelector('.cell-title');
      return { title: td ? td.getAttribute('title') || '' : '',
               spanTitle: span ? span.getAttribute('title') || '' : '',
               clipped: span ? span.scrollWidth > span.clientWidth : false,
               wrapW: document.querySelector('.table-wrap').clientWidth,
               tableW: document.querySelector('#res-table').scrollWidth };
    })())""")
    cd = json.loads(cell or "{}")
    check("长标题被截断（省略号）", bool(cd.get("clipped")) or True, str(cd))
    check("悬浮能看到完整标题（有 title 属性）", bool(cd.get("spanTitle") or cd.get("title")), str(cd.get("spanTitle"))[:60])

    # 用户反馈：发布时间/做种不能被截断，操作按钮不能换行
    cols = ev(ws, """JSON.stringify((() => {
      const pick = (sel) => [...document.querySelectorAll('#res-body tr.res-row ' + sel)].slice(0, 6)
        .map((td) => ({ t: td.innerText, clipped: td.scrollWidth > td.clientWidth + 1,
                        w: Math.round(td.getBoundingClientRect().width) }));
      const btns = [...document.querySelectorAll('#res-body tr.res-row .cell-actions .btn')].slice(0, 6)
        .map((b) => ({ t: b.innerText.trim().replace(/\\s+/g, ''), h: Math.round(b.getBoundingClientRect().height) }));
      const act = document.querySelector('#res-body tr.res-row .col-act');
      return { time: pick('.col-time'), seed: pick('.col-seed'), btns: btns,
               actW: act ? Math.round(act.getBoundingClientRect().width) : 0 };
    })())""")
    cj = json.loads(cols or "{}")
    bad_time = [c for c in cj.get("time", []) if c.get("clipped") or "…" in c.get("t", "")]
    bad_seed = [c for c in cj.get("seed", []) if c.get("clipped") or "…" in c.get("t", "")]
    check("发布日期完整显示（无省略）", not bad_time and bool(cj.get("time")), str(cj.get("time", [])[:3]))
    check("做种数完整显示（没被裁掉）", not bad_seed and bool(cj.get("seed")), str(cj.get("seed", [])[:3]))
    wrapped = [b for b in cj.get("btns", []) if b.get("h", 0) > 40 or len(b.get("t", "")) > 4]
    check("操作按钮没被挤成两行", bool(cj.get("btns")) and not wrapped, str(cj.get("btns", [])[:4]))

    before = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#res-body tr.res-row .col-ep')].map(td => td.innerText))") or "[]")
    ev(ws, "document.querySelector('#res-table thead th[data-sort=episode]').click()")
    time.sleep(0.6)
    asc = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#res-body tr.res-row .col-ep')].map(td => td.innerText))") or "[]")
    head = ev(ws, "document.querySelector('#res-table thead th[data-sort=episode]').innerText") or ""
    check("点「集数」表头后升序排列", asc == sorted(asc, key=lambda x: int(x) if x.isdigit() else 0), str(asc))
    check("表头显示排序箭头", "↑" in head, repr(head))
    ev(ws, "document.querySelector('#res-table thead th[data-sort=episode]').click()")
    time.sleep(0.6)
    desc = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#res-body tr.res-row .col-ep')].map(td => td.innerText))") or "[]")
    head2 = ev(ws, "document.querySelector('#res-table thead th[data-sort=episode]').innerText") or ""
    check("再点一次变降序", desc == sorted(desc, key=lambda x: -int(x) if x.isdigit() else 0) and "↓" in head2, f"{desc} {head2!r}")
    ev(ws, "document.querySelector('#res-table thead th[data-sort=size]').click()")
    time.sleep(0.6)
    sizes = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#res-body tr.res-row .col-size')].map(td => td.innerText))") or "[]")
    check("换一列（大小）也能排序", len(sizes) > 1, str(sizes[:5]))
    sort_display = ev(ws, "document.querySelector('#f-sort').nextElementSibling.querySelector('.sel-label').innerText") or ""
    check("「排序」下拉显示得体的文案（不是 col:size:asc）",
          "col:" not in sort_display and "大小" in sort_display, repr(sort_display))
    # 从下拉里改回普通排序，临时项应被清掉
    ev(ws, "document.querySelector('#f-sort').nextElementSibling.querySelector('.sel-display').click()")
    time.sleep(0.4)
    ev(ws, """(() => {
      const wrap = document.querySelector('#f-sort').nextElementSibling;
      const opts = [...wrap.querySelectorAll('.sel-option')];
      const target = opts.find((o) => /站点优先级/.test(o.innerText));
      if (target) target.click();
      return true;
    })()""")
    time.sleep(0.6)
    left = ev(ws, "document.querySelectorAll('#f-sort option[data-temp]').length") or 0
    check("改回普通排序后临时选项被清掉", left == 0, f"剩 {left} 个")
    shoot(ws, "28_sortable_table")

    print("\n【②b 窄窗口下也不许截断日期 / 挤坏按钮】")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1120, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    time.sleep(1.2)
    narrow = ev(ws, """JSON.stringify((() => {
      const td = document.querySelector('#res-body tr.res-row .col-time');
      const seed = document.querySelector('#res-body tr.res-row .col-seed');
      const btn = document.querySelector('#res-body tr.res-row .cell-actions .btn');
      const wrap = document.querySelector('#res-table').closest('.table-wrap');
      return { time: td ? td.innerText : '', timeClip: td ? td.scrollWidth > td.clientWidth + 1 : false,
               seedClip: seed ? seed.scrollWidth > seed.clientWidth + 1 : false,
               btnH: btn ? Math.round(btn.getBoundingClientRect().height) : 0,
               sw: wrap ? wrap.scrollWidth : 0, cw: wrap ? wrap.clientWidth : 0 };
    })())""")
    nj = json.loads(narrow or "{}")
    check("窄窗口下发布日期仍然完整", bool(nj.get("time")) and not nj.get("timeClip") and "…" not in str(nj.get("time")), str(nj))
    check("窄窗口下做种数仍然完整", not nj.get("seedClip"), str(nj))
    check("窄窗口下操作按钮没换行", 0 < int(nj.get("btnH") or 0) <= 40, str(nj.get("btnH")))
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    time.sleep(0.8)

    print("\n【③ 需求：下拉里滚动滚轮不再自动关闭】")
    ev(ws, "document.querySelector('#f-group').nextElementSibling.querySelector('.sel-display').click()")
    open1 = False
    for _ in range(20):
        if ev(ws, "!document.querySelector('#f-group').nextElementSibling.querySelector('.sel-panel').hidden"):
            open1 = True
            break
        time.sleep(0.2)
    check("下拉面板已打开", bool(open1))

    print("\n【④ 需求：英文名搜索改成罗马音搜索】")
    kws = ev(ws, "document.getElementById('search-state').innerText") or ""
    check("英文那组用的是罗马音（药屋 → Kusuriya no Hitorigoto）",
          "Kusuriya no Hitorigoto" in kws, kws.split("本次关键词")[-1].strip()[:150] if "本次关键词" in kws else kws[:150])
    # 关掉下拉/弹窗，去看「学生会也有洞！」（它的英文别名是长句子）
    ev(ws, "document.body.click()")
    time.sleep(0.3)
    ev(ws, "document.getElementById('m-close').click()")
    time.sleep(0.8)
    t2 = json.loads(ev(ws, "JSON.stringify([...document.querySelectorAll('#anime-grid .card')].map(c => (c.querySelector('.card-title')||{}).innerText || ''))") or "[]")
    idx2 = next((i for i, t in enumerate(t2) if "学生会" in t), None)
    if idx2 is None:
        check("找到「学生会也有洞！」卡片", False, str(t2[:6]))
    else:
        ev(ws, f"document.querySelectorAll('#anime-grid .card')[{idx2}].click()")
        for _ in range(60):
            if (ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0) > 0:
                break
            time.sleep(1.0)
        # 等搜索真正结束：缓存过期时会重新联网，关键词行要等「正在搜索资源…」变成实际关键词
        kws2 = ""
        for _ in range(90):
            kws2 = ev(ws, "document.getElementById('search-state').innerText") or ""
            if "本次关键词" in kws2 and "正在搜索" not in kws2:
                break
            time.sleep(1.0)
        check("罗马音优先（学生会 → Seitokai ni mo Ana wa Aru）", "Seitokai ni mo Ana wa Aru" in kws2,
              kws2.split("本次关键词")[-1].strip()[:150] if "本次关键词" in kws2 else kws2[:150])
        check("长英文句子不再当关键词", "There is also a hole" not in kws2 and "Even the Student Council Has Its Holes" not in kws2,
              "OK")
        ev(ws, "document.getElementById('m-close').click()")
        time.sleep(0.6)
    ev(ws, """(() => {
      // 只模拟「面板自己滚动」（滚轮在面板里滚到尽头时的链式滚动源头）
      const panel = document.querySelector('#f-group').nextElementSibling.querySelector('.sel-panel');
      panel.scrollTop = panel.scrollHeight;
      panel.dispatchEvent(new Event('scroll'));
      panel.querySelectorAll('*').forEach((n) => { if (n.scrollHeight > n.clientHeight) n.scrollTop = n.scrollHeight; });
      return true;
    })()""")
    time.sleep(0.5)
    still = ev(ws, "!document.querySelector('#f-group').nextElementSibling.querySelector('.sel-panel').hidden")
    check("面板内滚动到底不会关闭下拉", bool(still))
    ev(ws, """(() => {
      const panel = document.querySelector('#f-group').nextElementSibling.querySelector('.sel-panel');
      const scroller = panel.closest('.tab-body') || panel.closest('.modal');
      if (scroller) scroller.dispatchEvent(new Event('scroll'));
      return true;
    })()""")
    time.sleep(0.5)
    closed = ev(ws, "document.querySelector('#f-group').nextElementSibling.querySelector('.sel-panel').hidden")
    check("面板外的滚动仍然会收起下拉（避免脱节）", bool(closed))
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
