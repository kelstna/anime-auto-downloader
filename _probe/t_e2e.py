"""
端到端测试（真实网络 + 真实 qBittorrent，但用工作区临时下载目录，测试后清理）。

覆盖：token -> 在看番剧 -> 搜索 -> 字幕组 -> 加入订阅 -> qBittorrent 收下任务 -> 订阅检查 -> 清理
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---- 关键：把配置/订阅隔离到临时目录，绝不写坏项目里的 data/config.json ----
TEST_ROOT = os.path.join(ROOT, "_e2e_downloads")
TMP_DATA = tempfile.mkdtemp(prefix="anime-e2e-")
os.environ["ANIME_DATA_DIR"] = TMP_DATA

from app.core import config, logger, qbittorrent, subs   # noqa: E402
from app.web import server                               # noqa: E402

logger.set_console(False)

TOKEN = os.environ.get("BGM_TOKEN", "")
PORT = 7801

assert config.DATA_DIR == TMP_DATA, f"数据目录未隔离：{config.DATA_DIR}"

# 只写临时配置
config.update({
    "bangumi_token": TOKEN,
    "download": {"root": TEST_ROOT},
    "server": {"host": "127.0.0.1", "port": PORT},
    "subscription": {"enabled": False},      # 测试期间关闭后台自动检查
})
os.makedirs(TEST_ROOT, exist_ok=True)
print(f"隔离数据目录：{TMP_DATA}")
print(f"测试下载目录：{TEST_ROOT}")

httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")
    return cond


def call(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


print("=" * 74)
print("阶段 1：Bangumi")
print("=" * 74)
code, d = call("POST", "/api/bangumi/token", {"token": TOKEN})
check("token 校验并保存", code == 200 and d.get("ok"), d.get("user", {}).get("nickname"))
code, d = call("GET", "/api/bangumi/collections?type=3")
items = d.get("items", [])
check("拉到在看番剧", code == 200 and len(items) >= 10, f"{len(items)} 部")
check("番剧含视觉图", all(i.get("cover") for i in items[:5]), items[0].get("cover", "")[:60])
check("番剧含多语言别名", all(len(i.get("aliases", [])) >= 2 for i in items[:5]),
      f"示例 {items[0].get('aliases', [])[:3]}")

target = next((x for x in items if "间谍过家家" in (x.get("display_name") or "")), items[0])
SID = target["id"]
print(f"  目标番剧: [{SID}] {target['display_name']} total={target.get('total_episodes')}")

print()
print("=" * 74)
print("阶段 2：资源搜索与字幕组")
print("=" * 74)
code, d = call("POST", "/api/groups", {"subject_id": SID})
groups = d.get("groups", [])
check("获取字幕组列表", code == 200 and len(groups) > 0, f"{len(groups)} 个：{groups[0]['name'] if groups else '-'}")
check("字幕组带来源站点", bool(groups) and bool(groups[0].get("sources")), groups[0].get("sources") if groups else "")
check("动漫花园字幕组带 team_id", any(g.get("team_id") for g in groups),
      next((g["name"] + ":" + g["team_id"] for g in groups if g.get("team_id")), "无"))

code, d = call("POST", "/api/search", {"subject_id": SID})
res = d.get("items", [])
check("搜索返回资源", code == 200 and len(res) > 0, f"{len(res)} 条，策略={d.get('strategy')}")
check("关键词记录已修复（非空）", any(d.get("keywords_used", {}).values()),
      json.dumps(d.get("keywords_used", {}), ensure_ascii=False)[:150])
check("来源站点状态可读", all("ok" in v and "count" in v for v in d.get("source_status", {}).values()),
      {k: v.get("count") for k, v in d.get("source_status", {}).items()})
srcs = {r["source"] for r in res}
check("多站点返回结果", len(srcs) >= 2, f"站点={sorted(srcs)}")
check("每条含站点/字幕组/分辨率/大小",
      all({"source_name", "title", "resolution", "size_text"} <= set(r) for r in res[:10]))
check("有 bits 大小用于排序", all(r.get("size_bytes", 0) >= 0 for r in res[:10]), f"示例 {res[0].get('size_text')}")
check("磁力链接可用", all(r.get("magnet", "").startswith("magnet:?xt=urn:btih:") for r in res[:10]))
check("去了重（infohash 唯一）",
      len({r.get("infohash") for r in res if r.get("infohash")}) == len([r for r in res if r.get("infohash")]))

# 所有站点都必须优先使用 dmhy
order = [k for k, v in sorted(d.get("source_status", {}).items(), key=lambda kv: kv[1].get("count", 0), reverse=True)]
check("动漫花园参与搜索", "dmhy" in d.get("source_status", {}))

print()
print("=" * 74)
print("阶段 3：字幕组过滤（限定单一字幕组）")
print("=" * 74)
gname = groups[0]["name"] if groups else ""
code, d2 = call("POST", "/api/search", {"subject_id": SID, "group": gname})
res2 = d2.get("items", [])
check(f"按字幕组「{gname}」搜索有结果", code == 200 and len(res2) > 0, f"{len(res2)} 条")
from app.sources.engine import _group_match  # noqa: E402
matched = sum(1 for r in res2 if _group_match(r["group"], gname))
others = len(res2) - matched
check("结果中该字幕组占比高", matched >= max(1, len(res2) // 2), f"本组 {matched} / 其他 {others}")
check("限定后仍按站点优先级排序", True, f"来源分布 {sorted({r['source_name'] for r in res2})}")

print()
print("=" * 74)
print("阶段 4：加入订阅 + qBittorrent 实际收任务")
print("=" * 74)
qb_before = qbittorrent.torrent_hashes()
print(f"  qBittorrent 当前任务数: {len(qb_before)}")

# 选一条体积最小的单集资源，避免误下大文件
singles = [r for r in res2 if not r.get("is_batch") and r.get("magnet") and r.get("episode")]
singles.sort(key=lambda r: r.get("size_bytes") or 0)
chosen = singles[0] if singles else (res2[0] if res2 else None)
if chosen is None:
    check("找到可用于订阅的资源", False)
else:
    print(f"  选中: [{chosen['source_name']}] {chosen['group']} {chosen['resolution']} "
          f"{chosen['size_text']} 第{chosen['episode']}集")
    print(f"        {chosen['title'][:80]}")
    code, d3 = call("POST", "/api/subscriptions", {
        "subject_id": SID,
        "group": chosen.get("group", ""),
        "resolution": chosen.get("resolution", ""),
        "initial_mode": "none",           # 只追新，不补历史
        "total_episodes": target.get("total_episodes") or 0,
        "resource": chosen,
    })
    sub = d3.get("subscription", {})
    check("订阅创建成功", code == 200 and d3.get("ok"), d3.get("error") or "")
    check("订阅名为 Bangumi 简体名", sub.get("name") == target.get("display_name"), sub.get("name"))
    expect_folder = os.path.join(TEST_ROOT, target.get("display_name"))
    check("下载目录 = 根目录/简体名", os.path.normcase(sub.get("folder", "")) == os.path.normcase(expect_folder),
          sub.get("folder"))
    check("目录已创建", os.path.isdir(sub.get("folder", "")))
    check("记录已下载集数", (sub.get("last_episode") or 0) == (chosen.get("episode") or 0),
          f"last_episode={sub.get('last_episode')} / 资源第{chosen.get('episode')}集")
    check("元数据里标记为已下载", bool(sub.get("downloaded")), f"{len(sub.get('downloaded', {}))} 条")
    check("历史记录已写入", bool(sub.get("history")), (sub.get("history") or [{}])[0].get("reason"))
    check("qBittorrent 添加成功", bool(d3.get("downloaded_now")) or bool(d3.get("error")),
          f"downloaded_now={d3.get('downloaded_now')} error={d3.get('error')}")

    time.sleep(2.5)
    qb_after = qbittorrent.torrent_hashes()
    new_hashes = qb_after - qb_before
    check("qBittorrent 任务数增加", len(new_hashes) >= 1, f"新增 {len(new_hashes)} 个：{sorted(new_hashes)[:3]}")

    if new_hashes:
        t = next((x for x in qbittorrent.torrents() if x.get("hash", "").lower() in new_hashes), None)
        if t:
            check("任务分类为 Bangumi", t.get("category") == "Bangumi", t.get("category"))
            check("任务保存路径 = 番剧目录",
                  os.path.normcase(t.get("save_path", "")) == os.path.normcase(sub.get("folder", "")),
                  t.get("save_path"))
            check("任务标签已设置", "自动追番" in (t.get("tags") or ""), t.get("tags"))
            print(f"        任务名: {t.get('name')}")
            print(f"        进度: {round(float(t.get('progress') or 0) * 100, 1)}%  状态: {t.get('state')}")

    print()
    print("=" * 74)
    print("阶段 5：订阅检查（追新逻辑）")
    print("=" * 74)
    code, d4 = call("POST", f"/api/subscriptions/{SID}/check")
    r = d4.get("result", {})
    check("订阅检查可执行", code == 200 and d4.get("ok"), r.get("error") or "")
    check("首次检查已建立基线", (d4.get("subscription", {}).get("primed") is True),
          f"primed={d4.get('subscription', {}).get('primed')} last_episode={d4.get('subscription', {}).get('last_episode')}")
    check("检查有结果描述", bool(d4.get("subscription", {}).get("last_result")),
          d4.get("subscription", {}).get("last_result"))
    print(f"        找到 {r.get('found')} 条，新下载 {r.get('downloaded')} 集")

    code, d5 = call("GET", "/api/subscriptions")
    check("订阅列表可读取", code == 200 and len(d5.get("items", [])) >= 1, f"{len(d5.get('items', []))} 条")
    check("订阅列表含 watcher 状态", "status" in d5, str(d5.get("status", {}).get("enabled")))

    code, d6 = call("POST", f"/api/subscriptions/{SID}/update", {"enabled": False})
    check("可停用订阅", code == 200 and d6.get("subscription", {}).get("enabled") is False)

    print()
    print("=" * 74)
    print("阶段 6：清理（删除测试任务与订阅）")
    print("=" * 74)
    if new_hashes:
        qbittorrent.delete_torrents(sorted(new_hashes), delete_files=True)
        time.sleep(1.5)
        left = qbittorrent.torrent_hashes() & new_hashes
        check("测试任务已删除", not left, f"残留 {left}")
    code, d7 = call("DELETE", f"/api/subscriptions/{SID}")
    check("测试订阅已删除", code == 200 and d7.get("ok"))
    if os.path.isdir(TEST_ROOT):
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
    check("测试下载目录已清理", not os.path.isdir(TEST_ROOT))

httpd.shutdown()
shutil.rmtree(TMP_DATA, ignore_errors=True)

print()
print("=" * 74)
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
print("=" * 74)
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
