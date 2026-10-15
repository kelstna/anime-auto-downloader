"""检查罗马字生成与「像罗马音」判断（离线，便于快速迭代）。"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.sources.romaji import looks_like_romaji, romanize, romaji_variants  # noqa: E402

print("=== 生成罗马字 ===")
for t in ["#ゾンビさがしてます", "ゾンビさがしてます", "ブラッククローバー 2nd Season",
          "スパイファミリー", "薬屋のひとりごと 第3期", "FX戦士くるみちゃん",
          "STEEL BALL RUN ジョジョの奇妙な冒険 2nd & 3rd STAGE"]:
    print(f"  {t!r:46} -> {romanize(t)!r:32} {romaji_variants(t)[:2]}")

print()
print("=== 「像罗马音」判断（True = 当作罗马字优先用） ===")
for t in ["Kusuriya no Hitorigoto 3rd Season", "Seitokai ni mo Ana wa Aru", "NamaAnaru",
          "There is also a hole in the student organization!",
          "Even the Student Council Has Its Holes!", "The Apothecary Diaries Season 3",
          "Black Clover Season 2", "FX Senshi Kurumi-chan", "Yasei no Last Boss ga Arawareta!",
          "STEEL BALL RUN JoJo's Bizarre Adventure 2nd & 3rd STAGE", "SPY×FAMILY",
          "Burakkukuroba 2nd Season", "Zombie Sagashitemasu"]:
    print(f"  {t!r:54} -> {looks_like_romaji(t)}")
