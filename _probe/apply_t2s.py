"""把 util.py 里的简繁转换区块替换为新的显式映射实现。"""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "core", "util.py")
NEW = os.path.join(ROOT, "_probe", "t2s_new.py")

src = open(TARGET, encoding="utf-8").read()
new_block = open(NEW, encoding="utf-8").read()

start_marker = "# --------------------------------------------------------------------------- #\n# 中文简繁转换"
end_marker = "def normalize_title("

start = src.index(start_marker)
end = src.index(end_marker)
print(f"替换区间: {start}..{end}（{end - start} 字符）")

shutil.copy(TARGET, TARGET + ".bak")
open(TARGET, "w", encoding="utf-8").write(src[:start] + new_block + src[end:])
print("已替换，备份在 util.py.bak")

# 立刻验证
import sys
sys.path.insert(0, ROOT)
from app.core import util   # noqa: E402

cases = {
    "說話語讀": "说话语读",
    "葬送的芙莉蓮": "葬送的芙莉莲",
    "間諜家家酒": "间谍家家酒",
    "賽博朋克：邊緣行者 2": "赛博朋克：边缘行者 2",
    "天月動漫&發佈組": "天月动漫&发布组",
    "藥屋少女的呢喃": "药屋少女的呢喃",
    "從零開始的異世界生活": "从零开始的异世界生活",
    "薇爾莉特": "薇尔莉特",
    "進擊的巨人": "进击的巨人",
    "為美好的世界獻上祝福": "为美好的世界献上祝福",
}
bad = []
for trad, want in cases.items():
    got = util.to_simplified(trad)
    ok = got == want
    if not ok:
        bad.append((trad, want, got))
    print(f"  [{'OK ' if ok else 'FAIL'}] {trad} -> {got}")

print(f"\n映射条数 {len(util._T2S)}，失败 {len(bad)}")
print("反向验证：", util.to_traditional("间谍过家家 第三季"), "|", util.to_traditional("发布组"))
