# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
自动下载番剧 —— 启动入口。

用法：
    python -m app.main                 # 使用 config.json 中的 host/port
    python -m app.main --port 7788
    python -m app.main --no-browser    # 后台常驻（自启动用）
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

if __package__ in (None, ""):  # 支持直接 python app/main.py
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
else:
    __package__ = "app"

from .core import airtimes, bangumi, config, logger, pending, qbittorrent, watcher  # noqa: E402
from .core.util import lan_ipv4_addresses                      # noqa: E402
from .web import server                                          # noqa: E402

BANNER = r"""
   ___          _                 _      ___       _      __
  / _ \        (_)               | |    / _ \     | |    / /
 / /_\ \_ __   _ _ __ ___   ___  | |   / /_\ \_ __| |_  / /
 |  _  | '_ \ | | '_ ` _ \ / _ \ | |   |  _  | '__| __|/ /
 | | | | | | || | | | | | |  __/ | |   | | | | |  | |_/ /
 \_| |_/_| |_|_|_| |_| |_|\___| |_|   \_| |_/_|   \__/_/

   自动下载番剧  ·  本地 Web 服务
"""


def pick_port(host: str, port: int) -> int:
    """端口被占用时自动往后找一个可用端口。"""
    for candidate in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise SystemExit(f"端口 {port}~{port + 19} 都被占用，请修改配置里的 server.port")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自动下载番剧 本地服务")
    parser.add_argument("--host", default=None, help="监听地址（默认取配置，127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认取配置，7788）")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--no-watcher", action="store_true", help="不启动自动追番后台线程")
    parser.add_argument("--verbose", action="store_true", help="输出访问日志到控制台")
    args = parser.parse_args(argv)

    config.ensure_dirs()
    if args.verbose:
        os.environ["ANIME_DEBUG"] = "1"

    host = args.host or config.get("server.host", "127.0.0.1")
    if config.get("server.allow_lan", False) and not args.host:
        host = "0.0.0.0"
    want_port = args.port or int(config.get("server.port", 7788))
    port = pick_port(host, want_port)

    print(BANNER)
    logger.info("=" * 62)
    logger.info("自动下载番剧 启动中…")
    logger.info("配置目录：%s", config.DATA_DIR)
    logger.info("下载目录：%s", config.get("download.root", ""))
    logger.info("代理：%s", _proxy_desc())

    qb_info = qbittorrent.test_connection()
    if qb_info.get("ok"):
        ver = str(qb_info.get("version") or "").lstrip("vV")
        logger.info("qBittorrent 已连接：v%s（WebAPI %s），默认目录 %s",
                    ver, qb_info.get("webapi_version"),
                    qb_info.get("default_save_path"))
    else:
        logger.warn("qBittorrent 未连接：%s", qb_info.get("error", "未知错误"))
        logger.warn("请确认 qBittorrent 已启动且 WebUI 端口与配置一致（当前 %s）",
                    config.get("qbittorrent.base_url", ""))

    if config.bangumi_token():
        try:
            me = bangumi.get_me()
            logger.info("Bangumi 已登录：%s", me.get("nickname") or me.get("username"))
        except bangumi.BangumiError as e:
            logger.warn("Bangumi Token 校验失败：%s", e)
    else:
        logger.warn("尚未填写 Bangumi Access Token，请在网页里填写")

    if not args.no_watcher:
        watcher.start()
    _queued = pending.count()
    if _queued:
        logger.info("待下载队列：%d 条（qBittorrent 恢复连接后自动补下载）", _queued)

    # 番剧更新时刻（bangumi-data → data/airtimes.json，每天刷新一次）：过期就后台刷，不挡启动
    airtimes.ensure_fresh_async()
    _air = airtimes.status()
    if _air.get("enabled"):
        logger.info("更新时刻数据：%d 部番%s", _air.get("count") or 0,
                    f"（更新于 {_air['updated_text']}）" if _air.get("updated_text") else "（缓存为空，正在后台拉取）")

    httpd = server.serve_forever(host, port)
    url_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    url = f"http://{url_host}:{port}/"
    logger.info("服务已就绪：%s", url)
    if host == "0.0.0.0":
        # 局域网访问：把真实的网卡地址打出来（手机/平板照着填），不要写 «本机IP» 让用户自己猜
        lan = lan_ipv4_addresses()
        if lan:
            logger.info("局域网访问（手机/平板用同一 Wi-Fi 打开）：")
            for ip in lan:
                logger.info("    http://%s:%d/", ip, port)
        else:
            logger.warn("局域网访问已开启，但没找到可用的网卡地址（可能只有回环/虚拟网卡）")
    print(f"\n  打开浏览器访问： {url}\n")

    if not args.no_browser and config.get("server.open_browser_on_start", True):
        threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(url)),
                         name="open-browser", daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，正在退出…")
    finally:
        watcher.stop()
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass
    return 0


def _proxy_desc() -> str:
    if not config.get("proxy.enabled", False):
        return "未启用（直连）"
    parts = []
    if config.get("proxy.for_bangumi", True):
        parts.append("Bangumi")
    if config.get("proxy.for_sources", True):
        parts.append("资源站")
    return f"{config.get('proxy.url', '')}（作用于 {'/'.join(parts) or '无'}，不代理 qBittorrent）"


if __name__ == "__main__":
    raise SystemExit(main())
