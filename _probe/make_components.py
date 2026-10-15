"""生成组件布局快照页：用真实 CSS + 与 index.html 一致的表格/卡片结构，验证对齐。"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "app", "web")
OUT = os.path.join(ROOT, "_probe", "ui_components.html")

html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
m = re.search(r'<div class="table-wrap">.*?</div>\s*</div>', html, re.S)
table_block = m.group(0) if m else ""

rows = [
    ("动漫花园", "桜都字幕组", "[桜都字幕组] / Spy x Family (2025) [13][1080p][简体内嵌]间谍过家家第三季", "简体", "chs", "1080p", "13", "384.2 MB", "1,204", "2026/08/28"),
    ("爱恋动漫", "爱恋字幕社", "[爱恋字幕社] 间谍过家家 第三季 - 12 [1080p][繁日內嵌]", "繁体", "cht", "1080p", "12", "515.1 MB", "86", "2026/08/21"),
    ("Nyaa", "SubsPlease", "[SubsPlease] Spy x Family S03E13 (1080p) [A1B2C3D4].mkv", "未标注", "none", "1080p", "13", "1.4 GiB", "711", "2026/08/28"),
    ("动漫花园", "沸班亚马制作组", "[沸班亚马制作组] 间谍过家家 第三季 [01-13Fin][1080p][简繁内封]", "简繁", "both", "1080p", "13", "5.8 GB", "42", "2026/08/30"),
    ("动漫花园", "云光字幕组", "[云光字幕组] 间谍过家家 第三季 - 11 [1080p][简日双语]", "简繁", "both", "1080p", "11", "498.0 MB", "9", "2026/08/14"),
    ("Nyaa", "Erai-raws", "[Erai-raws] Spy x Family - 13 [1080p][MultiSub]", "简繁", "both", "1080p", "13", "864.6 MiB", "284", "2026/08/28"),
]

tbody = "\n".join(
    f"""<tr class="res-row{f' is-selected' if i == 0 else ''}">
      <td class="col-src">{s}</td>
      <td class="col-group" title="{g}">{g}</td>
      <td class="col-title"><span class="ellipsis" title="{t}">{t}</span></td>
      <td class="col-lang"><span class="lang-pill lang-{lc}">{lang}</span></td>
      <td class="col-res">{r}</td>
      <td class="col-ep num">{e}</td>
      <td class="col-size num">{z}</td>
      <td class="col-seed num">{sd}</td>
      <td class="col-time">{d}</td>
      <td class="col-act act-cell"><span class="cell-actions">
        <button type="button" class="btn btn-sm btn-primary">下载</button>
        <button type="button" class="btn btn-sm">复制磁力</button></span></td>
    </tr>"""
    for i, (s, g, t, lang, lc, r, e, z, sd, d) in enumerate(rows)
)

groups = "\n".join(
    f"""<div class="group-card{' is-selected' if i == 0 else ''}">
      <div class="group-head"><span class="group-name">{g}</span><span class="badge badge-accent">n={n}</span></div>
      <div class="group-meta">{' '.join(f'<span class="tag">{s}</span>' for s in srcs)}
        {'<span class="tag">team_id: 619</span>' if tid else ''}</div>
      <button type="button" class="btn btn-sm">只从此字幕组下载</button>
    </div>"""
    for i, (g, n, srcs, tid) in enumerate([
        ("桜都字幕组", 42, ["动漫花园", "爱恋动漫"], True),
        ("沸班亚马制作组", 21, ["动漫花园", "爱恋动漫"], True),
        ("云光字幕组", 14, ["动漫花园"], True),
        ("SubsPlease", 22, ["Nyaa"], False),
        ("爱恋&猫恋汉化组", 12, ["爱恋动漫"], False),
        ("ToonsHub", 12, ["Nyaa"], False),
    ])
)

cards = "\n".join(
    f"""<div class="card{' is-subscribed' if i == 1 else ''}">
      <div class="card-cover"><span class="card-cover-fallback">番</span>
        <label class="card-check"><input type="checkbox"{' checked' if i == 0 else ''}></label>
        {'<div class="card-badges"><span class="badge badge-ok">已订阅</span></div>' if i == 1 else ''}
      </div>
      <div class="card-body">
        <div class="card-title">{t}</div>
        <div class="card-sub">{j}</div>
        <div class="card-meta"><span class="tag">全 {e} 话</span><span class="tag">{d}</span><span class="num">7.{s}</span></div>
      </div>
    </div>"""
    for i, (t, j, e, d, s) in enumerate([
        ("间谍过家家 第三季", "SPY×FAMILY Season 3", 13, "2025-10-04", 3),
        ("药屋少女的呢喃 第三季", "薬屋のひとりごと 第3期", 12, "2025-10-22", 8),
        ("僵尸搜寻中", "#ゾンビさがしてます", 12, "2026-10-03", 6),
        ("赛博朋克：边缘行者 2", "Cyberpunk: Edgerunners 2", 10, "2026-10-20", 9),
    ])
)

def extract_balanced(html_text: str, start_marker: str, open_tag: str = "<div") -> str:
    """
    从 start_marker 处开始，按 <div> 嵌套计数提取完整片段。
    之前用非贪婪正则会在第一个 </div> 处截断，导致量测到的是残缺表单。
    """
    i = html_text.index(start_marker)
    depth = 0
    pos = i
    tag = open_tag[1:]                     # 'div'
    while pos < len(html_text):
        nxt_open = html_text.find(f"<{tag}", pos)
        nxt_close = html_text.find(f"</{tag}>", pos)
        if nxt_close == -1:
            break
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            pos = nxt_open + len(tag) + 1
        else:
            depth -= 1
            pos = nxt_close + len(tag) + 3
            if depth == 0:
                return html_text[i:pos]
    return html_text[i:]


# 从 index.html 抽取真实的「订阅设置」标签页（含新的下拉与预览结构）
sub_tab = extract_balanced(html, '<div class="tab-body" id="tab-sub"')
sub_tab = sub_tab.replace(' hidden>', '>', 1)
assert 'id="s-folder"' in sub_tab, f"订阅页片段缺少 s-folder，长度 {len(sub_tab)}"
assert 'id="btn-sub-add"' in sub_tab, "订阅页片段缺少 btn-sub-add"
assert 'id="s-preview"' in sub_tab, "订阅页片段缺少 s-preview"
# 填入示例选项，模拟 app.js 生成后的状态
sub_tab = sub_tab.replace(
    '<option value="">不限字幕组（任意组）</option>',
    '<option value="">不限字幕组（任意组）</option>\n            '
    '<option value="桜都字幕组" selected>桜都字幕组（42 条 · 动漫花园 / 爱恋动漫）</option>\n            '
    '<option value="SubsPlease">SubsPlease（22 条 · Nyaa）</option>')
sub_tab = sub_tab.replace(
    '<option value="">不下载（仅订阅，之后自动追新）</option>',
    '<option value="">不下载（仅订阅，之后自动追新）</option>\n            '
    '<option value="k13" selected>第 13 集 · 桜都字幕组 · 1080p · 384.2 MB</option>\n            '
    '<option value="k12">第 12 集 · 桜都字幕组 · 1080p · 515.1 MB</option>\n            '
    '<option value="k11">第 11 集 · 云光字幕组 · 1080p · 498.0 MB</option>')
sub_tab = sub_tab.replace(
    '<div class="sub-preview" id="s-preview"></div>',
    '<div class="sub-preview" id="s-preview">将订阅：<b>间谍过家家 第三季</b>'
    '<span>字幕组 <b>桜都字幕组</b></span><span>1080p</span>'
    '<span>立即下载 <b>第 13 集</b></span>'
    '<span class="ellipsis">目录 <b>D:\\Anime\\间谍过家家 第三季</b></span></div>')
sub_tab = sub_tab.replace('<div id="sub-history"></div>', '')

# 从 index.html 抽取真实的设置页（新的 form-grid 结构）
config_view = re.search(r'<section class="view" id="view-config".*?</section>', html, re.S).group(0)
config_view = config_view.replace(' hidden>', '>', 1) if ' hidden>' in config_view else config_view

# 抽取工具栏，并模拟「已勾选 3 部」的状态以展示批量操作按钮
toolbar = re.search(r'<div class="toolbar" id="anime-toolbar">.*?\n      </div>', html, re.S).group(0)
toolbar = toolbar.replace('<input type="checkbox" id="check-all">',
                          '<input type="checkbox" id="check-all" checked>')
toolbar = toolbar.replace('<div class="batch-actions" id="batch-actions" hidden>',
                          '<div class="batch-actions" id="batch-actions">')
toolbar = toolbar.replace('>已选 0 部<', '>已选 3 部<')

page = f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<title>组件布局快照</title>
<link rel="stylesheet" href="../app/web/styles.css">
<style>
  body {{ padding: 20px 40px; }}
  h3 {{ font-size: 14px; margin: 26px 0 10px; color: var(--text-2); font-weight: 600; }}
  .data-table tbody td {{ height: 40px; }}
  .sub-item {{ margin-bottom: 12px; }}
  .sub-progress {{ width: 320px; }}
  .snap {{ border: 1px solid var(--border); border-radius: var(--r-lg); padding: 16px 20px; background: var(--surface); }}
</style>
</head>
<body>
<h3>1. 工具栏（勾选后出现批量操作，让「全选」有实际用途）</h3>
{toolbar}

<h3>2. 资源表格（列对齐 / 数字右对齐 / 标题省略号）</h3>
{table_block.replace('<tbody id="res-body"></tbody>', '<tbody id="res-body">' + tbody + '</tbody>')}

<h3>3. 番剧卡片（等高 / 标题两行 / 复选框）</h3>
<div class="grid">{cards}</div>

<h3>4. 弹窗「订阅设置」标签页（新结构：字幕组下拉 + 集数下拉 + 预览）</h3>
<div class="snap">{sub_tab}</div>

<h3>5. 设置页（统一后的 form-grid 结构）</h3>
{config_view}

<h3>6. 字幕组卡片</h3>
<div class="group-list">{groups}</div>

<h3>7. 订阅条目（封面 / 事实行 / 进度 / 操作）</h3>
<div class="sub-list">
  <div class="sub-item">
    <img class="sub-cover" alt="" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='62' height='84'%3E%3Crect width='62' height='84' fill='%23222'/%3E%3C/svg%3E">
    <div class="sub-item-body">
      <div class="sub-item-title">间谍过家家 第三季</div>
      <div class="sub-meta">
        <span class="sub-fact">字幕组 <b>桜都字幕组</b></span>
        <span class="sub-fact">分辨率 <b>1080p</b></span>
        <span class="sub-fact">已下载 <b>13</b> 集</span>
        <span class="sub-fact">上次检查 <b>2026-10-04 16:20</b></span>
        <span class="badge badge-ok">新增 2 集</span>
      </div>
      <div class="sub-progress"><i style="width:100%"></i></div>
      <div class="sub-path">D:\\Anime\\间谍过家家 第三季</div>
    </div>
    <div class="sub-item-actions">
      <button type="button" class="btn btn-sm btn-primary">补下载单集</button>
      <button type="button" class="btn btn-sm">立即检查</button>
      <button type="button" class="btn btn-sm">打开目录</button>
      <button type="button" class="btn btn-sm btn-danger">删除订阅</button>
    </div>
  </div>
</div>
</body>
</html>
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(page)
print("已生成", OUT)
print(f"  订阅 tab 片段 {len(sub_tab)} 字符；设置页片段 {len(config_view)} 字符")
