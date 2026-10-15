"""「番剧到底几点更新（北京时间）」的数据源调研 + 现场实测。

候选来源（都在本机用代理实测）：
  ① Bangumi /v0/subjects/{id}          → 放送开始（只有日期）、infobox 里的「放送星期 / 播放电视台」
  ② Bangumi /v0/episodes               → 每集 airdate（只有日期，没有时刻）
  ③ bangumi-data（bangumi-data/bangumi-data 的 items.json）
                                       → begin（精确到分钟的 ISO 时间 +09:00）+ broadcast（「每周日 24:30」）+ 各站 ID 映射
  ④ AniList GraphQL airingSchedule     → 每集 airingAt（Unix 时间戳，精确到秒）
  ⑤ Jikan（MyAnimeList）               → anime.broadcast{day,time,timezone}、episodes[].aired（带时区）

输出：几部真实番剧的「下一次更新」在**北京时间**是几月几号几点几分，以及各来源是否一致。

用法：python _probe/t_airtime.py [subject_id ...]      # 不带参数就用你的订阅
"""
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.core import config, subs  # noqa: E402

PROXY = config.get("proxy.url", "http://127.0.0.1:7890") if config.get("proxy.enabled", True) else None
TOKEN = config.bangumi_token()
CST = timezone(timedelta(hours=8))        # 北京时间
JST = timezone(timedelta(hours=9))        # 日本时间
# bangumi-data（社区维护的番剧数据，含精确到分钟的放送时刻 + 各站 ID 映射）
# npm 包 dist/data.json 直接给整份数据，走 jsDelivr CDN；0.3.230 的 schema：begin/broadcast(RRULE)/sites
BANGUMI_DATA = os.environ.get("BANGUMI_DATA_URL") or \
    "https://cdn.jsdelivr.net/npm/bangumi-data@0.3.230/dist/data.json"
_opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": PROXY, "https": PROXY} if PROXY else {}))
_opener.addheaders = [("User-Agent", "DSH-AnimeAutoDownloader/1.0 (local)")]


def fetch(url, *, data=None, headers=None, timeout=45, tries=4):
    """带重试的请求（代理偶尔会「Remote end closed connection」，见本次实测）。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with _opener.open(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:             # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def load_bangumi_data():
    """
    bangumi-data：7~8MB 整份数据，下载一次本地缓存（默认 3 天内不重复下载）。
    数据源：npm 包 dist/data.json（jsDelivr CDN）。
    """
    cache_dir = os.path.join(ROOT, "_probe", ".cache")
    cache_path = os.path.join(cache_dir, "bangumi-data.json")
    fresh = (os.path.exists(cache_path)
             and time.time() - os.path.getmtime(cache_path) < 3 * 86400)
    if fresh:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"   用本地缓存 {cache_path}（{os.path.getsize(cache_path) / 1048576:.1f} MB，"
              f"{int((time.time() - os.path.getmtime(cache_path)) / 3600)} 小时前下载）")
        return data.get("items") or []
    raw = None
    last = None
    for i in range(4):
        try:
            raw = _opener.open(BANGUMI_DATA, timeout=180).read()
            break
        except Exception as e:             # noqa: BLE001
            last = e
            print(f"   第 {i + 1} 次下载失败：{e}")
            time.sleep(2.0 * (i + 1))
    if raw is None:
        if os.path.exists(cache_path):     # 下载失败但有旧缓存 → 用旧的
            print(f"   下载失败（{last}），退回旧缓存")
            with open(cache_path, "r", encoding="utf-8") as f:
                return (json.load(f).get("items") or [])
        raise last
    data = json.loads(raw.decode("utf-8"))
    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(raw)
    except OSError:
        pass
    print(f"   下载成功并缓存到 {cache_path}（{len(raw) / 1048576:.1f} MB）")
    return data.get("items") or []


def bgm(path):
    h = {"Accept": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return fetch("https://api.bgm.tv" + path, headers=h)


def cst(ts):
    return datetime.fromtimestamp(ts, CST) if isinstance(ts, (int, float)) else ts


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if isinstance(dt, datetime) else "-"


def weekday_cn(dt):
    return "周" + "一二三四五六日"[dt.weekday()]


def parse_iso(s):
    if not s:
        return None
    s = str(s).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_rrule(rrule: str):
    """
    bangumi-data 的 broadcast 是 RFC5545 重复区间：`R/2026-10-04T16:20:00.000Z/P7D`
    → 返回 (首次时刻, 周期 timedelta)；解析不出来就 (None, 7 天)。
    """
    parts = str(rrule or "").split("/")
    start = parse_iso(parts[1]) if len(parts) > 1 else None
    period = timedelta(days=7)
    if len(parts) > 2:
        m = re.match(r"^P(\d+)([DWM])$", parts[2].strip())
        if m:
            n = int(m.group(1))
            period = {"D": timedelta(days=n), "W": timedelta(weeks=n), "M": timedelta(days=30 * n)}[m.group(2)]
    return start, period


def next_airing(begin: datetime, period: timedelta, now: datetime):
    """按周期往后推到「下一次」放送时刻。"""
    if not begin or not period or period.total_seconds() <= 0:
        return None
    if begin > now:
        return begin
    steps = int((now - begin) / period) + 1
    return begin + period * steps


print("=" * 100)
print(f"数据源实测（代理：{PROXY or '直连'}）")
print("=" * 100)

# ---------- 选几部番：优先用户的订阅（正在追的），没有就取在看前三 ----------
ids = [int(x) for x in sys.argv[1:] if x.isdigit()]
if not ids:
    ids = [int(s.subject_id) for s in subs.all_subs()][:6]
if not ids:
    col = bgm("/v0/users/-/collections?limit=3") if TOKEN else {"data": []}
    ids = [int(x["subject_id"]) for x in (col.get("data") or [])][:3]
print(f"参与实测的 subject_id：{ids}\n")

# ---------- ③ bangumi-data：一次拉全量，按 bangumi id 建索引 ----------
print("① 拉 bangumi-data（含 begin 精确时刻 + broadcast 周期 + 各站 ID 映射）…")
t0 = time.time()
try:
    items = load_bangumi_data()
    print(f"   OK：{len(items)} 条，用时 {time.time() - t0:.1f}s\n   URL：{BANGUMI_DATA}")
except Exception as e:                     # noqa: BLE001
    items = []
    print(f"   失败：{e}")
by_bgm = {}
for it in items:
    for site in (it.get("sites") or []):
        if site.get("site") == "bangumi":
            try:
                by_bgm[int(site.get("id"))] = it
            except (TypeError, ValueError):
                pass
print(f"   命中索引：{len(by_bgm)} 条（按 bangumi id）\n")

NOW = datetime.now(timezone.utc)
rows = []
for sid in ids:
    print("=" * 100)
    row = {"id": sid, "title": "", "search_title": "", "date": "", "weekday": "", "bd_begin": "",
           "bd_next_cst": "", "bd_broadcast": "", "bd_period": "", "anilist_next": "",
           "jikan_broadcast": "", "ep_next": "", "sites": {}}
    # ① Bangumi 基础
    try:
        sub = bgm(f"/v0/subjects/{sid}")
        row["title"] = sub.get("name_cn") or sub.get("name") or str(sid)
        row["search_title"] = sub.get("name_cn") or sub.get("name") or ""
        row["date"] = sub.get("date") or ""
        box = {}
        for entry in (sub.get("infobox") or []):
            box[entry.get("key")] = entry.get("value")
        row["weekday"] = str(box.get("放送星期") or box.get("播放星期") or "")
        print(f"[{sid}] {row['title']}")
        print(f"   Bangumi    首播日期={row['date'] or '?'}  放送星期={row['weekday'] or '?'}"
              f"  电视台={box.get('播放电视台') or '-'}  话数={sub.get('total_episodes') or '-'}"
              f"   ⚠️ 只有日期/星期，没有几点几分")
    except Exception as e:                 # noqa: BLE001
        print(f"[{sid}] Bangumi 查询失败：{e}")
    # ② Bangumi 剧集（只有日期）
    try:
        eps = bgm(f"/v0/episodes?subject_id={sid}&limit=100")
        dated = [(e.get("sort"), e.get("airdate")) for e in (eps.get("data") or []) if e.get("airdate")]
        row["ep_next"] = str(dated[-1]) if dated else ""
        print(f"   /episodes  {len(dated)} 集有日期（只有 YYYY-MM-DD，没有时刻）"
              f"{'，最后一集 ' + str(dated[-1]) if dated else ''}")
    except Exception as e:                 # noqa: BLE001
        print(f"   /episodes 查询失败：{e}")
    # ③ bangumi-data：精确时刻 + 周期
    it = by_bgm.get(sid)
    if it:
        begin = parse_iso(it.get("begin"))
        period = parse_rrule(it.get("broadcast"))[1]
        nxt = next_airing(begin, period, NOW)
        row["bd_begin"] = fmt(begin.astimezone(CST)) if begin else ""
        row["bd_next_cst"] = f"{fmt(nxt.astimezone(CST))} {weekday_cn(nxt.astimezone(CST))}" if nxt else ""
        row["bd_broadcast"] = str(it.get("broadcast") or "")
        row["bd_period"] = f"每 {int(period.total_seconds() // 86400)} 天" if period else ""
        row["sites"] = {s.get("site"): s.get("id") for s in (it.get("sites") or [])}
        print(f"   bangumi-data  begin={it.get('begin')} → 北京时间首播 {row['bd_begin']}"
              f"   broadcast={row['bd_broadcast']!r}（{row['bd_period']}）")
        if nxt:
            print(f"                 ▶ 下一次更新（北京时间）：{row['bd_next_cst']}")
    else:
        print("   bangumi-data  没有这一条（新番收录可能滞后）")
    # ④ AniList：每集 airingAt（Unix 时间戳，精确到秒）
    al_id = (row.get("sites") or {}).get("aniList")
    try:
        if al_id:
            q = {"query": "query($id:Int){Media(id:$id){title{native} status episodes "
                          "nextAiringEpisode{episode airingAt} "
                          "airingSchedule(notYetAired:true){nodes{episode airingAt}}}}",
                 "variables": {"id": int(al_id)}}
        else:
            # bangumi-data 里没给 aniList id 时用标题搜（优先中文名，再日文名）
            q = {"query": "query($s:String){Media(search:$s,type:ANIME){title{native} status episodes "
                          "nextAiringEpisode{episode airingAt} "
                          "airingSchedule(notYetAired:true){nodes{episode airingAt}}}}",
                 "variables": {"s": row["search_title"] or row["title"]}}
        res = fetch("https://graphql.anilist.co", data=json.dumps(q).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Accept": "application/json"})
        media = ((res or {}).get("data") or {}).get("Media") or {}
        if media:
            print(f"   AniList      匹配到《{((media.get('title') or {}).get('native') or '?')}》"
                  f"（{'按记录 ID' if al_id else '按标题搜索'}）")
        nxt = media.get("nextAiringEpisode") or {}
        if nxt.get("airingAt"):
            dt = cst(int(nxt["airingAt"]))
            row["anilist_next"] = f"第 {nxt.get('episode')} 集 {fmt(dt)} {weekday_cn(dt)}"
            print(f"                 nextAiringEpisode=第 {nxt.get('episode')} 集 → 北京时间 {fmt(dt)} {weekday_cn(dt)}")
        nodes = [n for n in ((media.get("airingSchedule") or {}).get("nodes") or []) if n.get("airingAt")][:3]
        if nodes:
            print("                 之后几集：" + "，".join(
                f"第 {n.get('episode')} 集 {fmt(cst(int(n['airingAt'])))}" for n in nodes))
    except Exception as e:                 # noqa: BLE001
        print(f"   AniList 查询失败：{e}")
    # ⑤ Jikan（MyAnimeList）：broadcast 字段 + 每集 aired（带时区）
    mal_id = (row.get("sites") or {}).get("mal")
    if mal_id:
        try:
            j = (fetch(f"https://api.jikan.moe/v4/anime/{int(mal_id)}/full") or {}).get("data") or {}
            bc = j.get("broadcast") or {}
            row["jikan_broadcast"] = str(bc.get("string") or "")
            if bc:
                print(f"   Jikan        broadcast={row['jikan_broadcast']!r}"
                      f"（{bc.get('day')} {bc.get('time')} {bc.get('timezone')}）")
            eps = fetch(f"https://api.jikan.moe/v4/anime/{int(mal_id)}/episodes") or {}
            dated = [e for e in (eps.get("data") or []) if e.get("aired")]
            if dated:
                dt = parse_iso(dated[-1]["aired"])
                print(f"                最新一集 aired={dated[-1]['aired']}"
                      f" → 北京时间 {fmt(dt.astimezone(CST))}（原始时区 {dt.tzinfo}）")
            time.sleep(0.6)                # Jikan 限流：每秒 3 次以内
        except Exception as e:             # noqa: BLE001
            print(f"   Jikan 查询失败：{e}")
    rows.append(row)

print()
print("=" * 100)
print("汇总：下一次更新（北京时间，精确到分钟）")
print("=" * 100)
print(f"{'番剧':<24}{'来源①bangumi-data':<24}{'周期':<8}{'来源②AniList':<24}{'来源③Jikan 每周'}")
for r in rows:
    print(f"{(r['title'] or str(r['id']))[:22]:<24}{r['bd_next_cst'] or '-':<24}{r['bd_period'] or '-':<8}"
          f"{r['anilist_next'] or '-':<24}{r['jikan_broadcast'] or '-'}")

out = os.path.join(ROOT, "_probe", "airtime_report.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump({"generated": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"), "rows": rows}, f,
              ensure_ascii=False, indent=2)
print(f"\n明细已写入 {out}")

# 结论性断言：至少要有来源给出「时刻」（不是只有日期）
with_time = [r for r in rows if r["bd_begin"] or r["anilist_next"] or r["jikan_broadcast"]]
print(f"\n有精确时刻的来源覆盖：{len(with_time)}/{len(rows)} 部")
sys.exit(0 if with_time else 1)
