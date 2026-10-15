"""
统一设置页表单结构：把 .grid-form/.field 改成 .form-grid/.form-cell（与弹窗订阅页一致），
并给按钮所在格加 .form-cell-btn，给「标签」这类空 label 换成占位 span。
只改设置页区域（#view-config 内），不动顶部 Token 面板。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "app", "web", "index.html")
src = open(P, encoding="utf-8").read()
orig = src

start = src.index('<section class="view" id="view-config"')
end = src.index("</section>", src.index('<div class="save-bar"'))
block = src[start:end]

before = block
block = block.replace('class="grid-form"', 'class="form-grid"')
block = block.replace('class="field span2"', 'class="form-cell span-2"')
block = block.replace('class="field"', 'class="form-cell"')
# 空 label（&nbsp;）换成语义占位，保证和真实 label 同高对齐
block = block.replace('<label>&nbsp;</label>', '<span class="label-ghost" aria-hidden="true"></span>')
# 只放按钮的格子加标记，方便 CSS 让按钮与输入框同高对齐
block = re.sub(
    r'<div class="form-cell"><span class="label-ghost"[^>]*></span>(<button[^>]*>)',
    r'<div class="form-cell form-cell-btn"><span class="label-ghost" aria-hidden="true"></span>\1',
    block,
)

src = src[:start] + block + src[end:]
assert src != orig
open(P, "w", encoding="utf-8").write(src)

print("已更新", P)
print("form-grid:", src.count('class="form-grid"'))
print("form-cell:", src.count('class="form-cell"'))
print("form-cell-btn:", src.count('form-cell-btn'))
print("残留 grid-form:", src.count('grid-form'), "| 残留 field span2:", src.count('field span2'))
print("残留裸 field:", len(re.findall(r'class="field"', src)))
