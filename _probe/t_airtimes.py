"""构建/校验更新时刻缓存（data/airtimes.json），并打印几部番的北京时间。”

用测试脚本跑，避免命令行里嵌套引号。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.core import airtimes  # noqa: E402

print("构建更新时刻缓存（下载 bangumi-data，约 20 秒）…")
ok = airtimes.refresh(force=True)
st = airtimes.status()
print(f"刷新结果={ok} 条数={st['count']} 更新于={st['updated_text']} 错误={st['error'] or '无'}")
p = os.path.join(ROOT, "data", "airtimes.json")
if os.path.exists(p):
    print(f"缓存文件 {p}：{os.path.getsize(p) / 1048576:.2f} MB，过期={st['stale']}")

print("\n几部番的下次更新（北京时间）：")
# 期望值来自 2026-10-10 的实测（bangumi-data 的 begin 周期换算）
EXPECT = {
    568244: ("药屋少女的呢喃 第三季", "22:00 周五"),
    630160: ("黑暗召唤师在地下恋爱中", "00:20 周一"),
    412008: ("转生就是剑 第二季", "23:00 周三"),
}
bad = 0
for sid, (name, want) in EXPECT.items():
    info = airtimes.for_subject(sid)
    if not info:
        print(f"  {name}: 没有数据 ✗")
        bad += 1
        continue
    got = info["next_text"]
    okk = want.split()[0] in got and want.split()[1] in got
    if not okk:
        bad += 1
    print(f"  {'OK ' if okk else '✗  '}{name}: 下次 {got}（期望含 {want}）"
          f" | 日本时间 {info['jst_text'].split['·'][0] if False else info['jst_text']}")
    print(f"      悬浮说明：{airtimes.attach(sid, 'TOKYO MX')['tip'].replace(chr(10), ' ｜ ')}")

print(f"\n{'全部符合预期' if bad == 0 else f'{bad} 部不符合预期'}")
sys.exit(1 if bad else 0)
