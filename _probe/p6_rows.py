"""Probe 6: exact row extraction for dmhy + kisssub."""
import re

print("=" * 70)
print("DMHY rows: full column dump")
t = open("_probe/out/dmhy_search.html", encoding="utf-8").read()
rows = t.split('<tr class="')
print("rows:", len(rows))
for r in rows[1:4]:
    tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
    print(f"--- {len(tds)} tds")
    for i, td in enumerate(tds):
        txt = re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", td)).strip()
        print(f"   [{i}] {txt[:95]}")
    print("   hrefs:", re.findall(r'href="(/topics/[^"]+)"', r)[:3])
    m = re.search(r'href="(magnet:[^"]{0,50})', r)
    print("   magnet:", m.group(1) if m else "NONE")
    print("   all links:", re.findall(r'<a[^>]*class="([^"]*)"', r))

print("\n   -- where do /topics/list/team_id/N links live? --")
for m in re.finditer(r"/topics/list/team_id/(\d+)", t):
    s = max(0, m.start() - 260)
    seg = t[s:m.end() + 120]
    if "td" in seg:
        print("   ...", re.sub(r"\s+", " ", seg)[-300:])
        break
# count occurrences per row index
idx = [t[:m.start()].count('<tr class="') for m in re.finditer(r"/topics/list/team_id/\d+", t)]
print("   team-link row indices:", idx[:20])

print("\n" + "=" * 70)
print("KISSSUB: result rows")
k = open("_probe/out/kisssub_after.html", encoding="utf-8").read()
trs = re.findall(r"<tr[^>]*>(.*?)</tr>", k, re.S)
print("total trs:", len(trs))
for n, tr in enumerate(trs):
    if "magnet" in tr or "hash" in tr:
        print(f"--- tr#{n} (len {len(tr)}) ---")
        print(re.sub(r"\s+", " ", tr)[:1800])
        print()
        if n > 30:
            break
