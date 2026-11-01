# 项目状态（交接单）

> 每个新会话开工前先读这个文件；收工前更新它。
> 规则和流程见 `AGENTS.md`；**这里只写会变的现状，不写规则。**

最后更新：2026-11-01

## 当前状态

| 项 | 值 |
| --- | --- |
| 版本 | **1.2**（README 顶部写的就是这个；tag `v1.2` → `24c8f16`。本次没发版，仍是 1.2） |
| 配置 schema | `data/config.json` 里 `"version": 3`（**不是 App 版本**，别混；本次没动配置） |
| 最后一次提交 | **`c74308c`**（本次会话：修改订阅 = 整套弹窗 + 按订阅预筛；撤掉了被否决的「筛选结果」面板） |
| 分支 / 远端 | `main` 跟踪 `kelstna/main`（https://github.com/kelstna/anime-auto-downloader），本地 **领先远端 5 个提交**（含本次，未 push，用户没要求 push） |
| 仓库体量 | `main` 上 **9 个提交**；另有**独立**本地分支 `backup-9919` → `9919e74`（2026-10-15，不在 main 的历史里） |
| 工作区 | ✅ **干净**（2026-11-01 14:4x 提交后复核） |
| 服务 | **正在运行**：`pythonw` PID **5844**（`-m app.main`，2026-11-01 16:2x 重启，为的是让前端资源版本号刷新），监听 **`0.0.0.0:7788`**，实测 `GET /` 200、`app.js?v=d8a15b7863`。**数据目录是 `E:\アニメ\anifetch\data`**（见「已知问题 8」） |
| 测试 | `python tests\run_all.py`：**325 例 = 322 通过 + 3 跳过 + 0 失败**，7.7 秒（2026-11-01 14:37 实测） |
| 产物 | 无（本地服务，没有 APK/安装包；「发布」= 推送仓库，用户自己 `git pull` 或复制目录） |

## 本次会话（续）：修「修改订阅点了保存没生效」

**用户反馈（原话）**：修改订阅点保存后没有修改成功（截图里他在**资源列表**把字幕组改成「桜都字幕组」，
点保存，toast 却是「订阅已更新（字幕组 动漫花园 · LoliHouse）」）。

**根因**：`addSubscriptionFromResList()` 在 edit 模式下直接 `addSubscription(null)`，
读的是 `#s-*`（订阅设置里预填的旧值），**完全没用资源列表那一页 `#f-*` 上的改动**。
当初是怕「浏览用的筛选」污染订阅设置，结果变成用户改了也白改。

**修法**（`app/web/app.js`）：

1. 新增 `syncSubFormFromResFilters()`：把 `#f-source / #f-group / #f-res / #f-lang` 里
   **用户真的改过**的项写回 `#s-*`，再走原来的 `addSubscription()`。判「改过」的基准是
   `modal.resFilterBaseline`（`applySubscriptionFilterToFilters()` 每次预选后记下的快照）——
   没动过的项保持订阅原值，避免「订阅限定的项这一轮没搜到 → 筛选条是空白 → 把设置洗掉」。
2. 组名要配回站点：`#s-group` 的 value 是 `站点::组名`，新增 `setSubGroupValue()`，
   选项里没有就补占位项（不让刚选的组被静默丢掉）。
3. 切到「订阅设置」页签时也同步一次（`switchTab('sub')`），两个页签显示同一套值。
4. 保存成功后用新订阅对象再预选一次 `#f-*`，资源列表立刻反映新设置。
5. `source_ids`：edit 模式选「不限」现在会真的清空（以前会保留旧值）。

验证：`_probe/t_edit_sub_ui.py` 扩到 **39 项**，新增两段回归：
【7】把 `#f-group` 改成「爱恋字幕社」→ 点资源列表的「保存修改」→ 提交的 body 必须是
`group=爱恋字幕社 / sub_group=kisssub::爱恋字幕社`（**修前提交的是老组，就是这个 bug**）；
【8】什么都不改直接保存 → 字幕组/分辨率保持订阅原值（防洗掉）。

## 本次会话：修改订阅 = 整套弹窗（+ 一次被否决的第一版）

> 已入库：**`c74308c`**（撤掉被否决的第一版之后重做的那一笔）；被否决的第一版是 `3f118cf`。

最终交付（**纯前端，后端零改动**，不触发铁律 6 的缓存失效）：

1. **修改订阅打开的就是点卡片那一整套弹窗**：`tabs.hidden = backfill`（edit 不再隐藏页签栏），
   默认 `switchTab('res')`（停在**资源列表**）。
2. **弹出的资源列表按订阅自动筛选**：`applySubscriptionFilterToFilters()` 在 `edit` 模式下也跑
   （与「补下载单集」共用同一个函数；订阅限定的项本轮没有就不锁，并写在提示条里）。
3. **主按钮改「保存修改」**：`#btn-sub-add-res` 与 `#btn-sub-add` 都改文案，且不再因「当前筛选没资源」置灰；
   `addSubscriptionFromResList()` 在 edit 模式下直接保存设置（不带 resource、不带 filters，不重新下载）。
4. 资源列表顶部的提示条按模式分两套文案（`renderBackfillHint()`）：补下载 vs 修改订阅。
5. **订阅设置那一页保持原样**：`index.html` / `styles.css` 与改动前**逐字节相同**（`git diff` 无输出），
   只改 `app/web/app.js`（+53 / −22）。

**被否决的第一版（已撤）**：先在订阅设置页加了「筛选结果」只读表（`#sub-results` + 含合集开关 +
整页滚动 + 落点吸底），用户明确说「订阅设置底下的筛选结果不需要，你不要改动原来的」——
按原话把 `index.html` / `styles.css` 整个退回，相关 JS 全部删除，只看资源列表就够了。
教训写进 README「注意 12」：**修改订阅就是整套弹窗，别再往订阅设置页里塞预览区块。**

涉及文件：

```
app/web/app.js（唯一有代码改动的文件）
_probe/t_edit_sub_ui.py（新增：Chrome headless + CDP 探针，29 项；含「订阅设置页结构 = 原版」的守卫）
_probe/ui_fixture.html（make_fixture.py 重生成）
README.md（§一.3 新增第 5 条「改一条已有订阅的设置」、第九节新增「注意 12」）
ARCHITECTURE.md（§③ 补「修改订阅」流程、§六 弹窗两个页签的职责）
AGENTS.md（「注意 1~11」→「1~12」两处）  STATUS.md
```

验证记录：

- `python tests\run_all.py` → **全部通过**（0 失败 / 0 错误）
- `python -X utf8 _probe\t_edit_sub_ui.py`（**只用 Google Chrome**）→ **29 项全过**：
  订阅设置页结构 = 原版（无 `#sub-results`、无 `#tab-sub` 样式规则）；修改订阅两页签都在、默认资源列表；
  `#f-group=桜都字幕组`、`#f-res=1080p`、表里只剩 2 条、提示条写「已按订阅筛选」；
  两个按钮都是「保存修改」；点它提交的 body 不带 `resource`
- 已把 `app/web/{index.html,app.js,styles.css}` 复制到部署副本 `E:\アニメ\anifetch\app\web\`
  （SHA256 逐个一致），**并按顺序跑了那边的 `stop.bat` → `start.bat`**（新 PID 58548）；
  线上 `/` 已确认不含「筛选结果」，服务端 `app.js` 含「保存修改」且不含 `renderSubResources`

> **改了前端一定要重启服务，不能只刷新页面**：`server._ASSET_VERSION` 是进程启动时按
> `styles.css+ui.js+app.js` 内容算的哈希，而带 `?v=` 的资源按 `max-age=3600` 缓存 ——
> 不重启，版本号不变，浏览器会继续用旧 JS/CSS（本会话就踩了：14:33 复制了新文件，
> 用户 14:40 刷新看到的还是旧界面）。重启后页面里的 `?v=` 变成新哈希，浏览器自动重新拉取。

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

### 本批（修改订阅 = 整套弹窗）

0. **保存链路**（16:2x 刚修的）：修改订阅 → 在**资源列表**把字幕组 / 语言 / 分辨率改一改 →
   点这页的「保存修改」→ toast 里的组必须是你**刚改的那个**（旧版这里是旧的，等于保存失败）；
   再点一次不改 → 订阅设置保持原值不被洗掉。
1. 「我的订阅」→ 任意订阅 → **修改订阅**：弹窗**两个页签都在**（资源列表 / 订阅设置），
   **默认停在资源列表**，且**已按这条订阅的字幕组 / 语言 / 分辨率筛好**（顶部提示条写
   「已按订阅筛选：…（可自行放宽）」）；订阅限定的项这轮没搜到就不锁它，提示条会写明哪一项没过滤。
2. 两个页签上的主按钮都是**保存修改**；点它 → 提示「订阅已更新」，订阅里的设置被改掉，
   **不会重新下载**；资源列表行内「下载」是「只给这条订阅补这一集」，不动设置。
3. **订阅设置那一页必须还是老样子**（上半部分四项限定条件 + 预览行 + 按钮，没有多出任何表/区块）。
4. 已订阅的番剧点卡片进「订阅设置」，字幕组下拉仍会默认选中订阅里的组（老行为，没动）。
5. 点卡片（即「加入订阅」入口）不该受影响：两页签、默认资源列表、筛选条不预选（除了已有订阅的组）。

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
| 2026-11-01（晚） | **修改订阅改成整套弹窗并按订阅自动筛选**：两个页签都保留、默认资源列表、`#f-*` 按订阅预选、主按钮「保存修改」；新增 `_probe/t_edit_sub_ui.py`（29 项）；第一版在订阅设置页加过「筛选结果」表，用户否决后**整个撤掉**（index.html/styles.css 退回原版）；已同步部署副本（刷新即生效） | `c74308c` |
| 2026-11-01（下午） | **修「批量订阅不显示字幕组」**：候选改从预热缓存 `search_<id>` 汇总（`/api/groups/cached` 新增 `subject_ids`），不再依赖订阅；新增 `tests/test_groups_cached.py`；同步 README/ARCHITECTURE；服务已重启并在接口层验证 | `861aaf7` |
| 2026-11-01 | 建立这套交接机制：`AGENTS.md` + `STATUS.md` + `新会话开场白.txt`（从"优化本地番剧播放"移植过来）；顺手实测测试与运行状态 | 未提交（本次只新增文档） |
| 2026-10-26 | 「最近更新」弹窗改成按自动追番的下载记录显示 | `24c8f16`（= tag `v1.2`） |
| 2026-10-23 | README 去掉「更新日志」段 | `39c2660`、`8da6bc6` |
| 2026-10-15 | 项目初始导入 | `160e0a3` |
| 未归档 | 手动搜索关键词 / 合集判定 / 集号解析（**在途，未提交**，见上文） | — |
