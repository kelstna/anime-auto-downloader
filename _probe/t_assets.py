"""验证静态资源版本号注入（在独立端口上起服务，避免与用户实例冲突）。"""
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["ANIME_DATA_DIR"] = tempfile.mkdtemp(prefix="vercheck-")

from app.core import logger                     # noqa: E402
from app.web import server                      # noqa: E402

logger.set_console(False)
PORT = 7841

print(f"计算出的资源版本号: {server._ASSET_VERSION}")
httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)


def fetch(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=20) as r:
        return r.status, r.read()


def head_headers(path, extra=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", headers=extra or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)          # 304 会走到这里


PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


code, body = fetch("/")
html = body.decode("utf-8")
refs = re.findall(r'(?:href|src)="((?:styles\.css|ui\.js|app\.js)[^"]*)"', html)
print(f"  资源引用: {refs}")
check("index.html 里不再残留占位符", "__APP_VERSION__" not in html)
check("三个资源都带上了版本号", len(refs) == 3 and all("?v=" in r for r in refs), str(refs))
check("版本号与计算值一致",
      all(r.endswith(f"?v={server._ASSET_VERSION}") for r in refs), server._ASSET_VERSION)
for r in refs:
    code, data = fetch("/" + r)
    check(f"带版本号的 {r.split('?')[0]} 可正常访问", code == 200 and len(data) > 1000, f"{len(data)} 字节")

# HTML 不能长缓存：否则改完界面用户刷新还是旧页面（新元素根本不出现）
status, headers = head_headers("/")
cc = (headers.get("Cache-Control") or "").lower()
etag = headers.get("ETag") or ""
check("index.html 不允许长缓存（no-cache）", "no-cache" in cc, cc or "(无)")
check("index.html 带 ETag", bool(etag), etag or "(无)")
if etag:
    status2, _ = head_headers("/", {"If-None-Match": etag})
    check("带 If-None-Match 刷新返回 304（省流量又不会用旧页面）", status2 == 304, f"状态 {status2}")
_, headers3 = head_headers("/app.js?v=" + server._ASSET_VERSION)
check("带版本号的 JS 仍然可以长缓存",
      "max-age=3600" in (headers3.get("Cache-Control") or ""), headers3.get("Cache-Control"))

httpd.shutdown()
print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
