"""订阅设置页的「筛选结果」+「修改订阅 = 整套弹窗」（mock 页面，不联网、不碰真实 data/）。

用户需求（原话）：
  ① 订阅设置页（修改订阅）下方显示「筛选后的搜索结果」；
  ② 这个页面要能滚动；资源站 / 限定字幕组 / 限定分辨率 / 字幕语言就是筛选条件；
  ③ 修改订阅别砍成一个精简页 —— 直接用人点卡片的那一整套（两个页签都在），默认停在资源列表；
  ④ edit 模式主按钮改成「保存修改」。

本探针在 `_probe/ui_fixture.html`（mock 数据）上验收前端能验的部分，并截图
`_probe/shots/50_sub_results.png`。

mock 数据（见 ui_fixture_template.html）：番剧 498378 共 8 条资源，其中 1 条合集
（沸班亚马制作组 [01-13Fin]）、7 条单集、全部 1080p；订阅存的是「桜都字幕组 + 1080p」。

用法：python _probe\\t_sub_results_ui.py
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
from cdp_test import WS, free_port, open_page, serve, wait_cdp   # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{('  — ' + str(extra)) if extra else ''}")


def main() -> int:
    print("=" * 76)
    print("订阅设置：筛选结果 + 修改订阅（整套弹窗）")
    print("=" * 76)
    if not BROWSER:
        print("找不到 Chrome，跳过")
        return 0

    static_port, cdp = free_port(), free_port()
    httpd = serve(ROOT, static_port)
    profile = os.path.join(tempfile.gettempdir(), f"subres-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--disable-extensions", "--force-device-scale-factor=1",
         "--window-size=1600,1000", f"--user-data-dir={profile}",
         f"--remote-debugging-port={cdp}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def ev(ws, expr, timeout=120):
        r = ws.call("Runtime.evaluate",
                    {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(res.get("description"))
        return res.get("value")

    def rows(ws):
        return ev(ws, "document.querySelectorAll('#sub-res-body tr.sub-res-row').length") or 0

    def count_text(ws):
        return ev(ws, "document.getElementById('sub-results-count').innerText") or ""

    def set_sel(ws, id_, value):
        """给原生 select 赋值并派发 change（自绘下拉的显示由 ui.js 自己跟，筛选读的是原生 value）。"""
        return ev(ws, f"""(() => {{
          const el = document.getElementById({json.dumps(id_)});
          if (!el) return null;
          el.value = {json.dumps(value)};
          el.dispatchEvent(new Event('change', {{ bubbles: true }}));
          return el.value;
        }})()""")

    def cell_texts(ws, nth):
        raw = ev(ws, "JSON.stringify([...document.querySelectorAll('#sub-res-body tr.sub-res-row')]"
                     f".map(tr => ((tr.children[{nth}] || {{}}).textContent || '').trim()))") or "[]"
        return json.loads(raw)

    def wait_app(ws):
        for _ in range(60):
            if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
                return True
            time.sleep(1.0)
        return False

    def wait_rows(ws, n=1, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            got = rows(ws)
            if got >= n:
                return got
            time.sleep(0.4)
        return rows(ws)

    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{static_port}/_probe/ui_fixture.html"})
        check("页面初始化完成（app-ready）", wait_app(ws))

        # ---- ① 结构 ----
        print("\n【1】订阅设置页里有「筛选结果」区块（只有一份）")
        check("区块 #sub-results 存在", bool(ev(ws, "!!document.getElementById('sub-results')")))
        check("结果表 / 表体 / 空态 / 含合集开关都在",
              bool(ev(ws, "!!document.getElementById('sub-res-table')"
                          " && !!document.getElementById('sub-res-body')"
                          " && !!document.getElementById('sub-res-empty')"
                          " && !!document.getElementById('s-batch')")))
        check("整页只有一张结果表（没有在资源列表里重复一份）",
              ev(ws, "document.querySelectorAll('#sub-res-body').length") == 1)

        # ---- ② 点卡片 → 订阅设置：订阅里的字幕组默认选中 ----
        print("\n【2】点卡片打开「已订阅」的番剧 → 订阅设置默认选中订阅里的字幕组")
        check("已打开番剧弹窗", bool(ev(ws, "window.__probe.openModal(498378)")))
        ev(ws, "window.__probe.switchTab('sub')")
        got = wait_rows(ws, 1, 60)
        check("字幕组下拉默认选中订阅里的「桜都字幕组」",
              "桜都" in (ev(ws, "document.getElementById('s-group').value") or ""),
              ev(ws, "document.getElementById('s-group').value"))
        check("按该组筛出 2 条（合集仍默认隐藏）", got == 2, f"{got} 行")
        check("计数写「共 2 条」", "共 2 条" in count_text(ws), count_text(ws))
        check("计数说明隐藏了 1 条合集", "1 条合集" in count_text(ws), count_text(ws))
        set_sel(ws, "s-group", "")
        time.sleep(0.4)
        check("字幕组改「不限」→ 7 条（8 条里 1 条合集被隐藏）", rows(ws) == 7, f"{rows(ws)} 行")

        # ---- ③ 限定字幕组 ----
        print("\n【3】限定字幕组 = 筛选条件（结果实时收窄）")
        group_value = ev(ws, "(() => { const s = document.getElementById('s-group');"
                             " const o = [...s.options].find(o => (o.textContent || '').includes('桜都'));"
                             " return o ? o.value : ''; })()") or ""
        check("字幕组下拉里能拿到「桜都字幕组」的 value", bool(group_value), repr(group_value))
        set_sel(ws, "s-group", group_value)
        time.sleep(0.4)
        check("限定桜都字幕组 → 2 条", rows(ws) == 2, f"{rows(ws)} 行")
        check("这 2 条都是桜都字幕组", set(cell_texts(ws, 1)) == {"桜都字幕组"}, cell_texts(ws, 1))

        # ---- ④ 字幕语言 ----
        print("\n【4】字幕语言 = 筛选条件（精确匹配：选简体不含简繁）")
        check("语言下拉有「简体」", set_sel(ws, "s-lang", "chs") == "chs")
        time.sleep(0.4)
        check("桜都 + 简体 → 1 条", rows(ws) == 1, f"{rows(ws)} 行")
        check("留下的是简体那条", cell_texts(ws, 3) == ["简体"], cell_texts(ws, 3))
        set_sel(ws, "s-lang", "")
        time.sleep(0.4)
        check("语言回「不限」→ 回到 2 条", rows(ws) == 2, f"{rows(ws)} 行")

        # ---- ⑤ 限定分辨率（空态） ----
        print("\n【5】限定分辨率 = 筛选条件，筛空时给「放宽」的提示")
        set_sel(ws, "s-res", "720p")
        time.sleep(0.4)
        check("锁定 720p（结果里没有）→ 0 条", rows(ws) == 0, f"{rows(ws)} 行")
        check("空态提示可见", not ev(ws, "document.getElementById('sub-res-empty').hidden"))
        empty_text = ev(ws, "document.getElementById('sub-res-empty').innerText") or ""
        check("提示教用户放宽条件", "放宽" in empty_text, empty_text[:80])
        set_sel(ws, "s-res", "1080p")
        time.sleep(0.4)
        check("改回 1080p → 又回到 2 条", rows(ws) == 2, f"{rows(ws)} 行")

        # ---- ⑥ 资源站（站点与字幕组必须成对） ----
        print("\n【6】资源站 = 筛选条件，且与字幕组的站点必须对得上")
        set_sel(ws, "s-source", "nyaa")
        time.sleep(0.4)
        check("资源站=Nyaa 但字幕组是 dmhy 的 → 0 条", rows(ws) == 0, f"{rows(ws)} 行")
        set_sel(ws, "s-group", "")
        time.sleep(0.4)
        check("字幕组改回「不限」→ Nyaa 的 2 条单集", rows(ws) == 2, f"{rows(ws)} 行")
        check("这 2 条都在 Nyaa", set(cell_texts(ws, 0)) == {"Nyaa"}, cell_texts(ws, 0))
        set_sel(ws, "s-source", "")
        time.sleep(0.4)
        check("资源站回「不限」→ 回到 7 条", rows(ws) == 7, f"{rows(ws)} 行")

        # ---- ⑦ 含合集开关 ----
        print("\n【7】「含合集」是筛选开关：勾上才把合集列出来")
        check("默认没勾", not ev(ws, "document.getElementById('s-batch').checked"))
        ev(ws, "document.getElementById('s-batch').click()")
        time.sleep(0.4)
        check("勾上后 → 8 条", rows(ws) == 8, f"{rows(ws)} 行")
        check("勾上后计数不再说「已隐藏」", "已隐藏" not in count_text(ws), count_text(ws))
        check("合集那条的集数格显示「合集」",
              any("合集" in t for t in cell_texts(ws, 5)), str(cell_texts(ws, 5))[:120])

        # ---- ⑧ 页面可滚动 ----
        print("\n【8】订阅设置页可上下滚动（结果表自己限高，操作行在结果表之后）")
        box = json.loads(ev(ws, """JSON.stringify({
          ov: getComputedStyle(document.getElementById('tab-sub')).overflowY,
          mh: getComputedStyle(document.getElementById('tab-sub')).minHeight,
          sh: document.getElementById('tab-sub').scrollHeight,
          ch: document.getElementById('tab-sub').clientHeight,
          wsh: document.querySelector('.sub-results-wrap').scrollHeight,
          wch: document.querySelector('.sub-results-wrap').clientHeight,
          actPos: getComputedStyle(document.querySelector('#tab-sub .sub-actions')).position,
          order: [...document.getElementById('tab-sub').children]
                   .map(n => n.id || n.className.split(' ')[0]).join(' > '),
          after: (() => {
            const kids = [...document.getElementById('tab-sub').children];
            const iRes = kids.findIndex(n => n.id === 'sub-results');
            const iAct = kids.findIndex(n => n.classList.contains('sub-actions'));
            return iRes >= 0 && iAct >= 0 && iRes < iAct;
          })()
        })""") or "{}")
        check("订阅设置页是滚动容器（overflow-y:auto）", box.get("ov") == "auto", box.get("ov"))
        check("flex 子项能收缩（min-height:0，否则顶出去不滚）", box.get("mh") == "0px", box.get("mh"))
        check("内容高于可视区 → 页面可上下滚",
              box.get("sh", 0) > box.get("ch", 0), f"{box.get('sh')} > {box.get('ch')}")
        check("结果表自己限高、表内滚动", box.get("wsh", 0) > box.get("wch", 0),
              f"{box.get('wsh')} > {box.get('wch')}")
        check("操作行不做吸底（吸底会浮在结果表上把它挡住）",
              box.get("actPos") == "static", box.get("actPos"))
        check("操作行排在结果表之后（滚到底就能点「保存修改」）", bool(box.get("after")),
              box.get("order"))

        # ---- ⑨ 修改订阅 = 整套弹窗，默认停在资源列表 ----
        print("\n【9】「修改订阅」用的是点卡片那一整套：两个页签都在，默认资源列表")
        ev(ws, "document.getElementById('m-close').click()")
        time.sleep(0.6)
        check("已切到「我的订阅」", bool(ev(ws, "window.__probe.switchView('subs')")))
        time.sleep(1.2)
        clicked = ev(ws, """(() => {
          const card = document.querySelector('#sub-list');
          if (!card) return false;
          const btn = [...card.querySelectorAll('button')].find(b => (b.textContent || '').trim() === '修改订阅');
          if (!btn) return false;
          btn.click();
          return true;
        })()""")
        check("订阅卡片上有「修改订阅」按钮并点开了", bool(clicked))
        time.sleep(2.5)

        check("弹窗打开了", not ev(ws, "document.getElementById('modal').hidden"))
        check("两个页签都在（不再砍成一个页）", not ev(ws, "document.getElementById('m-tabs').hidden"))
        check("默认停在「资源列表」",
              ev(ws, "document.querySelector('#m-tabs .tab.is-active').dataset.tab") == "res",
              ev(ws, "document.querySelector('#m-tabs .tab.is-active').dataset.tab"))
        res_rows = ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0
        check("资源列表已按订阅自动筛选：字幕组 = 桜都字幕组",
              (ev(ws, "document.getElementById('f-group').value") or "") == "桜都字幕组",
              ev(ws, "document.getElementById('f-group').value"))
        check("资源列表已按订阅自动筛选：分辨率 = 1080p",
              (ev(ws, "document.getElementById('f-res').value") or "") == "1080p",
              ev(ws, "document.getElementById('f-res').value"))
        hint_text = ev(ws, "(() => { const h = document.querySelector('#tab-res .section-hint');"
                           " return h ? h.innerText : ''; })()") or ""
        check("提示条写明「已按订阅筛选」", "已按订阅筛选" in hint_text, hint_text[:120])
        check("提示条说明这是「修改订阅」而不是补下载", "修改订阅" in hint_text, hint_text[:60])
        check("资源表只剩该订阅的 2 条（能直接挑着补某一集）", res_rows == 2, f"{res_rows} 行")
        check("底部主按钮文案 = 保存修改",
              (ev(ws, "document.getElementById('btn-sub-add').textContent") or "").strip() == "保存修改",
              ev(ws, "document.getElementById('btn-sub-add').textContent"))
        check("资源列表筛选条上的按钮也 = 保存修改",
              (ev(ws, "document.getElementById('btn-sub-add-res').textContent") or "").strip() == "保存修改")
        check("这个按钮没被「当前筛选没资源」置灰（保存设置与有没有资源无关）",
              ev(ws, "document.getElementById('btn-sub-add-res').disabled") is False)

        # 截图①：修改订阅 → 资源列表（已按订阅筛好）
        os.makedirs(SHOTS, exist_ok=True)
        shot_res = os.path.join(SHOTS, "51_edit_resources.png")
        r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
        with open(shot_res, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"  截图 -> {shot_res}")

        ev(ws, "window.__probe.switchTab('sub')")
        time.sleep(0.8)
        check("订阅设置预填了订阅的字幕组",
              "桜都" in (ev(ws, "document.getElementById('s-group').value") or ""),
              ev(ws, "document.getElementById('s-group').value"))
        check("订阅设置预填了订阅的分辨率",
              (ev(ws, "document.getElementById('s-res').value") or "") == "1080p",
              ev(ws, "document.getElementById('s-res').value"))
        check("结果按订阅设置直接筛出 2 条（桜都 + 1080p）", rows(ws) == 2, f"{rows(ws)} 行")

        # 截图②：订阅设置页顶部（表单 + 「筛选结果」标题行）
        os.makedirs(SHOTS, exist_ok=True)
        shot = os.path.join(SHOTS, "50_sub_results.png")
        r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
        with open(shot, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"\n  截图 -> {shot}")

        # 截图③：滚到底（结果表 + 操作行，证明「可滚动」不是把内容藏起来）
        ev(ws, "(() => { const b = document.getElementById('tab-sub');"
               " b.scrollTop = b.scrollHeight; return b.scrollTop; })()")
        time.sleep(0.5)
        check("滚到底能看到操作行（保存修改 / 去资源列表）",
              ev(ws, """(() => {
                const b = document.getElementById('tab-sub').getBoundingClientRect();
                const a = document.querySelector('#tab-sub .sub-actions').getBoundingClientRect();
                return a.top >= b.top && a.bottom <= b.bottom + 1;
              })()""") is True)
        shot_bottom = os.path.join(SHOTS, "52_sub_results_scrolled.png")
        r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
        with open(shot_bottom, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"  截图 -> {shot_bottom}")
        ws.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:   # noqa: BLE001
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        httpd.shutdown()

    print()
    print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for f in FAIL:
        print("  [失败]", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
