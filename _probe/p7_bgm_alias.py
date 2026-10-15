"""探测 bgm.tv 网页版是否提供更多别名（用于搜索关键词）。"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import http

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}

for sid in [400602, 513878]:
    url = f"https://bgm.tv/subject/{sid}"
    try:
        code, text, _ = http.request(url, headers=UA, timeout=20)
        print(f"=== {url} -> {code} len={len(text)}")
        m = re.search(r"<h2>中文名</h2>(.{0,400}?)</li>", text, re.S)
        if m:
            print("  中文名块:", re.sub(r"\s+", " ", m.group(1))[:300])
        # 别名区块
        m2 = re.search(r"(别名|別名|中文名|英文名).{0,80}?<div class=\"infobox\".{0,600}", text, re.S)
        i = text.find("infobox")
        # 找出所有 infobox 行
        rows = re.findall(r'<li[^>]*>\s*<span class="tip">([^<]+)</span>(.*?)</li>', text, re.S)
        print("  infobox rows:", len(rows))
        for k, v in rows:
            vv = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", v)).strip()
            if ("别名" in k or "中文名" in k or "英文" in k or "日文" in k or "話數" in k or "话数" in k or "放送" in k):
                print(f"    {k.strip()} = {vv[:200]}")
        open(f"_probe/out/bgm_{sid}.html", "w", encoding="utf-8").write(text)
    except Exception as e:
        print(f"=== {url} ERR {type(e).__name__} {e}")

print("\n=== /v0/subjects/{id}/persons 是否含制作组 ===")
try:
    d = http.get_json("https://api.bgm.tv/v0/subjects/400602/persons", headers=UA, timeout=20)
    print("  persons:", len(d) if isinstance(d, list) else d)
    if isinstance(d, list) and d:
        print("  sample:", json.dumps(d[0], ensure_ascii=False)[:300])
except Exception as e:
    print("  ERR", type(e).__name__, e)
