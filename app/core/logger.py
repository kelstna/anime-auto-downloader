# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
轻量日志：控制台 + 滚动文件，线程安全。
后台常驻场景下限制文件体积，避免长期运行占用磁盘。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime

from . import config

_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 3
_lock = threading.RLock()
_log_path: str | None = None
_console = True


def _path() -> str:
    global _log_path
    if _log_path is None:
        config.ensure_dirs()
        _log_path = os.path.join(config.DATA_DIR, "app.log")
    return _log_path


def _rotate() -> None:
    p = _path()
    try:
        if os.path.exists(p) and os.path.getsize(p) > _MAX_BYTES:
            for i in range(_BACKUPS - 1, 0, -1):
                src, dst = f"{p}.{i}", f"{p}.{i + 1}"
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(p, f"{p}.1")
    except OSError:
        pass


def set_console(enabled: bool) -> None:
    global _console
    _console = enabled


def log(level: str, msg: str, *args) -> None:
    if args:
        try:
            msg = msg % args
        except (TypeError, ValueError):
            msg = f"{msg} {args}"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level:<5}] {msg}"
    with _lock:
        if _console:
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass
        try:
            _rotate()
            with open(_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def info(msg: str, *args) -> None:
    log("INFO", msg, *args)


def warn(msg: str, *args) -> None:
    log("WARN", msg, *args)


def error(msg: str, *args) -> None:
    log("ERROR", msg, *args)


def debug(msg: str, *args) -> None:
    if os.environ.get("ANIME_DEBUG"):
        log("DEBUG", msg, *args)


def tail(n: int = 200) -> list[str]:
    """读取最后 n 行日志，供 UI 展示。"""
    try:
        with open(_path(), "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]]
    except OSError:
        return []
