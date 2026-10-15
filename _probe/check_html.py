"""HTML/CSS 结构健康检查：标签配平、id 唯一、新元素齐备、CSS 花括号配平、class 覆盖。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "app", "web")
html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
css = open(os.path.join(WEB, "styles.css"), encoding="utf-8").read()
js_path = os.path.join(WEB, "app.js")
js = open(js_path, encoding="utf-8").read() if os.path.exists(js_path) else ""

errors, warns = [], []
print("=" * 74)
print("1. HTML 标签配平")
print("=" * 74)
for tag in ("div", "section", "span", "button", "label", "select", "option",
            "table", "thead", "tbody", "tr", "td", "th", "p", "pre", "a"):
    o = len(re.findall(r"<%s[\s>]" % tag, html))
    c = len(re.findall(r"</%s>" % tag, html))
    ok = o == c
    if not ok and tag not in ("option", "td", "th", "tr", "p", "a"):
        errors.append(f"<{tag}> 标签不配平 open={o} close={c}")
    print(f"  [{'OK ' if ok else '!! '}] {tag:8s} open={o:3d} close={c:3d}")

print()
print("=" * 74)
print("2. id 唯一性与新元素")
print("=" * 74)
ids = re.findall(r'id="([^"]+)"', html)
dups = sorted({i for i in ids if ids.count(i) > 1})
if dups:
    errors.append(f"重复 id: {dups}")
print(f"  id 总数 {len(ids)}，重复 {dups if dups else '无'}")
need = ["s-episode", "s-episode-tip", "s-preview", "btn-goto-res", "batch-actions",
        "btn-batch-sub", "btn-batch-fetch", "btn-clear-selection", "s-group-tip"]
missing = [x for x in need if x not in ids]
if missing:
    errors.append(f"缺少新元素: {missing}")
print(f"  新增元素齐备: {'是' if not missing else missing}")
print(f"  btn-sub-only 已移除: {'是' if 'btn-sub-only' not in html else '否！！'}")
if "btn-sub-only" in html:
    errors.append("遗留 btn-sub-only")
if "btn-sub-only" in js:
    warns.append("app.js 仍引用 #btn-sub-only（需前端移除绑定）")
    print("  !! app.js 仍引用 #btn-sub-only")
print(f"  #s-group 是 select: {'是' if re.search(r'<select id=\"s-group\"', html) else '否！！'}")
print(f"  #s-episode 是 select: {'是' if re.search(r'<select id=\"s-episode\"', html) else '否！！'}")

print()
print("=" * 74)
print("3. CSS 配平与主题变量")
print("=" * 74)
o, c = css.count("{"), css.count("}")
print(f"  花括号 {o}/{c} {'配平' if o == c else '不配平！！'}")
if o != c:
    errors.append("CSS 花括号不配平")
themes = re.findall(r'html\[data-theme="(\w+)"\]\s*\{(.*?)\n\}', css, re.S)
if len(themes) < 2:
    errors.append("主题变量块不足")
for name, body in themes:
    print(f"  {name}: {len(re.findall(r'--[a-z0-9-]+:', body))} 个变量")
for cls in (".form-grid", ".form-cell", ".field-tip", ".sub-preview",
            ".batch-actions", ".section-hint", ".label-ghost", ".sub-actions"):
    ok = cls in css
    if not ok:
        errors.append(f"CSS 缺少 {cls}")
    print(f"  [{'OK ' if ok else '!! '}] {cls}")

print()
print("=" * 74)
print("4. form-grid 结构一致性（设置页 6 处 + 弹窗 1 处）")
print("=" * 74)
print(f"  .form-grid 出现 {html.count('class=\"form-grid\"')} 次")
print(f"  .form-cell 出现 {html.count('class=\"form-cell')} 次")
print(f"  残留 .grid-form: {html.count('grid-form')}（应为 0）")
if html.count("grid-form"):
    errors.append("设置页仍有旧 grid-form")
print(f"  残留 class=\"field\": {len(re.findall(chr(99)+'lass=\"field\"', html))}（应为 0）")
cells_with_btn = html.count("form-cell-btn")
print(f"  form-cell-btn: {cells_with_btn}")

print()
print("=" * 74)
print(f"结果：错误 {len(errors)}，提示 {len(warns)}")
print("=" * 74)
for e in errors:
    print("  [错误]", e)
for w in warns:
    print("  [提示]", w)
sys.exit(1 if errors else 0)
