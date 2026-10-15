"""局域网访问验收：配置已开、真的监听了局域网地址、设置页能看到可复制的地址。

用法：python _probe\\t_lan.py   （默认打 http://127.0.0.1:7788，也就是当前跑着的那个实例）
产物：_probe/shots/31_lan_settings.png
"""
import base64
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = os.environ.get("ANIME_BASE", "http://127.0.0.1:7788")
PASS, FAIL = [], []
SHOTS = os.path.join(ROOT, "_probe", "shots")


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


def get_json(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


print("=" * 74)
print("1. 配置与状态：局域网访问已开启，且给出了可用地址")
print("=" * 74)
t0 = time.time()
st = get_json(BASE + "/api/status")
elapsed = time.time() - t0
check("开启局域网访问后 /api/status 返回 lan_enabled=true", st.get("lan_enabled") is True, str(st.get("lan_enabled")))
urls = st.get("lan_urls") or []
print(f"    服务给出的局域网地址：{urls}")
check("给出了至少一个局域网地址", bool(urls), str(urls))
check("地址里没有回环/链路本地/代理 fake-IP",
      all(not u.split("//")[1].startswith(("127.", "169.254.", "198.18.", "198.19.")) for u in urls), str(urls))
check("状态接口没有被地址探测拖慢（<2s）", elapsed < 2.0, f"{elapsed:.2f}s")

print()
print("=" * 74)
print("2. 真的能从局域网地址连上（只绑 127.0.0.1 的话这里会连不上）")
print("=" * 74)
reachable = []
for u in urls:
    host = u.split("//")[1].split(":")[0]
    port = int(u.split(":")[-1].rstrip("/"))
    try:
        with socket.create_connection((host, port), timeout=4):
            reachable.append(u)
    except OSError as e:
        print(f"    {u} -> 连不上（{e}）")
check("至少一个局域网地址可以建立 TCP 连接", bool(reachable), str(reachable))
if reachable:
    try:
        page = get_json(reachable[0].rstrip("/") + "/api/status")
        check("从局域网地址能取到 API 数据", page.get("ok") is True, str(page.get("subscriptions")) + " 条订阅")
    except Exception as e:                                   # noqa: BLE001
        check("从局域网地址能取到 API 数据", False, str(e))
    try:
        with urllib.request.urlopen(reachable[0], timeout=10) as r:
            html = r.read().decode("utf-8", "replace")
        check("从局域网地址能打开页面", r.status == 200 and "app.js" in html, f"HTTP {r.status}")
    except Exception as e:                                   # noqa: BLE001
        check("从局域网地址能打开页面", False, str(e))

print()
print("=" * 74)
print("3. 其它设备能不能进来：监听状态 + Windows 防火墙")
print("=" * 74)
listen = ""
try:
    listen = subprocess.run(["powershell", "-NoProfile", "-Command",
                             "(Get-NetTCPConnection -LocalPort %d -State Listen).LocalAddress -join ','"
                             % (int(urls[0].split(':')[-1].rstrip('/')) if urls else 7788)],
                            capture_output=True, text=True, timeout=60).stdout.strip()
except Exception as e:                                       # noqa: BLE001
    listen = f"(查询失败 {e})"
print(f"    监听地址：{listen or '(空)'}")
check("监听在 0.0.0.0（所有网卡）而不是只有 127.0.0.1",
      "0.0.0.0" in listen or any(u.split("//")[1].split(":")[0] in listen for u in urls), listen)

prof = ""
try:
    prof = subprocess.run(["netsh", "advfirewall", "show", "allprofiles", "state"],
                          capture_output=True, text=True, timeout=60).stdout
except Exception:                                            # noqa: BLE001
    pass
pub_off = "Public Profile Settings" in prof and "State" in prof and \
    any(line.strip().upper().startswith("STATE") and "OFF" in line.upper()
        for line in prof.split("Public Profile Settings")[-1].splitlines()[:6])
rule = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
                      capture_output=True, text=True, timeout=120).stdout
has_rule = ("7788" in rule) or ("自动下载番剧" in rule)
print(f"    防火墙：公网配置文件关闭={pub_off}，有针对 7788/本程序的入站规则={has_rule}")
check("防火墙不会挡住局域网访问（公网配置文件关闭 或 已有入站放行规则）", pub_off or has_rule,
      f"pub_off={pub_off} rule={has_rule}")

print()
print("=" * 74)
print("4. 设置页能看到地址（手机照着填）")
print("=" * 74)
BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe") if os.path.exists(p)), None)
sys.path.insert(0, os.path.join(ROOT, "_probe"))
from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

cdp = free_port()
profile = os.path.join(tempfile.gettempdir(), f"lan-{int(time.time())}")
proc = subprocess.Popen([BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                         f"--user-data-dir={profile}", f"--remote-debugging-port={cdp}",
                         "--window-size=1600,1000", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ev(ws, expr, timeout=120):
    r = ws.call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True}, timeout=timeout)
    res = r.get("result", {})
    if res.get("subtype") == "error":
        raise RuntimeError(res.get("description"))
    return res.get("value")


try:
    wait_cdp(cdp)
    ws = WS(open_page(cdp, "about:blank"))
    ws.call("Runtime.enable")
    ws.call("Page.enable")
    ws.call("Emulation.setDeviceMetricsOverride",
            {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    ws.call("Page.navigate", {"url": BASE + "/"})
    for _ in range(60):
        if ev(ws, "!!document.body && document.body.classList.contains('app-ready')"):
            break
        time.sleep(1.0)
    ev(ws, "document.querySelector('.nav-item[data-view=config]').click()")
    time.sleep(2.0)
    hint = ev(ws, "document.getElementById('lan-hint').innerText") or ""
    shown = bool(ev(ws, "!document.getElementById('lan-hint').hidden"))
    print(f"    设置页提示：{hint.replace(chr(10), ' | ')[:160]}")
    check("设置页显示了局域网地址区块", shown)
    check("提示里含可点击的完整地址", ("http://" in hint) and any(
        u.split("//")[1].split(":")[0] in hint for u in urls), hint[:120])
    check("勾选状态与配置一致（允许局域网访问已勾上）",
          ev(ws, "document.getElementById('cfg-lan').checked") is True)
    # 截图前把「服务」面板滚到视野里（局域网地址就在那块下面）
    ev(ws, """(() => {
      const box = document.getElementById('lan-hint');
      box.scrollIntoView({block: 'center'});
      return true;
    })()""")
    time.sleep(0.8)
    r = ws.call("Page.captureScreenshot", {"format": "png"}, timeout=90)
    shot = os.path.join(SHOTS, "31_lan_settings.png")
    open(shot, "wb").write(base64.b64decode(r["data"]))
    print(f"  截图 -> {shot}")
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
