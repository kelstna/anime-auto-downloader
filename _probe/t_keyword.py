"""手动搜索（自定义关键词）+ 订阅记住关键词的接口级测试（隔离数据目录，不动生产数据）。

用法：python _probe\\t_keyword.py
会真实联网搜索（走 data/config.json 里的代理设置），只写临时 data 目录。
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 必须在 import app.* 之前设置：config.DATA_DIR 在导入时确定
TMP = tempfile.mkdtemp(prefix="anime-kw-")
os.environ["ANIME_DATA_DIR"] = TMP
shutil.copyfile(os.path.join(ROOT, "data", "config.json"), os.path.join(TMP, "config.json"))

from app.web import server  # noqa: E402

PASS, FAIL = [], []
PORT = 7863


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


def post(path, body, timeout=180):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, timeout=60):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


httpd = server.serve_forever("127.0.0.1", PORT)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
time.sleep(0.4)

SUBJECT = 622288          # FX战士久留美
KEYWORD = "FX战士久留美"
try:
    print("=" * 74)
    print("1. 手动搜索：只按用户给的词搜")
    print("=" * 74)
    t0 = time.time()
    d1 = post("/api/search", {"subject_id": SUBJECT, "keyword": KEYWORD})
    print(f"    首次用时 {time.time() - t0:.1f}s，命中 {d1.get('total')} 条")
    check("带 keyword 能搜到资源", d1.get("total", 0) > 0, str(d1.get("total")))
    check("回显 search_keyword", d1.get("search_keyword") == KEYWORD, repr(d1.get("search_keyword")))
    check("策略文案写明是手动关键词", "手动关键词" in (d1.get("strategy") or ""), d1.get("strategy"))
    used = d1.get("keywords_used") or {}
    flat = [w for ws in used.values() for w in ws]
    check("各站点只用了这一个关键词",
          bool(flat) and all(KEYWORD in w for w in flat), str(used))
    langs = {it.get("lang") for it in d1.get("items", [])}
    check("结果里带语言识别（不是全空）", any(langs), str(langs))

    print()
    print("=" * 74)
    print("2. 手动搜索的缓存口径独立（不与自动搜索串味）")
    print("=" * 74)
    d2 = post("/api/search", {"subject_id": SUBJECT, "keyword": KEYWORD})
    check("同一关键词第二次走缓存", d2.get("cached") is True, f"cached={d2.get('cached')}")
    check("缓存返回结果一致", d2.get("total") == d1.get("total"))
    d3 = post("/api/search", {"subject_id": SUBJECT, "keyword": "FX 戰士久留美"})
    check("换个关键词不会命中上一个词的缓存", d3.get("cached") is False, f"cached={d3.get('cached')}")
    d4 = post("/api/search", {"subject_id": SUBJECT})
    check("不带关键词的自动搜索是另一份缓存", d4.get("cached") is False, f"cached={d4.get('cached')}")
    check("自动搜索不带 search_keyword", not d4.get("search_keyword"), repr(d4.get("search_keyword")))

    print()
    print("=" * 74)
    print("3. 订阅保存自定义搜索词（自动追新也用它）")
    print("=" * 74)
    r1 = post("/api/subscriptions", {"subject_id": SUBJECT, "group": "绿茶字幕组",
                                     "custom_keyword": KEYWORD, "initial_mode": "latest"})
    sub = r1.get("subscription") or {}
    check("订阅接口回显 custom_keyword", sub.get("custom_keyword") == KEYWORD, repr(sub.get("custom_keyword")))
    items = get("/api/subscriptions").get("items") or []
    got = next((s for s in items if int(s.get("subject_id")) == SUBJECT), {})
    check("订阅列表里存下来了", got.get("custom_keyword") == KEYWORD, repr(got.get("custom_keyword")))

    r2 = post("/api/subscriptions", {"subject_id": SUBJECT, "group": "绿茶字幕组"})
    check("请求里不带该字段时保留原值",
          (r2.get("subscription") or {}).get("custom_keyword") == KEYWORD,
          repr((r2.get("subscription") or {}).get("custom_keyword")))
    r3 = post("/api/subscriptions", {"subject_id": SUBJECT, "group": "绿茶字幕组", "custom_keyword": ""})
    check("显式传空字符串可以清掉",
          (r3.get("subscription") or {}).get("custom_keyword") == "", repr((r3.get("subscription") or {}).get("custom_keyword")))

    print()
    print("=" * 74)
    print("4. watcher 用订阅里的关键词搜索")
    print("=" * 74)
    from app.core import subs, watcher  # noqa: E402
    s = subs.get(SUBJECT)
    s.custom_keyword = KEYWORD
    seen = {}
    real = watcher.engine.search_by_subject

    def spy(subject, **kw):
        seen.update(kw)
        return real(subject, **kw)

    watcher.engine.search_by_subject = spy
    try:
        out = watcher.search_for(s)
    finally:
        watcher.engine.search_by_subject = real
    check("自动追新把 custom_keyword 传给了 engine", seen.get("keyword") == KEYWORD, str(seen))
    check("追新搜索有结果", bool(out.resources), str(len(out.resources)))
    check("策略也标了手动关键词", "手动关键词" in (out.strategy or ""), out.strategy)
finally:
    httpd.shutdown()

print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if FAIL else 0)
