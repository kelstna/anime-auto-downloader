# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
tests 包：把项目根目录加入 sys.path，并把数据目录指向临时目录。

为什么要把数据目录指向临时目录：单元测试会真的跑搜索流程，而搜索现在会写
「关键词学习记录」（data/keyword_stats.json）—— 不隔离的话，测试会污染用户真实数据，
而且测试之间还会互相影响（上一轮学到的关键词跑到下一轮的候选表最前面，断言就飘了）。
这里在任何 app.* 模块被导入之前设置 ANIME_DATA_DIR，保证测试永远不碰真实 data\\ 目录。
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 只有没被显式指定过才设置（探针脚本会自己指定临时目录，别覆盖它）
if not os.environ.get("ANIME_DATA_DIR"):
    os.environ["ANIME_DATA_DIR"] = tempfile.mkdtemp(prefix="anime-tests-")
