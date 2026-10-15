"""Final probe: dmhy team filter, nyaa categories, bangumi episodes, qB API specifics."""
import os
import urllib.request, urllib.parse, ssl, re, json

CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TOKEN = os.environ.get("BGM_TOKEN", "")

def get(u, hdr=None):
    h = {"User-Agent": UA}
    if hdr: h.update(hdr)
    with urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=25, context=CTX) as r:
        return r.read().decode("utf-8", "replace")

print("=" * 70)
print("D1. dmhy team filter: keyword + team_id:NNN")
kw = urllib.parse.quote("葬送的芙莉莲")
for tid in ["865", "856", "867"]:
    try:
        t = get(f"https://share.dmhy.org/topics/list?keyword={kw}+team_id%3A{tid}")
        n = t.count('<td class="title">')
        rows = re.findall(r'<td class="title">\s*(?:.*?)<a href="([^"]+)"[^>]*>\s*(.*?)</a>', t, re.S)
        names = [re.sub(r"<[^>]+>", "", b).strip()[:70] for a, b in rows[:3]]
        print(f"  team_id:{tid} -> rows={n} {names}")
    except Exception as e:
        print(f"  team_id:{tid} ERR {e}")

print("\nD2. dmhy: extract team link per row (regex candidate)")
t = open("_probe/out/dmhy_search.html", encoding="utf-8").read()
rows = t.split('<tr class="')
print("  split rows:", len(rows))
r1 = rows[1]
print("  team links in row1:", re.findall(r'/topics/list/team_id/(\d+)"[^>]*>([^<]{1,40})', r1))
print("  all row1 tds:", [re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", x)).strip()[:60] for x in re.findall(r"<td[^>]*>(.*?)</td>", r1, re.S)])

print("\n" + "=" * 70)
print("N1. nyaa category option markup")
n = get("https://nyaa.si/")
i = n.find('name="c"')
print("  ", re.sub(r"\s+", " ", n[i-100:i+2500])[:2200] if i > 0 else "no name=c")

print("\n" + "=" * 70)
print("B1. bangumi subject infobox names (aliases) for 3 subjects")
for sid in [253, 400602, 624923]:
    try:
        d = json.loads(get(f"https://api.bgm.tv/v0/subjects/{sid}"))
        print(f"  --- {sid}: name={d.get('name')!r} name_cn={d.get('name_cn')!r} eps={d.get('eps')} total={d.get('total_episodes')} date={d.get('date')}")
        for ib in d.get("infobox", []):
            if ib.get("key") in ("别名", "中文名", "英文名", "话数", "放送开始", "官方网站"):
                v = ib.get("value")
                if isinstance(v, list):
                    v = [(x.get("v") if isinstance(x, dict) else x) for x in v]
                print(f"      {ib.get('key')}: {v}")
    except Exception as e:
        print(f"  {sid} ERR {e}")

print("\nB2. bangumi episodes endpoint")
try:
    e = json.loads(get("https://api.bgm.tv/v0/episodes?subject_id=253&type=0&limit=3&offset=0"))
    print("  total:", e.get("total"), "| first:", json.dumps(e["data"][0], ensure_ascii=False)[:400] if e.get("data") else None)
except Exception as e:
    print("  ERR", e)

print("\n" + "=" * 70)
print("Q1. qBittorrent API details")
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/v2/torrents/info?limit=3", timeout=8) as r:
        ts = json.loads(r.read().decode())
    print("  torrent count(sample):", len(ts))
    if ts:
        t0 = ts[0]
        print("  keys:", sorted(t0.keys())[:40])
        print("  sample:", json.dumps({k: t0.get(k) for k in ["name", "hash", "save_path", "content_path", "category", "state", "progress"]}, ensure_ascii=False))
except Exception as e:
    print("  ERR", type(e).__name__, e)

print("\nQ2. qBittorrent app/buildInfo + api version detection")
for ep in ["/api/v2/app/buildInfo", "/api/v2/app/webapiVersion"]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080" + ep, timeout=8) as r:
            print("  ", ep, "->", r.read().decode()[:200])
    except Exception as e:
        print("  ", ep, "ERR", e)

print("\nQ3. check add params support (dry: only GET app/defaultSavePath)")
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/v2/app/defaultSavePath", timeout=8) as r:
        print("  defaultSavePath:", r.read().decode())
except Exception as e:
    print("  ERR", e)
