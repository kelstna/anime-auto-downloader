"""真实浏览器里检查「我的订阅」页能不能正常渲染（防止 JS 运行时错误把整块打挂）。

用法：python _probe/check_subs_page.py
打开的是**正在运行的服务**（默认 http://127.0.0.1:7788/），不需要 mock 数据。
检查：订阅卡片数量、每张卡的「下次更新」、侧栏「最近更新」、有没有报错横幅。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))

from cdp_test import BROWSER, WS, free_port, open_page, wait_cdp  # noqa: E402

URL = os.environ.get("ANIFETCH_URL", "http://127.0.0.1:7788/")

COUNT_JS = r"""
(() => {
  const list = document.getElementById('sub-list');
  const empty = document.getElementById('subs-empty');
  return {
    cards: document.querySelectorAll('#sub-list .sub-item').length,
    subLen: (typeof state !== 'undefined' && state.subs ? state.subs.length : -1),
    listHtmlLen: (list ? list.innerHTML.length : -1),
    emptyVisible: !!(empty && empty.offsetParent !== null),
    emptyText: (empty ? empty.textContent : '').trim().slice(0, 120),
    airFacts: document.querySelectorAll('#sub-list .sub-fact-air').length,
    sideRows: document.querySelectorAll('#side-updates-list .update-row').length,
  };
})()
"""


def ev(ws, expr):
    res = ws.call("Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "awaitPromise": True})
    return res.get("result", {}).get("value")


def main() -> int:
    print("=" * 70)
    print("检查「我的订阅」页渲染（真实浏览器 + 正在运行的服务）")
    print(f"  URL：{URL}")
    print(f"  浏览器：{BROWSER}")
    cdp_port = free_port()
    profile = tempfile.mkdtemp(prefix="cdp-subs-")
    proc = subprocess.Popen(
        [
            BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--no-first-run", "--disable-extensions", "--force-device-scale-factor=1",
            f"--user-data-dir={profile}", f"--remote-debugging-port={cdp_port}",
            "--window-size=1600,1100", "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws = None
    try:
        wait_cdp(cdp_port)
        ws = WS(open_page(cdp_port, URL))
        ws.call("Runtime.enable")
        # 等订阅数据到位（页面首屏会先拉 /api/subscriptions）
        for _ in range(30):
            n = ev(ws, "typeof state !== 'undefined' && state.subs ? state.subs.length : 0")
            if n:
                break
            time.sleep(0.5)
        ws.call("Runtime.evaluate",
                {"expression": "document.querySelector('[data-view=\"subs\"]').click()"})
        time.sleep(2.5)
        data = ev(ws, COUNT_JS) or {}
        if not data.get("cards"):
            # 点击没生效时直接切视图再试一次（headless 下偶发）
            ws.call("Runtime.evaluate", {"expression": "switchView('subs')"})
            time.sleep(2.0)
            data = ev(ws, COUNT_JS) or {}
    finally:
        if ws is not None:
            ws.close()
        proc.terminate()

    print(json.dumps(data, ensure_ascii=False, indent=2))
    ok = (data.get("cards", 0) > 0
          and not data.get("emptyVisible")
          and "is not defined" not in (data.get("emptyText") or ""))
    print("结果：" + ("订阅页正常渲染" if ok else "订阅页渲染异常"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
