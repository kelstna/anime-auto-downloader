# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
待下载队列（qBittorrent 掉线期间的资源先存起来、恢复后自动补下载）的离线测试。

对应用户反馈：番剧更新时 qBittorrent 没开就下载不了，之后再打开也不会补上。
现在流程是：番剧更新 → 下载失败 → 先把资源信息存进 data/pending.json
→ qBittorrent 恢复连接 → 巡检线程/下一轮检查自动补下载。
"""
import os
import sys
import time
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import config, pending, qbittorrent, rules, subs, watcher  # noqa: E402
from app.sources import engine                                      # noqa: E402
from app.sources.base import Resource                               # noqa: E402


def _magnet(tag: str) -> str:
    return f"magnet:?xt=urn:btih:{tag:40s}&dn=x"


def _res(title: str, tag: str, episode=3, **kw) -> Resource:
    return Resource(source="dmhy", source_name="动漫花园", title=title, group=kw.pop("group", "ANi"),
                    resolution="1080p", size_text="400MB", magnet=_magnet(tag),
                    infohash=tag, episode=episode, **kw)


def _sub(**kw) -> subs.Subscription:
    base = dict(subject_id=900001, name="测试番", total_episodes=12, last_episode=2,
                folder=os.path.join(config.get("download.root", "D:/Anime"), "测试番"))
    base.update(kw)
    return subs.Subscription(**base)


class PendingStoreTest(unittest.TestCase):
    """队列本身：入队去重、上限、过期、增删、持久化。"""

    def setUp(self):
        pending.reset_cache()
        pending.clear()

    def tearDown(self):
        pending.clear()
        pending.reset_cache()

    def _item(self, tag="a", sid=900001, ep=3, title="[ANi] 测试番 - 03", magnet=None):
        return pending.make_item(subject_id=sid, name="测试番", folder="D:/Anime/测试番", episode=ep,
                                 title=title, magnet=magnet or _magnet(tag), infohash=tag)

    def test_add_and_dedupe(self):
        self.assertIsNotNone(pending.add(self._item(tag="a")))
        self.assertEqual(pending.count(), 1)
        # 同一集（哪怕 magnet 不同）不重复入队
        self.assertIsNone(pending.add(self._item(tag="b", ep=3)))
        self.assertEqual(pending.count(), 1)
        # 不同一集可以入队
        self.assertIsNotNone(pending.add(self._item(tag="c", ep=4, title="[ANi] 测试番 - 04")))
        self.assertEqual(pending.count(), 2)

    def test_dedupe_by_infohash_even_for_other_episode(self):
        self.assertIsNotNone(pending.add(self._item(tag="a", ep=3)))
        self.assertIsNone(pending.add(self._item(tag="a", ep=9, title="[ANi] 测试番 - 09")))

    def test_remove_and_clear(self):
        it = pending.add(self._item(tag="a"))
        self.assertTrue(pending.remove(it["id"]))
        self.assertFalse(pending.remove(it["id"]))
        self.assertEqual(pending.count(), 0)
        pending.add(self._item(tag="a", ep=3))
        pending.add(self._item(tag="b", ep=4))
        self.assertEqual(pending.remove_subject(900001, episode=4), 1)
        self.assertEqual(pending.count(), 1)
        self.assertEqual(pending.clear(), 1)
        self.assertEqual(pending.count(), 0)

    def test_persisted_across_reload(self):
        pending.add(self._item(tag="a"))
        pending.reset_cache()                     # 模拟进程重启：丢内存缓存，重新读盘
        self.assertEqual(pending.count(), 1)
        items = pending.items()
        self.assertEqual(items[0]["episode"], 3)
        self.assertIn("magnet:?xt=urn:btih:", items[0]["magnet"])

    def test_summary_has_no_magnet(self):
        pending.add(self._item(tag="a"))
        s = pending.summary()
        self.assertEqual(s["count"], 1)
        self.assertEqual(s["subjects"], 1)
        self.assertNotIn("magnet", s["items"][0], "接口不能把磁力链撒出去")

    def test_max_items_drops_oldest(self):
        with mock.patch.object(config, "load", wraps=config.load):
            cfg = config.load()
            cfg.setdefault("queue", {})["max_items"] = 2
            config._cache = cfg                     # 直接改缓存，避免落盘影响真实配置
            try:
                for i in range(3):
                    pending.add(self._item(tag=str(i % 10) * 40, ep=i + 1, title=f"第 {i + 1} 集"))
                self.assertEqual(pending.count(), 2)
                self.assertEqual([i["episode"] for i in pending.items()], [2, 3])
            finally:
                config._cache = None
                config.load(force=True)

    def test_prune_old_items(self):
        # 直接构造一条很早以前的记录（正常入队时 add() 会立刻清理过期项）
        old = self._item(tag="a")
        old["created"] = time.time() - 400 * 3600      # 400 小时前（超过 168 小时）
        cfg = config.load()
        cfg.setdefault("queue", {})["max_age_hours"] = 0     # 先关掉自动清理
        config._cache = cfg
        try:
            pending.add(old)
            pending.add(self._item(tag="b", ep=5, title="新的"))
        finally:
            cfg["queue"]["max_age_hours"] = 168
            config._cache = cfg
        self.assertEqual(pending.count(), 2)
        self.assertEqual(pending.prune(), 1, "超过 max_age_hours 的要清理")
        self.assertEqual(pending.count(), 1)
        config._cache = None
        config.load(force=True)


class FlushTest(unittest.TestCase):
    """qBittorrent 从掉线到恢复：资源必须补下载成功，且进度/历史都要记账。"""

    def setUp(self):
        pending.reset_cache()
        pending.clear()
        subs.save_all([])
        self.sub = _sub()
        subs.save_all([self.sub])
        self.added = []

    def tearDown(self):
        pending.clear()
        pending.reset_cache()
        subs.save_all([])

    def _fake_add(self, magnet, **kw):
        self.added.append(magnet)

    def test_flush_when_qb_still_down_keeps_items(self):
        res = _res("[ANi] 测试番 - 03", "a" * 40)
        watcher._queue_failed(self.sub, res, 3, "无法连接 qBittorrent（http://127.0.0.1:8080）：拒绝连接")
        self.assertEqual(pending.count(), 1)
        with mock.patch.object(qbittorrent, "version", side_effect=qbittorrent.QBError("拒绝连接")):
            out = watcher.flush_pending()
        self.assertFalse(out["ok"])
        self.assertEqual(out["flushed"], 0)
        self.assertEqual(pending.count(), 1, "qBittorrent 没恢复时不能把队列清掉")
        self.assertIn("last_error", pending.summary())

    def test_flush_after_recovery_downloads_and_clears(self):
        res = _res("[ANi] 测试番 - 03", "a" * 40)
        watcher._queue_failed(self.sub, res, 3, "无法连接 qBittorrent")
        # 先走一遍「qBittorrent 还没起来」的补下载，模拟用户等待的那段
        with mock.patch.object(qbittorrent, "version", side_effect=qbittorrent.QBError("拒绝连接")):
            watcher.flush_pending()
        with mock.patch.object(qbittorrent, "version", return_value="v5.2.1"), \
                mock.patch.object(qbittorrent, "ensure_category", return_value=None), \
                mock.patch.object(qbittorrent, "add_magnet", side_effect=self._fake_add):
            out = watcher.flush_pending()
        self.assertTrue(out["ok"])
        self.assertEqual(out["flushed"], 1)
        self.assertEqual(pending.count(), 0)
        self.assertEqual(len(self.added), 1)
        cur = subs.get(self.sub.subject_id)
        self.assertEqual(cur.last_episode, 3, "补下载后进度要前进")
        self.assertTrue(any(h.get("reason") == "恢复补下载" for h in cur.history))
        self.assertEqual(pending.summary()["flushed_total"], 1)
        self.assertGreater(pending.summary()["recovered_at"], 0, "恢复时刻要记下来给界面提示")
        self.assertEqual(pending.summary()["last_error"], "", "补下载成功后清掉错误")

    def test_flush_skips_items_of_removed_subscription(self):
        res = _res("[ANi] 测试番 - 03", "a" * 40)
        watcher._queue_failed(self.sub, res, 3, "无法连接 qBittorrent")
        subs.save_all([])                          # 用户把这部番取消订阅了
        with mock.patch.object(qbittorrent, "version", return_value="v5.2.1"), \
                mock.patch.object(qbittorrent, "ensure_category", return_value=None), \
                mock.patch.object(qbittorrent, "add_magnet", side_effect=self._fake_add):
            out = watcher.flush_pending()
        self.assertEqual(out["flushed"], 0)
        self.assertEqual(pending.count(), 0, "番剧已不在订阅里，这条要丢掉")
        self.assertEqual(self.added, [])

    def test_flush_respects_max_per_flush(self):
        for i in range(3):
            watcher._queue_failed(self.sub, _res(f"[ANi] 测试番 - {i + 3:02d}", str(i) * 40, episode=i + 3),
                                  i + 3, "无法连接 qBittorrent")
        with mock.patch.object(qbittorrent, "version", return_value="v5.2.1"), \
                mock.patch.object(qbittorrent, "ensure_category", return_value=None), \
                mock.patch.object(qbittorrent, "add_magnet", side_effect=self._fake_add):
            cfg = config.load()
            cfg.setdefault("queue", {})["max_per_flush"] = 2
            config._cache = cfg
            try:
                out = watcher.flush_pending()
            finally:
                config._cache = None
                config.load(force=True)
        self.assertEqual(out["flushed"], 2)
        self.assertEqual(pending.count(), 1, "剩下的留给下一轮，别一次灌爆 qB")

    def test_queue_disabled_means_no_queue(self):
        cfg = config.load()
        cfg.setdefault("queue", {})["enabled"] = False
        config._cache = cfg
        try:
            res = _res("[ANi] 测试番 - 03", "a" * 40)
            self.assertIsNone(watcher._queue_failed(self.sub, res, 3, "无法连接 qBittorrent"))
            self.assertEqual(pending.count(), 0)
        finally:
            config._cache = None
            config.load(force=True)


class WatcherIntegrationTest(unittest.TestCase):
    """check_subscription 在下载失败时要把资源入队（而不是静默丢掉）。"""

    def setUp(self):
        pending.reset_cache()
        pending.clear()
        subs.save_all([])
        self.sub = _sub()
        subs.save_all([self.sub])

    def tearDown(self):
        pending.clear()
        pending.reset_cache()
        subs.save_all([])

    def test_check_enqueues_on_qb_failure(self):
        res = _res("[ANi] 测试番 - 03", "a" * 40, episode=3)
        outcome = engine.SearchOutcome()
        outcome.resources = [res]
        ctx = rules.SeasonContext(total=12, air_date="2026-10-01")
        with mock.patch.object(watcher, "search_for", return_value=outcome), \
                mock.patch.object(watcher, "season_context", return_value=ctx), \
                mock.patch.object(qbittorrent, "ensure_category", return_value=None), \
                mock.patch.object(qbittorrent, "add_magnet",
                                  side_effect=qbittorrent.QBError("无法连接 qBittorrent")):
            out = watcher.check_subscription(self.sub)
        self.assertEqual(out["downloaded"], 0)
        self.assertEqual(out.get("queued"), 1)
        self.assertEqual(pending.count(), 1)
        cur = subs.get(self.sub.subject_id)
        self.assertIn("已排队", cur.last_result)
        self.assertEqual(cur.last_episode, 2, "没下载成功就不能前进进度")

    def test_successful_download_does_not_queue(self):
        res = _res("[ANi] 测试番 - 03", "a" * 40, episode=3)
        outcome = engine.SearchOutcome()
        outcome.resources = [res]
        ctx = rules.SeasonContext(total=12, air_date="2026-10-01")
        with mock.patch.object(watcher, "search_for", return_value=outcome), \
                mock.patch.object(watcher, "season_context", return_value=ctx), \
                mock.patch.object(qbittorrent, "ensure_category", return_value=None), \
                mock.patch.object(qbittorrent, "add_magnet", return_value=None):
            out = watcher.check_subscription(self.sub)
        self.assertEqual(out["downloaded"], 1)
        self.assertEqual(pending.count(), 0)


if __name__ == "__main__":
    unittest.main()

class CheckNoUpdateTest(unittest.TestCase):
    """没有新集时的检查分支（回归：这里曾经 KeyError: 'queued'，所有订阅检查全变成「检查异常」）。"""

    def setUp(self):
        pending.reset_cache()
        pending.clear()
        subs.save_all([])
        self.sub = _sub()
        subs.save_all([self.sub])

    def tearDown(self):
        pending.clear()
        pending.reset_cache()
        subs.save_all([])

    def test_no_update_records_result_without_error(self):
        empty = engine.SearchOutcome()
        empty.resources = []
        with mock.patch.object(watcher, "search_for", return_value=empty), \
                mock.patch.object(watcher.subs, "save_all"):
            result = watcher.check_subscription(self.sub, manual=True)
        self.assertEqual(result["downloaded"], 0)
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["error"], "")
        self.assertEqual(self.sub.last_result, "未搜索到资源")
        self.assertGreater(self.sub.last_check, 0, "检查时间要写回，否则界面一直显示「从未」")

    def test_no_update_but_has_resources(self):
        outcome = engine.SearchOutcome()
        outcome.resources = [_res("[ANi] 测试番 - 01", "b" * 40, episode=1)]
        with mock.patch.object(watcher, "search_for", return_value=outcome), \
                mock.patch.object(watcher.subs, "save_all"):
            result = watcher.check_subscription(self.sub, manual=True)
        self.assertEqual(result["downloaded"], 0)
        self.assertIn("无更新", self.sub.last_result)

class LangFilterTest(unittest.TestCase):
    """订阅里选了字幕语言后，自动追番只能下载该语言（回归：选了简体却把繁体/生肉也下了）。"""

    def test_lang_matches_exact(self):
        self.assertTrue(watcher.lang_matches("chs", "chs"))
        self.assertFalse(watcher.lang_matches("cht", "chs"))
        self.assertFalse(watcher.lang_matches("both", "chs"))
        self.assertFalse(watcher.lang_matches("jp", "chs"))
        self.assertFalse(watcher.lang_matches("", "chs"), "未标注不能当成简体")
        self.assertTrue(watcher.lang_matches("", ""), "订阅没限语言时都放行")

    def test_candidates_filtered_by_subscription_lang(self):
        sub = _sub(group="", lang="chs")
        chs = _res("[桜都字幕组] 测试番 - 03 [1080p][简体内嵌]", "c" * 40, episode=3, lang="chs")
        cht = _res("[桜都字幕组] 测试番 - 03 [1080p][繁体内嵌]", "d" * 40, episode=3, lang="cht")
        both = _res("[桜都字幕组] 测试番 - 03 [1080p][简繁内封]", "e" * 40, episode=3, lang="both")
        en = _res("[ToonsHub] Test - 03 [1080p][Dual-Audio]", "f" * 40, episode=3, lang="en")
        outcome = engine.SearchOutcome()
        outcome.resources = [chs, cht, both, en]
        with mock.patch.object(watcher, "in_current_season", return_value=True), \
                mock.patch.object(watcher, "pick_best", side_effect=lambda bucket, preferred: bucket[0]):
            got = watcher._new_candidates(sub, outcome, air_date="", total_episodes=12, sub_season=1)
        self.assertEqual([r.lang for r in got], ["chs"], f"只应留下简体，实际 {[r.lang for r in got]}")

class StatusIntervalTest(unittest.TestCase):
    """回归：status() 里曾用 cfg.get("a.b")（嵌套字典取点号路径永远拿不到 → 永远显示默认 30）。"""

    def test_status_reflects_current_interval(self):
        from app.core import config as _cfg
        before = _cfg.get("subscription.interval_minutes", 30)
        try:
            _cfg.update({"subscription": {"interval_minutes": 7}})
            self.assertEqual(watcher.status()["interval_minutes"], 7)
        finally:
            _cfg.update({"subscription": {"interval_minutes": before}})

