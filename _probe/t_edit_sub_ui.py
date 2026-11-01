"""「修改订阅」= 点卡片那一整套弹窗 + 资源列表按订阅自动筛选（mock 页面，不联网、不碰真实 data/）。

用户需求（原话要点）：
  ① 修改订阅别砍成精简页 —— 直接用人点卡片的那一整套弹窗；
  ② 默认停在**资源列表**；
  ③ 弹出的资源列表**按订阅自动筛选**；
  ④ 主按钮改「保存修改」（只改设置，不重新下载）；
  ⑤ **订阅设置那一页保持原样**（不要往里面加「筛选结果」之类的区块）。

本探针在 `_probe/ui_fixture.html`（mock 数据）上验收，并截图
`_probe/shots/60_edit_sub.png`。浏览器只用 Google Chrome。

mock 数据（见 ui_fixture_template.html）：番剧 498378 共 8 条资源，订阅存的是
「桜都字幕组 + 1080p」，其中该组有 2 条单集。

用法：python _probe\\t_edit_sub_ui.py
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

# 只用 Google Chrome（用户明确要求，别换 Edge）
CHROME_PATHS = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")
BROWSER = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{('  — ' + str(extra)) if extra else ''}")


def main() -> int:
    print("=" * 76)
    print("修改订阅：整套弹窗 + 资源列表按订阅自动筛选")
    print("=" * 76)
    if not BROWSER:
        print("找不到 Google Chrome，跳过")
        return 0

    static_port, cdp = free_port(), free_port()
    httpd = serve(ROOT, static_port)
    profile = os.path.join(tempfile.gettempdir(), f"editsub-{int(time.time())}")
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

    def wait_app(ws):
        for _ in range(60):
            if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
                return True
            time.sleep(1.0)
        return False

    def visible(id_):
        return ev(ws, f"(() => {{ const el = document.getElementById({json.dumps(id_)});"
                      " return !!el && !el.hidden && el.getClientRects().length > 0; })()") is True

    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{static_port}/_probe/ui_fixture.html"})
        check("页面初始化完成（app-ready）", wait_app(ws))

        # ---- ① 订阅设置页必须保持原样 ----
        print("\n【1】订阅设置页保持原样（没有新增「筛选结果」区块）")
        check("不再有 #sub-results 区块", ev(ws, "!document.getElementById('sub-results')") is True)
        check("不再有「筛选结果」文案",
              "筛选结果" not in (ev(ws, "document.documentElement.innerText") or ""))
        check("styles.css 里没有任何 #tab-sub 规则（没给这页加过滚动/吸底样式）",
              (ev(ws, """(() => [...document.styleSheets]
                  .flatMap(s => { try { return [...s.cssRules]; } catch (e) { return []; } })
                  .filter(r => r.selectorText && r.selectorText.includes('#tab-sub')).length)()""") or 0) == 0,
              ev(ws, """(() => [...document.styleSheets]
                  .flatMap(s => { try { return [...s.cssRules]; } catch (e) { return []; } })
                  .filter(r => r.selectorText && r.selectorText.includes('#tab-sub'))
                  .map(r => r.selectorText).join(' | '))()"""))
        order = ev(ws, """(() => [...document.getElementById('tab-sub').children]
                   .map(n => n.id || n.className.split(' ')[0]).join(' > '))()""")
        check("订阅设置页结构 = 原版（提示 → 表单 → 预览 → 按钮 → 历史）",
              order == "muted > form-grid > s-preview > sub-actions > sub-history", order)

        # ---- ② 修改订阅 = 整套弹窗 ----
        print("\n【2】「修改订阅」打开的是点卡片那一整套弹窗")
        check("已切到「我的订阅」", bool(ev(ws, "window.__probe.switchView('subs')")))
        time.sleep(1.2)
        clicked = ev(ws, """(() => {
          const list = document.querySelector('#sub-list');
          if (!list) return false;
          const btn = [...list.querySelectorAll('button')].find(b => (b.textContent || '').trim() === '修改订阅');
          if (!btn) return false;
          btn.click();
          return true;
        })()""")
        check("订阅卡片上有「修改订阅」并点开了", bool(clicked))
        time.sleep(2.5)

        check("弹窗打开了", not ev(ws, "document.getElementById('modal').hidden"))
        check("两个页签都在（不再砍成一个精简页）", not ev(ws, "document.getElementById('m-tabs').hidden"))
        check("默认停在「资源列表」",
              ev(ws, "document.querySelector('#m-tabs .tab.is-active').dataset.tab") == "res",
              ev(ws, "document.querySelector('#m-tabs .tab.is-active').dataset.tab"))
        check("资源列表这一页真的显示着", visible("tab-res"))
        check("订阅设置这一页是隐藏的", not visible("tab-sub"))

        # ---- ③ 资源列表按订阅自动筛选 ----
        print("\n【3】弹出的资源列表已按订阅自动筛选")
        check("筛选条：字幕组 = 桜都字幕组",
              (ev(ws, "document.getElementById('f-group').value") or "") == "桜都字幕组",
              ev(ws, "document.getElementById('f-group').value"))
        check("筛选条：分辨率 = 1080p",
              (ev(ws, "document.getElementById('f-res').value") or "") == "1080p",
              ev(ws, "document.getElementById('f-res').value"))
        rows = ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0
        check("资源表只剩该订阅的 2 条", rows == 2, f"{rows} 行")
        hint = ev(ws, "(() => { const h = document.querySelector('#tab-res .section-hint');"
                      " return h ? h.innerText : ''; })()") or ""
        check("提示条写明「已按订阅筛选」", "已按订阅筛选" in hint, hint[:110])
        check("提示条说明这是「修改订阅」而不是补下载", "修改订阅" in hint, hint[:50])

        # ---- ④ 主按钮 = 保存修改 ----
        print("\n【4】两个页签上的主按钮都是「保存修改」")
        check("资源列表筛选条上的按钮 = 保存修改",
              (ev(ws, "document.getElementById('btn-sub-add-res').textContent") or "").strip() == "保存修改",
              ev(ws, "document.getElementById('btn-sub-add-res').textContent"))
        check("它没被「当前筛选没资源」置灰",
              ev(ws, "document.getElementById('btn-sub-add-res').disabled") is False)
        check("订阅设置底部的按钮 = 保存修改",
              (ev(ws, "document.getElementById('btn-sub-add').textContent") or "").strip() == "保存修改",
              ev(ws, "document.getElementById('btn-sub-add').textContent"))

        os.makedirs(SHOTS, exist_ok=True)
        shot = os.path.join(SHOTS, "60_edit_sub.png")
        r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
        with open(shot, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"  截图 -> {shot}")

        # ---- ⑤ 切到订阅设置：高亮与内容一起换，且预填订阅的值 ----
        print("\n【5】切到「订阅设置」：页签高亮与内容一起换，并预填订阅的设置")
        ev(ws, "window.__probe.switchTab('sub')")
        time.sleep(0.8)
        check("高亮切到「订阅设置」",
              ev(ws, "document.querySelector('#m-tabs .tab.is-active').dataset.tab") == "sub")
        check("订阅设置这一页显示出来了", visible("tab-sub"))
        check("资源列表这一页隐藏了", not visible("tab-res"))
        check("预填字幕组（含站点）",
              "桜都" in (ev(ws, "document.getElementById('s-group').value") or ""),
              ev(ws, "document.getElementById('s-group').value"))
        check("预填分辨率",
              (ev(ws, "document.getElementById('s-res').value") or "") == "1080p",
              ev(ws, "document.getElementById('s-res').value"))

        # ---- ⑥ 保存修改：只写回设置，不下载 ----
        print("\n【6】点「保存修改」：提交订阅设置，不带 resource（不重新下载）")
        ev(ws, "window.__probe.clearCalls()")
        ev(ws, "document.getElementById('btn-sub-add').click()")
        time.sleep(1.5)
        calls = json.loads(ev(ws, "JSON.stringify(window.__probe.calls('/api/subscriptions', 'POST')"
                                  ".map(c => c.body))") or "[]")
        body = calls[-1] if calls else {}
        check("提交了订阅设置", bool(calls), json.dumps(body, ensure_ascii=False)[:180])
        check("没有带 resource（= 只改设置、不下载）", "resource" not in body,
              json.dumps(body, ensure_ascii=False)[:180])
        check("提交的字幕组是桜都", "桜都" in str(body.get("group") or ""), body.get("group"))
        check("提交的分辨率是 1080p", str(body.get("resolution") or "") == "1080p", body.get("resolution"))

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
