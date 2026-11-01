"""手动搜索关键词 = 联网搜索关键词（mock 页面，不联网、不动真实数据）。

用户要求（原话）：
  ① 在搜索框里手动指定关键词，联网搜索就用这里的词
  ② 点「手动搜索」用框里的词联网重搜；没指定就按原本的关键词（番剧名/别名）搜
  ③ 删掉「重新搜索」按钮
  ④ 订阅里存了手动关键词 → 自动追番的自动检查只用这个词

本探针在 `_probe/ui_fixture.html`（mock 数据）上验收 ①②③④ 里**前端**能验证的部分，
并截图 `_probe/shots/45_manual_keyword.png`。
（④ 的后端行为见 tests/test_manual_keyword.py::WatcherOnlyManualKeywordTest）

用法：python _probe\\t_manual_keyword_ui.py
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
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


def main() -> int:
    print("=" * 76)
    print("手动搜索关键词 → 联网搜索（mock 页面）")
    print("=" * 76)
    if not BROWSER:
        print("找不到 Chrome，跳过")
        return 0

    static_port, cdp = free_port(), free_port()
    httpd = serve(ROOT, static_port)
    profile = os.path.join(tempfile.gettempdir(), f"kwui-{int(time.time())}")
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

    def searches(ws):
        """本次打开弹窗后发出的 /api/search 请求体（按顺序）。"""
        raw = ev(ws, "JSON.stringify(window.__probe.calls('/api/search', 'POST').map(c => c.body))") or "[]"
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
            rows = ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0
            if rows >= n:
                return rows
            time.sleep(0.5)
        return ev(ws, "document.querySelectorAll('#res-body tr.res-row').length") or 0

    def set_input(ws, id_, value):
        ev(ws, f"""(() => {{
          const el = document.getElementById({json.dumps(id_)});
          el.value = {json.dumps(value)};
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }})()""")

    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, "about:blank"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{static_port}/_probe/ui_fixture.html"})
        check("页面初始化完成（app-ready）", wait_app(ws))

        # ---- ① 「重新搜索」按钮已删 ----
        print("\n【1】「重新搜索」按钮已删，联网入口只剩「手动搜索」")
        check("页面上没有 #btn-research", bool(ev(ws, "!document.getElementById('btn-research')")))
        check("页面文字里也没有「重新搜索」",
              "重新搜索" not in (ev(ws, "document.documentElement.innerText") or ""))
        check("手动搜索框 / 按钮都在",
              bool(ev(ws, "!!document.getElementById('f-keyword')"
                          " && !!document.getElementById('btn-keyword-search')")))

        # ---- ② 订阅里存了关键词：打开弹窗就按这个词联网搜 ----
        print("\n【2】订阅存了手动关键词 → 打开弹窗的联网搜索就用它")
        KW_STORED = "SPY x FAMILY 1080p"
        # 给 mock 订阅塞一个手动关键词，并清掉前端缓存的订阅列表
        # （findSubscription 只在 state.subs 为空时重新拉取，否则读的是启动时的旧快照）
        ev(ws, f"window.__mock.subscription.custom_keyword = {json.dumps(KW_STORED)}; state.subs = [];")
        ev(ws, "window.__probe.clearCalls()")
        check("已打开订阅番剧的弹窗", bool(ev(ws, "window.__probe.openModal(498378)")))
        rows = wait_rows(ws, 1, 60)
        check("资源列表加载出来了", rows > 0, f"{rows} 行")
        bodies = searches(ws)
        check("打开弹窗时就发起了搜索", bool(bodies), str(bodies)[:180])
        first = bodies[0] if bodies else {}
        check("搜索请求带上了订阅里存的关键词",
              first.get("keyword") == KW_STORED, json.dumps(first, ensure_ascii=False)[:200])
        check("搜索框里显示的就是这个词",
              (ev(ws, "document.getElementById('f-keyword').value") or "").strip() == KW_STORED,
              repr(ev(ws, "document.getElementById('f-keyword').value")))
        check("订阅设置里的搜索词同步成同一个值",
              (ev(ws, "document.getElementById('s-keyword').value") or "").strip() == KW_STORED)
        state = ev(ws, "document.getElementById('search-state').innerText.replace(/\\n/g, ' | ')") or ""
        check("搜索状态写明是手动关键词", "手动关键词" in state, state[:150])
        check("状态里能看到「本次关键词」就是这个词",
              KW_STORED in state.split("本次关键词")[-1] if "本次关键词" in state else False,
              state[-150:])

        # ---- ③ 点「手动搜索」= 用框里的词联网重搜（force=true） ----
        print("\n【3】点「手动搜索」：用框里的词 + 强制联网（force=true）")
        KW_TYPED = "GROTESQQUE"
        ev(ws, "window.__probe.clearCalls()")
        set_input(ws, "f-keyword", KW_TYPED)
        ev(ws, "document.getElementById('btn-keyword-search').click()")
        time.sleep(1.0)
        bodies = searches(ws)
        body = bodies[-1] if bodies else {}
        check("发出了搜索请求", bool(bodies), str(bodies)[:180])
        check("请求里的关键词就是框里输入的词", body.get("keyword") == KW_TYPED,
              json.dumps(body, ensure_ascii=False)[:200])
        check("手动搜索强制联网（force=true）", body.get("force") is True, json.dumps(body, ensure_ascii=False)[:200])
        state = ev(ws, "document.getElementById('search-state').innerText.replace(/\\n/g, ' | ')") or ""
        check("界面上写明「手动关键词」", KW_TYPED in state and "手动关键词" in state, state[:160])

        # ---- ④ 留空 = 按原本的关键词（番剧名/别名）联网搜 ----
        print("\n【4】清空关键词 → 按番剧名/别名联网搜（不带 keyword）")
        ev(ws, "window.__probe.clearCalls()")
        ev(ws, "document.getElementById('btn-keyword-reset').click()")    # 恢复自动搜索
        time.sleep(1.0)
        bodies = searches(ws)
        body = bodies[-1] if bodies else {}
        check("清空后仍会联网搜索", bool(bodies), str(bodies)[:180])
        check("请求里没有关键词（= 按番剧名/别名）", not body.get("keyword"),
              json.dumps(body, ensure_ascii=False)[:200])
        check("仍然强制联网（force=true）", body.get("force") is True)
        check("搜索框已清空", not (ev(ws, "document.getElementById('f-keyword').value") or "").strip())
        check("订阅设置的搜索词也清空", not (ev(ws, "document.getElementById('s-keyword').value") or "").strip())
        check("「恢复自动搜索」按钮已隐藏",
              bool(ev(ws, "document.getElementById('btn-keyword-reset').hidden")))

        # ---- ⑤ 加入订阅会把框里的词存进订阅 ----
        print("\n【5】加入订阅：把搜索框里的词带进订阅（自动追新只认它）")
        set_input(ws, "f-keyword", KW_TYPED)
        ev(ws, "document.getElementById('btn-keyword-search').click()")
        time.sleep(1.0)
        ev(ws, "window.__probe.clearCalls()")
        ev(ws, "document.getElementById('btn-sub-add-res').click()")
        time.sleep(1.5)
        subs_calls = json.loads(ev(ws, "JSON.stringify(window.__probe.calls('/api/subscriptions', 'POST').map(c => c.body))") or "[]")
        sub_body = subs_calls[-1] if subs_calls else {}
        check("点「加入订阅」提交了订阅", bool(subs_calls), json.dumps(sub_body, ensure_ascii=False)[:200])
        check("订阅里存下了搜索框里的关键词", sub_body.get("custom_keyword") == KW_TYPED,
              json.dumps(sub_body, ensure_ascii=False)[:200])

        # 截图（给人工看：搜索框 / 手动搜索 / 没有重新搜索按钮 / 订阅设置里的搜索词）
        os.makedirs(SHOTS, exist_ok=True)
        shot = os.path.join(SHOTS, "45_manual_keyword.png")
        r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
        with open(shot, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        print(f"\n  截图 -> {shot}")
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
