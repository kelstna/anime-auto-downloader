# SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
# SPDX-License-Identifier: GPL-3.0-only
"""
HTTP 客户端（标准库实现）：
- 按用途选择代理（Bangumi / 资源站走代理，qBittorrent 永不代理）
- Cookie 会话、gzip 解压、编码自适应、超时与重试
"""
from __future__ import annotations

import gzip
import io
import json
import random
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar
import zlib
from typing import Any, Optional

from . import logger

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = "", message: str = ""):
        self.status = status
        self.code = status               # 两种写法都留着，调用方别踩坑
        self.url = url
        self.body = body
        super().__init__(message or f"HTTP {status} for {url}")


_SSL_CTX = ssl.create_default_context()
_lock = threading.RLock()
_openers: dict[tuple, urllib.request.OpenerDirector] = {}
_cookiejars: dict[str, http.cookiejar.CookieJar] = {}


def ssl_context() -> ssl.SSLContext:
    return _SSL_CTX


def _build_opener(proxy: Optional[str], jar: http.cookiejar.CookieJar) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}),
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=_SSL_CTX),
    ]
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = []
    return opener


def _get_opener(proxy: Optional[str], session: Optional[str]):
    jar = None
    if session:
        with _lock:
            jar = _cookiejars.get(session)
            if jar is None:
                jar = http.cookiejar.CookieJar()
                _cookiejars[session] = jar
    key = (proxy or "", session or "")
    with _lock:
        op = _openers.get(key)
        if op is None:
            op = _build_opener(proxy, jar or http.cookiejar.CookieJar())
            _openers[key] = op
        return op


def clear_session(name: str) -> None:
    with _lock:
        _cookiejars.pop(name, None)
        for k in [k for k in _openers if k[1] == name]:
            _openers.pop(k, None)


def _retry_after(headers) -> float:
    """解析 Retry-After（秒数写法；日期写法忽略），拿不到返回 0。"""
    try:
        value = (headers or {}).get("Retry-After", "")
    except AttributeError:
        return 0.0
    try:
        return max(0.0, float(str(value).strip()))
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- #
# 站点限流（429）冷却
# --------------------------------------------------------------------------- #
# 爱恋动漫（kisssub）在批量预热时会返回 429。被限流后再连着重试只会被继续拦，
# 而且每个请求都要等好几秒才失败 —— 所以记一下「这个站点到什么时候为止别再打了」，
# 冷却期内直接快速失败（错误信息里写清楚），预热/搜索才能跑完。
_COOLDOWN: dict[str, float] = {}
_COOLDOWN_DEFAULT = 60.0


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def cooldown_left(url: str) -> float:
    """该地址所属站点还剩多少秒冷却（0 = 没在冷却）。"""
    host = _host_of(url)
    if not host:
        return 0.0
    with _lock:
        left = _COOLDOWN.get(host, 0.0) - time.time()
    return left if left > 0 else 0.0


def mark_cooldown(url: str, seconds: float = _COOLDOWN_DEFAULT) -> float:
    """标记站点冷却（返回实际设置的秒数）。"""
    host = _host_of(url)
    if not host:
        return 0.0
    secs = max(5.0, min(float(seconds or _COOLDOWN_DEFAULT), 600.0))
    with _lock:
        _COOLDOWN[host] = max(_COOLDOWN.get(host, 0.0), time.time() + secs)
    logger.debug("站点 %s 被限流，冷却 %.0fs", host, secs)
    return secs


def clear_cooldown(url: str = "") -> None:
    """清掉冷却（测试 / 用户手动重试用）。"""
    with _lock:
        if url:
            _COOLDOWN.pop(_host_of(url), None)
        else:
            _COOLDOWN.clear()


def _decode(raw: bytes, headers) -> str:
    if headers.get("Content-Encoding", "").lower() == "gzip":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass
    ctype = headers.get("Content-Type", "") or ""
    m = re.search(r"charset=([\w\-]+)", ctype, re.I)
    if m:
        enc = m.group(1)
        try:
            return raw.decode(enc, "replace")
        except LookupError:
            pass
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def request(
    url: str,
    *,
    method: str = "GET",
    params: Optional[dict] = None,
    data: Optional[dict | bytes] = None,
    headers: Optional[dict] = None,
    proxy: Optional[str] = None,
    session: Optional[str] = None,
    timeout: float = 20.0,
    retries: int = 2,
    backoff: float = 1.2,
    referer: Optional[str] = None,
) -> tuple[int, str, dict]:
    """
    发起 HTTP 请求，返回 (状态码, 文本, 响应头字典)。
    失败抛出 HttpError / OSError 的包装异常。
    """
    if params:
        sep = "&" if urllib.parse.urlparse(url).query else "?"
        url = url + sep + urllib.parse.urlencode(params, doseq=True)

    body: Optional[bytes] = None
    if isinstance(data, bytes):
        body = data
    elif isinstance(data, dict):
        body = urllib.parse.urlencode(data, doseq=True).encode("utf-8")

    hdrs = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip",
        "Connection": "close",
    }
    if body is not None:
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    if referer:
        hdrs["Referer"] = referer
    if headers:
        hdrs.update({k: v for k, v in headers.items() if v is not None})

    opener = _get_opener(proxy, session)
    last_exc: Optional[Exception] = None

    left = cooldown_left(url)
    if left > 0 and retries >= 0:
        # 冷却期内不再打这个站点：直接快速失败，报错里写清楚还剩多久
        raise HttpError(429, url, "站点限流冷却中",
                        message=f"HTTP 429 {url}：该站点正在限流，请约 {int(left) + 1} 秒后重试")

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                rh = {k: v for k, v in resp.headers.items()}
                return resp.status, _decode(raw, resp.headers), rh
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:
                pass
            text = _decode(raw, e.headers or {})
            # 4xx 除 429 外不重试
            if e.code < 500 and e.code != 429:
                raise HttpError(e.code, url, text[:500]) from None
            last_exc = HttpError(e.code, url, text[:500])
            if e.code == 429:
                # 站点限流：记下冷却时间（优先听 Retry-After），冷却期内不再打这个站点
                mark_cooldown(url, _retry_after(e.headers) or _COOLDOWN_DEFAULT)
                if attempt < retries:
                    wait = _retry_after(e.headers)
                    delay = min(wait if wait else 3.0 * (attempt + 1), 20.0)
                    logger.debug("被限流(429)，等 %.1fs 后重试 %s", delay, url)
                    time.sleep(delay + random.uniform(0, 0.6))
                    continue
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as e:
            last_exc = e
        if attempt < retries:
            time.sleep(backoff * (attempt + 1) + random.uniform(0, 0.4))
            logger.debug("重试 %s (%d/%d): %s", url, attempt + 1, retries, last_exc)

    if isinstance(last_exc, HttpError):
        raise last_exc
    raise OSError(f"请求失败 {url}: {last_exc}")


def get_text(url: str, **kw) -> str:
    _, text, _ = request(url, **kw)
    return text


def get_json(url: str, **kw) -> Any:
    _, text, _ = request(url, **kw)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"响应不是合法 JSON: {e}: {text[:200]}") from None


def download_bytes(url: str, *, proxy: Optional[str] = None, timeout: float = 30.0,
                   max_bytes: int = 12 * 1024 * 1024) -> bytes:
    """下载二进制内容（用于封面图缓存）。"""
    opener = _get_opener(proxy, None)
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA, "Accept": "image/*,*/*"})
    with opener.open(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


# --------------------------------------------------------------------------- #
# 连通性自检：用来判断「是不是该开代理」
# --------------------------------------------------------------------------- #
_probe_cache: dict[str, tuple[float, dict]] = {}
_probe_lock = threading.RLock()


def probe(url: str, *, proxy: Optional[str] = None, timeout: float = 6.0,
          ttl: float = 120.0, key: Optional[str] = None) -> dict:
    """
    探测某个地址在当前（或指定）代理下是否可达。结果带 TTL 缓存，避免每次都打网络。

    返回 {"ok": bool, "status": int, "elapsed": float, "error": str}
    """
    ck = key or f"{url}|{proxy or 'direct'}"
    now = time.time()
    with _probe_lock:
        hit = _probe_cache.get(ck)
        if hit and now - hit[0] < ttl:
            return hit[1]

    started = time.time()
    result: dict
    try:
        code, _, _ = request(url, proxy=proxy, timeout=timeout, retries=0,
                             headers={"Accept": "application/json"})
        result = {"ok": 200 <= code < 400, "status": code,
                  "elapsed": round(time.time() - started, 2), "error": ""}
    except HttpError as e:
        result = {"ok": False, "status": e.status,
                  "elapsed": round(time.time() - started, 2), "error": f"HTTP {e.status}"}
    except (OSError, TimeoutError, ssl.SSLError) as e:
        result = {"ok": False, "status": 0,
                  "elapsed": round(time.time() - started, 2), "error": str(e)[:160]}

    with _probe_lock:
        _probe_cache[ck] = (now, result)
    return result


def clear_probe_cache() -> None:
    with _probe_lock:
        _probe_cache.clear()
