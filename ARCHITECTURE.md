# 项目逻辑总览（v1.2）

自托管番剧自动下载器：本地网页服务 + 浏览器界面。从 Bangumi 拉「在看」→ 搜索资源站 → 按规则筛 → 加入订阅 → 后台定时追新 → 推送 qBittorrent。

---

## 一、目录结构

```
app/
  main.py                 启动入口（读配置 → 起 HTTP 服务 + 后台线程）
  core/                   业务核心（不涉及 HTTP / 页面）
    config.py             配置读写（data/config.json）、迁移、点号路径 get()
    bangumi.py            Bangumi API 客户端（在看列表 / 番剧信息 / 别名 / 集数）
    meta.py               Bangumi 元数据 + 章节表本地缓存（data/bangumi_meta.json）
    subs.py               订阅存储（data/subscriptions.json），线程安全 + 原子写 + 删除前快照
    watcher.py            自动追番（后台循环、候选筛选、下载、待下载队列）
    qbittorrent.py        qBittorrent WebUI 客户端（不经过代理）
    pending.py            待下载队列（qB 掉线时暂存，恢复后补下载）
    warmup.py             搜索结果预热（打开弹窗秒显示）
    cache.py              通用磁盘缓存（搜索结果 / 收藏列表）
    airtimes.py           每周更新时间推算
    keywords.py           关键词统计（给手动搜索提示）
    http.py               HTTP 封装（代理、超时、重试、冷却、SSL）
    util.py               番剧名清洗、集号解析、季判定细节（season_tokens / in_current_season）
    rules.py              **资源挑选的唯一入口**：季上下文装配 + 季判定 + 集号换算
                          （首页筛选搜索 / 补单集 / 自动追番三条路都调它，改规则只改这里）
    logger.py             日志（data/app.log + 控制台）
  sources/
    base.py               Resource 数据类、语言/分辨率/合集判定、enrich()
    engine.py             多站并发搜索、字幕组聚合、排序
    dmhy.py / kisssub.py / nyaa.py   三个资源站适配器
  web/
    server.py             HTTP 路由 + 全部 API
    index.html            页面结构
    app.js                前端逻辑
    styles.css            设计系统（暖纸/墨色，深浅两套）
    ui.js                 自绘下拉、主题切换、动效
tests/                    单元/集成测试（296 例）
_probe/                   界面探针（CDP 截图 + 断言）、迁移脚本
data/                     （运行期生成，不进版本库）
  config.json             Bangumi token、qB 地址、代理、订阅策略、服务端口
  subscriptions.json      订阅列表（含历史记录、集号偏移）
  bangumi_meta.json       Bangumi 元数据 + 章节表缓存
  pending.json            待下载队列（为空时不生成）
  cache/                  搜索结果缓存
  covers/                 封面缓存
  app.log / console.log   日志
```

---

## 二、统一的三条规则（页面、补下载、自动追番共用）

> **唯一入口**：`core/rules.py`
> `SeasonContext.load()` 装配上下文（起点 / 番名 / 别名 / 本季标识）→ `filter_items()` 做季判定 + 集号换算。
> 页面走 `server._prepare_episodes`，追番走 `watcher.search_for` / `_new_candidates`，两边都只调这两个函数；
> 要改「什么算本季 / 集号怎么换算 / 别名从哪来」，只改 `rules.py`（判定细节）和 `util.py`。

### 1. 本季判定（`core/util.py: apply_season_rules`）

按顺序，先成立先算：

1. **本季标识命中** → 保留。标识从「番剧名 + Bangumi 别名」两处搜集（`season_tokens`）：
   - `第 N 季 / 期 / 部`
   - `Season N` / `Nnd Season`
   - `…篇/編/编`：取「篇」前最后一个空格之后的字符
     （`凡人修仙传 慕兰之战篇` → `慕兰之战`）；「篇」前没有空格的连写（`凡人慕兰之战篇`）不切
   - 裸番名（`凡人修仙传`）不算标识，否则整部系列都会被当成本季
2. 标题写明**别的季**（`第二季` / `Season 2`）→ 排除
3. 标题写明**本季季数** → 保留（有的组用本季编号，如「第五季 - 01」）
4. 集号不在本季区间 `[起点, 终点]` → 排除
5. 集号不明 / 拿不到起点 → 保留（宁可不筛）

区间来自 **Bangumi 章节表**：起点 = 第一集的 `sort`，终点 = 最后一集的 `sort`
（凡人修仙传第五季 = 177…228，共 52 集）。
关掉「只看本季」（请求带 `all_seasons: true`）时不隐藏任何资源，集号换算照旧。

### 2. 集号偏移（`episode_offset`）

```
偏移 = 起点 - 1                     例：凡人第五季 177 - 1 = 176
显示集号 = 标题里的编号 - 偏移        例：194 - 176 = 第 18 集
```

换算只在 `rules.filter_items` 里做一次：dict 返回副本（带 `episode_absolute`），
Resource 就地改集号。偏移由 `_probe/fix_offsets_bgm.py` 按 Bangumi 章节表统一写入订阅。
拿不到章节数据时，`rules.resolve_base` 退回「标题里最小编号 - 1」。

### 3. 筛选（`server._matches_search_filters`）

站点 → 字幕组 → 字幕语言 → 分辨率，四道筛选，缓存命中和联网走同一口径。

---

## 三、主要流程

### ① 拉取「在看」番剧

```
界面点「拉取在看番剧」 → GET /api/bangumi/collections?type=3&force=1
  → bangumi.get_collections()（强制联网，不用旧缓存）
  → meta.save_many(items)          ← 一次性把 首播/总话数/封面/评分/更新时刻 存本地
  → 返回卡片列表
```

### ② 打开某部番的资源弹窗

```
点卡片 → POST /api/search {subject_id}
  → 命中预热缓存？是：读缓存（快，0.0x 秒）
  → 否：engine.search_by_subject() 并发搜 3 个站
  → apply_season_rules()：季判定 + 集号换算（起点用 meta.start_ep）
  → 前端渲染资源表（多列可排序、可按站点/字幕组/语言/分辨率筛）
```

### ③ 加入订阅

```
弹窗里点「加入订阅」
  → POST /api/subscriptions
  → 记录：站点/字幕组/语言/分辨率、集号偏移、目录、初始下载策略
  → 按 initial_mode 决定是否立刻下载最新一集
```

### ④ 自动追番（后台每 5 分钟）

```
watcher._loop
  └→ run_once()
      ├→ flush_pending()        先把队列里攒的补下载掉
      └→ 每条订阅 check_subscription()
          ├→ _season_meta()     和资源弹窗同一口径：别名取 Bangumi 缓存（含 infobox「别名」），
          │                     本季起点取章节表 start_ep，标识命中的资源直接算本季
          ├→ search_for()       搜索 + 套同一套季判定（起点来自 Bangumi）
          ├→ _new_candidates()  组/语言/季/去重过滤
          │    ├ 已下载过的集号 → 跳过
          │    ├ 换算后集号 < 1 → 跳过
          │    └ 小于等于「已下载到」→ 跳过（不往回下载）
          ├→ pick_best()        同一集多版本：站点优先级 → 做种数 → 体积
          └→ download_resource() 推送给 qB（savepath = 该订阅目录）
              ├ 成功 → 写历史、更新 last_episode
              └ 失败 → 进待下载队列，qB 恢复后自动补
```

注意：季判定/关键词和弹窗一致，但**订阅自己限定的站点 / 字幕组 / 语言仍会收窄实际下载**
（例：凡人修仙传第五季订阅限定「FSP DN + Nyaa」，dmhy 的 GM-Team 资源不会自动下，
弹窗里仍能看到）。要换源就把订阅设置里的站点/字幕组清空。

### ⑤ 补下载单集

```
订阅卡「补下载单集」→ 以订阅身份打开同一个资源弹窗（backfill 模式）
  → 筛选预设成该订阅的站点/组/语言（不猜、不改订阅）
  → 点某行「下载」→ POST /api/subscriptions/{id}/download
```

### ⑥ 已下载文件管理

```
订阅卡「已下载文件管理」→ 只列**文件夹里的视频文件**（不看历史、不看 qB）
  → 每行「删除」→ POST /api/subscriptions/{id}/file/delete
      有对应种子 → 先删种子（delete_files=true，种子+文件一起删）
      没有种子   → 直接删文件
```

### ⑦ 待下载队列

qB 连不上 / 添加失败时，集不丢：写入 `pending.json`，每轮追番与独立巡检线程都会重试，
qB 恢复后自动补下载并累加 `flushed_total`。

---

## 四、后台常驻任务

| 线程 | 周期 | 作用 |
| --- | --- | --- |
| `anime-watcher` | 5 分钟（可配） | 自动追番 |
| `anime-pending` | 1 分钟 | 探测 qB 是否恢复，补下载队列 |
| `bangumi-meta` | 24 小时 | 刷新过期（>7 天）的 Bangumi 元数据 |
| 预热线程 | 启动时 | 逐部搜一遍存缓存，打开弹窗秒显示 |

---

## 五、主要 API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/status` | 版本、qB 状态、资源站、追番状态与队列 |
| GET | `/api/config` | 读取设置 |
| POST | `/api/config` | 保存设置（立即生效） |
| GET | `/api/bangumi/collections?type=3&force=1` | 在看列表（force=1 强制刷新） |
| GET | `/api/bangumi/meta` | 元数据缓存状态 |
| POST | `/api/search` | 搜资源（季判定 + 集号换算） |
| GET/POST | `/api/subscriptions` | 列表 / 加入订阅 |
| POST | `/api/subscriptions/{id}/update` | 修改订阅 |
| DELETE | `/api/subscriptions/{id}` | 删除订阅（删前自动快照） |
| POST | `/api/subscriptions/{id}/check` | 立即检查该订阅 |
| POST | `/api/subscriptions/{id}/download` | 下载某条资源（补下载） |
| POST | `/api/subscriptions/{id}/file/delete` | 删除文件夹里的某个视频（联动删种子） |
| POST | `/api/subscriptions/batch` | 批量订阅（按规则优先级依次匹配） |
| POST | `/api/warmup/*` | 预热控制与状态 |

---

## 六、前端结构

- `index.html`：四块视图（在看番剧 / 我的订阅 / 设置 / 运行日志）+ 三个弹窗
  （番剧详情、已下载文件管理、批量订阅设置）
- `app.js`：状态机 + 渲染 + 事件；关键状态 `state.subjects / state.subs / state.selected /
  state.modal / state.batchRules(存 localStorage)`
- `ui.js`：自绘下拉（`.sel`）、主题切换（跟随系统/深色/浅色）、入场动效
- `styles.css`：暖纸+墨色设计系统，含 1280 / 1180 / 760 / 520 断点与 reduced-motion

---

## 七、稳定性设计

| 场景 | 处理 |
| --- | --- |
| qB 掉线 | 进待下载队列，每分钟探测、恢复后自动补；界面沿用旧计数不清零 |
| 搜索慢 | 预热缓存 + 缓存命中不回源；强制刷新单列按钮 |
| Bangumi 限流/离线 | 元数据本地缓存 7 天，断网可用；每天强制联网刷一次（别名/首播日/话数），别名只增不减 |
| 订阅数据误删 | 删除前写 `subscriptions.json.before-delete-*.bak`，最多留 20 份 |
| 迁移脚本改坏字段 | 迁移前逐条校验 `group/sub_group/lang/source_ids/resolution`，一旦会变就整体中止 |
| 按钮卡死 | `withBusy` 30 秒强制恢复 |
| dmhy 返回 500 | 记 `site_errors`，其余站结果照常返回 |

---

## 八、已知限制 / TODO

1. 「按当前筛选订阅」（未选中具体行时的订阅按钮）没有把 `all_seasons` 传下去，
   关掉「只看本季」后表里能看到上一季资源，但按筛选订阅仍按只看本季找
2. 批量订阅设置里的规则优先级提示可以更明确（第几条命中会在结果里标出）
3. 探针 `_probe/shoot_ui_batch.py`、`_probe/cdp_ui.py` 各有一条断言基于旧交互，待更新
4. 按篇章名发的资源（如「凡人修仙传 慕兰之战 16」）标题里是**篇章内集号**，
   命中本季标识后会保留，但显示的是篇章集号，和本季累计集号（177 起）对不上
   例：dmhy 的 16 → 本季第 16 集字面对应 192，实际是这一篇章的第 16 集
5. 剧集解析优先用可选依赖 `aniparse`，未安装时用内置正则
6. 同一番剧多个季若在 Bangumi 章节表里编号重叠（罕见），偏移可能需手工修正
