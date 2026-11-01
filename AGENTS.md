# AGENTS.md — 自动下载番剧 固定守则（每个新会话自动加载）

> 你是接手这个项目的 AI 助手。读完本文件再动手。
> **开工第一步：读同目录的 `STATUS.md`**（当前版本、在途改动、待验收、回滚点都在那里）。
> 分工死规矩：**本文件只放"不会变"的规则，会变的现状一律写 `STATUS.md`。** 两边混写 = 新会话读到过期信息。

## 1. 这是什么

自托管**番剧自动下载器**：本地 Python Web 服务 + 浏览器界面（默认 `http://127.0.0.1:7788`）。
链路：Bangumi「在看」→ 三站搜索（动漫花园 / 爱恋动漫 / Nyaa）→ 按季/集/字幕组规则筛 →
加入订阅 → 后台定时追新 → 推给 qBittorrent 下载。

- 技术栈：**Python 3.10+ 标准库**，零第三方依赖（`aniparse` 仅可选）；前端原生 HTML/CSS/JS，**无构建步骤**
- 许可证：GPL-3.0-only；代码由 AI 按需求生成（见 `NOTICE.md`），非官方项目，与三站及 qBittorrent 无关
- 部署形态：**没有安装包、没有编译产物** —— 部署就是双击 `start.bat`
- 文档分工：`README.md` = 用户手册（**第九节有 12 条「注意」，改代码前必看**）、
  `ARCHITECTURE.md` = 架构与流程、`NOTICE.md` = 边界与免责

## 2. 目录与角色（先认清哪个是"真相"）

| 路径 | 角色 |
| --- | --- |
| `app/` | **源码唯一真相**：`main.py` 入口、`core/` 业务、`sources/` 三站适配器、`web/` 前端 |
| `tests/` | 离线单测；`tests/__init__.py` 把数据目录指到临时目录，跑测试不动真实 `data/` |
| `_probe/` | 开发期探针脚本（**进库**）；`_probe/shots/`、`_probe/design/` 的截图录屏**不进库** |
| `data/` | **运行期数据，整体在 `.gitignore` 里**：`config.json`（Bangumi token、qB 账号密码）、`subscriptions.json`、日志、缓存 |
| `data/config.example.json` | **这条进库**（唯一例外）：样例配置，不含真实凭据；改默认配置改它 + `app/core/config.py` |
| `README.md` / `ARCHITECTURE.md` / `NOTICE.md` | 文档真相；改了行为要同步对应章节 |
| `start.bat` / `start-debug.bat` / `stop.bat` / `setup.bat` / `install-autostart.bat` / `uninstall-autostart.bat` | 用户侧启停与自启动脚本 |
| `_e2e_downloads/`、`probe-lszfyjvj/`、`.pytest_cache/` | 临时目录，可删 |

**和"源码/构建副本"型项目最大的差异**：这里**没有构建副本**，改 `app/` 立刻生效 ——
但服务是常驻进程，**不重启，页面看到的还是旧代码**。

## 3. 铁律（每条都能判定是否违反）

1. **没让你动手改之前，绝对不要动手改。** 读代码、量数据、写方案可以；要动文件（源码 / 脚本 / 配置 /
   文档 / 提交）必须先说明改什么，等用户说「改 / 可以 / 动手 / 做吧」再动。被否掉的方案不要偷偷夹带。
2. **`data/` 整体不进 git**（里面有 token 和 qB 密码），**唯一例外是 `data/config.example.json`**。
   要加/改默认项，只动 `data/config.example.json` 和 `app/core/config.py` 的 `DEFAULT_CONFIG`。
3. **不引入第三方依赖。** 只用标准库；`aniparse` 保持可选（没装就走内置正则）。真要加，先说清
   「重装系统后要多做哪一步、体积/踩坑代价是什么」。
4. **改默认值必须走 `config._migrate()`。** `load()` 是 `_deep_merge(DEFAULT_CONFIG, raw)`，
   已存在的持久化值会盖住新默认值 —— 只改 `DEFAULT_CONFIG` 对已经跑过的机器无效。
5. **两个"版本号"别混**：`config.json` 里的 `"version"` 是**配置 schema 号**（在 `_migrate()` 里加一档），
   App 版本是 **README 顶部 + git tag**。发版顺序固定：先改 README 顶部 → 再 `git tag`，
   否则会出现 tag `v1.3` 而 README 还写 1.2 的分裂。
6. **改了解析/识别/筛选规则，必须让旧搜索缓存失效。** `warmup.SEARCH_SCHEMA` 是相关源码的内容指纹
   （改了自动作废重搜），新增字段还要在 `base.normalize_items()` 里兜底重算。
7. **一次会话只做一件事**（一个功能 / 一个 bug）。顺手重构无关代码 = 事故。
8. **编码：源码统一 UTF-8（无 BOM）。** **不要用 `Set-Content` / `Out-File` 改源码**
   （本机 PowerShell 5.1 默认按 ANSI/GBK 读写，中文必乱）。`.bat` 保持 CRLF、其余 LF（见 `.gitattributes`）。
9. **收工三件套**：更新 `STATUS.md`、同步被改到的 README / ARCHITECTURE 章节、`git commit`
   （中文，说清「改了什么 + 为什么」）。用户没明确要求**不要 push**。
10. **出货判据**：`python tests\run_all.py` 摘要「全部通过」（0 失败 / 0 错误），再重启服务实测一遍。
11. 不改写 git 历史、不 force push、不 `reset --hard` 丢掉别人的改动。

## 4. 标准流程（改代码 → 验证 → 交班）

```powershell
# 会话的工作目录就是项目根（DSH 按 cwd 加载本文件），下面一律用相对路径。
# 项目路径含空格和中文：需要拼绝对路径的地方一定加引号。

# 1) 改代码：只动 app/（前端 app/web/ 无构建步骤，改完刷新页面即可）
#    改了 index.html 又想跑 mock 页面探针，先重生成测试页：
python _probe\make_fixture.py

# 2) 离线测试（约 9 秒；不联网，不碰真实 data/）
python tests\run_all.py
#    联网用例要显式开（真打三个站点，慢且可能被限流）：
#    $env:ANIME_ONLINE='1'; python tests\run_all.py

# 3) 重启服务看真实效果（改后端必做）
.\stop.bat            # 按命令行匹配 app.main；只预览不动手：先 set ANIME_DRYRUN=1
.\start.bat           # 想看日志窗口用 start-debug.bat
#    打开 http://127.0.0.1:7788

# 4) 收工
git add -A
git commit -m "feat(范围): 改了什么 + 为什么"
```

- 端口被占会自动往后找（`main.pick_port`，最多 +19）——**以启动日志打印的 URL 为准**，别假定 7788。
- 判据：测试摘要全绿 + 页面实测（弹窗搜索 / 加订阅 / 追番一轮 / 待下载队列 / 已下载文件管理）。

## 5. 代码地图

| 功能 | 文件 |
| --- | --- |
| 启动入口、端口探测、后台线程拉起 | `app/main.py` |
| 配置读写 / 默认值 / 迁移 | `app/core/config.py`（`DEFAULT_CONFIG`、`_migrate()`） |
| **季判定 + 集号换算的唯一入口** | `app/core/rules.py`（`SeasonContext` / `filter_items`）；细节在 `app/core/util.py` |
| 番剧名清洗 / 集号解析 / 合集判定 | `app/core/util.py`（`parse_episode_range`、`_BATCH_RE`、`apply_season_rules`） |
| 自动追番（后台循环、候选筛选、下载、记账） | `app/core/watcher.py` |
| 待下载队列（qB 掉线兜底） | `app/core/pending.py` + `data/pending.json` |
| qBittorrent 客户端（不走代理） | `app/core/qbittorrent.py` |
| Bangumi API / 元数据 / 章节表缓存 | `app/core/bangumi.py`、`app/core/meta.py` |
| 订阅存储（原子写 + 删除前快照） | `app/core/subs.py`（`data/subscriptions.json`） |
| 搜索缓存 / 预热 | `app/core/cache.py`、`app/core/warmup.py` |
| 资源模型 / 语言与分辨率识别 / 派生字段 | `app/sources/base.py`（`detect_language`、`normalize_items`） |
| 多站并发搜索 / 字幕组聚合 / 排序 | `app/sources/engine.py` |
| 三站适配器 | `app/sources/dmhy.py`、`kisssub.py`、`nyaa.py`、`romaji.py` |
| HTTP（分用途代理、重试、429 冷却） | `app/core/http.py` |
| 更新时间推算 | `app/core/airtimes.py`（`data/airtimes.json`） |
| 全部 HTTP 路由与 API | `app/web/server.py` |
| 前端页面 / 逻辑 / 自绘下拉 / 样式 | `app/web/index.html`、`app.js`、`ui.js`、`styles.css` |

**改「什么算本季 / 集号怎么换算」时，判定逻辑只改 `app/core/rules.py` + `app/core/util.py`**
（页面、补单集、自动追番三条路都只调这两个文件，改别处一定漏）。
但**改完必须按铁律 6 处理缓存**——`app/core/warmup.py` 的 `SEARCH_SCHEMA`、`app/sources/base.py`
的 `normalize_items()`，否则用户看到的还是上一版解析出来的结果。

## 6. 踩过的坑（别再踩）

**代码级坑已经写在 `README.md` 第九节「注意 1~12」，改代码前先读那一节**（自绘下拉的值、
缓存键要带字幕组/关键词、默认值迁移、适配器 `search()` 签名、429 退避、`htmlx` 文本顺序、
组过滤、待下载队列、修改订阅就是整套弹窗……）。这里只记**流程级**的新坑，踩一次加一条：

- **改了后端没重启就验收** → 页面永远是旧代码，白测。（`stop.bat` → `start.bat`）
- **改前端也要重启**：`?v=<资源版本号>` 是进程启动时按 `styles.css+ui.js+app.js` 算的哈希，
  带 `?v=` 的资源按 `max-age=3600` 缓存 —— 不重启版本号不变，浏览器继续用旧 JS/CSS，
  刷新多少次都看不到改动（2026-11-01 踩过：文件已同步，用户刷新仍是旧界面）。
- **`_probe/ui_fixture.html` 是 `make_fixture.py` 的产物**：改了 `index.html` 不重跑，mock 探针测的是旧页面。
- **探针脚本默认会写真 `data/`**：自己跑探针前先设隔离目录（`ANIME_DATA_DIR`），否则污染真实订阅/配置。
- **别在文档里写死用例数**：README 和 ARCHITECTURE 里那两处数字都已经过期（还不止一次）。
  统一写「跑 `python tests\run_all.py` 看摘要」，别记数字。
- **提交信息用中文**；`.gitattributes` 已统一 LF，别把 CRLF 混进 `.py/.md`（会让整个文件变成 diff）。
- **`data/` 里的东西改坏了没有 git 兜底**：动订阅前先备份（`subs.py` 删除时有自动快照，手改没有）。

## 7. 开工 / 收工

**开工**（新会话第一条消息通常已经要求先读这两份文件）：

1. 读 `STATUS.md`，用 **3 行**复述：当前版本 + 最后提交 / 这次要动哪些文件 / 怎么做怎么验证；
2. 有疑问先问用户，别猜需求；
3. 涉及新功能先给方案（改哪些文件、风险、怎么验证），**等用户确认再写代码**。

**收工**：

1. `python tests\run_all.py` 全绿；
2. 更新 `STATUS.md`（版本、在途改动、待验收、已知问题、下次可做的）；
3. 同步 README / ARCHITECTURE 里被改到的章节；
4. `git commit`（中文，说清「改了什么 + 为什么」）；
5. 给用户一段人话总结：改了什么、怎么验证、有什么限制。
