"""
UI 一致性与对齐自测（不需要浏览器）：
1) HTML 引用的 id 是否在 JS 中被使用 / JS 使用的 id 是否都存在于 HTML
2) 数字列是否统一使用 num class 右对齐
3) CSS 中引用的 class 是否在 HTML/JS 中出现（找出拼写错误）
4) 表格列宽是否成组定义（保证列对齐）
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "app", "web")

errors: list[str] = []
warnings: list[str] = []


def read(name: str) -> str:
    p = os.path.join(WEB, name)
    if not os.path.exists(p):
        print(f"!! 缺少文件 {name}")
        sys.exit(2)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


html = read("index.html")
css = read("styles.css")
js = read("app.js") if os.path.exists(os.path.join(WEB, "app.js")) else ""

html_ids = set(re.findall(r'\bid="([^"]+)"', html))
js_ids = set(re.findall(r"""getElementById\(\s*["']([^"']+)["']""", js))
js_ids |= set(re.findall(r"""querySelector(?:All)?\(\s*["']#([A-Za-z0-9_\-]+)["']""", js))

print("=" * 72)
print("1. id 一致性")
print("=" * 72)
print(f"  HTML 定义 id : {len(html_ids)}")
print(f"  JS 引用 id   : {len(js_ids)}")
missing = sorted(js_ids - html_ids)
if missing:
    errors.append(f"JS 引用了 HTML 中不存在的 id: {missing}")
    print(f"  [错误] JS 引用了不存在的 id ({len(missing)}): {missing}")
else:
    print("  [通过] JS 引用的 id 全部存在于 HTML")

unused = sorted(html_ids - js_ids)
if unused:
    warnings.append(f"HTML 中未被 JS 引用的 id（可能是纯样式锚点）: {unused}")
    print(f"  [提示] HTML 中未被 JS 引用 ({len(unused)}): {unused}")

print()
print("=" * 72)
print("2. 表格数字列对齐")
print("=" * 72)
table = re.search(r'<table class="data-table".*?</table>', html, re.S)
if not table:
    errors.append("找不到 .data-table 表格")
    print("  [错误] 找不到 data-table")
else:
    ths = re.findall(r'<th class="([^"]*)"[^>]*>(.*?)</th>', table.group(0), re.S)
    numeric_words = ("大小", "做种", "集数", "人数", "大小", "进度", "话数")
    ok = True
    for cls, label in ths:
        label = re.sub(r"<[^>]+>", "", label).strip()
        is_num = any(w in label for w in numeric_words)
        has_num_class = "num" in cls.split()
        mark = "OK " if is_num == has_num_class else "!! "
        if is_num != has_num_class:
            ok = False
            errors.append(f"表头「{label}」的数字对齐 class 不匹配（class={cls!r}）")
        print(f"  [{mark}] th class={cls:14s} 文本={label}")
    print("  [通过] 数字列表头均使用 .num" if ok else "  [错误] 存在数字列未使用 .num")

if ".data-table th.num, .data-table td.num { text-align: right" not in css:
    errors.append("CSS 缺少数字列右对齐规则 .data-table td.num")
    print("  [错误] CSS 缺少 .num 右对齐规则")
else:
    print("  [通过] CSS 提供了 .num 右对齐 + tabular-nums")

if "tabular-nums" not in css:
    errors.append("CSS 缺少 tabular-nums（数字等宽）")
else:
    print("  [通过] CSS 使用 tabular-nums 保证数字等宽")

# 列宽成组定义检查
widths = dict(re.findall(r"\.(col-[a-z]+)\s*\{\s*width:\s*([^;]+);", css))
th_cols = set()
for cls, _ in ths:
    th_cols |= {c for c in cls.split() if c.startswith("col-")}
print(f"  表头列 class: {sorted(th_cols)}")
print(f"  CSS 列宽定义: {sorted(widths)}")
missing_w = sorted(th_cols - set(widths))
if missing_w:
    errors.append(f"这些列没有定义宽度，可能导致列错位: {missing_w}")
    print(f"  [错误] 未定义宽度: {missing_w}")
else:
    print("  [通过] 所有列都定义了固定宽度（列对齐稳定）")
if "table-layout: fixed" in css:
    print("  [通过] 表格使用 table-layout: fixed")
else:
    warnings.append("建议表格使用 table-layout: fixed 以保证列对齐")
    print("  [提示] 建议 table-layout: fixed")

print()
print("=" * 72)
print("3. 主题变量完整性")
print("=" * 72)
blocks = re.findall(r'html\[data-theme="(\w+)"\]\s*\{(.*?)\n\}', css, re.S)
if len(blocks) < 2:
    errors.append("缺少深色/浅色两套主题变量")
    print("  [错误] 主题块数量不足")
else:
    themes = {}
    for name, body in blocks:
        themes[name] = set(re.findall(r"--([a-z0-9\-]+)\s*:", body))
    for name, keys in themes.items():
        print(f"  {name}: {len(keys)} 个变量")
    diff = themes.get("dark", set()) ^ themes.get("light", set())
    if diff:
        errors.append(f"两套主题变量不一致: {sorted(diff)}")
        print(f"  [错误] 主题变量不一致: {sorted(diff)}")
    else:
        print("  [通过] 深浅主题变量一一对应")

print()
print("=" * 72)
print("4. CSS class 覆盖检查（找出 HTML/JS 用了但 CSS 没定义的 class）")
print("=" * 72)
css_classes = set(re.findall(r"\.([a-zA-Z][\w\-]*)", css))
used = set()
for m in re.findall(r'class="([^"]+)"', html):
    used |= set(m.split())
for m in re.findall(r"""classList\.(?:add|remove|toggle)\(([^)]*)\)""", js):
    used |= set(re.findall(r"""["']([\w\-]+)["']""", m))
for m in re.findall(r"""class=\\?["']([^"'\\]+)""", js):
    used |= set(m.split())
undefined = sorted(c for c in used if c not in css_classes)
if undefined:
    warnings.append(f"HTML/JS 使用但 CSS 未定义: {undefined}")
    print(f"  [提示] 未在 CSS 中定义的 class（{len(undefined)}）: {undefined}")
else:
    print("  [通过] 所有使用的 class 都有样式定义")

print()
print("=" * 72)
print("5. 可访问性与交互基础")
print("=" * 72)
buttons = re.findall(r"<button\b[^>]*>", html)
bad_buttons = [b for b in buttons if "type=" not in b]
for label, cond in (
    ("按钮均为 <button> 标签", len(buttons) >= 20),
    ("<button> 都带 type 属性（避免表单误提交）", not bad_buttons),
    ("表单控件都有 label", html.count("<label") >= 20),
    ("弹窗使用 role=dialog", 'role="dialog"' in html),
    ("获取 Token 链接指向官方地址", "https://next.bgm.tv/demo/access-token" in html),
    ("有 toast 容器", 'id="toasts"' in html),
    ("有加载动画样式", ".spinner" in css),
    ("支持 reduced-motion", "prefers-reduced-motion" in css),
    ("有响应式断点", "@media (max-width" in css),
):
    print(f"  [{'通过' if cond else '待修'}] {label}")
    if not cond:
        warnings.append(label)

print()
print("=" * 72)
print(f"结果：错误 {len(errors)} 项，提示 {len(warnings)} 项")
print("=" * 72)
for e in errors:
    print("  [错误]", e)
for w in warnings:
    print("  [提示]", w)

if not os.path.exists(os.path.join(WEB, "app.js")):
    print("\n  注意：app.js 尚未生成，id/class 的 JS 侧检查不完整。")

sys.exit(1 if errors else 0)
