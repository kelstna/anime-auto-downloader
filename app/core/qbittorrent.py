# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
qBittorrent WebUI API 客户端。
本模块的请求**永不使用代理**（即使全局代理开启），符合「不代理 qBittorrent」的要求。
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Optional

from . import config, http, logger
from .util import sanitize_name

_SESSION = "qbittorrent"
_lock = threading.RLock()
_logged_in = False
_api_version = ""


class QBError(Exception):
    pass


def base_url(cfg: Optional[dict] = None) -> str:
    c = (cfg or config.load().get("qbittorrent", {}) or {})
    url = (c.get("base_url") or "http://127.0.0.1:8080").strip().rstrip("/")
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url


def _call(path: str, *, method: str = "GET", params: Optional[dict] = None,
          data: Optional[dict | bytes] = None, timeout: float = 15.0,
          retry_auth: bool = True, headers: Optional[dict] = None) -> tuple[int, str]:
    """调用 qBittorrent API（不经过代理）。"""
    url = base_url() + path
    try:
        code, text, _ = http.request(
            url, method=method, params=params, data=data,
            headers=headers or {"Referer": base_url() + "/", "Origin": base_url()},
            proxy=None,                      # 关键：qBittorrent 不走代理
            session=_SESSION,
            timeout=timeout,
            retries=1,
        )
        return code, text
    except http.HttpError as e:
        if e.status == 403 and retry_auth and login(force=True):
            return _call(path, method=method, params=params, data=data,
                         timeout=timeout, retry_auth=False, headers=headers)
        raise QBError(_friendly(e.status, path)) from None
    except OSError as e:
        raise QBError(f"无法连接 qBittorrent（{base_url()}）：{e}") from None


def _friendly(status: int, path: str) -> str:
    if status == 403:
        return "qBittorrent 拒绝访问（403）：请检查 WebUI 用户名/密码，或把本机加入免密白名单"
    if status == 404:
        return f"qBittorrent 接口不存在（404）：{path}"
    if status == 409:
        return "qBittorrent 返回冲突（409）：种子可能已存在"
    return f"qBittorrent 返回 HTTP {status}：{path}"


def login(force: bool = False) -> bool:
    """登录 WebUI；本机免密（LocalHostAuth=false）时无需登录。"""
    global _logged_in
    cfg = config.load().get("qbittorrent", {}) or {}
    user = (cfg.get("username") or "").strip()
    pwd = cfg.get("password") or ""
    if not user:
        return False
    with _lock:
        if _logged_in and not force:
            return True
        if force:
            http.clear_session(_SESSION)
        try:
            _, text, _ = http.request(
                base_url() + "/api/v2/auth/login",
                method="POST", data={"username": user, "password": pwd},
                headers={"Referer": base_url() + "/", "Origin": base_url()},
                proxy=None, session=_SESSION, timeout=15, retries=0,
            )
        except (http.HttpError, OSError) as e:
            logger.warn("qBittorrent 登录失败：%s", e)
            return False
        ok = "Ok" in (text or "")
        _logged_in = ok
        if not ok:
            logger.warn("qBittorrent 登录被拒绝，请检查用户名/密码")
        return ok


def api_version() -> str:
    global _api_version
    if not _api_version:
        try:
            _, text = _call("/api/v2/app/webapiVersion")
            _api_version = text.strip()
        except QBError:
            _api_version = ""
    return _api_version


def version() -> str:
    _, text = _call("/api/v2/app/version")
    return text.strip()


def preferences() -> dict:
    _, text = _call("/api/v2/app/preferences")
    import json
    try:
        return json.loads(text)
    except ValueError:
        return {}


def default_save_path() -> str:
    try:
        _, text = _call("/api/v2/app/defaultSavePath")
        return text.strip()
    except QBError:
        return ""


def test_connection() -> dict:
    """连接自检：返回版本、免密状态、默认下载目录等。"""
    info: dict[str, Any] = {"ok": False, "base_url": base_url()}
    try:
        info["version"] = version()
        info["webapi_version"] = api_version()
        prefs = preferences()
        info["default_save_path"] = prefs.get("save_path", "")
        info["listen_port"] = prefs.get("listen_port")
        info["ok"] = True
    except QBError as e:
        info["error"] = str(e)
        return info
    try:
        cats = categories()
        info["categories"] = list(cats.keys())
    except QBError:
        info["categories"] = []
    return info


def categories() -> dict:
    _, text = _call("/api/v2/torrents/categories")
    import json
    try:
        return json.loads(text) or {}
    except ValueError:
        return {}


def ensure_category(name: str, save_path: str = "") -> None:
    """确保分类存在（用于在 qB 里归类番剧）。"""
    name = (name or "").strip()
    if not name:
        return
    try:
        existing = categories()
    except QBError:
        return
    if name in existing:
        return
    payload = {"category": name}
    if save_path:
        payload["savePath"] = save_path
    try:
        _call("/api/v2/torrents/createCategory", method="POST", data=payload)
    except QBError as e:
        logger.warn("创建分类 %s 失败：%s", name, e)


def add_magnet(magnet: str, *, save_path: str = "", category: str = "", tags: str = "",
               paused: bool = False, subfolder: str = "false") -> bool:
    """
    添加磁力任务。返回是否成功（已存在视为成功）。

    关于 subfolder：
    番剧目录本身已经是「一部番一个文件夹」（save_path = D:\\Anime\\<简体名>），
    所以这里默认 **NoSubfolder** —— 文件直接落在番剧目录里，
    和「在 qBittorrent 客户端里直接添加磁链」的行为一致。
    曾经默认 Subfolder，导致多出一层与种子同名的文件夹：
      D:\\Anime\\番剧\\[组] 番剧 - 01 [1080P]...\\[组] 番剧 - 01 [1080P]....mp4   ← 多余
    现在：
      D:\\Anime\\番剧\\[组] 番剧 - 01 [1080P]....mp4
    （合集种子内部的目录结构不受影响，NoSubfolder 只影响最外层是否再包一层）
    """
    magnet = (magnet or "").strip()
    if not magnet:
        raise QBError("磁力链接为空")
    if not magnet.startswith("magnet:"):
        raise QBError("不是合法的磁力链接")

    ver = api_version()
    payload: dict[str, str] = {
        "urls": magnet,
        "contentLayout": "Subfolder" if subfolder == "true" else "NoSubfolder",
    }
    if save_path:
        payload["savepath"] = save_path
    if category:
        payload["category"] = category
    if tags:
        payload["tags"] = tags
    # WebAPI >= 2.11.0 使用 stopped 代替 paused
    payload["stopped" if _ge(ver, "2.11") else "paused"] = "true" if paused else "false"

    try:
        code, text = _call("/api/v2/torrents/add", method="POST", data=payload,
                           headers={"Referer": base_url() + "/", "Origin": base_url()})
    except QBError as e:
        msg = str(e)
        if "409" in msg:
            logger.info("种子已存在于 qBittorrent，跳过：%s", magnet[:60])
            return True
        raise
    if code == 200 and (not text or "Ok" in text or "Fails" not in text):
        return True
    if "Fails" in (text or ""):
        # 已存在的任务会返回 Fails.
        logger.info("qBittorrent 未新增任务（可能已存在）：%s", magnet[:60])
        return True
    return code == 200


def _ge(version: str, target: str) -> bool:
    """比较 WebAPI 版本号，如 '2.15.1' >= '2.11'。"""
    def parts(v: str) -> list[int]:
        return [int(x) for x in re.findall(r"\d+", v or "")] or [0]
    a, b = parts(version), parts(target)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a >= b


def torrents(filter_: str = "all", category: str = "", limit: int = 0) -> list[dict]:
    params: dict[str, Any] = {"filter": filter_}
    if category:
        params["category"] = category
    if limit:
        params["limit"] = limit
    _, text = _call("/api/v2/torrents/info", params=params)
    import json
    try:
        return json.loads(text) or []
    except ValueError:
        return []


def torrent_hashes(filter_: str = "all") -> set[str]:
    try:
        return {t.get("hash", "").lower() for t in torrents(filter_) if t.get("hash")}
    except QBError:
        return set()


def torrent_files(hash_: str) -> list[dict]:
    _, text = _call("/api/v2/torrents/files", params={"hash": hash_})
    import json
    try:
        return json.loads(text) or []
    except ValueError:
        return []


def delete_torrents(hashes: list[str], delete_files: bool = False) -> None:
    if not hashes:
        return
    _call("/api/v2/torrents/delete", method="POST",
          data={"hashes": "|".join(hashes), "deleteFiles": "true" if delete_files else "false"})


def to_hex_hash(stored: str) -> str:
    """
    订阅里记的可能是 magnet 里的 base32 infohash（32 位字母数字），qBittorrent 要 40 位十六进制。
    已经是十六进制（或认不出来）就原样返回。
    """
    import base64
    import binascii
    import re as _re
    s = str(stored or "").strip().lower()
    if _re.fullmatch(r"[0-9a-f]{40}", s):
        return s
    if _re.fullmatch(r"[a-z2-7]{32}", s):
        try:
            return binascii.hexlify(base64.b32decode(s.upper())).decode()
        except (binascii.Error, ValueError):
            return s
    return s


def find_torrent(stored_hash: str, name_hint: str = "") -> Optional[dict]:
    """
    在 qBittorrent 里找一条任务：先按 hash（含 base32 转换）匹配，找不到再按标题兜底。
    找不到返回 None（任务可能已经被手动删掉了）。
    """
    want = to_hex_hash(stored_hash)
    hint = (name_hint or "").strip().lower()
    try:
        items = torrents()
    except QBError:
        return None
    for t in items:
        if want and str(t.get("hash", "")).lower() == want:
            return t
    if hint:
        for t in items:
            name = str(t.get("name", "")).lower()
            if name and (name == hint or hint in name or name in hint):
                return t
    return None


def folder_for(subject_name: str, root: Optional[str] = None) -> str:
    """计算某番剧的下载目录：<root>/<简体名>。"""
    import os
    cfg = config.load()
    root = root if root is not None else config.get("download.root", r"D:\Anime")
    mode = config.get("download.folder_mode", "name_cn")
    folder = sanitize_name(subject_name)
    return os.path.normpath(os.path.join(root, folder))
