"""检查生成的快照页是否包含完整的订阅 tab 结构。"""
import re

s = open("_probe/ui_components.html", encoding="utf-8").read()
h = open("app/web/index.html", encoding="utf-8").read()

i = s.find('id="tab-sub"')
j = s.find('id="tab-group"')
print(f"tab-sub 起始 {i}，tab-group 起始 {j}")
if i >= 0 and j > i:
    print("  tab-group 出现在 tab-sub 之后 -> 说明 tab-sub 片段被截断了")
seg = s[i - 60: i + 200] if i >= 0 else "(未找到)"
print("--- 片段开头 ---")
print(seg)

print("\n原 index.html 里 tab-sub 到 tab-group 的顺序:")
print("  tab-sub @", h.find('id="tab-sub"'), " tab-group @", h.find('id="tab-group"'))

for key in ("s-folder", "s-preview", "btn-sub-add", "sub-history", "s-episode"):
    print(f"  快照含 {key}: {('id=\"%s\"' % key) in s}")

print("\ns-episode 选项数:", len(re.findall(r'<option value="k1', s)))
print("s-group 填充选项数:", len(re.findall(r'字幕组（', s)))
print("按钮数量:", len(re.findall(r'<button', s)))
