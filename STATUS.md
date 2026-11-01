# 项目状态（交接单）

> 每个新会话开工前先读这个文件；收工前更新它。
> 规则和流程见 `AGENTS.md`；**这里只写会变的现状，不写规则。**

最后更新：2026-11-01

## 当前状态

| 项 | 值 |
| --- | --- |
| 版本 | **1.2**（README 顶部写的就是这个；tag `v1.2` → `24c8f16`） |
| 配置 schema | `data/config.json` 里 `"version": 3`（**不是 App 版本**，别混） |
| 最后一次提交 | 本次会话三笔（按时间）：`861aaf7` 功能修复 → `3259f12` STATUS 补记 → `da09195` 性能修复（**代码就在这三笔里**，之后只可能有 STATUS 补记提交） |
| 分支 / 远端 | `main` 跟踪 `kelstna/main`（https://github.com/kelstna/anime-auto-downloader），本地 **领先远端 3 个提交**（未 push，用户没要求 push） |
| 仓库体量 | `main` 上 **7 个提交**（`160e0a3` / `8da6bc6` / `39c2660` / `24c8f16` / `861aaf7` / `3259f12` / `da09195`）；另有**独立**本地分支 `backup-9919` → `9919e74`（2026-10-15，不在 main 的历史里） |
| 工作区 | ✅ **干净**（2026-11-01 14:02 提交后复核，`git status --short` 无输出） |
| 服务 | **正在运行**：`pythonw` PID **48796**（`-m app.main --no-browser`，2026-11-01 13:59:52 重启），监听 **`0.0.0.0:7788`**。注意：**进程 cwd 与数据目录都是 `E:\アニメ\anifetch`**，不是本工作区（见「已知问题 8」） |
| 测试 | `python tests\run_all.py`：**323 例 = 320 通过 + 3 跳过 + 0 失败**，9.5 秒（2026-11-01 14:00 实测） |
| 产物 | 无（本地服务，没有 APK/安装包；「发布」= 推送仓库，用户自己 `git pull` 或复制目录） |

## 已提交、等你验收（`861aaf7`）

四件事在同一个提交里（1~3 是上一批在途改动，4 是本次修的）：

1. **手动搜索升级为「联网关键词的唯一来源」**
   填了词就只按这个词联网搜、留空就按番剧名/别名搜；点「手动搜索」**强制联网**（吸收原来的
   「重新搜索」按钮）。关键词进订阅的 `custom_keyword`，之后自动追新只用它；
   缓存键带 `kw=` 且**只认自己的缓存**，绝不回退别名口径（`server._pick_search_cache`）。
2. **合集 / 剧场版判定**
   `END` / `FIN` 是最终话、**不是**合集（修「自动追番永远下不到最后一集」）；`[Movie]` / `剧场版`
   标 `is_movie`、不算合集也不隐藏；`(Part N)` 是分段标记不是集号。
3. **集号解析修复** + 配套测试（`parse_episode_range` 重写、`_NON_EPISODE_NUMBERS`）。
4. **批量订阅的字幕组候选改挂预热缓存**（2026-11-01 本次）
   根因：`/api/groups/cached` 只遍历 `subs.all_subs()`，13:16 订阅被清空后候选池归零，
   批量订阅弹窗的字幕组下拉只剩「不限字幕组」。现在：
   - 后端 `GET /api/groups/cached?subject_ids=1,2,…`：候选从预热缓存 `search_<id>.json`
     的 `items[].source/group` 汇总，订阅只作**附加来源**（并集）；不传参 = 旧口径
   - 前端 `loadBatchGroups()` 传当前勾选；候选为空时弹窗里给一句原因提示（`#batch-group-hint`）
   - 只读缓存不联网；不碰解析/筛选 → **不触发铁律 6 的缓存失效**
   - **性能坑（当次就修了）**：候选第一版照搬了 `normalize_items()`，对 34 部 × 约 5800 条
     重算派生字段，接口实测 **25.9 秒**。改成只读缓存里的原始 `source`/`group`
     （`group` 缺失才用 `extract_group(title)` 兜底）后：34 部 **119 ms**、6 部 **19 ms**。

涉及文件：

```
# 1~3（上一批在途改动，本次一并入库）
app/core/util.py  app/core/warmup.py  app/sources/base.py  app/sources/engine.py
app/web/app.js    app/web/index.html  app/web/server.py    app/web/styles.css
README.md         ARCHITECTURE.md
_probe/ui_fixture.html  _probe/ui_fixture_template.html  _probe/t_manual_keyword_ui.py（新增）
tests/test_util.py  tests/test_engine.py  tests/test_manual_keyword.py
# 4（本次修复）
app/web/server.py  app/web/app.js  app/web/index.html  app/web/styles.css
tests/test_groups_cached.py（新增）  README.md  ARCHITECTURE.md  STATUS.md
```

> 测试已全绿；4 还额外做过接口实测：6 部勾选 → 61 个组 / 19 ms，34 部勾选 → 299 个组 / 119 ms。
> 剩下的是**页面上点一遍**（见下面「待验收」第 8 条）。

## 待验收（这批改动）

1. 弹窗搜索框填词 → 日志/网络里确认**只按这个词**联网搜；留空 → 按番剧名/别名搜。
2. 点「手动搜索」**必走联网**（不吃缓存），页面上不再有「重新搜索」按钮。
3. 加订阅后订阅里存了 `custom_keyword`；之后自动追新只用它；点「恢复自动搜索」能清空。
4. `Show - 12 END` 这类标题**不再被当合集**，自动追番能下到最后一集。
5. 剧场版那几条显示「剧场版」，不被「含合集」开关藏掉。
6. 同一部番换关键词 → **不串用**别名口径的缓存（换词会重新联网一次）。
7. 改了 `index.html` 后要重跑 `_probe/make_fixture.py`，再跑 UI 探针 —— 否则测的是旧 mock 页面（跟重启服务无关）。
8. **字幕组候选走预热缓存**：勾选几部 → 点「批量订阅」→ 下拉里要有组（**订阅为 0 条时也要有**）；
   把资源站选成「动漫花园」后只出现该站的组；候选为空时弹窗里有一句原因提示。
   接口自查（命令行）：`curl "http://127.0.0.1:7788/api/groups/cached?subject_ids=502499,554779"`。

## 已知问题 / 限制

1. `ARCHITECTURE.md` 第八节列的 6 条 TODO 都还在（「按当前筛选订阅」没传 `all_seasons`、批量订阅优先级提示、
   `shoot_ui_batch.py`/`cdp_ui.py` 各一条断言基于旧交互、篇章集号字面不一致、`aniparse` 可选、罕见编号重叠）。
2. **文档里的用例数过期**（2026-11-01 观察：README 写 274、ARCHITECTURE 写 296、实测 323 例）。
   改文档时别再写死数字，统一写「跑 `tests\run_all.py` 看摘要」。
3. `data/config.example.json` 里有本机用户名 `tsubaki`，`"version"` 还是 1（会被 `_migrate()` 升到 3）；
   开源给别人前值得清一遍。
4. 运行期数据全在 `data/`、**不进库**：换机器/重装要自己带走 `config.json`，否则等于重新配置。
5. 订阅/关键词学习记录没有 git 兜底；只有 `subs.py` 删除订阅时自动留 `.before-delete-*.bak`（最多 20 份）。
6. 三站都是外部站点：改版/限流/证书问题随时可能让某个站静默返回空（历史上 Nyaa 因 `search(lang=…)`
   签名不匹配整站静默空结果过）。
7. 交接三件套**刻意不写本机绝对路径**（DSH 以项目根为 cwd，命令全用相对路径）：换机器、搬目录都不用改文档。
   （唯一的例外是下面第 8 条要说明运行位置，不得不写死一个路径。）
8. **运行中的服务跑的是「部署副本」**：`E:\アニメ\anifetch`（`app/` 与本工作区逐字节同步，数据目录也在
   `E:\アニメ\anifetch\data`）。改完源码的生效步骤是：改 `app/` → 复制改动文件到那边的 `app/` →
   重启（在该目录执行 `stop.bat` / `start.bat`，脚本用 `%~dp0`，别在工作区里 double-click，
   否则会拿工作区那份 `data/` 起服务）。本工作区的 `data/` 是旧副本，别拿它看现状。
9. **订阅已清空**：`E:\アニメ\anifetch\data\subscriptions.json` = `[]`（2026-11-01 13:16 清空），
   快照在 `.before-delete-20261101-131621.bak`（102 KB）与 `.before-delete-20261101-131623.bak`（10 KB）。
   要恢复：先停服务，再把快照覆盖回 `subscriptions.json`。

## 下次可以做的（候选，等用户挑）

- **收尾在途改动**：按上面「待验收」7 条真机走一遍 → 提交 →（用户要的话）发版：
  **先把 README 顶部改成 1.3，再打 tag `v1.3`**（顺序反了会出现 tag 1.3 / README 1.2）。
- 修 ARCHITECTURE 那 6 条 TODO，先挑「按当前筛选订阅没传 `all_seasons`」这条（用户能直接感知）。
- 文档统一：「测试多少例」改成「跑 `tests\run_all.py` 看摘要」，消灭三处过期数字。
- 跑一次全量 UI 探针回归（`_probe/shoot_*.py`），把过期断言更新掉。

## 回滚

```powershell
# 全部在项目根执行（会话 cwd 就是项目根）

# 1) 只还原"已跟踪文件"的改动，未跟踪文件（探针、三份交接文档）不受影响
git checkout -- .

# 2) 要连未跟踪文件一起清：先预演，看清楚会删什么
git clean -nd            # 预演
git clean -fd            # 真删 —— 注意：本次新增的 AGENTS.md / STATUS.md / 新会话开场白.txt 也会被删

# 3) 最稳：把在途改动整包收起来，随时能取回
git stash push -u -m "WIP 手动搜索/合集判定"
git stash list           # 取回：git stash pop

# 4) 真正的"整仓回到某次提交"（丢弃一切未提交改动，含未跟踪）
git reset --hard 24c8f16
#    只退一个文件：git checkout 24c8f16 -- app/core/util.py

# 5) 老底仓：独立分支 backup-9919 → 9919e74（不在 main 的历史里）
git checkout backup-9919
```

## 一分钟上手

```powershell
# 会话 cwd 就是项目根；路径含空格/中文，需要绝对路径时加引号

# 看状态
git log --oneline -4
git status --short

# 跑测试（约 9 秒，不联网）
python tests\run_all.py

# 重启服务（改后端必做）
.\stop.bat
.\start.bat          # 看日志窗口用 start-debug.bat
# 浏览器打开 http://127.0.0.1:7788
```

## 最近几次会话

| 日期 | 做了什么 | 提交 |
| --- | --- | --- |
| 2026-11-01（下午） | **修「批量订阅不显示字幕组」**：候选改从预热缓存 `search_<id>` 汇总（`/api/groups/cached` 新增 `subject_ids`），不再依赖订阅；新增 `tests/test_groups_cached.py`；同步 README/ARCHITECTURE；服务已重启并在接口层验证 | `861aaf7` |
| 2026-11-01 | 建立这套交接机制：`AGENTS.md` + `STATUS.md` + `新会话开场白.txt`（从"优化本地番剧播放"移植过来）；顺手实测测试与运行状态 | 未提交（本次只新增文档） |
| 2026-10-26 | 「最近更新」弹窗改成按自动追番的下载记录显示 | `24c8f16`（= tag `v1.2`） |
| 2026-10-23 | README 去掉「更新日志」段 | `39c2660`、`8da6bc6` |
| 2026-10-15 | 项目初始导入 | `160e0a3` |
| 未归档 | 手动搜索关键词 / 合集判定 / 集号解析（**在途，未提交**，见上文） | — |
