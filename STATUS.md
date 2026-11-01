# 项目状态（交接单）

> 每个新会话开工前先读这个文件；收工前更新它。
> 规则和流程见 `AGENTS.md`；**这里只写会变的现状，不写规则。**

最后更新：2026-11-01

## 当前状态

| 项 | 值 |
| --- | --- |
| 版本 | **1.2**（README 顶部写的就是这个；tag `v1.2` → `24c8f16`。本次没发版，仍是 1.2） |
| 配置 schema | `data/config.json` 里 `"version": 3`（**不是 App 版本**，别混；本次没动配置） |
| 最后一次提交 | **`3f118cf`**（本次会话：订阅设置「筛选结果」+ 修改订阅整套弹窗）；上一笔是 `187bfc1`（上一批 STATUS 补记） |
| 分支 / 远端 | `main` 跟踪 `kelstna/main`（https://github.com/kelstna/anime-auto-downloader），本地 **领先远端 5 个提交**（含本次，未 push，用户没要求 push） |
| 仓库体量 | `main` 上 **9 个提交**；另有**独立**本地分支 `backup-9919` → `9919e74`（2026-10-15，不在 main 的历史里） |
| 工作区 | ✅ **干净**（2026-11-01 14:4x 提交后复核） |
| 服务 | **正在运行**：`pythonw` PID **16212**（`-m app.main --no-browser`，启动于 2026-11-01 14:03），监听 **`0.0.0.0:7788`**，实测 `GET /app.js` 200。**进程 cwd 与数据目录都是 `E:\アニメ\anifetch`**，不是本工作区（见「已知问题 8」） |
| 测试 | `python tests\run_all.py`：**325 例 = 322 通过 + 3 跳过 + 0 失败**，7.7 秒（2026-11-01 14:37 实测） |
| 产物 | 无（本地服务，没有 APK/安装包；「发布」= 推送仓库，用户自己 `git pull` 或复制目录） |

## 本次会话：订阅设置「筛选结果」+「修改订阅 = 整套弹窗」

> 已入库：**`3f118cf`**（10 个文件，+910 / −42）。

**用户需求（原话要点）**：修改订阅页面下方显示筛选后的搜索结果、页面改成可滚动；
资源站 / 限定字幕组 / 限定分辨率 / 字幕语言就是筛选条件；含合集给筛选开关；
修改订阅别再砍成一个精简页，直接用人点卡片的那一整套，默认停在**资源列表**，且
**弹出的资源列表要按订阅自动筛选**；主按钮改成「保存修改」。

做了什么（**纯前端，后端零改动**，所以不触发铁律 6 的缓存失效）：

1. `index.html`：`#tab-sub` 里 `#s-preview` 与 `.sub-actions` 之间新增 `#sub-results`
   （标题 + 计数 +「含合集」开关 + 只读结果表 `#sub-res-table`/`#sub-res-body` + 空态）。
2. `app.js`：
   - 新增 `subResFilters()` / `filterSubResources()` / `subResEmptyText()` / `buildSubResRow()` /
     `renderSubResources()`；口径复用 `groupMatch` / `langMatches` / `sortResourceRows`
     （顺序同后端：站点 → 字幕组 → 语言 → 分辨率；噪声恒隐藏、合集默认隐藏、上限 300 行）
   - 总闸挂在 `renderSubPreview()` 尾部 + `switchTab('sub')`，改任一 `#s-*` 都会重算
   - **补上原本没绑的** `#s-source` / `#s-lang` 的 `change`（以前改这两个下拉界面一动不动）
   - `edit` 模式：`tabs.hidden = backfill`（两页签都保留）、默认 `switchTab('res')`；
     `applySubscriptionFilterToFilters()` 在 edit 模式下也跑（用户要的「资源列表按订阅自动筛选」）；
     `#btn-sub-add-res` 与 `#btn-sub-add` 文案都是「保存修改」，且不再因「没资源」置灰；
     `addSubscriptionFromResList()` 在 edit 模式下直接保存设置（不带 resource、不带 filters）
   - `renderBackfillHint()` 一分为二：补下载 / 修改订阅两套文案（同一个提示元素）
3. `styles.css`：`#tab-sub { flex: 1 1 auto; min-height: 0 }`（**滚动成立的前提**）、
   `.sub-results*` 区块、`.sub-results-wrap { max-height: min(34vh, 320px) }`、
   `#tab-sub .sub-actions` 只留分隔线（**不做吸底**：实测吸底会浮在结果表上把它挡住）

涉及文件：

```
app/web/index.html  app/web/app.js  app/web/styles.css
_probe/ui_fixture.html（make_fixture.py 重生成，index.html 改了必须重跑）
_probe/t_sub_results_ui.py（新增：CDP 真浏览器探针，52 项，出 3 张截图）
_probe/t_sub_results_logic.mjs（新增：Node 抽取真实函数源码跑筛选口径，19 项）
README.md（§一.3 订阅设置/修改订阅 + 第九节新增「注意 12」）
ARCHITECTURE.md（§③ 加入订阅 补「修改订阅」流程、§六 前端结构）
AGENTS.md（「注意 1~11」→「1~12」两处）  STATUS.md
```

验证记录：

- `python tests\run_all.py` → **全部通过**（322 通过 / 3 跳过 / 0 失败，7.71 秒）
- `node _probe\t_sub_results_logic.mjs` → **19 项全过**（7 条/2 条/1 条/0 条、站点与组成对、
  含合集 8 条、空态 total=0 等口径全部对上）
- `python -X utf8 _probe\t_sub_results_ui.py`（Chrome headless + CDP）→ **52 项全过**，
  截图 `_probe/shots/50_sub_results.png`（订阅设置）、`51_edit_resources.png`（修改订阅→资源列表已按订阅筛好）、
  `52_sub_results_scrolled.png`（滚到底能看到结果表 + 保存修改）
- 已把 3 个前端文件复制到运行中的部署副本 `E:\アニメ\anifetch\app\web\`（逐个 SHA256 比对一致）；
  静态文件是按请求读盘的，**刷新页面即可生效，不用重启服务**（本次没改后端）

## 上一批（已入库，待你验收）：`861aaf7` + `da09195`

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

## 待验收

### 本批（订阅设置「筛选结果」+ 修改订阅）

1. 点番剧卡片 → 「订阅设置」：**拉到下半部分**能看到「筛选结果 · 共 N 条」和一张只读表；
   改 资源站 / 限定字幕组 / 限定分辨率 / 字幕语言 任一条件，表里的条数立刻跟着变。
2. 勾「含合集」→ 多出合集行（默认不列合集）；计数行会写「已隐藏 N 条合集 / 噪声」。
3. 整页可上下滚（滚的是订阅设置这一页，结果表自己限高、表头固定在表内）；滚到底能看到
   「加入订阅 / 去资源列表挑选单集 / 合集」。
4. 「我的订阅」→ 任意订阅 → **修改订阅**：弹窗**两个页签都在**，默认停在**资源列表**，
   且**已按这条订阅的字幕组 / 语言 / 分辨率筛好**（顶部提示条写「已按订阅筛选：…（可自行放宽）」）；
   订阅限定的项这轮没搜到就不锁它，提示条会写明哪一项没过滤。
5. 两个页签上的主按钮都是**保存修改**；点它 → 提示「订阅已更新」，订阅里的设置被改掉，
   **不会重新下载**；资源列表行内「下载」是「只给这条订阅补这一集」，不动设置。
6. 已订阅的番剧点卡片进「订阅设置」，字幕组下拉仍会默认选中订阅里的组（老行为，没动）。

### 上一批（手动搜索 / 合集判定 / 批量订阅字幕组）

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
2. **文档里的用例数过期**（2026-11-01 观察：README 写 274、ARCHITECTURE 写 296、实测 325 例）。
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
9. **订阅已恢复**：`E:\アニメ\anifetch\data\subscriptions.json` 现有 **17 条**（2026-11-01 14:37 复核，
   40913 字节；13:16 清空时的快照 `.before-delete-20261101-131621.bak` / `-131623.bak` 还在，可回退）。
10. **DSH 沙箱下跑不了的工具**（本会话实测，2026-11-01）：
    - 受限模式下 `tempfile.mkdtemp()` 建的目录会被拒绝访问 → `python tests\run_all.py` 会报一堆
      `PermissionError: …\.json.tmp`。**切到「完全权限」(danger-full-access) 再跑**，即全绿。
    - 受限模式下 Chrome headless 起不来（弹「Error launching CrashSender.exe」，CDP 连接超时）
      → `_probe/t_sub_results_ui.py` 等 CDP 探针同样要完全权限才有结果。
    - 浏览器探针只认 **Google Chrome**（用户明确要求，别换 Edge）。

## 下次可以做的（候选，等用户挑）

- **真机验收本批**：按上面「待验收 · 本批」6 条点一遍（**刷新页面即可生效**，前端改动不用重启服务）→
  （用户要的话）发版：**先把 README 顶部改成 1.3，再打 tag `v1.3`**（顺序反了会出现 tag 1.3 / README 1.2）。
- 上一批（手动搜索 / 合集判定 / 批量订阅字幕组）的 8 条待验收也还没真机走过，可一并走。
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
| 2026-11-01（晚） | **订阅设置加「筛选结果」+ 修改订阅改成整套弹窗**：订阅设置页下方只读结果表（四个限定条件当筛选条、含合集开关、整页可滚）；「修改订阅」保留两个页签、默认资源列表、并**按订阅自动筛选**；主按钮改「保存修改」；新增 2 个探针（CDP 52 项 + Node 口径 19 项）；前置同步到部署副本（刷新即生效） | 见「本次会话」一节 |
| 2026-11-01（下午） | **修「批量订阅不显示字幕组」**：候选改从预热缓存 `search_<id>` 汇总（`/api/groups/cached` 新增 `subject_ids`），不再依赖订阅；新增 `tests/test_groups_cached.py`；同步 README/ARCHITECTURE；服务已重启并在接口层验证 | `861aaf7` |
| 2026-11-01 | 建立这套交接机制：`AGENTS.md` + `STATUS.md` + `新会话开场白.txt`（从"优化本地番剧播放"移植过来）；顺手实测测试与运行状态 | 未提交（本次只新增文档） |
| 2026-10-26 | 「最近更新」弹窗改成按自动追番的下载记录显示 | `24c8f16`（= tag `v1.2`） |
| 2026-10-23 | README 去掉「更新日志」段 | `39c2660`、`8da6bc6` |
| 2026-10-15 | 项目初始导入 | `160e0a3` |
| 未归档 | 手动搜索关键词 / 合集判定 / 集号解析（**在途，未提交**，见上文） | — |
