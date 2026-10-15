# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""app.core.subs 订阅存储的离线测试：用临时目录重定向存储文件，不碰真实 data\\。"""
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.core import config, subs  # noqa: E402
from app.core.util import sanitize_name  # noqa: E402


class _NullLogger:
    """把日志吞掉，避免污染真实 data\\app.log。"""

    def info(self, *a, **k):
        pass

    def warn(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


class SubsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="anime_subs_test_")
        self.path = os.path.join(self.tmp.name, "subscriptions.json")
        self._orig_path = subs._SUBS_PATH
        self._orig_cache = subs._cache
        self._orig_logger = subs.logger
        subs._SUBS_PATH = self.path
        subs._cache = None

    def tearDown(self):
        subs._SUBS_PATH = self._orig_path
        subs._cache = self._orig_cache
        subs.logger = self._orig_logger
        self.tmp.cleanup()

    # ---------------------------------------------------------------- #
    def _reload(self):
        subs._cache = None

    def test_empty_when_no_file(self):
        self.assertEqual(subs.all_subs(), [])
        self.assertIsNone(subs.get(1))

    def test_upsert_then_get_from_disk(self):
        sub = subs.Subscription(subject_id=42, name="葬送的芙莉莲", name_original="Sousou no Frieren")
        subs.upsert(sub)
        self.assertTrue(os.path.exists(self.path))
        self._reload()
        got = subs.get(42)
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "葬送的芙莉莲")
        self.assertEqual(got.name_original, "Sousou no Frieren")
        self.assertEqual(len(subs.all_subs()), 1)

    def test_upsert_merges_downloaded(self):
        sub = subs.Subscription(subject_id=42, name="番剧")
        sub.mark_downloaded("hash-a", "第01话", 1)
        subs.upsert(sub)

        again = subs.Subscription(subject_id=42, name="番剧改")
        again.mark_downloaded("hash-b", "第02话", 2)
        subs.upsert(again)

        self._reload()
        got = subs.get(42)
        self.assertEqual(got.name, "番剧改")
        self.assertEqual(set(got.downloaded), {"hash-a", "hash-b"})
        self.assertEqual(got.last_episode, 2)
        self.assertEqual(len(subs.all_subs()), 1, "同一 subject_id 不应产生第二条记录")

    def test_upsert_keeps_larger_last_episode_and_created_at(self):
        first = subs.Subscription(subject_id=7, name="A", last_episode=10)
        subs.upsert(first)
        created = first.created_at

        second = subs.Subscription(subject_id=7, name="A", last_episode=3)
        subs.upsert(second)

        self._reload()
        got = subs.get(7)
        self.assertEqual(got.last_episode, 10, "已下载集数不应被回退")
        self.assertEqual(got.created_at, created, "created_at 应保留首次创建时间")

    def test_upsert_keeps_history_when_new_is_empty(self):
        first = subs.Subscription(subject_id=8, name="A")
        first.add_history({"title": "旧的记录"})
        subs.upsert(first)

        subs.upsert(subs.Subscription(subject_id=8, name="A"))
        self._reload()
        self.assertEqual(len(subs.get(8).history), 1)

    def test_update_fields(self):
        subs.upsert(subs.Subscription(subject_id=5, name="A"))
        got = subs.update_fields(5, group="北宇治字幕组", resolution="1080p", last_episode=9)
        self.assertIsNotNone(got)
        self.assertEqual(got.group, "北宇治字幕组")
        self.assertEqual(got.resolution, "1080p")
        self.assertEqual(got.last_episode, 9)
        self._reload()
        self.assertEqual(subs.get(5).group, "北宇治字幕组")

    def test_update_fields_unknown_id_returns_none(self):
        self.assertIsNone(subs.update_fields(999, group="x"))

    def test_update_fields_ignores_unknown_field(self):
        subs.upsert(subs.Subscription(subject_id=5, name="A"))
        got = subs.update_fields(5, 不存在的字段="x")
        self.assertIsNotNone(got)
        self.assertFalse(hasattr(got, "不存在的字段"))

    def test_remove(self):
        subs.upsert(subs.Subscription(subject_id=1, name="A"))
        subs.upsert(subs.Subscription(subject_id=2, name="B"))
        self.assertTrue(subs.remove(1))
        self.assertFalse(subs.remove(1), "重复删除应返回 False")
        self._reload()
        self.assertEqual([s.subject_id for s in subs.all_subs()], [2])

    def test_mark_downloaded_does_not_go_backwards(self):
        sub = subs.Subscription(subject_id=1)
        sub.mark_downloaded("h1", "第03话", 3)
        self.assertEqual(sub.downloaded, {"h1": "第03话"})
        self.assertEqual(sub.last_episode, 3)
        sub.mark_downloaded("h2", "第02话", 2)
        self.assertEqual(sub.last_episode, 3)
        sub.mark_downloaded("", "没有 infohash", 5)
        self.assertNotIn("", sub.downloaded)
        self.assertEqual(sub.last_episode, 5)

    def test_history_newest_first_and_capped(self):
        sub = subs.Subscription(subject_id=1)
        for i in range(250):
            sub.add_history({"title": f"第{i}条"})
        self.assertEqual(len(sub.history), 200)
        self.assertEqual(sub.history[0]["title"], "第249条")

    def test_to_dict_fields(self):
        sub = subs.Subscription(subject_id=3, name="中文名", name_original="Romanized")
        sub.mark_downloaded("h", "标题", 1)
        d = sub.to_dict()
        self.assertEqual(d["subject_id"], 3)
        self.assertEqual(d["display_name"], "中文名")
        self.assertEqual(d["downloaded_count"], 1)
        self.assertEqual(d["name_original"], "Romanized")

    def test_display_name_fallback(self):
        sub = subs.Subscription(subject_id=99)
        self.assertEqual(sub.display_name, "subject-99")

    def test_safe_folder_and_default_folder(self):
        sub = subs.Subscription(subject_id=1, name='葬送的芙莉莲 / 第一季')
        self.assertEqual(sub.safe_folder, sanitize_name(sub.display_name))
        folder = subs.default_folder(sub.display_name)
        self.assertTrue(os.path.isabs(folder))
        self.assertTrue(folder.endswith(sanitize_name(sub.display_name)))
        self.assertEqual(config.get("download.root") is not None, True)

    def test_written_as_utf8_without_escapes(self):
        subs.upsert(subs.Subscription(subject_id=1, name="葬送的芙莉莲"))
        with open(self.path, "rb") as f:
            raw = f.read()
        self.assertIn("葬送的芙莉莲".encode("utf-8"), raw)
        self.assertNotIn(b"\\u846c", raw, "不应写成 \\uXXXX 转义")
        self.assertEqual(len(json.loads(raw.decode("utf-8"))), 1)

    def test_corrupted_file_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")
        subs.logger = _NullLogger()
        self.assertEqual(subs.all_subs(), [])

    def test_non_list_file_is_ignored(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"subject_id": 1}, f)
        self.assertEqual(subs.all_subs(), [])

    def test_unknown_keys_in_record_are_dropped(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"subject_id": 11, "name": "A", "未来字段": 1}], f, ensure_ascii=False)
        self._reload()
        got = subs.get(11)
        self.assertIsNotNone(got)
        self.assertEqual(got.name, "A")
        self.assertFalse(hasattr(got, "未来字段"))

    def test_invalid_record_is_skipped(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"name": "缺少 subject_id"}], f, ensure_ascii=False)
        subs.logger = _NullLogger()
        self.assertEqual(subs.all_subs(), [])

    def test_force_reload(self):
        subs.upsert(subs.Subscription(subject_id=1, name="A"))
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"subject_id": 2, "name": "B"}], f, ensure_ascii=False)
        self.assertEqual([s.subject_id for s in subs.all_subs(force=True)], [2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
