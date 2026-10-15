"""审计简繁转换表：找出错位/反向的成对条目并打印修正后的表。"""
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core import util   # noqa: E402

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "app", "core", "util.py"), encoding="utf-8").read()
block = re.search(r"_PAIRS = \((.*?)\n\)\n", src, re.S).group(1)
pairs_str = "".join(re.findall(r'"([^"]*)"', block))
print(f"原始字符数 {len(pairs_str)}，偶数={len(pairs_str) % 2 == 0}")

# 检查每一对：繁 -> 简 方向是否正确（用 unicodedata 名称粗判 + 已知简繁表对照）
problems = []
seen = {}
for i in range(0, len(pairs_str) - 1, 2):
    a, b = pairs_str[i], pairs_str[i + 1]
    if a == b:
        problems.append((i, a, b, "两字相同（占用一个槽位导致后续错位）"))
        continue
    ma = unicodedata.name(a, "")
    mb = unicodedata.name(b, "")
    if "CJK" not in ma or "CJK" not in mb:
        problems.append((i, a, b, f"非汉字 {ma} / {mb}"))
    if a in seen:
        problems.append((i, a, b, f"重复出现（首次在 {seen[a]}）"))
    seen[a] = i

print(f"\n可疑条目 {len(problems)} 个：")
for i, a, b, why in problems:
    print(f"  [{i:>4}] {a}({unicodedata.name(a, '?')}) -> {b} : {why}")

# 用常见繁简对照做反向校验
KNOWN = {
    "話": "话", "說": "说", "語": "语", "讀": "读", "電": "电", "視": "视", "車": "车",
    "馬": "马", "鳥": "鸟", "龍": "龙", "國": "国", "學": "学", "會": "会", "這": "这",
    "們": "们", "來": "来", "時": "时", "對": "对", "後": "后", "點": "点", "實": "实",
    "樣": "样", "麼": "么", "種": "种", "義": "义", "聲": "声", "體": "体", "戰": "战",
}
print("\n已知字的转换结果：")
bad = []
for t, s in KNOWN.items():
    got = util.to_simplified(t)
    if got != s:
        bad.append((t, s, got))
print(f"  错误 {len(bad)} / {len(KNOWN)}")
for t, s, got in bad:
    print(f"    {t} 应为 {s}，实际 {got}")
