"""快速自检：新增的语言筛选器/语言列/CSS 是否到位。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(ROOT, "app", "web", "index.html"), encoding="utf-8").read()
css = open(os.path.join(ROOT, "app", "web", "styles.css"), encoding="utf-8").read()

print("=== 表头列 ===")
ths = re.findall(r'<th class="([^"]+)"[^>]*>(.*?)</th>', html, re.S)
for cls, txt in ths:
    print(f"  {cls:18s} {re.sub('<[^>]+>', '', txt).strip()}")
print(f"  共 {len(ths)} 列")

print("\n=== 筛选器 ===")
for fid in ("f-source", "f-group", "f-lang", "f-res", "f-sort"):
    print(f"  {'OK ' if f'id=\"{fid}\"' in html else 'MISS'} {fid}")

print("\n=== 语言选项 ===")
m = re.search(r'<select id="f-lang">(.*?)</select>', html, re.S)
if m:
    for v, t in re.findall(r'<option value="([^"]*)"[^>]*>([^<]+)</option>', m.group(1)):
        print(f"  value={v!r:10s} {t}")
else:
    print("  未找到 #f-lang")

print("\n=== CSS ===")
print(f"  花括号配平: {css.count('{')}/{css.count('}')} "
      f"{'OK' if css.count('{') == css.count('}') else 'MISMATCH'}")
for cls in (".col-lang", ".lang-pill", ".lang-chs", ".lang-cht", ".lang-both", ".lang-jp", ".lang-none"):
    print(f"  {'OK ' if cls in css else 'MISS'} {cls}")

widths = dict(re.findall(r"\.(col-[a-z]+)\s*\{\s*width:\s*([^;]+);", css))
th_cols = {c for cls, _ in ths for c in cls.split() if c.startswith("col-")}
missing = sorted(th_cols - set(widths))
print(f"\n  列宽定义齐全: {'OK' if not missing else '缺 ' + str(missing)}")
sys.exit(1 if missing else 0)
