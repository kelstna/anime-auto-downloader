"""用 index.html 的真实 body 结构 + mock 数据生成 UI 测试页。"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "app", "web", "index.html")
TPL = os.path.join(ROOT, "_probe", "ui_fixture_template.html")
OUT = os.path.join(ROOT, "_probe", "ui_fixture.html")

html = open(INDEX, encoding="utf-8").read()
tpl = open(TPL, encoding="utf-8").read()

# 取 <body> 内容，去掉原有 script 引用（模板自己会用正确的相对路径加载 ui.js / app.js）
body = re.search(r"<body>(.*)</body>", html, re.S).group(1)
body = re.sub(r'<script src="(?:ui|app)\.js[^"]*"></script>', "", body)
# 模板里已内联主题占位脚本，去掉正文里的那份避免重复执行
body = re.sub(r"<!-- 主题先用内联脚本抢占.*?</script>", "", body, flags=re.S)
# 静态文件服务器不认识 ?v=__APP_VERSION__，模板用无查询串的相对路径
body = body.replace('href="styles.css?v=__APP_VERSION__"', 'href="../app/web/styles.css"')
body = body.replace('href="styles.css"', 'href="../app/web/styles.css"')

# 自检：不能残留会让静态服务器 404 的引用
for bad in ('src="ui.js', 'src="app.js', '__APP_VERSION__'):
    assert bad not in body, f"fixture 仍残留 {bad}（会导致 404 或占位符泄漏）"

out = tpl.replace("__BODY__", body)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(out)

print(f"已生成 {OUT}")
print(f"  body 长度 {len(body)}，包含 {body.count('id=')} 个 id")
for need in ("anime-grid", "res-body", "group-list", "sub-list", "modal", "token-input"):
    print(f"  {'OK ' if f'id=\"{need}\"' in body else 'MISS'} {need}")
print(f"  ui.js 由模板引入: {'OK' if 'src=\"../app/web/ui.js\"' in out else 'MISS'}")
print(f"  app.js 由模板引入: {'OK' if 'src=\"../app/web/app.js\"' in out else 'MISS'}")
