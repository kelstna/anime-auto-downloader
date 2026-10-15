# 离线 HTML 夹具

这些文件是**真实抓取的列表页快照**，用于 `tests/test_parsers.py` 做离线解析测试。
测试不联网，只读这些本地文件。

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `dmhy_search.html` | `_probe/out/dmhy_search.html` | 动漫花园 `/topics/list?keyword=...` 搜索结果页 |
| `kisssub_search.html` | `_probe/out/kisssub_after.html` | 爱恋动漫 `/search.php?keyword=...` 通过访客验证后的搜索页 |
| `nyaa_search.html` | `_probe/out/nyaa_search.html` | Nyaa `/?q=...&c=1_0&s=seeders` 搜索结果页 |

夹具是快照：站点改版后需要重新抓取并覆盖同名文件。
抓取后请重跑 `python -m unittest discover -s tests -t . -v`，
若断言中的条目数下限不再满足，按实际结果调整下限（但「每组都有 title / magnet 合法 / size > 0」这类不变量必须保持）。
