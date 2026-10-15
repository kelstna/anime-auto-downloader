"""缓存与预热端到端测试（真实 Bangumi，隔离数据目录）。

验证：
1. 首次拉取在看列表（慢）→ 第二次命中缓存（快）
2. token 变化时缓存自动失效（换一个假 token 不会命中上一份缓存）
3. 拉取后自动预热全部番剧资源，进度可查
4. 预热完成后 /api/search 命中缓存（秒回、cached=true）
5. 强制刷新 force=true 会重新联网
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="anime-cache-")
os.environ["ANIME_DATA_DIR"] = TMP
# 本机直连 api.bgm.tv 会超时，必须带上生产配置里的代理设置（否则这个探针整篇失败）
_PROD_CFG = os.path.join(ROOT, "data", "config.json")
if os.path.exists(_PROD_CFG):
    shutil.copyfile(_PROD_CFG, os.path.join(TMP, "config.json"))

from app.core import cache, config, logger, warmup   # noqa: E402
from app.web import server                            # noqa: E402

logger.set_console(False)
TOKEN = os.environ.get("BGM_TOKEN", "")
PORT = 7831
_cfg = config.load() or {}
_proxy_enabled = bool((_cfg.get("proxy") or {}).get("enabled"))
if not _proxy_enabled:
    print("[提示] 生产配置里没启用代理；本机直连 Bangumi 会超时，本探针可能整篇失败。")
config.update({
    "bangumi_token": TOKEN,
    "server": {"host": "127.0.0.1", "port": PORT},
    "subscription": {"enabled": False},
    "cache": {"auto_search_on_fetch": False},   # 手动控制预热时机，便于断言
})
assert config.DATA_DIR == TMP

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)


def call(method, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8")), time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8")), time.time() - t0
        except Exception:
            return e.code, {}, time.time() - t0
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}, time.time() - t0


print("=" * 74)
print("1. 命中缓存：第二次拉取应显著更快")
print("=" * 74)
code1, d1, t1 = call("GET", "/api/bangumi/collections?type=3&warm=0")
check("首次拉取成功", code1 == 200 and d1.get("ok"), d1.get("error", ""))
n1 = len(d1.get("items", []))
print(f"    首次：{t1:.1f}s，{n1} 部")
code2, d2, t2 = call("GET", "/api/bangumi/collections?type=3&warm=0")
n2 = len(d2.get("items", []))
print(f"    第二次：{t2:.1f}s，{n2} 部")
check("第二次数据一致", n1 == n2 and n1 > 0, f"{n1} vs {n2}")
check("第二次明显更快（走缓存）", t2 < max(1.0, t1 * 0.5), f"{t1:.1f}s -> {t2:.1f}s")
check("番剧项带缓存标记字段",
      all("resources_cached" in it for it in d2.get("items", [])[:3]),
      str({k: d2["items"][0].get(k) for k in ("resources_cached", "resources_cached_count")}))

print()
print("=" * 74)
print("2. token 变化会导致缓存失效（不会把别人的数据当自己的）")
print("=" * 74)
fp_same = cache.token_fingerprint(TOKEN) == cache.token_fingerprint(TOKEN)
fp_diff = cache.token_fingerprint(TOKEN) != cache.token_fingerprint(TOKEN + "x")
check("同 token 指纹一致", fp_same)
check("不同 token 指纹不同（缓存键随之变化）", fp_diff)

print()
print("=" * 74)
print("3. 自动预热：拉取后自动搜索全部番剧资源并缓存")
print("=" * 74)
config.update({"cache": {"auto_search_on_fetch": True}})
t0 = time.time()
code, d, dt = call("GET", "/api/bangumi/collections?type=3&force=1")
st = d.get("warmup") or {}
print(f"    拉取耗时 {dt:.1f}s；预热状态 running={st.get('running')} total={st.get('total')}")
check("拉取后自动启动预热", st.get("running") is True or st.get("total", 0) > 0, str(st)[:120])

# 等预热完成（每部约 5~10s，36 部 * 限速，给足时间）
deadline = time.time() + 900
last = None
while time.time() < deadline:
    code, cs, _ = call("GET", "/api/cache/status", timeout=60)
    if not cs.get("running"):
        break
    line = f"已缓存 {cs.get('done')}/{cs.get('total')}（命中 {cs.get('cached')}，失败 {cs.get('failed')}）当前：{cs.get('current','')[:22]}"
    if line != last:
        print("   ", line)
        last = line
    time.sleep(6)
cs = cs if isinstance(cs, dict) else {}
print(f"    最终：done={cs.get('done')} total={cs.get('total')} cached={cs.get('cached')} failed={cs.get('failed')}")
check("预热跑完且成功缓存了大部分番剧",
      (cs.get("total") or 0) > 0 and (cs.get("done") or 0) >= (cs.get("total") or 0) * 0.8,
      f"{cs.get('done')}/{cs.get('total')}")
check("缓存文件已落盘", (cs.get("cache") or {}).get("count", 0) > 0,
      f"{((cs.get('cache') or {}).get('count'))} 个文件，{((cs.get('cache') or {}).get('bytes'))} 字节")

print()
print("=" * 74)
print("4. 预热后打开番剧：/api/search 直接命中缓存（秒回）")
print("=" * 74)
# 从缓存文件里挑一部**确实有资源**的番剧来断言（有些番剧各站就是没资源，属正常）
best_sid, best_total = 0, 0
for it in d2.get("items", []):
    cached, _age = warmup.search_any_age(it["id"])
    total = (cached or {}).get("total", 0)
    if total > best_total:
        best_sid, best_total = it["id"], total
sid = best_sid or (d2["items"][0]["id"] if d2.get("items") else 0)
print(f"    选用有资源的番剧：subject_id={sid}（预热缓存 {best_total} 条）")
code, s1, st1 = call("POST", "/api/search", {"subject_id": sid})
if s1.get("cached") is not True:
    # 预热之后如果又学到了新的关键词，缓存键（…|lk=…）会变一次 → 这一发重新联网；
    # 再搜一次就是稳定命中缓存（学习结果本身也是「搜过一次之后才知道」的）。
    print(f"    预热后首次搜索未命中缓存（关键词学习变了缓存键），再搜一次")
    code, s1, st1 = call("POST", "/api/search", {"subject_id": sid})
print(f"    /api/search：{st1:.2f}s cached={s1.get('cached')} age={s1.get('cache_age')} 条数={s1.get('total')}")
check("命中缓存返回", s1.get("cached") is True, f"cached={s1.get('cached')}")
check("缓存响应很快（<2s）", st1 < 2.0, f"{st1:.2f}s")
# 接口会按「本季」过滤：返回条数 + 隐藏条数 应该正好等于**当前**缓存里的条数
# （缓存可能刚被这一轮重搜覆盖，所以要重新读一次，不能拿预热时的旧数字比）
_now_cached, _ = warmup.search_any_age(sid)
_now_total = int((_now_cached or {}).get("total") or 0)
_hidden = int(s1.get("hidden_other_season") or 0)
check("接口条数 + 本赛季隐藏条数 = 缓存条数",
      (s1.get("total") or 0) + _hidden == _now_total,
      f"{s1.get('total')} + {_hidden} vs 缓存 {_now_total}（预热时 {best_total}）")
check("缓存里确实有资源", (s1.get("total") or 0) > 0, f"{s1.get('total')} 条")
if s1.get("items"):
    it = s1["items"][0]
    check("缓存条目字段完整",
          {"source_name", "title", "group", "resolution", "size_text", "magnet", "episode"} <= set(it),
          str(sorted(it.keys())[:8]))
if best_total == 0:
    check("预热结果覆盖了全部番剧（含零资源的）",
          all(warmup.search_any_age(x["id"])[0] is not None for x in d2.get("items", [])),
          "有番剧完全没被预热")

code, s2, st2 = call("POST", "/api/search", {"subject_id": sid, "force": True})
print(f"    force=true：{st2:.1f}s cached={s2.get('cached')}")
check("force=true 会重新联网", s2.get("cached") is False, f"cached={s2.get('cached')} 用时 {st2:.1f}s")

print()
print("=" * 74)
print("4b. 带字幕组的搜索不能命中「全量」缓存（曾出过这个 bug）")
print("=" * 74)
gname = ""
if s1.get("groups"):
    gname = s1["groups"][0] if isinstance(s1["groups"][0], str) else s1["groups"][0].get("name", "")
print(f"    用字幕组 {gname!r} 搜索（subject_id={sid}）")
code, sg, stg = call("POST", "/api/search", {"subject_id": sid, "group": gname})
print(f"    返回 {sg.get('total')} 条，cached={sg.get('cached')}，search_group={sg.get('search_group')!r}")
check("带字幕组的搜索返回结果", code == 200 and (sg.get("total") or 0) > 0, f"{sg.get('total')} 条")
check("带字幕组的搜索没有命中全量缓存",
      sg.get("cached") is not True, f"cached={sg.get('cached')}")
check("返回条数少于全量（确实按组收敛）",
      (sg.get("total") or 0) < (s1.get("total") or 0), f"{sg.get('total')} < {s1.get('total')}")
from app.sources.engine import _group_match   # noqa: E402
bad = [r for r in (sg.get("items") or []) if not _group_match(r.get("group", ""), gname)]
check("返回的资源都属于该字幕组", not bad, f"越界 {len(bad)} 条：{[r.get('group') for r in bad[:3]]}")
code, sg2, stg2 = call("POST", "/api/search", {"subject_id": sid, "group": gname})
if sg2.get("cached") is not True:
    # 第一次用这个口径搜出来的结果会写进「关键词学习记录」，学习一旦有变化，缓存键就变了
    # （见 server.api_search 里的 `|lk=`）→ 这一发会重新联网；再搜一次才稳定命中缓存。
    print(f"    第一次带组搜索学到了新关键词（缓存键变化），再搜一次确认稳定")
    code, sg2, stg2 = call("POST", "/api/search", {"subject_id": sid, "group": gname})
check("第二次同口径搜索命中该口径自己的缓存",
      sg2.get("cached") is True and sg2.get("total") == sg.get("total"),
      f"cached={sg2.get('cached')} {sg2.get('total')} vs {sg.get('total')}")

print()
print("=" * 74)
print("6. 订阅保存站点限定的字幕组 sub_group（前端按站点分开选择）")
print("=" * 74)
grp = json.loads("{}")
code, gr, _ = call("POST", "/api/groups", {"subject_id": sid})
groups = gr.get("groups") or []
site_groups = [g for g in groups if g.get("value") and g.get("source")]
print(f"    /api/groups 返回 {len(groups)} 条，其中带站点标识（value 含 ::）的 {len(site_groups)} 条")
check("字幕组按站点分开返回（有 source 与唯一 value）",
      bool(site_groups) and all("::" in g["value"] for g in site_groups),
      f"示例 {site_groups[0]['value'] if site_groups else '-'}")
# 同名组在不同站点应是两条（若这部番存在这种组）
names = {}
for g in site_groups:
    names.setdefault(g["name"], set()).add(g["source"])
dupe = {k: sorted(v) for k, v in names.items() if len(v) > 1}
print(f"    跨站重名组（已分开）：{dupe if dupe else '本番剧无重名组'}")

if site_groups:
    sg = site_groups[0]
    code, sub_res, _ = call("POST", "/api/subscriptions", {
        "subject_id": sid,
        "group": sg["name"],
        "sub_group": sg["value"],
        "resolution": "1080p",
        "initial_mode": "none",
        "total_episodes": 12,
        "folder": os.path.join(TMP, "sub_group_test"),
    })
    saved = (sub_res.get("subscription") or {})
    print(f"    提交 sub_group={sg['value']!r} -> 订阅里存的是 {saved.get('sub_group')!r}"
          f"（group={saved.get('group')!r}）")
    check("订阅保存了 sub_group", saved.get("sub_group") == sg["value"], str(saved.get("sub_group")))
    check("订阅同时保留组名 group", saved.get("group") == sg["name"], str(saved.get("group")))

    code, lst, _ = call("GET", "/api/subscriptions")
    items = lst.get("items") or []
    one = next((x for x in items if x.get("subject_id") == sid), None)
    check("订阅列表里能读到 sub_group", bool(one) and one.get("sub_group") == sg["value"],
          str((one or {}).get("sub_group")))
    # 清理
    call("DELETE", f"/api/subscriptions/{sid}")
    code, after, _ = call("GET", "/api/subscriptions")
    check("测试订阅已清理", all(x.get("subject_id") != sid for x in (after.get("items") or [])))

print()
print("=" * 74)
print("5. 缓存管理接口")
print("=" * 74)
code, cs2, _ = call("GET", "/api/cache/status")
check("缓存状态可查", code == 200 and "cache" in cs2, f"{cs2.get('cache', {}).get('count')} 个文件")
code, cl, _ = call("POST", "/api/cache/clear", {"prefix": "search:"})
print(f"    清理 search: 前缀 -> 删除 {cl.get('removed')} 个文件")
check("可按前缀清理缓存", code == 200 and (cl.get("removed") or 0) > 0, str(cl))

httpd.shutdown()
shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 74)
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
print("=" * 74)
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
