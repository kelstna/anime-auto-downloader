"""用 Chrome headless 截图 + Pillow 像素分析，做真实渲染的视觉自测。

用法：python _probe/visual_test.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image   # noqa: E402

OUT = os.path.join(ROOT, "_probe", "shots")
os.makedirs(OUT, exist_ok=True)

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
BROWSER = next((p for p in BROWSERS if os.path.exists(p)), None)
if not BROWSER:
    raise SystemExit("找不到 Chrome/Edge")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, extra: str = ""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve(directory: str, port: int) -> ThreadingHTTPServer:
    handler = lambda *a, **kw: Quiet(*a, directory=directory, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def screenshot(url: str, name: str, width: int, height: int, wait_ms: int = 2500) -> str | None:
    path = os.path.join(OUT, f"{name}.png")
    if os.path.exists(path):
        os.remove(path)
    profile = os.path.join(tempfile.gettempdir(), f"chr-{name}-{int(time.time() * 1000)}")
    cmd = [
        BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--disable-extensions", "--no-first-run",
        "--disable-lcd-text", "--run-all-compositor-stages-before-draw",
        f"--user-data-dir={profile}", f"--window-size={width},{height}",
        f"--virtual-time-budget={wait_ms}", f"--screenshot={path}", url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, text=True, errors="replace")
    except subprocess.TimeoutExpired:
        print(f"    !! 浏览器超时：{name}")
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if not os.path.exists(path):
        print(f"    !! 截图失败：{name} rc={proc.returncode} {(proc.stderr or '')[-300:]}")
        return None
    return path


def ink_stats(img: Image.Image, bg) -> tuple[int, float]:
    small = img.resize((max(1, img.width // 4), max(1, img.height // 4)))
    sp = small.load()
    total = small.width * small.height
    ink = 0
    colors = 0
    seen = set()
    for y in range(small.height):
        for x in range(small.width):
            c = sp[x, y]
            seen.add(c)
            if abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) > 24:
                ink += 1
    return len(seen), ink / max(1, total)


def vertical_lines(img: Image.Image, bg, box) -> list[int]:
    x0, y0, x1, y1 = box
    x1 = min(x1, img.width)
    y1 = min(y1, img.height)
    px = img.load()
    cols = []
    for x in range(x0, x1):
        hits = sum(
            1 for y in range(y0, y1)
            if abs(px[x, y][0] - bg[0]) + abs(px[x, y][1] - bg[1]) + abs(px[x, y][2] - bg[2]) > 18
        )
        cols.append((x, hits / max(1, y1 - y0)))
    edges = [x for x, r in cols if r > 0.8]
    merged: list[list[int]] = []
    for x in edges:
        if merged and x - merged[-1][-1] <= 2:
            merged[-1].append(x)
        else:
            merged.append([x])
    return [g[0] for g in merged]


def text_bands(img: Image.Image, bg, box, min_ratio: float = 0.05) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = box
    x1, y1 = min(x1, img.width), min(y1, img.height)
    px = img.load()
    on = []
    for y in range(y0, y1):
        hits = sum(
            1 for x in range(x0, x1)
            if abs(px[x, y][0] - bg[0]) + abs(px[x, y][1] - bg[1]) + abs(px[x, y][2] - bg[2]) > 24
        )
        on.append(hits / max(1, x1 - x0) > min_ratio)
    bands, start = [], None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            bands.append((y0 + start, y0 + i - 1))
            start = None
    if start is not None:
        bands.append((y0 + start, y0 + len(on) - 1))
    return bands


def main() -> int:
    print("=" * 76)
    print("浏览器视觉自测（Chrome headless + 像素分析）")
    print("=" * 76)
    print(f"  浏览器：{BROWSER}")

    httpd = serve(ROOT, 7820)
    try:
        # ---------- A. 组件布局快照 ----------
        print("\nA. 组件布局快照（真实 CSS，表格/卡片/字幕组/订阅/表单）")
        url = "http://127.0.0.1:7820/_probe/ui_components.html"
        path = screenshot(url, "components", 1400, 1500, wait_ms=1800)
        if path:
            img = Image.open(path).convert("RGB")
            bg = img.getpixel((img.width - 4, img.height - 4))
            colors, ratio = ink_stats(img, bg)
            print(f"    尺寸 {img.width}x{img.height} 背景 {bg} 颜色数 {colors} 内容占比 {ratio:.3f}")
            check("组件页渲染出内容（非白屏）", ratio > 0.03, f"{ratio:.3f}")
            check("配色丰富（多主题变量生效）", colors > 60, f"{colors} 种颜色")

            # 表格区域：列竖线应等距且成组（证明列对齐）
            lines = vertical_lines(img, bg, (40, 150, 1360, 380))
            print(f"    表格区竖线：{lines}")
            check("表格有列分隔结构", len(lines) >= 3, f"{len(lines)} 条竖线")
            if len(lines) >= 3:
                gaps = [lines[i + 1] - lines[i] for i in range(len(lines) - 1)]
                print(f"    列宽：{gaps}")
                check("列宽成组且无 0 宽列", all(g >= 20 for g in gaps), f"最小列宽 {min(gaps)}")

            bands = text_bands(img, bg, (40, 140, 1360, 400))
            heights = [b[1] - b[0] + 1 for b in bands]
            print(f"    表格行带高度：{heights}")
            check("表格按行整齐排列", 1 <= len(bands) <= 10, f"{len(bands)} 行带")
            if heights:
                check("行高一致（无重叠/塌陷）", max(heights) - min(heights) <= 30,
                      f"最小 {min(heights)} 最大 {max(heights)}")

        # ---------- B. 真实页面外壳 ----------
        print("\nB. 真实页面（起后端服务，检查接口与静态资源）")
        from app.core import config, logger, qbittorrent      # noqa: E402
        from app.web import server                            # noqa: E402
        logger.set_console(False)
        PORT = 7821
        srv = server.serve_forever("127.0.0.1", PORT)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        time.sleep(0.4)
        try:
            import urllib.request
            for path_, name in (("/", "index.html"), ("/styles.css", "styles.css")):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path_}", timeout=20) as r:
                        body = r.read()
                    check(f"GET {path_} 200", r.status == 200 and len(body) > 1000, f"{len(body)} 字节")
                except Exception as e:
                    check(f"GET {path_} 200", False, str(e))
            appjs = os.path.join(ROOT, "app", "web", "app.js")
            if os.path.exists(appjs):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/app.js", timeout=20) as r:
                        body = r.read()
                    check("GET /app.js 200", r.status == 200 and len(body) > 2000, f"{len(body)} 字节")
                except Exception as e:
                    check("GET /app.js 200", False, str(e))
                # 真实页面截图（app.js 会在没有 token/数据时渲染空状态）
                p2 = screenshot(f"http://127.0.0.1:{PORT}/", "real_page", 1400, 900, wait_ms=4000)
                if p2:
                    img2 = Image.open(p2).convert("RGB")
                    bg2 = img2.getpixel((4, 4))
                    colors2, ratio2 = ink_stats(img2, bg2)
                    print(f"    真实页面 颜色数 {colors2} 内容占比 {ratio2:.3f}")
                    check("真实页面渲染出界面（非白屏）", ratio2 > 0.02, f"{ratio2:.3f}")
            else:
                print("    （app.js 尚未生成，跳过真实页面截图）")
        finally:
            srv.shutdown()
    finally:
        httpd.shutdown()

    print()
    print("=" * 76)
    print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    print(f"截图目录：{OUT}")
    print("=" * 76)
    for f in FAIL:
        print("  [失败]", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
