"""Probe: stdlib urllib vs httpx, proxy, kisssub captcha bypass, dmhy team filter, qB API."""
import urllib.request, urllib.parse, ssl, http.cookiejar, json, re, sys, time

CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

print("=== A. stdlib urllib direct ===")
for u in ["https://api.bgm.tv/v0/subjects/253", "https://share.dmhy.org/topics/list?keyword=test", "https://nyaa.si/"]:
    try:
        rq = urllib.request.Request(u, headers={"User-Agent": UA})
        with urllib.request.urlopen(rq, timeout=20, context=CTX) as r:
            print(" OK ", u, r.status, len(r.read()))
    except Exception as e:
        print(" ERR", u, type(e).__name__, str(e)[:100])

print("\n=== B. stdlib urllib via proxy 127.0.0.1:7890 ===")
ph = urllib.request.ProxyHandler({"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"})
op = urllib.request.build_opener(ph)
for u in ["https://share.dmhy.org/topics/list?keyword=test", "https://www.kisssub.org/search.php?keyword=test"]:
    try:
        rq = urllib.request.Request(u, headers={"User-Agent": UA})
        with op.open(rq, timeout=25) as r:
            print(" OK ", u, r.status, len(r.read()))
    except Exception as e:
        print(" ERR", u, type(e).__name__, str(e)[:100])

print("\n=== C. kisssub visitor-test with cookie jar (direct) ===")
cj = http.cookiejar.CookieJar()
op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
try:
    rq = urllib.request.Request("https://www.kisssub.org/", headers={"User-Agent": UA})
    with op2.open(rq, timeout=25) as r:
        body = r.read().decode("utf-8", "replace")
    print(" root status", r.status, "len", len(body), "cookies", [c.name for c in cj])
    if "visitor-test" in body:
        data = urllib.parse.urlencode({"visitor_test": "human"}).encode()
        rq2 = urllib.request.Request(
            "https://www.kisssub.org/addon.php?r=document/view&page=visitor-test", data=data,
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                     "Referer": "https://www.kisssub.org/"})
        with op2.open(rq2, timeout=25) as r2:
            b2 = r2.read().decode("utf-8", "replace")
        print(" after visitor-test:", r2.status, "len", len(b2), "cookies", [c.name for c in cj])
        kw = urllib.parse.quote("葬送的芙莉莲")
        rq3 = urllib.request.Request(f"https://www.kisssub.org/search.php?keyword={kw}",
                                     headers={"User-Agent": UA, "Referer": "https://www.kisssub.org/"})
        with op2.open(rq3, timeout=25) as r3:
            b3 = r3.read().decode("utf-8", "replace")
        print(" search:", r3.status, "len", len(b3), "has_list:", ("list" in b3), "title:", re.search(r"<title>(.*?)</title>", b3, re.S).group(1)[:80] if re.search(r"<title>(.*?)</title>", b3, re.S) else "?")
        open("_probe/out/kisssub_after.html", "w", encoding="utf-8").write(b3)
        i = b3.find("<table")
        print(b3[i:i+1800] if i > 0 else b3[:1200])
except Exception as e:
    print(" ERR", type(e).__name__, str(e)[:200])

print("\n=== D. dmhy team filter markup ===")
try:
    rq = urllib.request.Request("https://share.dmhy.org/topics/list?keyword=%E8%91%AC%E9%80%81%E7%9A%84%E8%8A%99%E8%8E%89%E8%8E%B2", headers={"User-Agent": UA})
    with urllib.request.urlopen(rq, timeout=25, context=CTX) as r:
        t = r.read().decode("utf-8", "replace")
    open("_probe/out/dmhy_search.html", "w", encoding="utf-8").write(t)
    m = re.findall(r'name="team_id\[\]"[^>]*value="(\d+)"[^>]*>\s*([^<]{0,40})', t)
    print(" team_id[] matches:", m[:10], "count", len(m))
    for pat in [r'team_id', r'class="team"', r'id="team"', r'<select[^>]*name="[^"]*"']:
        print("  ", pat, "->", len(re.findall(pat, t)))
    j = t.find("team_id")
    print(t[max(0, j-400):j+700] if j > 0 else "no team_id")
    # check .title spans for group
    print(" groups in results:", re.findall(r'<span class="keyword">|\[([^\]]{2,20})\]\s', t)[:12])
except Exception as e:
    print(" ERR", type(e).__name__, e)

print("\n=== E. qBittorrent WebUI 7004 API ===")
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/v2/app/version", timeout=6) as r:
        print(" version:", r.status, r.read().decode())
    with urllib.request.urlopen("http://127.0.0.1:8080/api/v2/app/preferences", timeout=6) as r:
        p = json.loads(r.read().decode())
        print(" save_path:", p.get("save_path"), "| proxy_type:", p.get("proxy_type"), "| listen_port:", p.get("listen_port"))
    with urllib.request.urlopen("http://127.0.0.1:8080/api/v2/torrents/categories", timeout=6) as r:
        print(" categories:", r.read().decode()[:200])
except Exception as e:
    print(" ERR", type(e).__name__, str(e)[:150])
