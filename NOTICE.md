# NOTICE / 声明

- 项目：自动下载番剧（Anime Auto Downloader）
- 版权：Copyright (C) 2026 kelstna
- 许可证：**GPL-3.0-only**（全文见 [LICENSE](LICENSE)）
- 本声明日期：2026-10-12

## 1. 关于作者与 AI

- **本项目全部代码由 AI 编写**：由 AI 助手（DeepSeek，2026-10）按使用者需求逐轮生成与修改，
  **不是人工逐行手写**。任何看到本仓库的人都应以此为前提评估代码质量。
- 本项目是**原创项目**，不是任何现有开源项目的 fork、修改版或衍生作品；仓库内不含第三方源代码副本。
- 版权署名：`kelstna`（GitHub 昵称）。源码文件头部均有
  `SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)` 与
  `SPDX-License-Identifier: GPL-3.0-only`。
- 项目**按「现状」提供**（见第 7 节），使用者自行评估与承担使用风险。

## 2. 这个程序做什么

一个跑在**本机**的小型 Web 服务 + 浏览器界面：从 Bangumi 读取你的「在看」收藏，
到动漫花园（share.dmhy.org）、爱恋动漫（kisssub.org）、Nyaa（nyaa.si）搜索公开的种子资源，
按你选定的字幕组与筛选条件，把磁力链接交给本机 qBittorrent 下载，并在后续剧集更新时自动追番。

## 3. 数据来源与第三方服务

| 来源 | 用途 | 说明 |
| --- | --- | --- |
| Bangumi API (`api.bgm.tv`) | 读取公开收藏与条目信息 | 需使用者自备 Access Token，属于 Bangumi 官方接口 |
| bangumi-data（jsDelivr CDN） | 每集更新时刻（北京时间） | 缓存到本机 `data/airtimes.json`，**仓库不含该数据文件** |
| 动漫花园 / 爱恋动漫 / Nyaa | 搜索公开的种子列表页 | 程序按需抓取**公开搜索页**，不做登录抓取 |
| qBittorrent WebUI | 提交下载任务 | 使用者本机已安装的软件 |

**本仓库不包含上述任何站点的数据副本**（缓存、种子、搜索结果、图片一律在 `.gitignore` 内，
只在运行时生成于本机 `data/` 目录）。

## 4. 工具 ≠ 内容：边界声明

这是一个**工具**，不是内容分发渠道。以下事实是本项目最重要的边界，也是实现上的硬约束：

- **本仓库与程序均不包含任何受版权保护的内容**：没有视频、种子文件、字幕、封面图或抓取结果快照；
  资源由**使用者的设备**在运行时自行从公开站点检索得到。
- **不提供任何服务端中转 / 代理 / 缓存服务**：程序只在本机运行、浏览器与本机服务通信、
  抓取请求由本机直连目标站点。项目没有也不会有自己的服务器。
- **不绕过任何付费 / 会员 / 登录限制**：只访问无需付费、无需登录即可看到的公开页面。
- **明示仅限个人使用**：再分发、商业使用请自行取得相关授权。
- **使用者自负合规责任**：使用本工具产生的任何后果由使用者承担。
- 下载内容（番剧、字幕等）的著作权归各自权利人所有，**请勿传播下载到的内容**。

第三方站点名称与商标归各自所有者；本项目为非官方工具，与它们无关联、未获其背书。

## 5. 仓库内的测试数据

- `tests/fixtures/*.html`：各站**公开搜索页**的少量 HTML 片段，仅用于离线解析单元测试。
- `_probe/*.html`：测试用**伪造页面**（番名、封面、日志均为占位内容），用于 UI 自动化测试。
- 仓库内**没有**任何真实用户的账号信息、Token、下载记录或截图。

## 6. 许可证

本项目以 **GNU General Public License v3.0（GPL-3.0-only）** 授权，全文见 [LICENSE](LICENSE)。

```
Copyright (C) 2026 kelstna

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```

要点（不构成法律意见，以 LICENSE 全文为准）：

- 任何人可以自由使用、修改、再分发本项目，**包括商业用途**。
- 再分发时必须：保留版权与许可证声明、**显著标明修改内容与日期**、**整体仍以 GPL-3.0 授权**、
  并提供**完整的对应源代码**；不得附加任何额外限制。
- GPL 只覆盖本项目的代码；**第三方站点、API、数据源与下载内容仍受各自条款与著作权约束**，
  本许可证不改变这些条款，也不授予任何第三方内容的权利。
- 本项目为非官方工具，第三方名称与商标归各自所有者，未获其背书。

## 7. 免责

本程序按「现状」提供，不附带任何明示或默示的担保。因使用本程序造成的任何损失
（包括但不限于下载失败、磁盘占用、账号风控、与第三方站点的纠纷），作者不承担责任。
