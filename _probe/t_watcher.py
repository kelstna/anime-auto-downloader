"""追番引擎行为测试（离线，用构造数据，不碰真实 qBittorrent）。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import config, logger, subs, watcher   # noqa: E402
from app.sources import engine                       # noqa: E402
from app.sources.base import Resource, enrich        # noqa: E402

logger.set_console(False)
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


import hashlib


def R(title, group="", source="dmhy", res="1080p", seeds=10, size="1.0GB", batch=False):
    """构造一条资源；infohash 用标题的 sha1 前 40 位，保证唯一且能被正则识别。"""
    ih = hashlib.sha1(f"{source}|{title}".encode("utf-8")).hexdigest()[:40]
    r = Resource(source=source, source_name=source, title=title, group=group, resolution=res,
                 size_text=size, seeders=seeds, infohash=ih,
                 magnet=f"magnet:?xt=urn:btih:{ih}")
    r = enrich(r)
    r.is_batch = r.is_batch or batch
    return r


print("=" * 74)
print("1. 剧集筛选：只挑比 last_episode 更新的单集")
print("=" * 74)
sub = subs.Subscription(subject_id=1, name="测试番", last_episode=5, initial_mode=subs.INITIAL_LATEST)
out = engine.SearchOutcome()
out.resources = [
    R("[A组] 测试番 - 03 [1080p]"),                      # 旧集，跳过
    R("[A组] 测试番 - 06 [1080p]"),                      # 新集，要
    R("[A组] 测试番 - 07 [1080p]"),                      # 新集，要
    R("[A组] 测试番 - 06 [1080p]", res="720p"),           # 新集但分辨率不同（未限定，保留）
    R("[A组] 测试番 [01-12][1080p]", batch=True),         # 合集，跳过
    R("[A组] 测试番 - 08 [1080p] PV", seeds=1),           # 噪声，跳过
    R("[A组] 测试番 - 09 [1080p]"),                      # 新集，要
]
cands = watcher._new_candidates(sub, out)
eps = sorted({watcher.episode_of(r) for r in cands})
check("过滤掉旧集/合集/噪声", eps == [6, 7, 9], f"候选集数={eps}")
check("候选数量正确（含 720p 同集）", len(cands) == 4, f"{len(cands)} 条")

print()
print("=" * 74)
print("2. 分辨率限定")
print("=" * 74)
sub.resolution = "1080p"
cands = watcher._new_candidates(sub, out)
eps = sorted({watcher.episode_of(r) for r in cands})
check("限定 1080p 后排除 720p", eps == [6, 7, 9], f"候选集数={eps}")
sub.resolution = ""

print()
print("=" * 74)
print("3. 站点优先级：同集多站时优先动漫花园")
print("=" * 74)
same_ep = [
    R("[B组] 测试番 - 10 [1080p]", source="nyaa", seeds=9999),
    R("[B组] 测试番 - 10 [1080p]", source="kisssub", seeds=500),
    R("[B组] 测试番 - 10 [1080p]", source="dmhy", seeds=1),
]
best = watcher.pick_best(same_ep, "1080p")
check("动漫花园优先（即使做种数最低）", best.source == "dmhy", f"选中={best.source} 种={best.seeders}")
no_dmhy = [r for r in same_ep if r.source != "dmhy"]
check("无动漫花园时选爱恋动漫", watcher.pick_best(no_dmhy, "1080p").source == "kisssub")

print()
print("=" * 74)
print("4. 已下载去重（同一 infohash 不再下）")
print("=" * 74)
sub2 = subs.Subscription(subject_id=2, name="测试番2", last_episode=0, initial_mode=subs.INITIAL_LATEST)
r1 = R("[A组] 测试番2 - 01 [1080p]")
sub2.downloaded = {r1.infohash: r1.title}
out2 = engine.SearchOutcome()
out2.resources = [r1, R("[A组] 测试番2 - 02 [1080p]")]
cands2 = watcher._new_candidates(sub2, out2)
check("已下载的 infohash 被排除", len(cands2) == 1 and cands2[0].episode == 2,
      f"剩余集数={[watcher.episode_of(r) for r in cands2]}")

print()
print("=" * 74)
print("5. initial_mode 语义（用桩替换搜索与下载，不联网/不碰 qB）")
print("=" * 74)
origin_search, origin_download = watcher.search_for, watcher.download_resource
downloaded_log = []


def fake_search(sub):
    o = engine.SearchOutcome()
    o.resources = [R(f"[A组] {sub.name} - {i:02d} [1080p]") for i in range(1, 6)]
    return o


def fake_download(sub, res, reason=""):
    downloaded_log.append((sub.subject_id, watcher.episode_of(res), reason))
    sub.mark_downloaded(res.infohash or res.key, res.title, watcher.episode_of(res))
    return True


watcher.search_for, watcher.download_resource = fake_search, fake_download
try:
    for mode, expect in ((subs.INITIAL_LATEST, [5]), (subs.INITIAL_ALL, [1, 2, 3]),
                         (subs.INITIAL_NONE, [])):
        downloaded_log.clear()
        s = subs.Subscription(subject_id=100 + len(mode), name=f"番{mode}", initial_mode=mode)
        cfg = config.load()
        cfg["subscription"]["max_episodes_per_round"] = 3
        r = watcher.check_subscription(s)
        got = [ep for _, ep, _ in downloaded_log]
        check(f"initial_mode={mode} -> 下载 {got}", got == expect, f"期望 {expect}")
    # 第二次检查（已 primed）应只拿更新的集
    downloaded_log.clear()
    s = subs.Subscription(subject_id=200, name="番再次", initial_mode=subs.INITIAL_ALL, primed=True)
    s.last_episode = 3
    watcher.check_subscription(s)
    check("已 primed 后继续追新", [ep for _, ep, _ in downloaded_log] == [4, 5],
          f"下载 {[ep for _, ep, _ in downloaded_log]}")
finally:
    watcher.search_for, watcher.download_resource = origin_search, origin_download

print()
print("=" * 74)
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
print("=" * 74)
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
