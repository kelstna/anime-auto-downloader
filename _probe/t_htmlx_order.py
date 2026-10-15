"""htmlx 文本顺序回归：内联标签（动漫花园的 <span class="keyword"> 高亮）不能把文字挪到末尾。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.core import htmlx  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


# 动漫花园真实写法：关键词被 <span class="keyword"> 包住，位置在标题中间
DMHY = ('<td class="title"><span class="tag"><a href="/topics/list/team_id/816">ANi</a></span>'
        '<a href="/topics/view/728187_x.html" target="_blank">'
        '[ANi] Yasei no Last Boss ga Arawareta /  <span class="keyword">野生的大魔王出現了</span>！'
        ' - 14 [1080P][Baha][WEB-DL][AAC AVC][CHT][MP4]</a>'
        '<span style="color: gray;">約1條評論</span></td>')
node = htmlx.parse(DMHY)
link = node.find("a", attr_contains_href="topics/view")
title = link.text
print(f"  解析出的标题：{title!r}")
check("关键词留在原位（没被挪到标题末尾）", "Arawareta / 野生的大魔王出現了！ - 14" in title, title)
check("标题结尾仍是分辨率标签", title.endswith("[CHT][MP4]"), title)
check("行内其它元素文本也在（评论数）", "約1條評論" in node.find("td").text, node.find("td").text)
check("own_text 只含自身文本", htmlx.parse(DMHY).find("a").own_text.count("野生") == 0)

mixed = htmlx.parse("<p>前<b>粗</b>中<i>斜</i>后</p>").find("p")
check("文本与子元素按文档顺序交错", mixed.text == "前粗中斜后", mixed.text)
check("嵌套深层也保持顺序", htmlx.parse("<div>a<span>b<span>c</span>d</span>e</div>").find("div").text == "abcde")

# 结构 API 不受影响
tbl = htmlx.parse('<table class="topic-list"><tr><td>1</td><td>2</td></tr></table>')
check("find_all / cells 仍然可用", len(htmlx.cells(htmlx.direct_rows(tbl.find("table"))[0])) == 2)

print()
print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
for f in FAIL:
    print("  [失败]", f)
sys.exit(1 if FAIL else 0)
