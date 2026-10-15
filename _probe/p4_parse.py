"""Probe round 4: dmhy team info, kisssub result rows, nyaa full cols."""
import urllib.request, urllib.parse, ssl, re, json

CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def get(u, ref=None):
    h = {"User-Agent": UA}
    if ref: h["Referer"] = ref
    with urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=25, context=CTX) as r:
        return r.read().decode("utf-8", "replace")

def save(n, t):
    open(f"_probe/out/{n}.html", "w", encoding="utf-8").write(t)

print("=" * 60)
print("D1. dmhy: team_id context (filter syntax check)")
t = get("https://share.dmhy.org/topics/list?keyword=" + urllib.parse.quote("葬送的芙莉莲"))
save("dmhy_search", t)
# Search for the search-box sidebar / team links inside results
for pat in [r'team_id%3A\d+', r'team_id:\d+', r'/topics/list/team_id/\d+', r'class="[^"]*team[^"]*"']:
    f = re.findall(pat, t)
    print(f"  {pat} -> {len(f)} {f[:5]}")

print("\n  -- first result row raw --")
i = t.find('<tbody>', t.find('id="topic_list"'))
j = t.find('</tr>', i)
print(t[i:j+6][:2200])

print("\nD2. dmhy search with team_id: filter")
t2 = get("https://share.dmhy.org/topics/list?keyword=" + urllib.parse.quote("葬送的芙莉莲") + "+team_id%3A407")
save("dmhy_teamfilter", t2)
rows = t2.count('<tr class=')
print("  rows:", rows, "| len", len(t2))
tt = re.findall(r'<td class="title">\s*.*?<a href="([^"]+)"[^>]*>\s*(.*?)</a>', t2, re.S)
print("  titles:", [(a[:30], re.sub(r"<[^>]+>", "", b).strip()[:60]) for a, b in tt[:5]])

print("\n" + "=" * 60)
print("K1. kisssub search result rows")
k = open("_probe/out/kisssub_after.html", encoding="utf-8").read()
i = k.find('<table class="list_style')
seg = k[i:i+4000]
# find second tr (first data row after language filter)
trs = re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S)
print("  trs:", len(trs))
for n, tr in enumerate(trs[1:4], 1):
    print(f"  --- row {n} ---")
    print("  ", re.sub(r"\s+", " ", tr)[:1400])
print("\n  kisssub: look for magnet / group markers")
for pat in [r'magnet:\?xt=urn:btih:[a-fA-F0-9]{40}', r'class="[^"]*team[^"]*"', r'rss\.php', r'target="_blank"[^>]*>([^<]{2,30})</a>']:
    f = re.findall(pat, k)
    print(f"  {pat[:40]} -> {len(f)} {f[:6]}")

print("\n" + "=" * 60)
print("N1. nyaa full row (all tds)")
n1 = get("https://nyaa.si/?q=" + urllib.parse.quote("Sousou no Frieren") + "&c=1_2&f=0&s=seeders&o=desc")
save("nyaa_search", n1)
i = n1.find("<tbody>")
trs = re.findall(r"<tr[^>]*>(.*?)</tr>", n1[i:], re.S)
print("  rows:", len(trs))
for tr in trs[:2]:
    tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
    print("  tds:", len(tds))
    for x, td in enumerate(tds):
        print(f"    [{x}]", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", td)).strip()[:120])
    print("    magnet:", (re.search(r'href="(magnet:[^"]+)"', tr) or ["", ""])[1][:80])

print("\nN2. nyaa categories available")
n2 = get("https://nyaa.si/")
cats = re.findall(r'<option value="(1_\d+|1_\d+)"[^>]*>([^<]+)</option>', n2)
print("  ", cats[:12])

print("\nN3. nyaa sort/filter params on 1_2 (eng) vs 1_0 (all anime)")
for c in ["1_0", "1_2"]:
    n3 = get(f"https://nyaa.si/?q={urllib.parse.quote('Frieren 1080p')}&c={c}&f=0")
    print(f"  c={c} rows={len(re.findall(r'<tr[^>]*>', n3[n3.find('<tbody>'):]))}")
