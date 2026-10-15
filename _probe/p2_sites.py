"""Probe HTML structure of dmhy / kisssub / nyaa (fixed httpx 0.28 proxy arg + encoding)."""
import httpx, re, os

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
os.makedirs("_probe/out", exist_ok=True)

def dump(name, url, params=None, encoding=None):
    try:
        r = httpx.get(url, params=params, headers=UA, timeout=25, follow_redirects=True)
    except Exception as e:
        print(f"### {name} ERR {type(e).__name__} {e}")
        return None
    if encoding:
        r.encoding = encoding
    else:
        r.encoding = r.charset_encoding or "utf-8"
    print(f"### {name} {r.status_code} len={len(r.text)} ctype={r.headers.get('content-type')} detected={r.charset_encoding} final={r.url}")
    with open(f"_probe/out/{name}.html", "w", encoding="utf-8", errors="replace") as f:
        f.write(r.text)
    return r

KW = "葬送的芙莉莲"

r = dump("dmhy", "https://share.dmhy.org/topics/list", {"keyword": KW, "sort_id": 2}, encoding="utf-8")
if r:
    t = r.text
    i = t.find('id="topic_list"')
    print(t[i:i+2600] if i > 0 else "NO topic_list\n" + t[:1500])

r2 = dump("kisssub", "https://www.kisssub.org/search.php", {"keyword": KW}, encoding="utf-8")
if r2:
    print(r2.text[:2500])

r3 = dump("nyaa", "https://nyaa.si/", {"q": "Sousou no Frieren", "c": "1_2", "f": "0", "s": "seeders", "o": "desc"})
if r3:
    t = r3.text
    i = t.find("<tbody")
    print(t[i:i+2800] if i > 0 else "NO tbody\n" + t[:1500])

# dmhy group filter page
r4 = dump("dmhy_groups", "https://share.dmhy.org/topics/list/sort_id/2", encoding="utf-8")
if r4:
    t = r4.text
    m = re.findall(r'<option value="(\d+)"[^>]*>([^<]+)</option>', t)
    print("dmhy sort options sample:", m[:8], "count", len(m))
