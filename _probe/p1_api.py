"""Probe bangumi API + qBittorrent + resource sites."""
import os
import httpx, json, sys, re

TOKEN = os.environ.get("BGM_TOKEN", "")
UA = {"User-Agent": "DSH-AnimeAutoDownloader/0.1 (https://github.com/local)"}
H = {**UA, "Authorization": f"Bearer {TOKEN}"}

def show(tag, r):
    print(f"--- {tag}: {r.status_code} len={len(r.content)}")
    return r

# 1) whoami with token
for base in ["https://api.bgm.tv", "https://next.bgm.tv"]:
    for path in ["/v0/me"]:
        try:
            r = httpx.get(base + path, headers=H, timeout=20, follow_redirects=True)
            show(f"GET {base}{path}", r)
            print(r.text[:500])
        except Exception as e:
            print(f"GET {base}{path} ERR {type(e).__name__} {e}")

# 2) collection type=3 (在看)
try:
    r = httpx.get("https://api.bgm.tv/v0/users/-/collections", params={"subject_type": 2, "type": 3, "limit": 5, "offset": 0}, headers=H, timeout=20)
    show("collections -", r)
    print(json.dumps(r.json(), ensure_ascii=False)[:1500])
except Exception as e:
    print("collections - ERR", type(e).__name__, e)

# 3) subject detail with infobox
try:
    r = httpx.get("https://api.bgm.tv/v0/subjects/253", headers=UA, timeout=20)
    show("subject 253", r)
    d = r.json()
    print(json.dumps({k: d.get(k) for k in ["id", "name", "name_cn", "infobox"]}, ensure_ascii=False)[:2500])
except Exception as e:
    print("subject ERR", type(e).__name__, e)

# 4) qBittorrent webui
for port in (8080, 8081, 8082, 8085, 9090):
    for scheme in ("http", "https"):
        try:
            r = httpx.get(f"{scheme}://127.0.0.1:{port}/api/v2/app/version", timeout=3, verify=False)
            print(f"QB {scheme}:{port} -> {r.status_code} {r.text[:40]}")
        except Exception as e:
            print(f"QB {scheme}:{port} -> ERR {type(e).__name__} {str(e)[:60]}")
