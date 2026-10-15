"""
从 dandanplay 自带的 OpenCC 字典生成简繁对照数据文件：
  app/data/t2s.tsv    每行「繁体<TAB>简体」
优先取系统上已存在的权威字典，失败时保留库里手写的小表作为兜底。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    r"D:\software\dandanplay-x64\Dictionary\TSCharacters.txt",
    r"C:\Program Files\dandanplay\Dictionary\TSCharacters.txt",
    os.path.join(ROOT, "_probe", "TSCharacters.txt"),
]
OUT_DIR = os.path.join(ROOT, "app", "data")
OUT = os.path.join(OUT_DIR, "t2s.tsv")

sys.path.insert(0, ROOT)


def is_han(ch: str) -> bool:
    o = ord(ch)
    return 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FA1F


src = next((p for p in CANDIDATES if os.path.exists(p)), None)
if not src:
    print("!! 找不到 TSCharacters.txt，跳过后备表以外的生成（内置手写表仍然可用）")
    raise SystemExit(0)

pairs: dict[str, str] = {}
skipped = 0
with open(src, encoding="utf-8", errors="replace") as f:
    for line in f:
        line = line.rstrip("\n").rstrip("\r")
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        trad, choices = parts[0].strip(), parts[1].strip()
        if not trad or not choices:
            continue
        simp = choices.split(" ")[0].strip()          # 多候选取第一个
        if not simp or trad == simp:
            skipped += 1
            continue
        # 只保留单字对单字（避免把一个繁体字映射成词组导致替换错位）
        if len(trad) != 1 or len(simp) != 1:
            skipped += 1
            continue
        if not (is_han(trad) and is_han(simp)):
            skipped += 1
            continue
        pairs[trad] = simp

os.makedirs(OUT_DIR, exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    f.write("# 简繁对照表：每行「繁体<TAB>简体」，来源 OpenCC 标准字典（dandanplay 随附副本）\n")
    for trad in sorted(pairs):
        f.write(f"{trad}\t{pairs[trad]}\n")

print(f"来源: {src}")
print(f"生成: {OUT}")
print(f"条目: {len(pairs)}（跳过 {skipped}）")

# 立刻用它验证关键用例
tbl = pairs
cases = {
    "說話語讀": "说话语读", "葬送的芙莉蓮": "葬送的芙莉莲", "間諜家家酒": "间谍家家酒",
    "賽博朋克：邊緣行者 2": "赛博朋克：边缘行者 2", "天月動漫&發佈組": "天月动漫&发布组",
    "從零開始的異世界生活": "从零开始的异世界生活", "進擊的巨人": "进击的巨人",
    "為美好的世界獻上祝福": "为美好的世界献上祝福", "藥屋少女的呢喃": "药屋少女的呢喃",
    "這個問題": "这个问题", "颳風": "刮风", "隻身": "只身",
}
bad = 0
for trad, want in cases.items():
    got = "".join(tbl.get(c, c) for c in trad)
    ok = got == want
    bad += 0 if ok else 1
    print(f"  [{'OK ' if ok else 'FAIL'}] {trad} -> {got}" + ("" if ok else f"   期望 {want}"))
print(f"失败 {bad}/{len(cases)}")
