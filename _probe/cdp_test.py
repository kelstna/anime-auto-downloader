"""
CDP 真实浏览器对齐测试（无需安装任何依赖）：
启动 Chrome headless --remote-debugging-port，用标准库 WebSocket 在真实渲染的页面上
执行 JS 测量元素几何信息，验证「文字是否对齐」（用户明确要求）。

检查项：
- 表格数字列右边缘是否共线（右对齐生效）
- 每列左边缘是否共线（列对齐）
- 标题单元格是否单行省略（无溢出/换行错位）
- 卡片高度、卡片内标题基线是否一致
- 表单 label 与输入框左边缘是否对齐
- 是否存在横向溢出（内容被裁切）
- 页面是否有控制台错误
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
BROWSER = next((p for p in BROWSERS if os.path.exists(p)), None)
if not BROWSER:
    raise SystemExit("找不到 Chrome/Edge")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = ""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


# --------------------------------------------------------------------------- #
# 极简 WebSocket 客户端（标准库实现，仅支持客户端文本帧）
# --------------------------------------------------------------------------- #
class WS:
    def __init__(self, url: str, timeout: float = 60.0):
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("WebSocket 握手失败")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise OSError(f"WebSocket 握手返回异常: {buf.split(b'\r\n')[0]!r}")
        self.buf = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0

    def _send_frame(self, payload: bytes, opcode: int = 0x1):
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("连接已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_message(self) -> str:
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            payload = self._recv_exact(length)
            if opcode == 0x1:
                return payload.decode("utf-8", "replace")
            if opcode == 0x8:
                raise OSError("服务端关闭了 WebSocket")
            # ping/pong/其他帧忽略

    def call(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        self._id += 1
        mid = self._id
        self._send_frame(json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.recv_message())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} 失败: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self):
        try:
            self._send_frame(b"", opcode=0x8)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory: str, port: int) -> ThreadingHTTPServer:
    handler = lambda *a, **kw: Quiet(*a, directory=directory, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def wait_cdp(port: int, timeout: float = 30.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                info = json.loads(r.read().decode())
            return info["webSocketDebuggerUrl"]
        except Exception:
            time.sleep(0.35)
    raise TimeoutError("Chrome 调试端口未就绪")


def open_page(port: int, url: str, timeout: float = 30.0) -> str:
    """新建标签页并返回其 webSocketDebuggerUrl。"""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{url}", method="PUT")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode())["webSocketDebuggerUrl"]
        except Exception as e:      # noqa: BLE001
            last = str(e)
            time.sleep(0.4)
    raise TimeoutError(f"无法新建标签页: {last}")


ALIGN_JS = r"""
(() => {
  const r = el => { const b = el.getBoundingClientRect(); return {l:b.left, r:b.right, t:b.top, b:b.bottom, w:b.width, h:b.height}; };
  const txt = el => (el.textContent || '').trim();
  const out = { errors: window.__capturedErrors || [] };

  // ---- 资源表格 ----
  const table = document.querySelector('#res-table') || document.querySelector('.data-table');
  if (table) {
    const heads = [...table.querySelectorAll('thead th')];
    out.thCount = heads.length;
    out.thClasses = heads.map(h => h.className);
    out.thBoxes = heads.map(h => r(h));
    const rows = [...table.querySelectorAll('tbody tr')];
    out.rowCount = rows.length;
    out.rows = rows.slice(0, 6).map(tr => {
      const tds = [...tr.querySelectorAll('td')];
      return {
        cellCount: tds.length,
        classes: tds.map(td => td.className),
        boxes: tds.map(td => r(td)),
        texts: tds.map(td => txt(td).slice(0, 28)),
        aligned: tds.map(td => getComputedStyle(td).textAlign),
        heights: tds.map(td => td.getBoundingClientRect().height),
      };
    });
    // 标题列是否单行省略（scrollHeight 不应明显超过客户端高度）
    out.titleOverflow = rows.slice(0, 6).map(tr => {
      const td = tr.querySelector('.col-title');
      if (!td) return null;
      const span = td.querySelector('span') || td;
      return { sh: span.scrollHeight, ch: span.clientHeight, ws: getComputedStyle(span).whiteSpace };
    });
    // 第一行各单元格的垂直中心（用于验证同一行内文字垂直对齐）
    if (rows[0]) {
      out.rowCenters = [...rows[0].querySelectorAll('td')].map(td => {
        const b = td.getBoundingClientRect();
        return +(b.top + b.height / 2).toFixed(1);
      });
    }
  }

  // ---- 卡片 ----
  const cards = [...document.querySelectorAll('.card')];
  out.cardCount = cards.length;
  if (cards.length) {
    out.cardHeights = cards.map(c => +c.getBoundingClientRect().height.toFixed(1));
    out.cardTitles = cards.map(c => { const t = c.querySelector('.card-title'); return t ? r(t).t : null; });
    out.cardTitleHeights = cards.map(c => { const t = c.querySelector('.card-title'); return t ? +t.getBoundingClientRect().height.toFixed(1) : null; });
  }

  // ---- 表单 label 与输入框左边缘 ----
  // 注意：开关控件(.switch)的 label 是包住 input 的，左边缘天然不同，需要排除
  const fields = [...document.querySelectorAll('.field')];
  out.fieldAlign = fields.slice(0, 10).map(f => {
    const lab = [...f.children].find(c => c.tagName === 'LABEL');
    const inp = f.querySelector('input:not([type=checkbox]), select');
    if (!lab || !inp) return null;
    if (lab.classList.contains('switch') || lab.querySelector('input')) return { dl: 0, skip: 'switch' };
    return { dl: +(lab.getBoundingClientRect().left - inp.getBoundingClientRect().left).toFixed(1) };
  }).filter(Boolean);

  // ---- 侧栏状态行 ----
  // hidden 的行（例如没排队时隐藏的「待下载」）要排除：它的 rect 全是 0，
  // 会让「行等距」算出 -845 / 871 这种假值
  const statusRows = [...document.querySelectorAll('.side-status .status-row')]
    .filter(x => !x.hidden && x.getBoundingClientRect().height > 0);
  out.statusRowBoxes = statusRows.map(x => r(x));

  // ---- 溢出检测 ----
  out.overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  const clipped = [];
  document.querySelectorAll('.card-title, .sub-item-title, .group-name, .ellipsis, .status-row b').forEach(el => {
    if (el.scrollWidth - el.clientWidth > 2) clipped.push({ cls: el.className, txt: txt(el).slice(0, 24), over: el.scrollWidth - el.clientWidth });
  });
  out.clipped = clipped.slice(0, 10);

  // ---- 主题与字体 ----
  const cs = getComputedStyle(document.body);
  out.bodyFont = cs.fontFamily;
  out.fontSize = cs.fontSize;
  out.theme = document.documentElement.dataset.theme;

  // ---- body 标记（app.js 约定） ----
  out.bodyClass = document.body.className;
  out.bodyView = document.body.dataset.view || '';
  out.hasApp = !!window.__APP_LOADED__;
  return out;
})()
"""


def main() -> int:
    print("=" * 76)
    print("CDP 真实浏览器对齐测试")
    print("=" * 76)
    print(f"  浏览器：{BROWSER}")

    static_port = free_port()
    cdp_port = free_port()
    httpd = serve(ROOT, static_port)

    from app.core import config as _cfg, logger            # noqa: E402
    from app.web import server                             # noqa: E402
    logger.set_console(False)
    api_port = free_port()
    srv = server.serve_forever("127.0.0.1", api_port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    profile = os.path.join(tempfile.gettempdir(), f"cdp-{int(time.time())}")
    proc = subprocess.Popen(
        [
            BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--no-first-run", "--disable-extensions", "--force-device-scale-factor=1",
            f"--user-data-dir={profile}", f"--remote-debugging-port={cdp_port}",
            "--window-size=1600,1100", "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    try:
        ws_url = wait_cdp(cdp_port)
        print(f"  CDP 已就绪：{ws_url}\n")

        # ---------------- A. 组件快照页 ----------------
        print("A. 组件布局（真实 CSS + 真实 DOM 结构）")
        page_ws = open_page(cdp_port, f"http://127.0.0.1:{static_port}/_probe/ui_components.html")
        ws = WS(page_ws)
        try:
            ws.call("Runtime.enable")
            time.sleep(1.2)
            res = ws.call("Runtime.evaluate", {"expression": ALIGN_JS, "returnByValue": True})
            d = res.get("result", {}).get("value") or {}
            print(f"    表格列数={d.get('thCount')} 行数={d.get('rowCount')} 卡片数={d.get('cardCount')}")

            # 1) 列对齐：每列左边缘共线
            rows = d.get("rows", [])
            if rows:
                ncols = max(len(x["boxes"]) for x in rows)
                check("表头与数据行列数一致", d.get("thCount") == ncols,
                      f"th={d.get('thCount')} td={ncols}")
                misaligned = []
                for ci in range(ncols):
                    lefts = [x["boxes"][ci]["l"] for x in rows if len(x["boxes"]) > ci]
                    if lefts and (max(lefts) - min(lefts)) > 1.5:
                        misaligned.append((ci, round(max(lefts) - min(lefts), 1)))
                check("每列左边缘共线（列对齐）", not misaligned, f"偏差列={misaligned}")

                # 2) 数字列右对齐：右边缘共线
                num_ok, num_bad = [], []
                for ci, cls in enumerate(rows[0]["classes"]):
                    if "num" in cls.split():
                        rights = [x["boxes"][ci]["r"] for x in rows if len(x["boxes"]) > ci]
                        spread = max(rights) - min(rights)
                        (num_ok if spread <= 1.5 else num_bad).append((cls, round(spread, 1)))
                check("数字列右边缘共线（右对齐生效）", not num_bad and len(num_ok) >= 3,
                      f"对齐列={num_ok} 偏差={num_bad}")
                aligns = {x["aligned"][ci] for x in rows for ci in range(len(x["aligned"]))
                          if "num" in rows[0]["classes"][ci].split()}
                check("数字列 text-align 为 right", aligns <= {"right"}, f"{aligns}")

                # 3) 行内垂直居中一致
                centers = d.get("rowCenters", [])
                check("同一行内各单元格垂直居中一致",
                      bool(centers) and (max(centers) - min(centers)) <= 1.0,
                      f"中心差 {round(max(centers) - min(centers), 2) if centers else '-'}px")

                heights = [h for x in rows for h in x["heights"]]
                check("行高一致（无塌陷/重叠）", bool(heights) and (max(heights) - min(heights)) <= 1.0,
                      f"最小 {min(heights):.1f} 最大 {max(heights):.1f}" if heights else "")

                # 4) 标题单行省略
                to = [x for x in d.get("titleOverflow", []) if x]
                check("标题列单行省略（不换行错位）",
                      all(x["ws"] == "nowrap" for x in to) and
                      all(x["sh"] - x["ch"] <= 1 for x in to),
                      f"{to[:2]}")

                # 5) 操作列按钮不换行
                act = [x for x in rows if len(x["boxes"]) == ncols]
                check("操作列宽度足够（按钮不换行）",
                      all(x["boxes"][-1]["w"] >= 100 for x in act),
                      f"最小 {min(x['boxes'][-1]['w'] for x in act):.0f}px" if act else "")

            # 6) 卡片对齐
            hs = d.get("cardHeights", [])
            if hs:
                check("卡片等高", (max(hs) - min(hs)) <= 2, f"高度 {hs}")
                tts = [t for t in d.get("cardTitles", []) if t]
                check("卡片标题顶边一致（网格对齐）",
                      len(tts) > 1 and (max(tts) - min(tts)) <= 2,
                      f"顶边 {[round(t, 1) for t in tts]}")
                ths = [x for x in d.get("cardTitleHeights", []) if x]
                check("卡片标题占两行高度（不被裁切）",
                      all(20 <= x <= 44 for x in ths), f"{ths}")

            # 7) 表单对齐
            fa = [x for x in d.get("fieldAlign", []) if x]
            check("表单 label 与输入框左边缘对齐",
                  all(abs(x["dl"]) <= 1 for x in fa), f"{[x['dl'] for x in fa]}")

            # 8) 无障碍/字体
            print(f"    字体：{d.get('bodyFont', '')[:70]}")
            check("使用了适合中文的字体栈",
                  any(k in (d.get("bodyFont") or "") for k in ("YaHei", "PingFang", "Noto Sans SC", "Source Han")),
                  d.get("bodyFont", "")[:50])
            check("无横向溢出（内容未被裁切）", d.get("overflowX", 0) <= 1, f"溢出 {d.get('overflowX')}px")
            check("无元素文字被意外裁切", not d.get("clipped"),
                  f"{d.get('clipped')}")
        finally:
            ws.close()

        # ---------------- B. 真实页面（带 app.js） ----------------
        appjs = os.path.join(ROOT, "app", "web", "app.js")
        if os.path.exists(appjs):
            print("\nB. 真实页面（app.js + 后端 API，实数据）")
            # 先开空白页 -> 注册新文档注入的错误收集 -> 导航，确保初始化阶段报错也能抓到
            page_ws = open_page(cdp_port, "about:blank")
            ws = WS(page_ws)
            try:
                ws.call("Runtime.enable")
                ws.call("Page.enable")
                ws.call("Page.addScriptToEvaluateOnNewDocument", {"source":
                        "window.__capturedErrors=[];"
                        "window.addEventListener('error',e=>window.__capturedErrors.push('error: '+String(e.message)));"
                        "window.addEventListener('unhandledrejection',e=>window.__capturedErrors.push('rej: '+String(e.reason)));"})
                ws.call("Page.navigate", {"url": f"http://127.0.0.1:{api_port}/"})
                time.sleep(1.0)
                injected = ws.call("Runtime.evaluate", {
                    "expression": "typeof window.__capturedErrors !== 'undefined'",
                    "returnByValue": True}).get("result", {}).get("value")
                check("JS 错误监听已注入生效（防止断言空转）", injected is True, str(injected))
                # 等待 app.js 初始化完成：真实接口（Bangumi 36 部详情）需要十几秒
                waited = 0.0
                while waited < 90.0:
                    ready = ws.call("Runtime.evaluate", {
                        "expression": "document.body.classList.contains('app-ready')",
                        "returnByValue": True,
                    }).get("result", {}).get("value")
                    if ready:
                        break
                    time.sleep(1.0)
                    waited += 1.0
                print(f"    等待初始化 {waited:.0f}s")
                time.sleep(0.8)
                # 若长时间拿不到数据，先告诉用户大概率是网络/代理问题（不静默失败）
                if waited >= 90.0:
                    hint = ws.call("Runtime.evaluate", {
                        "expression": "document.getElementById('anime-empty')?.textContent || ''",
                        "returnByValue": True}).get("result", {}).get("value")
                    print(f"    !! 未在 90s 内就绪；页面提示：{str(hint)[:120]}")
                    print("    !! 提示：这项测试需要联网（Bangumi）。直连不通时请在配置里启用代理。")
                res = ws.call("Runtime.evaluate", {"expression": ALIGN_JS, "returnByValue": True})
                d = res.get("result", {}).get("value") or {}
                print(f"    bodyClass={d.get('bodyClass')!r} view={d.get('bodyView')!r} 主题={d.get('theme')}")
                check("app.js 已加载并初始化（body 有 app-ready）",
                      "app-ready" in (d.get("bodyClass") or ""), d.get("bodyClass"))
                check("视图名写入 body.dataset.view", bool(d.get("bodyView")), d.get("bodyView"))
                check("深浅主题变量已应用", d.get("theme") in ("dark", "light"), d.get("theme"))
                check("页面无未捕获 JS 错误", not d.get("errors"), str(d.get("errors"))[:200])
                check("侧栏状态行已渲染", len(d.get("statusRowBoxes", [])) >= 4,
                      f"{len(d.get('statusRowBoxes', []))} 行")
                srows = d.get("statusRowBoxes", [])
                if len(srows) >= 3:
                    tops = [x["t"] for x in srows]
                    gaps = [round(tops[i + 1] - tops[i], 1) for i in range(len(tops) - 1)]
                    check("侧栏状态行等距排列（文字对齐）",
                          max(gaps) - min(gaps) <= 1.5, f"行距 {gaps}")

                # 真实页面 HTML 结构检查
                res2 = ws.call("Runtime.evaluate", {
                    "expression": "JSON.stringify({cards:document.querySelectorAll('#anime-grid .card').length,"
                                  "empty:!document.getElementById('anime-empty').hidden,"
                                  "tokenVal:document.getElementById('token-input').value.length,"
                                  "linkHref:document.getElementById('link-get-token').href,"
                                  "linkText:document.getElementById('link-get-token').textContent.trim(),"
                                  "navActive:document.querySelector('.nav-item.is-active')?.dataset.view,"
                                  "title:document.getElementById('view-title').textContent.trim()})",
                    "returnByValue": True,
                })
                info = json.loads(res2["result"]["value"])
                print(f"    卡片 {info['cards']} 张，标题 {info['title']!r}，当前视图 {info['navActive']!r}")
                check("获取 Token 链接指向官方地址",
                      info["linkHref"] == "https://next.bgm.tv/demo/access-token", info["linkHref"])
                check("获取 Token 链接有可见文字", len(info["linkText"]) >= 3, info["linkText"])
                check("侧栏默认激活「在看番剧」", info["navActive"] == "anime", info["navActive"])
                check("页面标题正确", "番剧" in info["title"], info["title"])
            finally:
                ws.close()
        else:
            print("\nB. app.js 尚未生成，跳过真实页面测试")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:      # noqa: BLE001
            proc.kill()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        srv.shutdown()
        httpd.shutdown()

    print()
    print("=" * 76)
    print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    print("=" * 76)
    for f in FAIL:
        print("  [失败]", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
