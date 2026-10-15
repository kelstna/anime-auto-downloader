# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""顺序执行 tests 目录下全部用例，打印中文摘要；有失败时退出码非 0。

用法（在项目根目录）：
    python tests\\run_all.py

等价于：
    python -m unittest discover -s tests -t . -v
"""
import os
import sys
import time
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT, _TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def build_suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    return loader.discover(start_dir=_TESTS, pattern="test_*.py", top_level_dir=_ROOT)


def main() -> int:
    os.chdir(_ROOT)
    print("=" * 64)
    print("自动下载番剧 - 离线测试套件")
    print(f"项目根目录：{_ROOT}")
    print(f"联网用例：{'已启用' if os.environ.get('ANIME_ONLINE') == '1' else '已跳过（设置 ANIME_ONLINE=1 启用）'}")
    print("=" * 64)

    suite = build_suite()
    started = time.time()
    result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    elapsed = time.time() - started

    total = result.testsRun
    failed = len(result.failures)
    errored = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - errored - skipped

    print()
    print("=" * 64)
    print("测试摘要")
    print("-" * 64)
    print(f"  用例总数：{total}")
    print(f"  通过：    {passed}")
    print(f"  失败：    {failed}")
    print(f"  错误：    {errored}")
    print(f"  跳过：    {skipped}")
    print(f"  耗时：    {elapsed:.2f} 秒")
    print("-" * 64)
    if result.wasSuccessful():
        print("  结果：全部通过")
    else:
        print("  结果：存在失败，详见上方 FAILED / ERROR 段落")
        for case, _ in result.failures:
            print(f"    失败：{case}")
        for case, _ in result.errors:
            print(f"    错误：{case}")
    print("=" * 64)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
