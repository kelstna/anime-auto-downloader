"""Probe 8: kisssub raw list structure + magnet location."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

k = open("_probe/out/kisssub_after.html", encoding="utf-8").read()
print("len", len(k), "counts: <tr", k.count("<tr"), "magnet", k.count("magnet"), "list_style", k.count("list_style"))
# 找到所有 magnet 出现位置前后的上下文
for m in list(re.finditer(r"magnet:\?xt=urn:btih:([0-9a-zA-Z]{32,40})", k))[:3]:
    print("\n--- magnet ctx ---")
    print(re.sub(r"\s+", " ", k[max(0, m.start() - 1200): m.start() + 300]))

print("\n\n===== 第二个 list_style 表格 =====")
idxs = [m.start() for m in re.finditer(r'class="list_style', k)]
print("list_style positions:", idxs)
if len(idxs) >= 2:
    seg = k[idxs[1]: idxs[1] + 5000]
    print(re.sub(r"\n\s*\n", "\n", seg))
