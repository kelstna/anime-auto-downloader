"""后端冒烟测试：导入、API 路由、qBittorrent、真实 HTTP 接口。

注意：配置与订阅写入临时目录（ANIME_DATA_DIR），不会改动项目 data/config.json。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP_DATA = tempfile.mkdtemp(prefix="anime-api-")
os.environ["ANIME_DATA_DIR"] = TMP_DATA

from app.core import config, logger, qbittorrent   # noqa: E402
from app.web import server                         # noqa: E402

logger.set_console(False)
assert config.DATA_DIR == TMP_DATA, f"数据目录未隔离：{config.DATA_DIR}"
config.update({"server": {"host": "127.0.0.1", "port": 7799},
               "bangumi_token": os.environ.get("BGM_TOKEN", "")})

PORT = 7799
httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.5)
print(f"服务已在 {PORT} 启动\n")


def call(method, path, body=None, timeout=120):
    url = f"http://127.0.0.1:{PORT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8")
            return r.status, txt, time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", time.time() - t0


def show(method, path, body=None, brief=260, timeout=120):
    code, txt, dt = call(method, path, body, timeout)
    flag = "OK " if code == 200 else "ERR"
    print(f"[{flag}] {method:6s} {path:42s} {code} {dt:5.1f}s")
    try:
        d = json.loads(txt)
        if isinstance(d, dict) and not d.get("ok", True) is False:
            pass
        s = json.dumps(d, ensure_ascii=False)
        print("      " + (s[:brief] + ("…" if len(s) > brief else "")))
    except ValueError:
        print("      " + txt[:brief])
    return code, txt


print("=== 1. 静态页面 ===")
for p in ("/", "/styles.css", "/app.js"):
    code, txt, dt = call("GET", p)
    print(f"  GET {p:12s} -> {code} len={len(txt)}")

print("\n=== 2. 基础接口 ===")
show("GET", "/api/status", brief=700)
show("GET", "/api/config", brief=400)
show("GET", "/api/qb/test", brief=500)

print("\n=== 3. Bangumi ===")
show("POST", "/api/bangumi/token", {"token": os.environ.get("BGM_TOKEN", "")}, brief=300)
code, txt = show("GET", "/api/bangumi/me", brief=300)
show("GET", "/api/bangumi/subject/498378", brief=900)

print("\n=== 4. 拉取在看番剧（应该 36 部）===")
code, txt = show("GET", "/api/bangumi/collections?type=3", brief=300, timeout=300)
try:
    items = json.loads(txt).get("items", [])
    print(f"      -> 共 {len(items)} 部")
    for it in items[:3]:
        print(f"         {it['display_name'][:30]:32s} eps={it.get('total_episodes')} 别名={len(it.get('aliases', []))}")
    target = next((x for x in items if "间谍过家家" in (x.get("display_name") or "")), None) or (items[0] if items else None)
except Exception as e:
    print("      解析失败:", e)
    target = None

print("\n=== 5. 字幕组 + 搜索 ===")
if target:
    sid = target["id"]
    print(f"  目标番剧: [{sid}] {target['display_name']}")
    code, txt = show("POST", "/api/groups", {"subject_id": sid}, brief=600, timeout=300)
    try:
        groups = json.loads(txt).get("groups", [])
        gn = groups[0]["name"] if groups else ""
        print(f"      -> {len(groups)} 个字幕组，示例：{gn}")
    except Exception:
        gn = ""
    show("POST", "/api/search", {"subject_id": sid, "group": gn}, brief=700, timeout=300)

print("\n=== 6. 订阅（不实际下载，先看接口形状）===")
show("GET", "/api/subscriptions", brief=400)
show("GET", "/api/qb/folders", brief=300)

print("\n=== 7. 封面代理 ===")
code, txt, dt = call("GET", "/api/cover?url=https%3A%2F%2Flain.bgm.tv%2Fpic%2Fcover%2Fl%2Fdb%2F94%2F513878_54i56.jpg")
print(f"  /api/cover -> {code} bytes={len(txt)} {dt:.1f}s")

print("\n=== 8. 错误处理 ===")
show("GET", "/api/nope", brief=120)
show("GET", "/api/subscriptions/999999", brief=120)
show("POST", "/api/search", {"subject_id": 0}, brief=120)

httpd.shutdown()
shutil.rmtree(TMP_DATA, ignore_errors=True)
print("\n完成")
