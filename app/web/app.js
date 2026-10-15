/* SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
   SPDX-License-Identifier: GPL-3.0-only */
/* =============================================================================
 * 自动下载番剧 · 前端交互逻辑（app/web/app.js）
 * -----------------------------------------------------------------------------
 * 纯原生 ES2020，无第三方库、无构建步骤，由 app/web/server.py 静态托管。
 *
 * 目录：
 *   0. 常量与配置（接口路径 / 视图元数据 / 阈值）
 *   1. 通用工具（DOM 构造、格式化、剪贴板）
 *   2. 状态文字与 Toast
 *   3. API 客户端（fetch 封装，统一解析 {ok,error}）
 *   4. 视图路由
 *   5. 侧栏状态与资源缓存预热（/api/status · /api/cache/status）
 *   6. Token 与在看番剧列表（卡片 / 筛选 / 多选 / 批量订阅）
 *   7. 详情弹窗（资源列表内直接加入订阅 / 字幕组 / 订阅设置一步订阅 / 补下载模式）
 *   8. 订阅页（检查 / 打开目录 / 补下载单集 / 删除）
 *   9. 设置页（qBittorrent / 下载位置 / 代理 / 资源站 / 自动追番 / 服务）
 *  10. 日志页
 *  11. 「显示噪声项」开关（动态注入资源列表筛选栏）
 *  12. 主题与启动引导
 *
 * 约定：
 *   - DOM 结构、静态 class、全部挂载 id 以 app/web/index.html 为准（本文件不修改它）
 *   - 动态生成的 class 以 app/web/styles.css 为准（.card/.sub-item/.res-row/.num/.state-ok…）
 *   - 弹窗里的表单统一用 .form-grid / .form-cell / .field-tip，状态文字用 .state-ok / .state-err
 *   - 所有文案为中文；空数据 / 502 / token 无效都会给出中文提示，绝不白屏
 * ========================================================================== */
'use strict';

/* =============================================================================
 * 0. 常量与配置
 * ========================================================================== */

/** 后端接口路径（唯一来源，业务代码里不再散落路径字面量）。 */
const API = {
  status:        '/api/status',
  config:        '/api/config',
  token:         '/api/bangumi/token',
  collections:   (type, force) => `/api/bangumi/collections?type=${encodeURIComponent(type)}`
    + (force ? '&force=1' : ''),   // 点按钮时要 force，否则拿到的是缓存里的旧「在看」列表
  search:        '/api/search',
  groups:        '/api/groups',
  subscriptions: '/api/subscriptions',
  subUpdate:     (id) => `/api/subscriptions/${encodeURIComponent(id)}/update`,
  subCheck:      (id) => `/api/subscriptions/${encodeURIComponent(id)}/check`,
  subDelete:     (id) => `/api/subscriptions/${encodeURIComponent(id)}`,
  subscriptionBatch: '/api/subscriptions/batch',
  subFileDelete: (id) => `/api/subscriptions/${encodeURIComponent(id)}/file/delete`,
  groupsCached:  '/api/groups/cached',
  /** 订阅详情里补下载指定单集 / 合集。 */
  subDownload:   (id) => `/api/subscriptions/${encodeURIComponent(id)}/download`,
  subEpisodeDelete: (id) => `/api/subscriptions/${encodeURIComponent(id)}/episodes/delete`,
  checkAll:      '/api/subscriptions/check-all',
  qbTest:        '/api/qb/test',
  qbFolders:     '/api/qb/folders',
  openFolder:    '/api/qb/open-folder',
  logs:          (n) => `/api/logs?n=${encodeURIComponent(n)}`,
  /** 资源缓存：状态 / 清理 / 预热 / 停止预热。 */
  cacheStatus:   '/api/cache/status',
  cacheClear:    '/api/cache/clear',
  cacheWarm:     '/api/cache/warm',
  cacheWarmStop: '/api/cache/warm/stop',
  /** 封面代理：整串编码后作为 <img src>（二进制响应，不走 request()）。 */
  cover:         (url) => `/api/cover?url=${encodeURIComponent(url)}`,
  /** 待下载队列：qBittorrent 掉线期间攒下的资源，恢复后自动补下载。 */
  queue:         '/api/queue',
  queueFlush:    '/api/queue/flush',
  queueDelete:   '/api/queue/delete',
};

/** Bangumi 收藏类型：3 = 在看。 */
const COLLECT_DOING = 3;

/** 视图元数据：#view-title / #view-sub 文案 + 进入视图时的懒加载。 */
const VIEWS = {
  anime:  { title: '在看番剧', sub: '从 Bangumi 拉取你正在追的番剧' },
  subs:   { title: '我的订阅', sub: '后台定时检查更新并自动下载新集', onEnter: () => loadSubscriptions() },
  config: { title: '设置', sub: 'qBittorrent · 下载位置 · 代理 · 资源站 · 自动追番' },
  logs:   { title: '运行日志', sub: '最近 300 行运行记录', onEnter: () => loadLogs() },
};
const VIEW_IDS = ['anime', 'subs', 'config', 'logs'];

/** 资源表列数（与 index.html 的 thead 一致，用于加载/错误行的 colspan）。
 *  顺序：资源站 / 字幕组 / 标题 / 语言 / 分辨率 / 集数 / 大小 / 做种 / 发布 / 操作。 */
const RES_COLUMNS = 10;

/** #s-group / #s-episode 的「不限 / 不下载」文案（与 index.html 首项保持一致）。 */
const GROUP_ANY_TEXT = '不限字幕组（任意组）';
const SUB_EPISODE_NONE = '不下载（仅订阅，之后自动追新）';

/**
 * #s-group 的 value 语义：`<站点 id>::<组名>`，例如 `dmhy::ANi`。
 * 同一个组名在不同资源站是两条独立条目（/api/groups 默认 by_source），
 * 只有带上站点才能表达「就要动漫花园那家 ANi」。
 */
const GROUP_VALUE_SEP = '::';

/** 资源列表筛选条「加入订阅」当前筛选下一条资源都没有时的下一步提示（同时作为按钮 title）。 */
const RES_SUB_NO_PICK_TIP = '当前筛选没有可用资源：放宽筛选条件，或到「订阅设置」里选要下载哪一集';

/** 点了「加入订阅」但按筛选条件搜不到资源时的提示。 */
const RES_SUB_EMPTY_TIP = '当前筛选没有可用资源，请放宽筛选';

/** 选集时的站点优先级：dmhy > kisssub > nyaa，其余站点按配置顺序排在其后。 */
const EPISODE_SOURCE_ORDER = ['dmhy', 'kisssub', 'nyaa'];

/** 补下载模式提示条的 id（动态注入 #tab-res，index.html 不修改）。 */
const BACKFILL_HINT_ID = 'res-mode-hint';

const LOG_LINES = 300;          // 日志页拉取行数
const TOAST_MS = 3000;          // toast 停留时长
const TOAST_MAX = 5;            // 同时最多显示的 toast 数
const SIX_MONTHS_MS = 183 * 24 * 60 * 60 * 1000;   // 「已完结」的日期兜底判断
const NUMBER_FMT = new Intl.NumberFormat('zh-CN');
// 主题的三态状态（模式 + localStorage）统一由 app/web/ui.js 管理，本文件不再持有副本。

/**
 * 视觉自测模式（Chrome headless 截图用）：URL 带 ?mock。
 * 该模式下不主动请求真实后端，数据全部来自测试页预置的 window.fetch，
 * 并在初始化前等待 window.__MOCK_READY__。
 */
const MOCK_MODE = new URLSearchParams(location.search).has('mock');

/** 封面加载失败时的占位图（内联 SVG，无额外网络请求）。 */
const PLACEHOLDER_COVER = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="168">' +
  '<rect width="120" height="168" fill="#211f1c"/>' +
  '<text x="60" y="96" font-size="44" text-anchor="middle" fill="#6b6152">番</text></svg>'
);

/* =============================================================================
 * 1. 通用工具
 * ========================================================================== */

/** 按 id 取元素（所有挂载点都来自 index.html）。 */
const $ = (id) => document.getElementById(id);
/** 查询全部匹配元素，返回真数组。 */
const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

/** 创建元素：el('div', 'card', '文本')。 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

/** 一次性写入多个属性。 */
function attrs(node, map) {
  Object.keys(map).forEach((k) => node.setAttribute(k, String(map[k])));
  return node;
}

/** 绑定事件（元素不存在时静默跳过，避免初始化中断导致白屏）。 */
function on(node, event, handler, options) {
  if (node) node.addEventListener(event, handler, options);
  return node;
}

/** Bangumi 条目详情页地址（用户要求：卡片上能一键跳过去看详情/评论）。 */
function bangumiSubjectUrl(subjectId) {
  const id = String(subjectId === undefined || subjectId === null ? '' : subjectId).trim();
  return id ? `https://bgm.tv/subject/${encodeURIComponent(id)}` : 'https://bgm.tv/';
}

/** 小闹钟图标（下次更新那行用；和 Bangumi 外链按钮同一套描边风格）。 */
const CLOCK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
  + '<circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>';

/** 小对勾图标（已完结那行用）。 */
const CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
  + '<circle cx="12" cy="12" r="8.5" /><path d="M8.2 12.4l2.6 2.6 5-5.4" /></svg>';

/**
 * 番剧卡片上的「下次更新」一行。
 *
 * 卡片窄（约 150px），只显示 `下次更新 10-12 00:20`（**不带周几、不带「北京时间」**，
 * 用户明确要求删掉这几个字，免得被省略号截断）；完整说明放在鼠标悬浮里
 * （精确到年月日的北京时间、日本时间、电视台、数据来源）。
 * 已完结的番显示「已完结」（不再编造下一次更新时间）；没有数据时返回隐藏占位行保证卡片等高。
 */
function airtimeLine(air) {
  const line = el('div', 'card-air');
  const icon = el('span', 'card-air-icon');
  if (air && air.finished) {
    line.classList.add('is-finished');
    icon.innerHTML = CHECK_SVG;
    line.append(icon);
    line.append(el('span', 'card-air-label', air.finished_text || '已完结'));
    if (air.tip) line.title = air.tip;
    return line;
  }
  if (!air || !air.next_text) {
    line.classList.add('is-empty');
    line.setAttribute('aria-hidden', 'true');
    return line;
  }
  const soon = Number(air.next_ts) > 0 && (Number(air.next_ts) - Date.now() / 1000) < 6 * 3600;
  if (soon) line.classList.add('is-soon');
  icon.innerHTML = CLOCK_SVG;
  line.append(icon);
  line.append(el('span', 'card-air-label', '下次更新'));
  // 只要「MM-DD HH:MM」，周几与「北京时间」交给悬浮说明（卡片放不下会被截断）
  line.append(el('span', 'card-air-time', String(air.next_text || '').split('（')[0]));
  if (air.tip) line.title = air.tip;
  return line;
}

/** 订阅卡片上的「下次更新」，塞进 .sub-facts 那一行（同样带悬浮说明）。 */
function airtimeFactItem(air) {
  if (!air) return null;
  if (air.finished) {
    const done = el('span', 'sub-fact sub-fact-air is-finished');
    done.append(el('span', null, '状态'));
    done.append(el('b', 'sub-air-value', air.finished_text || '已完结'));
    if (air.tip) done.title = air.tip;
    return done;
  }
  if (!air.next_text) return null;
  const wrap = el('span', 'sub-fact sub-fact-air');
  const soon = Number(air.next_ts) > 0 && (Number(air.next_ts) - Date.now() / 1000) < 6 * 3600;
  if (soon) wrap.classList.add('is-soon');
  wrap.append(el('span', null, '下次更新：'));
  wrap.append(el('b', 'sub-air-value', `${air.next_text} · 北京时间`));
  if (air.tip) wrap.title = air.tip;
  return wrap;
}

/**
 * Bangumi 跳转小按钮（外链图标）。
 * 用在卡片封面右上角：玻璃拟态、和左上角的复选框对称，不抢封面画面（用户要求「注意美观」）。
 * 点它只开新标签页，不要触发卡片本身的「打开详情弹窗」。
 */
function bangumiLink(subjectId, className) {
  const a = el('a', className || 'card-bgm');
  a.href = bangumiSubjectUrl(subjectId);
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.title = '在 Bangumi 打开详情页';
  a.setAttribute('aria-label', '在 Bangumi 打开详情页');
  a.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    + '<path d="M14 4h6v6" /><path d="M20 4l-8.5 8.5" />'
    + '<path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10" />'
    + '</svg>';
  // 卡片整体有点击事件（打开弹窗）：这里必须阻止冒泡，否则点链接会顺带弹窗
  on(a, 'click', (e) => e.stopPropagation());
  on(a, 'pointerdown', (e) => e.stopPropagation());
  return a;
}

/** 带 title 的文本节点（长文本省略号 + 悬浮提示）。 */
function titled(className, text) {
  const node = el('span', className, text);
  node.title = text === undefined || text === null ? '' : String(text);
  return node;
}

function setText(id, text) {
  const node = $(id);
  if (node) node.textContent = (text === undefined || text === null) ? '' : String(text);
}

function setTitle(id, text) {
  const node = $(id);
  if (node) node.title = (text === undefined || text === null) ? '' : String(text);
}

/** 读取输入框 / select 的字符串值。 */
function val(id) {
  const node = $(id);
  if (!node) return '';
  return String(node.value === undefined || node.value === null ? '' : node.value);
}

function checked(id) {
  const node = $(id);
  return !!(node && node.checked);
}

/** select 是否已被 ui.js 的自绘下拉接管（ui.js 会把 .sel 包在 select 之后）。 */
function hasCustomSelect(sel) {
  const wrap = sel && sel.nextElementSibling;
  return !!(wrap && wrap.classList.contains('sel'));
}

/**
 * 写 select 值；目标值不在选项里时先补一个选项（避免静默失效）。
 * ui.js 的自绘面板以原生 select 为真值来源，靠 change 事件 / DOM 变更同步显示文本，
 * 而「脚本直接写 value」这两者都不产生 —— 不补一下，自绘面板会停在上一个值
 * （原生 select 的值其实已经变了，用户看到的却是旧文案）。
 * 因此在值真的变化、且该 select 已被自绘接管时补派一次 change；其余情况保持原语义。
 */
function setSelectValue(sel, value) {
  if (!sel) return;
  const want = (value === undefined || value === null) ? '' : String(value);
  if (want && !Array.from(sel.options).some((o) => o.value === want)) {
    const opt = el('option', null, want);
    opt.value = want;
    sel.append(opt);
  }
  const before = String(sel.value);
  sel.value = want;
  if (String(sel.value) !== before && hasCustomSelect(sel)) {
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

function setValue(id, value) {
  const node = $(id);
  if (!node) return;
  if (node.tagName === 'SELECT') {
    setSelectValue(node, value);
    return;
  }
  node.value = (value === undefined || value === null) ? '' : String(value);
}

function setChecked(id, value) {
  const node = $(id);
  if (node) node.checked = !!value;
}

function clear(id) {
  const node = $(id);
  if (node) node.replaceChildren();
}

function show(id, visible) {
  const node = $(id);
  if (node) node.hidden = !visible;
}

/** 设置空状态区（.empty）里的说明文字。 */
function setEmptyText(id, text) {
  const node = $(id);
  if (!node) return;
  const p = node.querySelector('p');
  if (p) p.textContent = String(text || '');
  else node.textContent = String(text || '');
}

/** 数值格式化（空值显示破折号，保持列宽一致）。 */
function fmtInt(value, dash) {
  const n = Number(value);
  return Number.isFinite(n) ? NUMBER_FMT.format(n) : (dash === undefined ? '–' : dash);
}

/** 缓存年龄（秒）→ 中文相对时间：刚刚 / 3 分钟前 / 2 小时前 / 3 天前。 */
function cacheAgeText(seconds) {
  const s = Number(seconds);
  if (!Number.isFinite(s) || s <= 0) return '';
  if (s < 60) return '刚刚';
  const minutes = Math.floor(s / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

/** 种子大小：优先后端给的 size_text，其次 size_bytes。 */
function fmtSize(resource) {
  const text = String((resource && resource.size_text) || '').trim();
  if (text) return text;
  const bytes = Number(resource && resource.size_bytes) || 0;
  if (bytes <= 0) return '–';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${i === 0 ? v.toFixed(0) : v.toFixed(2)} ${units[i]}`;
}

/** Unix 秒 -> 'YYYY-MM-DD HH:mm'。 */
function fmtTime(ts, dash) {
  const n = Number(ts);
  const fallback = dash === undefined ? '从未' : dash;
  if (!Number.isFinite(n) || n <= 0) return fallback;
  const d = new Date(n * 1000);
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** 距离目标时间的中文描述（用于「下次运行」）。 */
function fmtCountdown(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '–';
  const diff = n * 1000 - Date.now();
  if (diff <= 0) return '即将执行';
  const minutes = Math.round(diff / 60000);
  if (minutes < 60) return `${minutes} 分钟后`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分钟后`;
}

function timeNow() {
  const d = new Date();
  const pad = (x) => String(x).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** 番剧总话数（total_episodes 优先，其次 eps）。 */
function totalEpisodesOf(subject) {
  if (!subject) return 0;
  return Number(subject.total_episodes) || Number(subject.eps) || 0;
}

/**
 * 番剧展示名：优先 Bangumi 简体名（display_name / name_cn），最后才回退日文原名。
 * 后端 display_name 缺失（接口降级 / 字段变更）时也不能退回日文名。
 */
function subjectName(subject) {
  if (!subject) return '';
  const raw = subject.display_name || subject.name_cn || subject.name
    || (subject.id === undefined || subject.id === null ? '' : `subject-${subject.id}`);
  return String(raw || '').trim();
}

/** 订阅展示名：优先简体名，其次原名。 */
function subscriptionName(sub) {
  if (!sub) return '';
  const raw = sub.display_name || sub.name || sub.name_original
    || (sub.subject_id === undefined || sub.subject_id === null ? '' : `subject-${sub.subject_id}`);
  return String(raw || '').trim();
}

/** Windows 非法字符（与后端 core/util.py 的 _WIN_FORBIDDEN 一致）。 */
const WIN_FORBIDDEN = '<>:"/\\|?*';
const WIN_RESERVED = ['CON', 'PRN', 'AUX', 'NUL',
  ...Array.from({ length: 9 }, (_, i) => `COM${i + 1}`),
  ...Array.from({ length: 9 }, (_, i) => `LPT${i + 1}`)];

/** 目录名净化：与后端 util.sanitize_name 行为保持一致，避免预填出非法路径。 */
function sanitizeName(name, fallback, maxLen) {
  const limit = maxLen || 120;
  const text = String(name || '').replace(/\u3000/g, ' ');
  if (!text) return fallback || '未命名';
  let out = '';
  for (const ch of text) {
    if (WIN_FORBIDDEN.includes(ch) || ch.charCodeAt(0) < 32) continue;
    out += ch;
  }
  let clean = out.replace(/\s+/g, ' ').trim().replace(/[. ]+$/, '');
  if (!clean) return fallback || '未命名';
  const head = clean.split('.')[0].toUpperCase();
  if (WIN_RESERVED.includes(clean.toUpperCase()) || WIN_RESERVED.includes(head)) clean = `_${clean}`;
  if (clean.length > limit) clean = clean.slice(0, limit).replace(/[. ]+$/, '');
  return clean || fallback || '未命名';
}

/** 拼接下载目录（Windows 风格，与后端 os.path.join 结果保持一致）。 */
function joinPath(root, name) {
  const base = String(root || '').trim();
  const safe = String(name || '').trim() || '未命名';
  if (!base) return safe;
  return base.replace(/[\\/]+$/, '') + '\\' + safe;
}

/** 字幕组名归一化（与后端 engine.normalize_group 对齐的宽松匹配）。 */
function normGroup(name) {
  return String(name || '')
    .trim()
    .replace(/^[\[【]|[\]】]$/g, '')
    .replace(/[\s_\-　]+/g, '')
    .toLowerCase();
}

function groupMatch(resourceGroup, want) {
  const a = normGroup(resourceGroup);
  const b = normGroup(want);
  if (!b) return true;
  if (!a) return false;
  return a === b || a.includes(b) || b.includes(a);
}

/**
 * 拆开 #s-group 的 value：'dmhy::ANi' -> {source:'dmhy', name:'ANi'}。
 * 没有 '::' 时按老格式处理（纯组名，站点留空），保证旧订阅 / 旧后端也能用。
 */
function splitGroupValue(value) {
  const raw = String(value || '').trim();
  const at = raw.indexOf(GROUP_VALUE_SEP);
  if (at < 0) return { source: '', name: raw, raw };
  return {
    source: raw.slice(0, at).trim(),
    name: raw.slice(at + GROUP_VALUE_SEP.length).trim(),
    raw,
  };
}

/** 组合 #s-group 的 value：站点已知时是 '<站点>::<组名>'，未知时退化成纯组名。 */
function joinGroupValue(source, name) {
  const site = String(source || '').trim();
  const group = String(name || '').trim();
  if (!group) return '';
  return site ? `${site}${GROUP_VALUE_SEP}${group}` : group;
}

/** 站点显示名：优先 /api/status 与 /api/config 里的 name，查不到就原样返回 id。 */
function sourceDisplayName(id) {
  const key = String(id || '').trim();
  if (!key) return '';
  const lists = [
    (state.status && state.status.sources) || [],
    (state.config && state.config.sources) || [],
    state.sources || [],
  ];
  for (let i = 0; i < lists.length; i += 1) {
    const list = Array.isArray(lists[i]) ? lists[i] : [];
    const hit = list.find((s) => s && String(s.id || '').trim() === key);
    if (hit && String(hit.name || '').trim()) return String(hit.name).trim();
  }
  return key;
}

/** 「动漫花园 · ANi」；没有站点信息时只显示组名。 */
function groupDisplayText(source, name) {
  const site = sourceDisplayName(source);
  const group = String(name || '').trim();
  if (!group) return site;
  return site ? `${site} · ${group}` : group;
}

/**
 * 订阅里能唯一确定的站点：source_ids 恰好一个时才敢用（多个说明是跨站订阅，不能瞎猜）。
 * 后端把带站点的字幕组存在 sub_group 里，老订阅只有 group + source_ids，这里做兜底。
 */
function subscriptionSourceId(sub) {
  if (!sub) return '';
  const raw = sub.source_ids;
  const ids = (Array.isArray(raw) ? raw : String(raw || '').split(','))
    .map((x) => String(x || '').trim())
    .filter(Boolean);
  return ids.length === 1 ? ids[0] : '';
}

/** 资源唯一键（infohash 优先）。 */
function resourceKey(r) {
  if (!r) return '';
  if (r.infohash) return String(r.infohash).toLowerCase();
  return `${r.source || ''}:${String(r.title || '').trim().toLowerCase()}`;
}

/** 集数展示：单集 / 区间 / 合集。 */
function episodeText(r) {
  if (!r) return '–';
  if (r.is_batch) {
    return (r.episode || r.episode_end) ? `合集 ${r.episode || r.episode_end}+` : '合集';
  }
  if (r.episode === null || r.episode === undefined) return '–';
  if (r.episode_end && r.episode_end !== r.episode) return `${r.episode}-${r.episode_end}`;
  return String(r.episode);
}

/** 封面：走后端代理，失败回落占位图。mock 模式下不打网络，只认 data URL 或占位图。 */
function setCover(img, url) {
  if (!img) return;
  const target = String(url || '').trim();
  if (MOCK_MODE) {
    img.src = target.startsWith('data:') ? target : PLACEHOLDER_COVER;
    return;
  }
  if (!target) {
    img.src = PLACEHOLDER_COVER;
    return;
  }
  img.onerror = () => {
    img.onerror = null;
    img.src = PLACEHOLDER_COVER;
  };
  img.src = API.cover(target);
}

/** 复制文本（Clipboard API 优先，非安全上下文回落 execCommand）。 */
async function copyText(text) {
  const value = String(text || '');
  if (!value) return false;
  if (navigator.clipboard && window.isSecureContext !== false) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch (err) { /* 继续尝试回落方案 */ }
  }
  try {
    const area = el('textarea');
    area.value = value;
    area.setAttribute('readonly', 'readonly');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch (err) {
    return false;
  }
}

/** 请求期间的忙碌态：disabled + .is-loading（容器无 disabled 属性时只加 class）。 */
async function withBusy(nodes, fn) {

  const restore = () => {
    list.forEach((item) => {
      if ('disabled' in item.node) item.node.disabled = item.disabled;
      item.node.classList.remove('is-loading');
      if (!item.hadAttr) item.node.removeAttribute('aria-busy');
    });
  };
  const timer = setTimeout(() => { try { restore(); } catch (e) {} }, 30000);
  const list = (Array.isArray(nodes) ? nodes : [nodes]).filter(Boolean);
  const saved = list.map((node) => ({
    node,
    disabled: node.disabled,
    hadAttr: node.hasAttribute('aria-busy'),
  }));
  list.forEach((node) => {
    if ('disabled' in node) node.disabled = true;
    node.classList.add('is-loading');
    node.setAttribute('aria-busy', 'true');
  });
  try {
    return await fn();
  } finally {
    clearTimeout(timer);
    saved.forEach(({ node, disabled, hadAttr }) => {
      if ('disabled' in node) node.disabled = !!disabled;
      node.classList.remove('is-loading');
      if (!hadAttr) node.removeAttribute('aria-busy');
    });
  }
}

/* =============================================================================
 * 2. 状态文字与 Toast
 * ========================================================================== */

/** 绿色成功文字（.state-ok）。 */
function showOk(node, message) {
  if (!node) return;
  node.classList.remove('state-err');
  node.classList.add('state-ok');
  node.textContent = String(message || '');
}

/** 红色错误文字（.state-err）。 */
function showError(node, message) {
  if (!node) return;
  node.classList.remove('state-ok');
  node.classList.add('state-err');
  node.textContent = String(message || '');
}

/** 中性提示文字。 */
function showInfo(node, message) {
  if (!node) return;
  node.classList.remove('state-ok', 'state-err');
  node.textContent = String(message || '');
}

/** 通知外部（截图脚本等）某块界面已渲染完成。 */
function announce(view) {
  document.dispatchEvent(new CustomEvent('app:rendered', { detail: { view } }));
}

/** 右下角轻提示。kind: 'ok' | 'err' | 'info'；3 秒后加 .is-out 淡出。 */
function toast(message, kind, ms) {
  const box = $('toasts');
  if (!box) return;
  const type = (kind === 'ok' || kind === 'err') ? kind : 'info';
  const node = el('div', `toast toast-${type}`, message);
  box.append(node);
  while (box.children.length > TOAST_MAX) box.firstElementChild.remove();
  window.setTimeout(() => {
    node.classList.add('is-out');
    window.setTimeout(() => node.remove(), 400);
  }, ms || TOAST_MS);
}

/* =============================================================================
 * 3. API 客户端
 * ========================================================================== */

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status || 0;
  }
}

/**
 * 统一请求封装：
 *   - 自动 JSON 序列化请求体
 *   - 自动解析 {ok:false,error} 与 HTTP 状态码，抛出中文 ApiError
 *   - 非 JSON / 断连时给出明确提示（调用方渲染错误态，不白屏）
 */
async function request(path, options) {
  const opts = options || {};
  const init = { method: opts.method || 'GET', headers: { Accept: 'application/json' } };
  if (opts.body !== undefined && opts.body !== null) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }

  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new ApiError('无法连接本地服务，请确认后台进程仍在运行', 0);
  }

  let text = '';
  try {
    text = await res.text();
  } catch (err) {
    text = '';
  }

  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (err) {
      data = null;
    }
  }

  if (data && data.ok === false) throw new ApiError(data.error || '请求被拒绝', res.status);
  if (!res.ok) throw new ApiError((data && data.error) || `服务返回 HTTP ${res.status}`, res.status);
  if (data === null) throw new ApiError('服务返回了非预期的数据格式', res.status);
  return data;
}

/* =============================================================================
 * 4. 全局状态 + 视图路由
 * ========================================================================== */

const state = {
  view: 'anime',
  config: null,           // GET /api/config
  status: null,           // GET /api/status
  tokenSet: false,
  subjects: [],           // 在看番剧原始数据
  visible: [],            // 当前可见（筛选后）的番剧
  selected: new Set(),    // 勾选的 subject_id
  subs: [],               // 订阅列表
  sources: [],            // 设置页资源站（数组顺序 = 优先级顺序）
  modal: null,            // 详情弹窗状态
};

/* ---------------------------------------------------------------------------
 * ui.js 集成：自绘下拉框的接管时机
 * ui.js 启动时就会接管页面上的全部 select（包括藏在未激活 tab / 视图里的），
 * 正常情况下这里不需要做任何事；保留这个幂等兜底是为了：
 *   1. ui.js 版本差异（老缓存版本只在 select 可见时才接管）；
 *   2. 以后若新插入的 select 出现在刚显示的容器里，ui.js 的观察器要等一帧才扫到，
 *      主动叫一次可以立刻变成自绘样式。
 * window.__ui 缺席时静默跳过，原生 select 依旧可用。
 * ------------------------------------------------------------------------ */
function enhanceSelects() {
  const ui = window.__ui;
  if (!ui || typeof ui.enhanceAll !== 'function') return;
  try {
    ui.enhanceAll(document);
  } catch (err) { /* 自绘失败不影响原生 select 的可用性 */ }
}

/** 切换视图：侧栏 .is-active、#view-* 的 hidden、标题与副标题。 */
function switchView(name) {
  const key = VIEWS[name] ? name : 'anime';
  const meta = VIEWS[key];
  state.view = key;
  $$('#nav .nav-item').forEach((btn) => btn.classList.toggle('is-active', btn.dataset.view === key));
  VIEW_IDS.forEach((v) => {
    const section = $('view-' + v);
    if (section) section.hidden = v !== key;
  });
  document.body.dataset.view = key;
  setText('view-title', meta.title);
  setText('view-sub', meta.sub);
  enhanceSelects();          // 设置页里的下拉刚变可见，交给 ui.js 接管
  if (key === 'config') ensureCachePanel();   // 设置页的「资源缓存」面板（动态注入）
  if (typeof meta.onEnter === 'function') meta.onEnter();
}

/**
 * 弹窗内的两个 tab：资源列表 / 订阅设置。
 * 「选择字幕组」已并入订阅设置里的 #s-group 下拉，index.html 只留 hidden 占位，
 * 所以这里不含 group，未知的 tab 名一律回落到资源列表（避免误显示隐藏占位）。
 */
function switchTab(name) {
  const key = (name === 'sub') ? 'sub' : 'res';
  $$('#m-tabs .tab').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.tab === key));
  const map = { res: 'tab-res', sub: 'tab-sub' };
  Object.keys(map).forEach((k) => show(map[k], k === key));
  enhanceSelects();          // 刚显示的 tab 里的下拉（如订阅设置的字幕组/集数）交给 ui.js
}

/* =============================================================================
 * 5. 侧栏状态
 * ========================================================================== */

/** 圆点状态：'ok' | 'bad' | 'warn' | 'idle'。 */
function setDot(id, kind) {
  const node = $(id);
  if (!node) return;
  node.classList.remove('dot-ok', 'dot-bad', 'dot-warn', 'dot-idle');
  node.classList.add(`dot-${kind === 'ok' || kind === 'bad' || kind === 'warn' ? kind : 'idle'}`);
}

/** GET /api/status：刷新侧栏状态与版本号。 */
async function refreshStatus() {
  try {
    const st = await request(API.status);
    state.status = st;
    state.tokenSet = !!st.token_set;
    setText('app-version', `v${st.version || '1.2'}`);
    if (state.config && state.config.server) renderLanHint(state.config.server);   // 局域网地址可能刚变

    setDot('dot-bgm', st.token_set ? 'ok' : 'idle');
    setText('st-bgm', st.token_set ? '已配置' : '未配置');
    setTitle('st-bgm', st.token_set ? 'Access Token 已保存' : '请在「在看番剧」页填写 Bangumi Access Token');

    const qb = st.qb || {};
    setDot('dot-qb', qb.ok ? 'ok' : 'bad');
    // 后端返回的 version 有时自带 'v' 前缀（如 v5.2.1.10），统一后只保留一个 v
    const qbVersion = String(qb.version || '').replace(/^v/i, '');
    setText('st-qb', qb.ok ? `已连接 ${qbVersion ? `v${qbVersion}` : ''}`.trim() : '未连接');
    setTitle('st-qb', qb.ok ? (qb.base_url || '') : (qb.error || 'qBittorrent 未连接'));

    const px = st.proxy || {};
    const pxParts = [];
    if (px.for_bangumi) pxParts.push('Bangumi');
    if (px.for_sources) pxParts.push('资源站');
    setDot('dot-proxy', px.enabled ? 'ok' : 'idle');
    setText('st-proxy', px.enabled ? (px.url || '已启用') : '关闭');
    setTitle('st-proxy', px.enabled
      ? `作用于 ${pxParts.join('/') || '无'}，不代理 qBittorrent`
      : '未启用（直连）');

    const w = st.watcher || {};
    if (w.running) {
      setDot('dot-watch', 'ok');
      setText('st-watch', '检查中');
    } else if (w.enabled) {
      setDot('dot-watch', 'ok');
      setText('st-watch', `已启用 ${fmtInt(w.interval_minutes, '30')} 分`);
    } else {
      setDot('dot-watch', 'idle');
      setText('st-watch', '已停用');
    }
    setTitle('st-watch', `上次运行 ${fmtTime(w.last_run)} · 下次 ${fmtTime(w.next_run)}` +
      (w.last_summary ? ` · ${w.last_summary}` : ''));

    setText('st-root', st.download_root || '未设置');
    setTitle('st-root', st.download_root || '未设置下载根目录');
    setText('nav-count-subs', String(Number(st.subscriptions) || 0));

    renderQueue(st.queue);

    // 资源缓存预热进度（老后端没有 warmup 字段时这一行保持隐藏）
    renderWarmup(st.warmup);
    syncWarmupPolling(st.warmup);
  } catch (err) {
    // 状态栏失败不影响其它功能，只把状态标成异常
    ['dot-bgm', 'dot-qb', 'dot-proxy', 'dot-watch'].forEach((id) => setDot(id, 'bad'));
    setText('st-bgm', '服务未就绪');
    setText('st-qb', '服务未就绪');
    setText('st-proxy', '服务未就绪');
    setText('st-watch', '服务未就绪');
    setText('st-root', '–');
    toast(`状态读取失败：${err.message}`, 'err');
  }
}

/* =============================================================================
 * 5a-2. 待下载队列（qBittorrent 掉线期间攒下的资源）
 * ========================================================================== */

/**
 * 侧栏「待下载」行 + 恢复提示。
 *
 * 用户场景：番剧更新时 qBittorrent 没开 → 下载不了 → 之后再打开也不会补。
 * 现在后端会先把资源存进队列（data/pending.json），恢复连接后自动补下载；
 * 这里负责把「还有几集在等」显示出来，并在补成功时给个提示。
 */
function renderQueue(queue, opts) {
  const box = $('row-pending');
  if (!box) return;
  const q = queue || {};
  const count = Number(q.count) || 0;
  const prev = Number(state.queueCount) || 0;
  state.queue = q;
  state.queueCount = count;

  box.hidden = count <= 0;
  if (count > 0) {
    const items = Array.isArray(q.items) ? q.items : [];
    const subjects = Number(q.subjects) || 0;
    setText('st-pending', `${fmtInt(count, '0')} 集`);
    const lines = items.slice(0, 4).map((it) => {
      const ep = Number(it.episode) > 0 ? `第 ${it.episode} 集` : '该资源';
      return `· ${it.name || it.title} ${ep}`;
    });
    const more = items.length > 4 ? `\n…还有 ${items.length - 4} 条` : '';
    const err = q.last_error ? `\n最近一次失败：${q.last_error}` : '';
    box.title = `qBittorrent 未连接，这 ${count} 集已排队，恢复连接后会自动补下载` +
      `（涉及 ${subjects} 部番）\n${lines.join('\n')}${more}${err}\n\n点这里立刻重试`;
    setDot('dot-pending', 'warn');
  } else {
    setText('st-pending', '0');
    box.removeAttribute('title');
  }

  // 从「有一批在等」变成「清空」= qBittorrent 回来了，补下载完成，提示一下
  // （主动点「补下载」时由 flushQueue 自己提示，这里不再重复弹一条）
  if (prev > 0 && count === 0 && !(opts && opts.silent)) {
    toast(`qBittorrent 已恢复：${prev} 集待下载已自动补上`, 'ok');
  }
}

/** 立刻重试补下载（侧栏那一行 / 订阅页的按钮都走它）。 */
async function flushQueue(button) {
  const run = async () => {
    try {
      const data = await request(API.queueFlush, { method: 'POST', body: {} });
      const n = Number(data.flushed) || 0;
      renderQueue(data.queue, { silent: true });
      if (n > 0) {
        toast(`已补下载 ${n} 集${data.remaining ? `，还剩 ${data.remaining} 集在排队` : ''}`, 'ok');
        await loadSubscriptions();
      } else {
        toast('qBittorrent 里没有可补下载的项', 'ok');
      }
      refreshStatus();
    } catch (err) {
      toast(err.message || '补下载失败', 'err');
      refreshStatus();
    }
  };
  if (button) await withBusy(button, run);
  else await run();
}

/* =============================================================================
 * 5b. 资源缓存：预热进度行 + 轮询（接口 /api/status · /api/cache/status）
 * ========================================================================== */

let warmupTimer = null;          // 预热进行中的轮询定时器（结束后必须清掉）

/** 预热进度行：动态插在「Token 面板」之后（index.html 不新增挂载点）。 */
function ensureWarmupLine() {
  const panel = $('token-panel');
  if (!panel) return null;
  let line = $('warmup-line');
  if (!line || !document.contains(line)) {
    line = el('p', 'muted small');
    line.id = 'warmup-line';
    line.hidden = true;
    panel.after(line);
  }
  return line;
}

/** 预热进度行文案：「正在预热资源…已缓存资源 12/36 · 命中缓存 3 · 6.2 MB」。 */
function warmupText(w) {
  const info = w || {};
  const total = Number(info.total) || 0;
  const done = Number(info.done) || 0;
  const cached = Number(info.cached) || 0;
  const failed = Number(info.failed) || 0;
  const parts = [`已缓存资源 ${fmtInt(done)}/${fmtInt(total)}`];
  if (cached) parts.push(`命中缓存 ${fmtInt(cached)}`);
  if (failed) parts.push(`失败 ${fmtInt(failed)}`);
  if (info.current) parts.push(`当前 ${info.current}`);
  const bytes = Number(info.bytes !== undefined ? info.bytes : info.size_bytes);
  if (Number.isFinite(bytes) && bytes > 0) parts.push(`${(bytes / 1048576).toFixed(1)} MB`);
  return `${info.running ? '正在预热资源…' : '资源缓存：'}${parts.join(' · ')}`;
}

/** 渲染预热进度行；没有可用数据（老后端 / 缓存未启用）时隐藏，不占位。 */
function renderWarmup(w) {
  const line = ensureWarmupLine();
  const info = w || {};
  const hasData = info.total !== undefined || info.running !== undefined;
  lastWarmup = hasData ? info : null;
  renderCachePanelState();
  if (!line) return;
  // 既没在跑、又一条都没缓存过：没必要在页面上留一行 0/0
  const idleEmpty = !info.running && !(Number(info.done) || 0) && !(Number(info.total) || 0);
  if (!hasData || idleEmpty) {
    line.hidden = true;
    line.replaceChildren();
    return;
  }
  const text = warmupText(info);
  line.textContent = text;
  line.title = text;
  line.hidden = false;
}

/** 预热进行中每 4 秒刷一次 /api/cache/status；结束后停止轮询（避免空转）。 */
function syncWarmupPolling(warmup) {
  const running = !!(warmup && warmup.running);
  if (running && !warmupTimer) {
    warmupTimer = window.setInterval(refreshCacheStatus, 4000);
  } else if (!running && warmupTimer) {
    window.clearInterval(warmupTimer);
    warmupTimer = null;
  }
}

/** GET /api/cache/status：刷新进度行与轮询状态（接口不存在时静默）。 */
async function refreshCacheStatus() {
  try {
    const data = await request(API.cacheStatus);
    const warmup = data.warmup || data;
    renderWarmup(warmup);
    syncWarmupPolling(warmup);
  } catch (err) {
    syncWarmupPolling(null);          // 拿不到状态就别再轮询，避免刷屏报错
  }
}

/* =============================================================================
 * 6. Token 与在看番剧
 * ========================================================================== */

/** #btn-save-token：POST /api/bangumi/token（401 显示红字）。 */
async function saveToken() {
  const input = $('token-input');
  const node = $('token-state');
  const token = input ? input.value.trim() : '';
  if (!token) {
    showError(node, '请先粘贴 Bangumi Access Token（留空表示不修改已保存的 Token）');
    return;
  }
  await withBusy($('btn-save-token'), async () => {
    showInfo(node, '正在验证 Token…');
    try {
      const data = await request(API.token, { method: 'POST', body: { token } });
      const user = data.user || {};
      const who = user.nickname || user.username || `uid ${user.id === undefined ? '?' : user.id}`;
      state.tokenSet = true;
      if (input) {
        input.value = '';
        input.placeholder = `已保存（${who}）· 留空表示不修改`;
      }
      showOk(node, `Token 验证通过，欢迎 ${who}`);
      toast(`Token 已保存：${who}`, 'ok');
      await refreshStatus();
      await loadAnime();      // 保存成功后顺手拉取，省一次点击
    } catch (err) {
      if (err.status === 401) {
        state.tokenSet = false;
        setDot('dot-bgm', 'bad');
        setText('st-bgm', '令牌无效');
        showError(node, `Token 无效或已过期：${err.message}`);
      } else {
        showError(node, `验证失败：${err.message}`);
      }
      toast('Token 保存失败', 'err');
    }
  });
}

/** 判断「已完结」：优先用后端算好的 airtime.finished（bangumi-data 的首播+周期+总话数），
 *  信息不足时退回旧规则（看到最后一话 / 首播超过半年），宁多显示不少显示。 */
function isFinished(subject) {
  const air = subject.airtime || {};
  if (air.finished === true) return true;
  const total = totalEpisodesOf(subject);
  const watched = Number(subject.ep_status) || 0;
  if (total > 0 && watched >= total) return true;
  if (total > 0 && subject.date) {
    const aired = Date.parse(subject.date);
    if (Number.isFinite(aired) && Date.now() - aired > SIX_MONTHS_MS) return true;
  }
  return false;
}

/** 名称匹配：#anime-filter（简体名 / 日文名 / 别名 / 英文名）。 */
function matchKeyword(subject, keyword) {
  if (!keyword) return true;
  const pool = [subject.display_name, subject.name, subject.name_cn, subject.english_name]
    .concat(Array.isArray(subject.aliases) ? subject.aliases : []);
  return pool.some((item) => String(item || '').toLowerCase().includes(keyword));
}

function visibleSubjects() {
  const keyword = val('anime-filter').trim().toLowerCase();
  const onlyAiring = checked('only-airing');
  return state.subjects.filter((s) => {
    if (!matchKeyword(s, keyword)) return false;
    if (onlyAiring && isFinished(s)) return false;
    return true;
  });
}

/** 空状态区（#anime-empty）文案 + 清空网格。 */
function showAnimeEmpty(message) {
  const grid = $('anime-grid');
  const empty = $('anime-empty');
  if (grid) grid.replaceChildren();
  setEmptyText('anime-empty', message);
  if (empty) empty.hidden = false;
}

/** 渲染番剧卡片网格。 */
function renderAnime() {
  const grid = $('anime-grid');
  const empty = $('anime-empty');
  if (!grid) return;

  const list = visibleSubjects();
  state.visible = list;
  // 筛选变化后，把「已经看不见的番剧」从勾选里剔除：
  // 否则先全选 → 再勾「只看在播」→ 再取消全选，被隐藏的那些仍然留在 state.selected 里
  const visibleIds = new Set(list.map((s) => Number(s.id)));
  [...state.selected].forEach((id) => { if (!visibleIds.has(Number(id))) state.selected.delete(id); });
  grid.replaceChildren(...list.map(buildAnimeCard));

  // 首次进入的一次出场：封面按阅读顺序依次出现；之后筛选/勾选的重渲染不再重播
  if (state.firstPaintGrid !== false) {
    state.firstPaintGrid = false;
    grid.classList.add('is-entering');
    window.setTimeout(() => grid.classList.remove('is-entering'), 900);
  }

  const hasData = state.subjects.length > 0;
  if (empty) {
    empty.hidden = list.length > 0;
    if (list.length === 0) {
      setEmptyText('anime-empty', hasData
        ? '没有符合筛选条件的番剧：试试取消「仅显示在播/未完结」或清空筛选框。'
        : '还没有数据。填写 Token 后点击「拉取在看番剧」。');
    }
  }
  setText('nav-count-anime', hasData ? String(state.subjects.length) : '–');
  updateSelectionUI();
  announce('anime');
}

/**
 * 单张番剧卡：
 *   .card > .card-check + .card-cover>.cover-img + .card-badges + .card-body
 */
function buildAnimeCard(subject) {
  const id = Number(subject.id);
  const card = el('article', 'card');
  card.dataset.id = String(subject.id);
  if (subject.subscribed) card.classList.add('is-subscribed');
  // 已完结的番仍然显示（用户要求「在看里的都要在这里显示」），只是弱化一点 + 卡片上写「已完结」
  if (isFinished(subject)) card.classList.add('is-finished');

  // 左上角复选框：点击不触发卡片打开
  const checkWrap = el('label', 'card-check');
  checkWrap.title = '勾选后可批量选择';
  const box = el('input');
  box.type = 'checkbox';
  box.value = String(subject.id);
  box.checked = state.selected.has(id);
  box.setAttribute('aria-label', `选择 ${subjectName(subject) || subject.id}`);
  on(box, 'change', () => toggleSelect(id, box.checked));
  on(box, 'click', (e) => e.stopPropagation());
  on(checkWrap, 'click', (e) => e.stopPropagation());
  checkWrap.append(box);

  const coverWrap = el('div', 'card-cover');
  const img = el('img', 'cover-img');
  img.loading = 'lazy';
  img.alt = subjectName(subject);
  setCover(img, subject.cover_medium || subject.cover);
  coverWrap.append(img);
  // 右上角：跳 Bangumi 详情页（与左上角复选框对称；点它不会打开弹窗）
  coverWrap.append(bangumiLink(subject.id));

  const badges = el('div', 'card-badges');
  if (subject.subscribed) badges.append(el('span', 'badge badge-ok', '已订阅'));
  // 资源已预热的番剧：卡片上加一枚小标记，鼠标悬停显示缓存年龄
  const cachedCount = Number(subject.resources_cached_count) || 0;
  if (subject.resources_cached || cachedCount > 0) {
    const age = cacheAgeText(subject.resources_cached_age);
    const badge = el('span', 'badge badge-cache', cachedCount > 0 ? `已缓存 ${fmtInt(cachedCount)}` : '已缓存');
    badge.title = `资源已缓存${age ? ` · ${age}` : ''}（打开详情秒显示，点「重新搜索」可联网刷新）`;
    badges.append(badge);
  }
  // 必须挂在封面容器内：标记是绝对定位，挂在 .card 上会落到卡片底部，
  // 正好压住「话数 / 日期 / 评分」那一行（用户反馈被挡住）。
  if (badges.children.length) coverWrap.append(badges);

  const body = el('div', 'card-body');
  const titleText = subjectName(subject) || `#${subject.id}`;
  body.append(titled('card-title', titleText));
  // 只显示中文简体名：原名放到 title 悬浮提示里，卡片上不再占一行（用户要求）
  const nameJp = subject.name || '';
  if (nameJp && nameJp !== titleText) card.title = `${titleText}\n${nameJp}`;

  const meta = el('div', 'card-meta');
  meta.append(el('span', 'tag', `${fmtInt(totalEpisodesOf(subject), '?')} 话`));
  if (subject.date) meta.append(el('span', 'tag', subject.date));
  if (Number(subject.score) > 0) meta.append(el('span', 'tag', `★ ${Number(subject.score).toFixed(1)}`));
  body.append(meta);

  // 下次更新（北京时间，来自 bangumi-data；悬浮显示日本时间 / 电视台 / 数据来源）
  // 没有数据时是一个隐藏的占位行，保证同一行卡片高度一致
  body.append(airtimeLine(subject.airtime));

  card.append(checkWrap, coverWrap);
  card.append(body);
  on(card, 'click', () => openModal(subject));
  return card;
}

function toggleSelect(id, isChecked) {
  if (isChecked) state.selected.add(id);
  else state.selected.delete(id);
  const card = document.querySelector(`#anime-grid .card[data-id="${id}"]`);
  if (card) card.classList.toggle('is-selected', !!isChecked);
  updateSelectionUI();
}

/** #check-all 只作用于当前可见卡片。 */
function onCheckAll() {
  const box = $('check-all');
  const want = !!(box && box.checked);
  state.visible.forEach((s) => {
    const id = Number(s.id);
    if (want) state.selected.add(id);
    else state.selected.delete(id);
  });
  renderAnime();
}

/** 勾选状态 -> 「已选 N 部」文案 + 批量操作区显隐 + 全选框三态。 */
function updateSelectionUI() {
  const count = state.selected.size;
  // 静止态的「已选 0 部」是零信息：文字照旧更新（探针/读屏要读得到），只是不显示
  setText('selected-count', `已选 ${count} 部`);
  show('selected-count', count > 0);
  show('batch-actions', count > 0);
  const all = $('check-all');
  if (!all) return;
  const visible = state.visible || [];
  const picked = visible.filter((s) => state.selected.has(Number(s.id))).length;
  all.checked = visible.length > 0 && picked === visible.length;
  all.indeterminate = picked > 0 && picked < visible.length;
}

/** #btn-clear-selection：清空勾选（批量操作区随之隐藏）。 */
function clearSelection() {
  if (!state.selected.size) {
    toast('当前没有勾选的番剧', 'info', 1500);
    return;
  }
  state.selected.clear();
  renderAnime();
  toast('已清空选择', 'info', 1500);
}

/**
 * 批量订阅（#btn-batch-sub / #btn-batch-fetch）：
 * 逐个 POST /api/subscriptions，只建订阅不带 resource，新集交给后台自动追番。
 *   kind = 'sub'   按设置里的 initial_mode 处理历史集
 *   kind = 'fetch' 强制 initial_mode='none'（只追新，不补旧）
 * 单个失败不中断整体，结束后汇总并清空勾选。
 */
async function batchSubscribe(kind, button) {
  const subjects = Array.from(state.selected)
    .map((id) => state.subjects.find((s) => Number(s.id) === Number(id)))
    .filter(Boolean);
  if (!subjects.length) {
    toast('请先勾选要订阅的番剧', 'err');
    return { ok: 0, failed: 0 };
  }

  const cfg = state.config || {};
  const download = cfg.download || {};
  const subscription = cfg.subscription || {};
  const root = String(download.root || '').trim();
  const dryRun = kind === 'fetch';
  const initialMode = dryRun ? 'none' : (subscription.initial_mode || 'latest');
  const total = subjects.length;
  const buttons = [$('btn-batch-sub'), $('btn-batch-fetch'), $('btn-clear-selection'), button];
  const failed = [];
  let ok = 0;

  await withBusy(buttons, async () => {
    for (let i = 0; i < total; i += 1) {
      const subject = subjects[i];
      setText('selected-count', `正在订阅 ${i + 1}/${total}：${subjectName(subject) || subject.id}`);
      // 不带 resource：只建订阅，之后由后台自动追番下载
      const body = {
        subject_id: subject.id,
        group: '',
        resolution: download.preferred_resolution || '',
        initial_mode: initialMode,
        total_episodes: totalEpisodesOf(subject),
      };
      if (root) body.folder = joinPath(root, sanitizeName(subjectName(subject)));
      try {
        const data = await request(API.subscriptions, { method: 'POST', body });
        subject.subscribed = true;
        rememberSubscription(data.subscription || {});
        ok += 1;
      } catch (err) {
        failed.push(`${subjectName(subject) || subject.id}：${err.message}`);
      }
    }
  });

  state.selected.clear();
  renderAnime();        // 刷新卡片「已订阅」标记 + 复位「已选 N 部」
  refreshStatus();      // 刷新侧栏计数

  const nameOf = (text) => text.length > 40 ? `${text.slice(0, 40)}…` : text;
  if (failed.length) {
    toast(dryRun
      ? `已为 ${ok} 部建立订阅（只追新，不会立即下载），失败 ${failed.length} 部`
      : `批量订阅：成功 ${ok} 部 / 失败 ${failed.length} 部`, 'err', 6000);
    toast(`失败原因：${nameOf(failed[0])}`, 'err', 8000);
  } else {
    toast(dryRun
      ? `已为 ${ok} 部建立订阅：只建了订阅，不会立即下载`
      : `批量订阅完成：成功 ${ok} 部 / 失败 0 部`, 'ok', 5000);
  }
  return { ok, failed: failed.length };
}

/** #btn-load-anime：GET /api/bangumi/collections?type=3。 */
async function loadAnime() {
  const node = $('token-state');
  await withBusy($('btn-load-anime'), async () => {
    showInfo(node, '正在拉取「在看」收藏…');
    try {
      const data = await request(API.collections(COLLECT_DOING, true));   // 强制刷新：只按 Bangumi 当前的「在看」
      state.subjects = Array.isArray(data.items) ? data.items : [];
      state.selected.clear();
      renderAnime();
      renderWarmup(data.warmup);          // 拉取在看列表时后端会同时启动预热
      syncWarmupPolling(data.warmup);
      setDot('dot-bgm', 'ok');
      setText('st-bgm', '已配置');
      showOk(node, `已拉取 ${state.subjects.length} 部在看番剧`);
      toast(`已拉取 ${state.subjects.length} 部在看番剧`, 'ok');
    } catch (err) {
      state.subjects = [];
      state.visible = [];
      const message = err.status === 401
        ? `Token 无效或已过期：${err.message}`
        : `拉取失败：${err.message}（可稍后点「拉取在看番剧」重试）`;
      showAnimeEmpty(message);
      setText('nav-count-anime', '–');
      if (err.status === 401) {
        state.tokenSet = false;
        setDot('dot-bgm', 'bad');
        setText('st-bgm', '令牌无效');
      }
      showError(node, message);
      toast(message, 'err');
    }
  });
}

/* =============================================================================
 * 7. 详情弹窗
 * ========================================================================== */

/**
 * 打开弹窗：填充头部 + 并发请求资源、字幕组、已有订阅。
 * options.mode = 'backfill' 表示从订阅页进来补下载单集（此时隐藏「订阅设置」tab，
 * 资源行「下载」直接推送到该订阅）。
 */
async function openModal(subject, options) {
  const node = $('modal');
  if (!node || !subject) return;
  const opts = options || {};

  // 本次打开的会话状态（state.modal 可能在 await 期间被 closeModal / 另一次 openModal 顶掉，
  // 结束时用它比对，避免给已经关掉或换掉的弹窗继续写界面）
  const session = {
    subject,
    mode: (opts.mode === 'backfill' || opts.mode === 'edit') ? opts.mode : 'subscribe',
    subscription: opts.subscription || null,   // 补下载模式必填
    defaultGroup: '',                          // 已有订阅限定的字幕组（用于默认选中）
    defaultSubGroup: '',                       // 已有订阅限定的「站点::组名」（新格式，优先）
    backfillFilter: null,                      // 补下载模式：已按订阅预选的筛选与未生效的项
    resources: [],
    outcome: null,                             // 最近一次 /api/search 的完整返回
    customKeyword: '',                         // 手动搜索关键词（空=按番剧名/别名自动搜索）
    groups: [],                                // /api/groups 的对象数组
    searchGroups: [],                          // /api/search 里附带的字幕组名
    episodeMap: {},                            // resourceKey -> 资源（#s-episode 用）
    sourceStatus: {},
    keywordsUsed: {},
    picked: null,
  };
  state.modal = session;

  fillModalHead(subject);
  resetFilters();
  clear('res-body');
  show('res-empty', false);
  clearGroupList();                          // 字幕组占位不可见时直接跳过（见 groupListVisible）
  clear('sub-history');
  showInfo($('sub-state'), '');
  showInfo($('search-state'), '');
  fillSubForm(subject);
  applyModalMode();
  refreshResSubscribeBtn();   // 先按当前状态（此刻通常还没资源）初始化筛选条上的「加入订阅」
  switchTab(session.mode === 'edit' ? 'sub' : 'res');

  node.hidden = false;
  document.body.classList.add('modal-open');
  enhanceSelects();          // 弹窗里的筛选器 / 订阅设置下拉此刻才可见，交给 ui.js 接管

  // 三个请求互相独立，任一失败都不影响另外两个
  // 注意：补下载的「按订阅预选筛选」要等资源结果一回来就做，
  // 不能等 loadGroups（有时很慢），否则用户先看到的是没预选的筛选条。
  await Promise.allSettled([
    runSearch().then(() => {
      if (session.mode === 'backfill' && session.subscription && state.modal === session) {
        applySubscriptionFilterToFilters(session.subscription);
      }
    }),
    loadGroups(),
    loadModalSubscription(),
  ]);
  if (state.modal !== session) return;      // 期间被关掉 / 换成了别的番剧：不再动界面

  // 资源与字幕组都到位后，再统一刷新订阅设置页的下拉与预览
  refreshSubGroupSelect();
  refreshEpisodeSelect();
  renderSubPreview();

  // 补下载模式：用户要求「提前按照订阅筛选好」——资源列表此刻已拿到结果，用订阅的
  // sub_group（站点 + 组名）+ resolution 预选筛选；缺哪项就不锁哪项并提示（可自行放宽）
  if (session.mode === 'backfill' && session.subscription) {
    applySubscriptionFilterToFilters(session.subscription);
  }
  // 修改订阅：等这一轮渲染跑完再切到「订阅设置」（前面会被默认 tab 覆盖掉）
  if (session.mode === 'edit' && state.modal === session) switchTab('sub');
}

/** 弹窗两种模式的静态差异：补下载模式下没有「订阅设置」，并在资源 tab 顶部给提示。 */
function applyModalMode() {
  const modal = state.modal;
  const backfill = !!(modal && modal.mode === 'backfill');
  const edit = !!(modal && modal.mode === 'edit');
  const tabBtn = document.querySelector('#m-tabs .tab[data-tab="sub"]');
  if (tabBtn) tabBtn.hidden = backfill;
  // 补下载模式只有一个页（资源列表）、修改订阅也只有一个页（订阅设置）→ 整条页签栏都不需要
  const tabs = document.querySelector('#m-tabs') || document.querySelector('.tabs');
  if (tabs) tabs.hidden = backfill || edit;
  // 修改订阅：直接停在「订阅设置」，主按钮变成「保存修改」（只改设置，不下载）
  const submit = $('btn-sub-add-res');
  if (submit) submit.textContent = edit ? '保存修改' : '加入订阅';
  if (edit) {
    switchTab('sub');
    const sub = modal.subscription;
    if (sub) {
      fillSourceOptions((sub.source_ids && sub.source_ids[0]) || (sub.sub_group || '').split('::')[0] || '');
      setSelectValue($('s-group'), sub.sub_group || joinGroupValue('', sub.group || ''));
      setSelectValue($('s-res'), sub.resolution || '');
      setSelectValue($('s-lang'), sub.lang || '');
      setSelectValue($('s-initial'), sub.initial_mode || 'latest');
      setText('s-total', sub.total_episodes ? String(sub.total_episodes) : '');
      setText('s-keyword', sub.custom_keyword || '');
      const folder = $('s-folder');
      if (folder) folder.value = sub.folder || '';
      refreshEpisodeSelect();
      renderSubPreview();
    }
  }

  const existing = document.getElementById(BACKFILL_HINT_ID);
  if (!backfill) {
    if (existing) existing.remove();
    return;
  }
  const tabRes = $('tab-res');
  if (!tabRes) return;
  let hint = existing;
  if (!hint) {
    hint = el('p', 'muted section-hint');
    hint.id = BACKFILL_HINT_ID;
    const filters = tabRes.querySelector('.filters');
    if (filters) filters.after(hint);      // .filters 之后、资源表之前
    else tabRes.prepend(hint);
  }
  renderBackfillHint();
}

/** 补下载提示条：说明当前在为哪个订阅挑选资源、已按订阅预选了哪些筛选，以及已选中的一条。 */
function renderBackfillHint() {
  const hint = document.getElementById(BACKFILL_HINT_ID);
  const modal = state.modal;
  if (!hint || !modal) return;
  const name = subscriptionName(modal.subscription) || subjectName(modal.subject);
  hint.replaceChildren();
  hint.append(el('span', null, `补下载模式：为「${name}」挑选单集或合集，` +
    '点资源行的「下载」即推送到 qBittorrent（不会改动订阅的字幕组 / 目录设置）。'));

  const plan = modal.backfillFilter;
  if (plan) {
    const parts = [
      plan.applied.source ? sourceDisplayName(plan.applied.source) : '',
      plan.applied.group,
      plan.applied.lang ? langFilterText(plan.applied.lang) : '',
      plan.applied.resolution,
    ].filter(Boolean);
    hint.append(el('b', null, parts.length
      ? ` 已按订阅筛选：${parts.join(' · ')}（可自行放宽）`
      : ' 该订阅没有限定站点 / 字幕组 / 语言 / 分辨率，可直接挑资源'));
    if (plan.skipped.length) {
      hint.append(el('span', 'muted',
        ` 本次结果里没有该订阅限定的${plan.skipped.join('、')}，${plan.skipped.length > 1 ? '这几项' : '该项'}没有过滤`));
    }
  }

  if (modal.picked) {
    hint.append(el('b', null, ` 已选中：${modal.picked.title || resourceKey(modal.picked)}`));
  }
}

/**
 * 补下载模式：用订阅的 sub_group（站点 + 组名）+ resolution 预选 #f-source / #f-group / #f-res。
 *   - 只预选「本次结果里真的存在」的项：某站点 / 组这一轮没搜到就不锁它，并在提示条里说明；
 *   - 不锁死：用户随时可以手动改成别的站点 / 组 / 分辨率（改完就是普通筛选）。
 * @returns {{applied: {source: string, group: string, resolution: string}, skipped: string[]}|null}
 */
function applySubscriptionFilterToFilters(sub) {
  const modal = state.modal;
  if (!modal || !sub) return null;
  const all = Array.isArray(modal.resources) ? modal.resources : [];
  const raw = String(sub.sub_group || '').trim() || String(sub.group || '').trim();
  const parsed = splitGroupValue(raw);
  const wantSource = parsed.source || subscriptionSourceId(sub);
  const wantGroup = parsed.name || String(sub.group || '').trim();
  const wantResolution = String(sub.resolution || '').trim();
  const applied = { source: '', group: '', resolution: '' };
  function resScopeAfterGroup() {
    return scope.filter((r) => !applied.group || groupMatch(r.group, applied.group));
  }
  const skipped = [];

  // 1) 站点：选项里有、结果里也有，才敢预选
  const sourceSel = $('f-source');
  const hasSource = !!wantSource
    && all.some((r) => String(r.source || '') === wantSource)
    && (!sourceSel || Array.from(sourceSel.options).some((o) => o.value === wantSource));
  if (hasSource) {
    setSelectValue(sourceSel, wantSource);
    applied.source = wantSource;
  } else if (wantSource) {
    skipped.push(`资源站「${sourceDisplayName(wantSource)}」`);
  }

  // 2) 字幕组：在已限定站点的范围内找，命中就用资源里的真实组名（保证能筛到）
  const scope = all.filter((r) => !applied.source || String(r.source || '') === applied.source);
  const groupHit = wantGroup ? scope.find((r) => groupMatch(r.group, wantGroup)) : null;
  if (wantGroup && groupHit) {
    const groupName = String(groupHit.group || '').trim();
    setSelectValue($('f-group'), groupName);
    applied.group = groupName;
  } else if (wantGroup) {
    skipped.push(`字幕组「${wantGroup}」`);
  }

  // 2.5) 字幕语言：**只认订阅里真正设置的值**。
  // 以前这里会「按已下载记录推断」，用户明明设的是「不限语言」也会被推断成繁体，
  // 结果一筛就什么都不剩 —— 这是明确要求去掉的行为。
  const wantLang = String(sub.lang || '').trim().toLowerCase();
  if (wantLang) {
    const langSel = $('f-lang');
    const hasLang = !langSel || Array.from(langSel.options).some((o) => o.value === wantLang);
    const langScope = resScopeAfterGroup();
    if (hasLang && langScope.some((r) => langMatches(r.lang, wantLang))) {
      setSelectValue(langSel, wantLang);
      applied.lang = wantLang;
    } else {
      skipped.push(`字幕语言「${langFilterText(wantLang)}」`);
    }
  }

  // 3) 分辨率
  const resScope = scope.filter((r) => !applied.group || groupMatch(r.group, applied.group));
  const hasRes = !!wantResolution
    && resScope.some((r) => String(r.resolution || '').toLowerCase() === wantResolution.toLowerCase());
  if (hasRes) {
    setSelectValue($('f-res'), wantResolution);
    applied.resolution = wantResolution;
  } else if (wantResolution) {
    skipped.push(`分辨率 ${wantResolution}`);
  }

  modal.backfillFilter = { applied, skipped };
  renderResources();          // 立即按预选筛选重渲染资源表
  renderBackfillHint();
  return modal.backfillFilter;
}

function closeModal() {
  const modal = $('modal');
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  document.body.classList.remove('modal-open');
  state.modal = null;
}

function fillModalHead(subject) {
  setCover($('m-cover'), subject.cover_medium || subject.cover);
  const titleText = subjectName(subject) || `#${subject.id}`;
  setText('m-title', titleText);
  setTitle('m-title', titleText);

  const sub = $('m-sub');
  if (sub) {
    const parts = [];
    if (subject.date) parts.push(`首播 ${subject.date}`);
    parts.push(`${fmtInt(totalEpisodesOf(subject), '?')} 话`);
    if (Number(subject.score) > 0) parts.push(`★ ${Number(subject.score).toFixed(1)}`);
    if (Number(subject.rank) > 0) parts.push(`排名 #${fmtInt(subject.rank)}`);
    if (Number(subject.ep_status) > 0) parts.push(`看到第 ${fmtInt(subject.ep_status)} 话`);
    parts.push(subject.subscribed ? '已订阅' : '未订阅');
    sub.replaceChildren();
    parts.forEach((text, index) => {
      if (index > 0) sub.append(el('span', 'sep', '·'));
      sub.append(el('span', null, text));
    });
    // 下次更新（北京时间）：详情页也要能看到几点几分更新，悬浮给出日本时间/电视台/数据来源；
    // 已完结的番显示「已完结」，不再显示编造的下一次更新时间
    const air = subject.airtime || {};
    if (air.finished || air.next_text) {
      sub.append(el('span', 'sep', '·'));
      const chip = el('span', 'm-air');
      const soon = !air.finished && Number(air.next_ts) > 0
        && (Number(air.next_ts) - Date.now() / 1000) < 6 * 3600;
      if (soon) chip.classList.add('is-soon');
      if (air.finished) chip.classList.add('is-finished');
      const icon = el('span', 'm-air-icon');
      icon.innerHTML = air.finished ? CHECK_SVG : CLOCK_SVG;
      chip.append(icon);
      chip.append(el('span', 'm-air-label', air.finished ? (air.finished_text || '已完结') : '下次更新：'));
      if (!air.finished) chip.append(el('b', 'm-air-time', `${air.next_text} · 北京时间`));
      if (air.tip) chip.title = air.tip;
      sub.append(chip);
    }
  }

  const aliasBox = $('m-aliases');
  if (aliasBox) {
    aliasBox.replaceChildren();
    const aliases = (Array.isArray(subject.aliases) ? subject.aliases : [])
      .filter((a, i, arr) => a && arr.indexOf(a) === i)
      .slice(0, 12);
    if (!aliases.length) {
      aliasBox.append(el('span', 'muted small', '暂无别名信息'));
    } else {
      const chips = el('div', 'chips');
      aliases.forEach((alias) => {
        const chip = el('span', 'chip', alias);
        chip.title = '点击复制该别名';
        on(chip, 'click', async () => {
          const ok = await copyText(alias);
          toast(ok ? `已复制：${alias}` : '复制失败，请手动选择文本', ok ? 'ok' : 'err');
        });
        chips.append(chip);
      });
      aliasBox.append(chips);
    }
  }
}

/** 订阅 tab 预填默认值（字幕组由 loadModalSubscription 按已有订阅补默认）。 */
/** 订阅设置里的「资源站」下拉：选项来自已启用的资源站，值用站点 id。 */
function fillSourceOptions(selected) {
  const sel = $('s-source');
  if (!sel) return;
  const sources = (state.status && state.status.sources) || state.sources || state.config?.sources || [];
  const opts = ['<option value="">不限</option>'];
  for (const s of sources) {
    const id = String(s.id || s.source || '').trim();
    if (!id) continue;
    const name = sourceDisplayName(id) || id;
    opts.push(`<option value="${id}">${name}</option>`);
  }
  sel.innerHTML = opts.join('');
  setSelectValue(sel, selected || '');
  if (typeof enhanceSelects === 'function') enhanceSelects();
}

function fillSubForm(subject) {
  const cfg = state.config || {};
  const download = cfg.download || {};
  const subscription = cfg.subscription || {};

  setSelectValue($('s-group'), '');
  fillSourceOptions('');
  setSelectValue($('s-res'), download.preferred_resolution || '');
  setSelectValue($('s-episode'), '');
  setValue('s-folder', joinPath(download.root, sanitizeName(subjectName(subject))));
  setSelectValue($('s-initial'), subscription.initial_mode || 'latest');
  setValue('s-total', totalEpisodesOf(subject) || '');
}

/** 该番剧的已有订阅（state.subs 为空时先拉一次订阅列表）。 */
async function findSubscription(subjectId) {
  if (!state.subs.length) {
    try {
      const data = await request(API.subscriptions);
      state.subs = Array.isArray(data.items) ? data.items : [];
    } catch (err) {
      return null;
    }
  }
  return state.subs.find((s) => Number(s.subject_id) === Number(subjectId)) || null;
}

/** 弹窗打开时查一次是否已有订阅：默认选中它限定的字幕组（带站点的 sub_group 优先）。 */
async function loadModalSubscription() {
  const modal = state.modal;
  if (!modal) return;
  let sub = modal.subscription;
  if (!sub) sub = await findSubscription(modal.subject.id);
  if (state.modal !== modal || !sub) return;
  modal.subscription = sub;
  const group = String(sub.group || '').trim();
  const subGroup = String(sub.sub_group || '').trim();
  modal.defaultGroup = group;
  modal.defaultSubGroup = subGroup;
  const wanted = subGroup || group;
  if (wanted) setSelectValue($('s-group'), wanted);
  // 订阅存的手动搜索关键词：回填到手动搜索框与订阅设置（用户能直接看到/改/清）
  const keyword = String(sub.custom_keyword || '').trim();
  modal.customKeyword = keyword;
  setValue('f-keyword', keyword);
  setValue('s-keyword', keyword);
  syncKeywordUI();
}

/** 把最新订阅写回 state.subs（订阅页与「补下载单集」据此工作）。 */
function rememberSubscription(sub) {
  if (!sub || sub.subject_id === undefined || sub.subject_id === null) return;
  const id = Number(sub.subject_id);
  const index = state.subs.findIndex((s) => Number(s.subject_id) === id);
  if (index >= 0) state.subs[index] = Object.assign({}, state.subs[index], sub);
  else state.subs.push(sub);
}

/**
 * 兼容 /api/groups（对象数组）与 /api/search（字幕组名数组）两种返回。
 * 新后端每个条目带 source / source_name / value（按站点分开）；老数据只有 sources 显示名数组：
 * 只出现一个站点时可以无歧义地推出站点 id，多个站点（跨站合并口径）则不猜。
 */
function normalizeGroups(list) {
  return (Array.isArray(list) ? list : [])
    .map((g) => {
      if (typeof g === 'string') {
        return { name: g.trim(), count: 0, sources: [], team_id: '', source: '', source_name: '', value: g.trim() };
      }
      if (!g || typeof g !== 'object') return null;
      const name = String(g.name || '').trim();
      const sources = (Array.isArray(g.sources) ? g.sources : [])
        .map((s) => String(s || '').trim()).filter(Boolean);
      let source = String(g.source || '').trim();
      const listedName = String(g.source_name || '').trim();
      // 老结构：sources 里写着站点显示名，只有一个时按配置里的 name -> id 反查
      if (!source && sources.length === 1) {
        const known = ((state.status && state.status.sources) || (state.config && state.config.sources) || [])
          .find((s) => s && String(s.name || '').trim() === sources[0]);
        if (known) source = String(known.id || '').trim();
      }
      return {
        name,
        count: Number(g.count) || 0,
        sources,
        team_id: String(g.team_id || ''),
        source,
        source_name: listedName || (source ? sourceDisplayName(source) : ''),
        value: String(g.value || '').trim() || joinGroupValue(source, name),
      };
    })
    .filter((g) => g && g.name);
}

/**
 * 从当前搜索结果现算「按站点分开」的字幕组（/api/groups 失败或还没返回时的兜底口径）。
 * 每条资源自带 source / source_name / team_id，因此即使接口挂了，下拉也能保持按站分组。
 */
function groupsFromResources() {
  const modal = state.modal || {};
  const buckets = new Map();
  (Array.isArray(modal.resources) ? modal.resources : []).forEach((r) => {
    const name = String((r && r.group) || '').trim();
    if (!name) return;
    const source = String(r.source || '').trim();
    const key = `${source}::${normGroup(name)}`;
    let item = buckets.get(key);
    if (!item) {
      item = {
        name,
        source,
        source_name: r.source_name || sourceDisplayName(source),
        count: 0,
        team_id: String(r.team_id || ''),
        sources: r.source_name ? [r.source_name] : [],
        value: joinGroupValue(source, name),
      };
      buckets.set(key, item);
    }
    item.count += 1;
    if (!item.team_id && r.team_id) item.team_id = String(r.team_id);
  });
  // 站点顺序跟配置里的优先级一致，站内按条数降序
  return Array.from(buckets.values())
    .sort((a, b) => sourceRank(a.source) - sourceRank(b.source) || b.count - a.count || a.name.localeCompare(b.name));
}

/** #s-group 的候选字幕组：优先 /api/groups，退回搜索结果现算，最后退回 /api/search 的组名。 */
function subGroupOptions() {
  const modal = state.modal || {};
  const groups = normalizeGroups(modal.groups);
  if (groups.length) return groups;
  const derived = groupsFromResources();
  return derived.length ? derived : normalizeGroups(modal.searchGroups);
}

/**
 * 把「期望选中的字幕组」解析成真实存在的 option value：
 *   ① 原样命中（'dmhy::ANi'）→ 直接用；
 *   ② 老格式纯组名（'ANi'）→ 先按订阅能确定的站点匹配，再按 team_id 匹配，最后按组名取第一个；
 *   ③ 一个都匹配不上 → 返回空，由调用方补一个占位项。
 * 之所以要②：用户早先建的订阅里只存了组名，而两个站可能有同名组（正是用户抱怨的点）。
 */
function resolveSubGroupValue(sel, groups, wanted, sub) {
  const want = String(wanted || '').trim();
  if (!want || !sel) return '';
  const options = Array.from(sel.options).filter((o) => o.value);
  if (options.some((o) => o.value === want)) return want;

  const parsed = splitGroupValue(want);
  const wantSource = parsed.source || subscriptionSourceId(sub);
  const teamId = String((sub && sub.team_id) || '').trim();
  const byValue = new Map(groups.map((g) => [g.value, g]));
  const candidates = options.filter((o) => groupMatch(splitGroupValue(o.value).name, parsed.name));
  if (!candidates.length) return '';
  const pick = candidates.find((o) => wantSource && splitGroupValue(o.value).source === wantSource)
    || candidates.find((o) => teamId && String((byValue.get(o.value) || {}).team_id || '') === teamId)
    || candidates[0];
  return pick.value;
}

/** 一个字幕组选项：文案只留「组名（N 条）」，站点靠 optgroup 标题，站点/team_id 放 title。 */
function buildSubGroupOption(g) {
  const opt = el('option', null, g.count > 0 ? `${g.name}（${fmtInt(g.count)} 条）` : g.name);
  opt.value = g.value;
  const bits = [];
  if (g.source_name || g.source) bits.push(g.source_name || sourceDisplayName(g.source));
  if (g.team_id) bits.push(`team_id ${g.team_id}`);
  if (g.count > 0) bits.push(`${fmtInt(g.count)} 条`);
  opt.title = [g.name].concat(bits).filter(Boolean).join(' · ');
  return opt;
}

/**
 * 用真实字幕组列表填充 #s-group（首项保持「不限」）。
 * 按资源站用 <optgroup> 分组：同名组在不同站是两条独立选项（value = 'dmhy::ANi'），
 * 选项文案里不再重复站点名（用户要求：不要出现「来源站点」那种文字）。
 */
function refreshSubGroupSelect() {
  const sel = $('s-group');
  const modal = state.modal;
  if (!sel || !modal) return;
  const previous = String(sel.value || '').trim();
  const groups = subGroupOptions();

  sel.replaceChildren();
  const none = el('option', null, GROUP_ANY_TEXT);
  none.value = '';
  sel.append(none);

  // 按站点分桶：桶的顺序 = 数组返回顺序（后端已按站点优先级排序）
  const buckets = new Map();
  groups.forEach((g) => {
    const key = g.source || '';
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { source: key, label: g.source_name || sourceDisplayName(key), items: [] };
      buckets.set(key, bucket);
    }
    if (!bucket.label) bucket.label = g.source_name || sourceDisplayName(key);
    bucket.items.push(g);
  });

  buckets.forEach((bucket) => {
    const options = bucket.items.map(buildSubGroupOption);
    if (!bucket.source) {
      // 老后端 / 跨站合并条目：没有站点信息就不分组，直接平铺（不编造站点名）
      options.forEach((opt) => sel.append(opt));
      return;
    }
    const box = el('optgroup');
    box.label = bucket.label || bucket.source;
    options.forEach((opt) => box.append(opt));
    sel.append(box);
  });

  const wanted = previous || modal.defaultSubGroup || modal.defaultGroup || '';
  let target = resolveSubGroupValue(sel, groups, wanted, modal.subscription);
  if (wanted && !target) {
    // 当前结果里没有这个组（例如已有订阅的组这轮没搜到）：补一个占位项，别让用户的选择悄悄丢掉
    const parsed = splitGroupValue(wanted);
    const fromSubscription = !previous && !!(modal.defaultSubGroup || modal.defaultGroup);
    const opt = el('option', null,
      `${groupDisplayText(parsed.source, parsed.name)}（${fromSubscription ? '已有订阅' : '当前选择'}）`);
    opt.value = joinGroupValue(parsed.source, parsed.name) || wanted;
    opt.title = '该字幕组不在本次搜索结果里，仍会按它订阅 / 追新';
    sel.append(opt);
    target = opt.value;
  }
  sel.value = target || '';
  updateSubGroupTip();
}

/** #s-group-tip：说明当前限定字幕组的含义（含站点）。 */
function updateSubGroupTip() {
  const tip = $('s-group-tip');
  if (!tip) return;
  const raw = val('s-group').trim();
  const modal = state.modal || {};
  if (raw) {
    const parsed = splitGroupValue(raw);
    tip.textContent = `只从「${groupDisplayText(parsed.source, parsed.name)}」下载，以后自动追新也走这个组`;
  } else if (modal.defaultGroup || modal.defaultSubGroup) {
    tip.textContent = '不限字幕组（该番剧已有订阅限定了字幕组，可在此改回不限）';
  } else {
    tip.textContent = '选定后只从这个字幕组下载';
  }
}

/** 选集候选项的集数展示：第 12 集 / 第 1-13 集。 */
function episodeNumberText(r) {
  const start = Number(r && r.episode);
  const end = Number(r && r.episode_end);
  if (!Number.isFinite(start) || start <= 0) return '未知集数';
  if (Number.isFinite(end) && end > start) return `第 ${start}-${end} 集`;
  return `第 ${start} 集`;
}

/** 选集的站点优先级：dmhy > kisssub > nyaa，其它站点按配置顺序排在其后。 */
function episodeSourceRank(id) {
  const index = EPISODE_SOURCE_ORDER.indexOf(String(id || ''));
  return index < 0 ? EPISODE_SOURCE_ORDER.length + sourceRank(id) : index;
}

/** 同一集多条资源时的取舍：站点优先级 -> 做种数 -> 集数跨度更窄。 */
function compareEpisodeResource(a, b) {
  const rank = episodeSourceRank(a.source) - episodeSourceRank(b.source);
  if (rank !== 0) return rank;
  const seeders = (Number(b.seeders) || 0) - (Number(a.seeders) || 0);
  if (seeders !== 0) return seeders;
  const spanA = (Number(a.episode_end) || Number(a.episode) || 0) - (Number(a.episode) || 0);
  const spanB = (Number(b.episode_end) || Number(b.episode) || 0) - (Number(b.episode) || 0);
  return spanA - spanB;
}

/**
 * #s-episode：按当前 #s-group / #s-res 过滤后，每个集数挑一条最优资源。
 * #s-group 的 value 形如 'dmhy::ANi'：站点与组名都要匹配（只列该站点该组的集数）。
 * 忽略 is_batch 与 is_noise；变化时保留用户已选的集数（仍存在才保留）。
 */
function refreshEpisodeSelect() {
  const sel = $('s-episode');
  const tip = $('s-episode-tip');
  const modal = state.modal;
  if (!sel || !modal || modal.mode === 'backfill') return;

  const previous = String(sel.value || '');
  const group = splitGroupValue(val('s-group'));
  const resolution = val('s-res').trim();
  const items = Array.isArray(modal.resources) ? modal.resources : [];
  const chosen = new Map();     // 集数 -> 资源

  items.forEach((r) => {
    if (!r || r.is_batch || r.is_noise) return;
    const episode = Number(r.episode);
    if (!Number.isFinite(episode) || episode <= 0) return;
    if (group.source && String(r.source || '') !== group.source) return;
    if (group.name && !groupMatch(r.group, group.name)) return;
    if (resolution && String(r.resolution || '').toLowerCase() !== resolution.toLowerCase()) return;
    const current = chosen.get(episode);
    if (!current || compareEpisodeResource(r, current) < 0) chosen.set(episode, r);
  });

  const episodes = Array.from(chosen.keys()).sort((a, b) => b - a);   // 新 -> 旧
  const map = {};
  sel.replaceChildren();
  const none = el('option', null, SUB_EPISODE_NONE);
  none.value = '';
  sel.append(none);
  episodes.forEach((episode) => {
    const r = chosen.get(episode);
    const key = resourceKey(r);
    if (!key) return;
    map[key] = r;
    const parts = [episodeNumberText(r), String(r.group || '').trim(),
      String(r.resolution || '').trim(), fmtSize(r)];
    const opt = el('option', null, parts.filter(Boolean).join(' · '));
    opt.value = key;
    opt.title = r.title || '';
    if (r.episode_absolute) {
      opt.title = `标题里的编号是 ${r.episode_absolute}（按本季算是第 ${r.episode} 集）\n${opt.title}`;
    }
    sel.append(opt);
  });

  modal.episodeMap = map;
  sel.disabled = episodes.length === 0;
  sel.value = (previous && map[previous]) ? previous : '';   // 旧 key 已失效时安全回退到「不下载」
  if (tip) {
    tip.textContent = episodes.length
      ? `可选 ${episodes.length} 集，已按字幕组/分辨率挑好最优的一条；别的版本请用「去资源列表挑选单集 / 合集」`
      : '当前字幕组/分辨率下没有单集；换字幕组或挑合集请用「去资源列表挑选单集 / 合集」';
  }
}

/**
 * #s-episode 当前选中项对应的资源。
 * 选中项不存在或已被新的搜索结果顶掉（悬空 key）时返回 null 并复位成「不下载」，
 * 绝不把不存在的资源提交给后端。
 */
function episodeResource() {
  const modal = state.modal;
  const key = val('s-episode');
  if (!modal || !key) return null;
  const picked = (modal.episodeMap || {})[key];
  if (!picked) {
    setSelectValue($('s-episode'), '');
    return null;
  }
  return picked;
}

/**
 * #s-preview：任何字段变化都刷新，让用户在点「加入订阅」前看到最终结果。
 * 形如：将订阅：<b>间谍过家家 第三季</b> · 字幕组 <b>桜都字幕组</b> · 1080p · 立即下载 <b>第 12 集</b> · 目录 E:\…
 * 每段都必须是独立的 <span>（CSS 用 .sub-preview > * 的 gap 排版，纯文本节点之间没有间距）。
 */
function renderSubPreview() {
  const box = $('s-preview');
  const modal = state.modal;
  // 订阅设置里任何改动都可能改变「加入订阅」按钮能订阅什么（补下载模式下会在函数内被置灰）
  refreshResSubscribeBtn();
  if (!box || !modal || modal.mode === 'backfill') return;

  const subject = modal.subject;
  const picked = episodeResource();
  const download = (state.config && state.config.download) || {};
  const group = splitGroupValue(val('s-group'));
  const resolution = val('s-res').trim();
  const folder = val('s-folder').trim()
    || joinPath(download.root, sanitizeName(subjectName(subject)));

  const subjectSeg = el('span');
  subjectSeg.append(el('span', null, '将订阅：'), el('b', null, subjectName(subject) || `#${subject.id}`));

  const groupSeg = el('span');
  // 带站点时显示「动漫花园 · ANi」，让用户一眼看出订的是哪个站的组（同名组在不同站是两条）
  const groupText = group.name ? groupDisplayText(group.source, group.name) : '不限';
  groupSeg.append(el('span', null, '字幕组 '), el('b', null, groupText));

  const resSeg = el('span', null, resolution || '不限分辨率');

  const keyword = String(val('s-keyword') || '').trim();
  const keywordSeg = el('span', keyword ? 'ellipsis' : '', keyword ? `搜索词 ${keyword}` : '按番剧名自动搜索');
  if (keyword) keywordSeg.title = `自动追新只按「${keyword}」搜索`;

  const episodeSeg = el('span');
  if (picked) episodeSeg.append(el('span', null, '立即下载 '), el('b', null, episodeNumberText(picked)));
  else episodeSeg.append(el('span', null, '不立即下载'));   // 状态文案；下拉里的选项文案仍是「不下载（仅订阅，之后自动追新）」

  const folderSeg = el('span', 'ellipsis', `目录 ${folder || '（默认目录）'}`);

  box.replaceChildren(subjectSeg, groupSeg, resSeg, keywordSeg, episodeSeg, folderSeg);
}

/** 重置筛选控件（每次打开弹窗）。 */
function resetFilters() {
  ['f-source', 'f-group'].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    sel.value = '';
  });
  setSelectValue($('f-lang'), '');
  setSelectValue($('f-res'), '');
  setSelectValue($('f-sort'), 'default');
  setChecked('f-batch', false);
  if (noiseToggle) noiseToggle.checked = false;
  setValue('f-keyword', '');
  setValue('s-keyword', '');
  syncKeywordUI();
}

/**
 * 手动搜索框的联动：非空时露出「恢复自动搜索」，并同步订阅设置里的说明文案。
 * 订阅存的是 #s-keyword（用户能在订阅设置里看到、也能改），这里只负责显示。
 */
function syncKeywordUI() {
  const kw = String(val('f-keyword') || '').trim();
  show('btn-keyword-reset', !!kw);
  const tip = $('s-keyword-tip');
  if (tip) {
    tip.textContent = kw
      ? `订阅后会一直用「${kw}」搜索（之后自动追新也用这个词）`
      : '填了就只用这个词搜索（手动搜索会自动填进来）';
  }
}

/** 资源列表的加载/错误占位行。 */
function showResMessage(text, kind) {
  const body = $('res-body');
  if (!body) return;
  const row = el('tr');
  const cell = el('td', kind === 'err' ? 'state-err' : 'muted', text);
  cell.colSpan = RES_COLUMNS;
  row.append(cell);
  body.replaceChildren(row);
}

/**
 * POST /api/search：资源列表 + 搜索统计。
 * 后端默认优先返回缓存（打开弹窗秒显示）；options.force = true 时跳过缓存重新联网，
 * 「重新搜索」按钮走的就是这条路径。
 * options.keyword 非空 = 手动搜索：只按这个词搜（后端不再展开番剧别名），
 * 并把它填进「订阅设置 → 自定义搜索词」，加入订阅时会一起存下来（自动追新也用这个词）。
 */
async function runSearch(options) {
  const modal = state.modal;
  if (!modal) return;
  const opts = options || {};
  const force = !!opts.force;
  const keyword = String(opts.keyword || '').trim();
  showResMessage(force ? '正在重新联网搜索资源…（多站点并发）' : '正在搜索资源，请稍候…（多站点并发）', 'info');
  show('res-empty', false);
  showInfo($('search-state'), '');

  try {
    const body = { subject_id: modal.subject.id };
    // 「只看本季」开关：关掉时让后端别隐藏上一季的资源（集号换算仍保留）
    if (!checked('f-season')) body.all_seasons = true;
    if (force) body.force = true;
    if (keyword) body.keyword = keyword;
    // 语言筛选：作为**站内原生搜索后缀**交给支持它的站点（dmhy / kisssub 比按标题猜更准），
    // 后端同时按同一口径过滤；本地渲染时再筛一次（见 langMatches）。
    const lang = currentLangFilter();
    if (lang) body.lang = lang;
    const data = await request(API.search, { method: 'POST', body });
    modal.outcome = data;
    modal.customKeyword = keyword;
    if (keyword) {
      // 手动搜索：订阅设置里的字幕组下拉改用这批结果（见 subGroupOptions 的回退顺序）
      modal.groups = [];
      setValue('s-keyword', keyword);
    }
    syncKeywordUI();
    modal.resources = Array.isArray(data.items) ? data.items : [];
    modal.sourceStatus = data.source_status || {};
    modal.keywordsUsed = data.keywords_used || {};
    modal.searchGroups = Array.isArray(data.groups) ? data.groups : [];
    modal.langHintShown = false;      // 新一轮结果：允许「站点未标注语言」的提示再出现一次
    fillSourceFilter();
    fillGroupFilter();
    renderSearchState(data);
    renderResources();
    refreshSubGroupSelect();    // 字幕组下拉跟随本次关键词的结果
    refreshEpisodeSelect();     // 集数下拉跟随新的资源列表重建
    renderSubPreview();
    if (!modal.resources.length) toast('没有搜索到资源，可换个字幕组或稍后重试', 'err');
  } catch (err) {
    modal.outcome = null;
    modal.resources = [];
    renderSearchState(null, err.message);
    renderResources();
    clear('res-body');
    showResMessage(`搜索失败：${err.message}`, 'err');
    show('res-empty', false);
    refreshEpisodeSelect();
    renderSubPreview();
    toast(`搜索失败：${err.message}`, 'err');
  }
}

/** POST /api/groups：字幕组列表（对象数组，含条数与来源站点）。 */
async function loadGroups() {
  const modal = state.modal;
  if (!modal) return;
  try {
    const data = await request(API.groups, { method: 'POST', body: { subject_id: modal.subject.id } });
    modal.groups = Array.isArray(data.groups) ? data.groups : [];
    renderGroups(modal.groups);
    if (modal === state.modal) refreshSubGroupSelect();   // 字幕组下拉用真实数据填充
  } catch (err) {
    modal.groups = [];
    // 字幕组卡片容器在 index.html 里是 hidden 占位：不可见时 renderGroups 自动跳过，
    // 真正的提示由订阅设置里的 #s-group 下拉（失败时只剩「不限」）承担。
    renderGroups([], `获取字幕组失败：${err.message}`);
  }
}

/** #search-state：策略 / 用时 / 每站命中与错误 / 本次关键词。 */
function renderSearchState(data, errorMessage) {
  const box = $('search-state');
  if (!box) return;
  box.replaceChildren();

  if (!data) {
    box.append(el('span', 'state-err', `搜索失败：${errorMessage || '未知错误'}`));
    return;
  }

  const chips = el('div', 'chips');
  chips.append(el('span', 'tag', `策略：${data.strategy || '按番剧名'}`));
  // 手动搜索时明确提示「这个词会跟着订阅走」，避免用户以为只是临时筛一下
  if (data.search_keyword) {
    const chip = el('span', 'tag', '加入订阅会记住这个搜索词');
    chip.title = `以后自动追新只用「${data.search_keyword}」搜索；可在「订阅设置」里改或清空`;
    chips.append(chip);
  }
  // 集号换算说明：发布组沿用系列连续编号（黑色五叶草第二季的 171 = 本季第 1 集）
  if (Number(data.episode_offset) > 0) {
    const chip = el('span', 'tag', `集数按本季显示（标题编号从 ${Number(data.episode_offset) + 1} 起）`);
    chip.title = '发布组沿用系列连续编号，已换算成本季集号；鼠标停在「集数」上能看到标题里的原始编号';
    chips.append(chip);
  }
  // 其它季的资源已经不在结果里（否则订阅进度会出现「49 / 12 集」这种数字）
  if (Number(data.hidden_other_season) > 0) {
    const chip = el('span', 'tag', `已隐藏 ${Number(data.hidden_other_season)} 条其它季资源`);
    chip.title = '这些资源属于同一系列的其他季，按当前番剧的季数过滤掉了；想下别的季请打开那一季的番剧卡片';
    chips.append(chip);
  }
  // 本次语言口径（后端把语言也写进 strategy 文案，这里再单独给一个 chip，一眼可见）
  const searchLang = langFilterText(data.search_lang);
  if (searchLang) chips.append(el('span', 'tag', `语言：${searchLang}`));
  chips.append(el('span', 'tag', `用时 ${(Number(data.elapsed) || 0).toFixed(2)}s`));
  // 结果来自本地缓存时明确标注（并提示可点「重新搜索」联网刷新）
  if (data.cached) {
    const age = cacheAgeText(data.cache_age);
    const chip = el('span', 'tag', `来自缓存${age ? ` · ${age}` : ''}${data.cache_stale ? '（已过期）' : ''}`);
    chip.title = data.cache_stale
      ? '缓存已过期：点右上角「重新搜索」可联网刷新'
      : '来自本地缓存，点右上角「重新搜索」可强制联网刷新';
    chips.append(chip);
  }
  if (data.total !== undefined && data.total !== null) chips.append(el('span', 'tag', `命中 ${fmtInt(data.total)} 条`));
  box.append(chips);

  // 每站命中 / 错误
  const status = data.source_status || {};
  const ids = Object.keys(status);
  const stationLine = el('div', 'search-detail');
  stationLine.append(el('span', null, '各站结果 ·'));
  if (ids.length) {
    ids.forEach((id) => {
      const info = status[id] || {};
      const name = info.name || id;
      const failed = info.ok === false;
      stationLine.append(el('span', failed ? 'state-err' : null,
        failed ? `${name}：失败（${info.error || '未知错误'}）` : `${name}：${fmtInt(info.count || 0)} 条`));
    });
  } else {
    stationLine.append(el('span', null, '后端未返回站点状态'));
  }
  box.append(stationLine);

  // 本次关键词（后端未记录时明确说明，不静默留白）
  const keywords = data.keywords_used || {};
  const used = Object.keys(keywords).flatMap((sid) => {
    const list = Array.isArray(keywords[sid]) ? keywords[sid] : [];
    return list.filter(Boolean).map((kw) => `${sid} → ${kw}`);
  });
  const keywordLine = el('div', 'search-detail');
  keywordLine.append(el('span', null, '本次关键词 ·'));
  if (used.length) keywordLine.append(el('span', null, used.join(' / ')));
  else keywordLine.append(el('span', 'muted', '接口未返回关键词记录'));
  box.append(keywordLine);
}

/** #f-source 选项来自 source_status，按配置里的站点优先级排序。 */
function fillSourceFilter() {
  const sel = $('f-source');
  if (!sel || !state.modal) return;
  const status = state.modal.sourceStatus || {};
  const configured = sourceOrder();
  const known = configured.filter((id) => status[id]);
  const rest = Object.keys(status).filter((id) => !known.includes(id));
  const ids = known.concat(rest);

  const previous = sel.value;
  sel.replaceChildren();
  const all = el('option', null, '全部');
  all.value = '';
  sel.append(all);
  ids.forEach((id) => {
    const info = status[id] || {};
    const label = info.ok === false
      ? `${info.name || id}（失败）`
      : `${info.name || id}（${fmtInt(info.count || 0)}）`;
    const opt = el('option', null, label);
    opt.value = id;
    sel.append(opt);
  });
  sel.value = ids.includes(previous) ? previous : '';
}

/** #f-group 选项来自实际资源的字幕组（保持站点优先级顺序）。 */
function fillGroupFilter() {
  const sel = $('f-group');
  if (!sel || !state.modal) return;
  const names = [];
  const seen = new Set();
  state.modal.resources.forEach((r) => {
    const name = String(r.group || '').trim();
    if (!name) return;
    const key = normGroup(name);
    if (seen.has(key)) return;
    seen.add(key);
    names.push(name);
  });

  const previous = sel.value;
  sel.replaceChildren();
  const all = el('option', null, '全部');
  all.value = '';
  sel.append(all);
  names.forEach((name) => {
    const opt = el('option', null, name);
    opt.value = name;
    sel.append(opt);
  });
  sel.value = names.includes(previous) ? previous : '';
}

/** 站点优先级顺序（来自配置的 sources.priority）。 */
function sourceOrder() {
  const list = (state.config && Array.isArray(state.config.sources)) ? state.config.sources : [];
  return list.slice()
    .sort((a, b) => (Number(a.priority) || 99) - (Number(b.priority) || 99))
    .map((s) => s.id);
}

function sourceRank(id) {
  const index = sourceOrder().indexOf(id);
  return index < 0 ? 99 : index;
}

/**
 * 按 #f-sort 就地排序资源数组（资源表与「按筛选订阅」共用同一套排序口径）。
 * 认不出的排序值一律按站点优先级（稳定排序，保持后端返回顺序）。
 */
function sortResourceRows(items) {
  const sort = val('f-sort') || 'default';
  const numOr = (v, fallback) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? fallback : Number(v));
  // 点表头排序：值是 col:<列>:<asc|desc>
  const col = /^col:([a-z]+):(asc|desc)$/.exec(sort);
  if (col) {
    const key = col[1];
    const dir = col[2] === 'asc' ? 1 : -1;
    const text = (v) => String(v === null || v === undefined ? '' : v).toLowerCase();
    const cmp = {
      source: (a, b) => sourceRank(a.source) - sourceRank(b.source) || text(a.source).localeCompare(text(b.source)),
      group: (a, b) => text(a.group).localeCompare(text(b.group), 'zh'),
      title: (a, b) => text(a.title).localeCompare(text(b.title), 'zh'),
      lang: (a, b) => text(normalizeLang(a.lang)).localeCompare(text(normalizeLang(b.lang))),
      resolution: (a, b) => numOr(String(a.resolution || '').replace(/\D/g, ''), -1) - numOr(String(b.resolution || '').replace(/\D/g, ''), -1),
      episode: (a, b) => numOr(a.episode, -1) - numOr(b.episode, -1),
      size: (a, b) => (Number(a.size_bytes) || 0) - (Number(b.size_bytes) || 0),
      seeders: (a, b) => numOr(a.seeders, -1) - numOr(b.seeders, -1),
      published: (a, b) => text(a.published).localeCompare(text(b.published)),
    }[key];
    if (cmp) {
      items.sort((a, b) => dir * cmp(a, b));
      return items;
    }
  }
  if (sort === 'ep-desc') items.sort((a, b) => numOr(b.episode, -1) - numOr(a.episode, -1));
  else if (sort === 'ep-asc') items.sort((a, b) => numOr(a.episode, Number.MAX_SAFE_INTEGER) - numOr(b.episode, Number.MAX_SAFE_INTEGER));
  else if (sort === 'seeders') items.sort((a, b) => numOr(b.seeders, -1) - numOr(a.seeders, -1));
  else if (sort === 'size') items.sort((a, b) => (Number(b.size_bytes) || 0) - (Number(a.size_bytes) || 0));
  else items.sort((a, b) => sourceRank(a.source) - sourceRank(b.source));   // 站点优先级（稳定）
  return items;
}

/** 表头排序指示：被点的列显示 ↑/↓，其它列清掉。 */
function paintSortIndicators() {
  const sort = val('f-sort') || 'default';
  const m = /^col:([a-z]+):(asc|desc)$/.exec(sort);
  if (!m) clearTempSortOption();
  $$('#res-table thead th.sortable').forEach((th) => {
    const active = !!(m && th.dataset.sort === m[1]);
    th.classList.toggle('is-sorted', active);
    th.dataset.dir = active ? m[2] : '';
    if (!th.dataset.label) th.dataset.label = th.textContent.replace(/[↑↓\s]+$/, '').trim();
    th.textContent = th.dataset.label + (active ? (m[2] === 'asc' ? ' ↑' : ' ↓') : '');
    th.title = active
      ? `当前按「${th.dataset.label}」${m[2] === 'asc' ? '升序' : '降序'}，再点一次切换`
      : `按「${th.dataset.label}」排序`;
  });
}

/**
 * 点表头排序（用户要求：搜索结果支持按标签排序）。
 * 第一次点升序，再点变降序，第三下回到「站点优先级」。
 */
function onHeaderSortClick(th) {
  if (!th || !th.dataset.sort) return;
  const cur = val('f-sort') || 'default';
  const m = /^col:([a-z]+):(asc|desc)$/.exec(cur);
  const key = th.dataset.sort;
  let next;
  if (!m || m[1] !== key) next = `col:${key}:asc`;
  else if (m[2] === 'asc') next = `col:${key}:desc`;
  else next = 'default';
  const label = th.dataset.label || th.textContent.replace(/[↑↓\s]+$/, '').trim();
  syncSortSelect(next, label, next.startsWith('col:') ? next.split(':')[2] : '');
  paintSortIndicators();
  renderResources();
}

/**
 * 让「排序」下拉显示得体的文案：
 * 点表头排序时下拉里没有对应选项，直接写 value 会显示 `col:size:asc` 这种内部值（很丑）。
 * 这里补一个临时选项（如「大小 ↑」），用户从下拉里改回普通排序时再清掉。
 */
function syncSortSelect(value, label, dir) {
  const sel = $('f-sort');
  if (!sel) return;
  Array.from(sel.options)
    .filter((o) => o.dataset && o.dataset.temp === '1' && o.value !== value)
    .forEach((o) => o.remove());
  let opt = Array.from(sel.options).find((o) => o.value === value);
  if (!opt) {
    opt = el('option', null, dir ? `${label} ${dir === 'asc' ? '↑' : '↓'}` : label);
    opt.value = value;
    opt.dataset.temp = '1';
    sel.append(opt);
  }
  sel.value = value;
  if (hasCustomSelect(sel)) sel.dispatchEvent(new Event('change', { bubbles: true }));
}

/** 用户从「排序」下拉里选了普通项时，把表头排序留下的临时选项清掉。 */
function clearTempSortOption() {
  const sel = $('f-sort');
  if (!sel) return;
  const cur = val('f-sort') || 'default';
  if (/^col:/.test(cur)) return;
  Array.from(sel.options).filter((o) => o.dataset && o.dataset.temp === '1').forEach((o) => o.remove());
  if (sel.value !== cur) sel.value = cur;
}

/* -----------------------------------------------------------------------------
 * 字幕语言（Resource.lang）：后端 base.detect_language() 只给 5 种归一化值
 *   'chs' 简体 / 'cht' 繁体 / 'both' 简繁（含双语 / MultiSub）/ 'jp' 日文生肉 / '' 未标注
 * #f-lang 比资源标签多一个 'unknown'（只看没标注的），语义见 langMatches()。
 * -------------------------------------------------------------------------- */

/** 资源语言值 → 胶囊文案（与后端 LANG_LABELS 一致）。 */
const LANG_LABELS = { chs: '简体', cht: '繁体', chj: '简日', cjt: '繁日', both: '简繁', jp: '日文', '': '未标注' };

/** 资源语言值 → 胶囊 class（styles.css 已备好 .lang-chs / .lang-cht / .lang-both / .lang-jp / .lang-none）。 */
const LANG_PILL_CLASS = { chs: 'lang-chs', cht: 'lang-cht', chj: 'lang-chj', cjt: 'lang-cjt',
                            both: 'lang-both', jp: 'lang-jp', '': 'lang-none' };

/** 胶囊 title：写清标签的依据；站点不标时也说明白，避免用户以为是猜的。 */
const LANG_PILL_TITLE = {
  chs: '标题标注了简体（如 [简体内嵌] / [CHS]）',
  cht: '标题标注了繁体（如 [繁日內嵌] / [CHT]）',
  both: '标题标注了简繁/双语（如 [简繁内封] / [双语] / MultiSub）',
  jp: '标题标注了日文生肉（如 [RAW] / [生肉]）',
  '': '站点未标注字幕语言（标题里看不出简繁，不代表没有字幕）',
};

/** #f-lang 的取值 → 文案（比资源标签多一个 unknown）。 */
const LANG_FILTER_LABELS = { chs: '简体', cht: '繁体', chj: '简日双语', cjt: '繁日双语',
                              both: '简繁/双语', jp: '日文生肉', unknown: '未标注' };

/** 资源语言值的原始归一（只去空白 + 转小写，不折叠认不出的值）。 */
function rawLang(value) {
  return String(value === undefined || value === null ? '' : value).trim().toLowerCase();
}

/** 归一化资源语言（用于展示）：后端只会给上表里的值，认不出的一律当「未标注」。 */
function normalizeLang(value) {
  const key = rawLang(value);
  return Object.prototype.hasOwnProperty.call(LANG_LABELS, key) ? key : '';
}

/** #f-lang 当前值（非法值 / 「全部」一律当「不限」）。 */
function currentLangFilter() {
  const want = rawLang(val('f-lang'));
  return Object.prototype.hasOwnProperty.call(LANG_FILTER_LABELS, want) ? want : '';
}

/**
 * 语言筛选：与后端 base.lang_matches() **逐行同口径**（这里刻意不做「认不出就折叠成未标注」，
 * 因为后端是拿原始值比较的；本地筛掉服务端明确返回的条目就是这么来的）。
 * **精确匹配**：每个选项只留它自己那一类 —— 用户反馈「选简体时简繁资源没被筛出去」，
 * 以前选简体时把简繁也算进来，等于没筛：
 *   简体 → 只认 chs；繁体 → 只认 cht；简繁/双语 → 只认 both；日文生肉 → 只认 jp；
 *   未标注 → 只认空（很多站点不标，不能猜）
 */
function langMatches(resourceLang, wanted) {
  const want = rawLang(wanted);
  if (!want) return true;
  const have = rawLang(resourceLang);
  if (want === 'unknown') return have === '';
  return have === want;
}

/**
 * 语言文案：筛选值（含 unknown）与资源值通用；空值返回空串，
 * 便于拼「站点 · 字幕组 · 分辨率 · 集数」这类摘要时不出现多余分隔符。
 */
function langFilterText(value) {
  const key = String(value === undefined || value === null ? '' : value).trim().toLowerCase();
  if (!key) return '';
  return LANG_FILTER_LABELS[key] || LANG_LABELS[key] || key;
}

/**
 * 整批结果都没标语言时提示一次：可点「重新搜索」让站点按语言过滤
 * （dmhy / kisssub 支持把「简体」等后缀拼进站内搜索，比我们猜标题更准）。
 * 只在用户真的选了语言时提示，且每轮搜索结果最多提示一次，避免来回切筛选刷屏。
 */
function promptLangRescan() {
  const modal = state.modal;
  if (!modal || modal.langHintShown) return;
  if (!currentLangFilter()) return;
  const list = Array.isArray(modal.resources) ? modal.resources : [];
  if (!list.length) return;
  if (list.some((r) => normalizeLang(r.lang))) return;   // 有标注：本地就能筛，不打扰
  modal.langHintShown = true;
  toast('这些站点未标注字幕语言，可点「重新搜索」让站点按语言过滤', 'info');
}

/**
 * 本地筛选 + 排序（不再请求后端）。
 * @returns {{rows: Array, noiseHidden: number}}
 */
function filterResources() {
  const modal = state.modal;
  if (!modal) return { rows: [], noiseHidden: 0 };

  const source = val('f-source');
  const group = val('f-group');
  const lang = currentLangFilter();
  const resolution = val('f-res');
  const withBatch = checked('f-batch');

  let items = modal.resources.slice();
  if (source) items = items.filter((r) => r.source === source);
  if (group) items = items.filter((r) => groupMatch(r.group, group));
  // 顺序与后端一致：站点 → 字幕组 → 语言 → 分辨率（同一套口径，见 langMatches）
  if (lang) items = items.filter((r) => langMatches(r.lang, lang));
  if (resolution) items = items.filter((r) => String(r.resolution || '').toLowerCase() === resolution.toLowerCase());
  if (!withBatch) items = items.filter((r) => !r.is_batch);

  const noise = items.filter((r) => r.is_noise);
  if (!(noiseToggle && noiseToggle.checked)) items = items.filter((r) => !r.is_noise);

  sortResourceRows(items);
  return { rows: items, noiseHidden: noise.length };
}

/** 渲染资源表。 */
function renderResources() {
  const modal = state.modal;
  if (!modal) return;
  const body = $('res-body');
  if (!body) return;

  paintSortIndicators();      // 排序可能从下拉改回来：同步表头箭头并清掉临时选项
  const result = filterResources();
  body.replaceChildren(...result.rows.map(buildResourceRow));
  updateNoiseLabel(result.noiseHidden);
  refreshResSubscribeBtn();   // 行数变了：同步筛选条上「加入订阅」的可用态 / 提示文案

  const empty = $('res-empty');
  if (empty) {
    empty.hidden = result.rows.length > 0;
    empty.textContent = modal.resources.length
      ? '当前筛选条件下没有资源，试试放宽筛选、勾选「含合集」或显示噪声项。'
      : '没有搜索到资源。可换字幕组，或点「重新搜索」再试一次。';
  }
  announce('modal');
}

const NOISE_LABEL = '显示噪声项';
function updateNoiseLabel(count) {
  if (!noiseLabelSpan) return;
  noiseLabelSpan.textContent = count > 0 ? `${NOISE_LABEL}（${count}）` : NOISE_LABEL;
}

/** 一行资源：数值列统一 .num（CSS 已右对齐 + tabular-nums）。 */
function buildResourceRow(r) {
  const modal = state.modal;
  const row = el('tr', 'res-row');
  const key = resourceKey(r);
  row.dataset.key = key;
  if (r.is_noise) row.classList.add('is-noise');
  if (modal && modal.picked && resourceKey(modal.picked) === key) row.classList.add('is-selected');

  row.append(el('td', 'col-src', r.source_name || r.source || '–'));

  const groupCell = el('td', 'col-group', r.group || '–');
  groupCell.title = r.group || '';
  row.append(groupCell);

  const titleCell = el('td', 'col-title');
  titleCell.append(titled('cell-title', r.title || '(无标题)'));
  row.append(titleCell);

  // 语言列：小胶囊（td 已 nowrap，胶囊固定 20px 高，不会撑破 38px 行高）
  const langKey = normalizeLang(r.lang);
  const langCell = el('td', 'col-lang');
  const langPill = el('span', `lang-pill ${LANG_PILL_CLASS[langKey]}`, LANG_LABELS[langKey]);
  langPill.title = LANG_PILL_TITLE[langKey];
  langCell.append(langPill);
  row.append(langCell);

  row.append(el('td', 'col-res', r.resolution || '–'));
  // 集数：发布组用「系列连续编号」时后端会换算成本季集号，原始编号放在 episode_absolute
  const epCell = el('td', 'col-ep num', episodeText(r));
  if (Number(r.episode_absolute) > 0) {
    epCell.title = `标题里的编号是 ${r.episode_absolute}（发布组沿用系列连续编号，按本季算是第 ${r.episode} 集）`;
  }
  row.append(epCell);

  const sizeCell = el('td', 'col-size num', fmtSize(r));
  if (Number(r.size_bytes) > 0) sizeCell.title = `${fmtInt(r.size_bytes)} B`;
  row.append(sizeCell);

  row.append(el('td', 'col-seed num', (r.seeders === null || r.seeders === undefined) ? '–' : fmtInt(r.seeders)));
  row.append(el('td', 'col-time', r.published || '–'));

  const actCell = el('td', 'col-act act-cell');
  const actions = el('div', 'cell-actions');

  // 补下载模式：资源行的「下载」直接推送到该订阅，而不是新建/更新订阅
  const backfill = !!(modal && (modal.mode === 'backfill' || modal.mode === 'edit') && modal.subscription);
  const downloadBtn = el('button', 'btn btn-sm btn-primary', '下载');
  attrs(downloadBtn, {
    type: 'button',
    title: backfill ? '下载这一集到该订阅' : '加入订阅并立即推送到 qBittorrent',
  });
  on(downloadBtn, 'click', (e) => {
    e.stopPropagation();
    if (backfill) downloadForSubscription(modal.subscription, r, downloadBtn);
    else addSubscription(r, { button: downloadBtn });
  });

  const copyBtn = el('button', 'btn btn-sm is-link', '复制磁力');
  attrs(copyBtn, { type: 'button', title: '复制磁力链接' });
  on(copyBtn, 'click', async (e) => {
    e.stopPropagation();
    const ok = await copyText(r.magnet);
    toast(ok ? '磁力链接已复制' : '该资源没有可用的磁力链接', ok ? 'ok' : 'err');
  });

  if (!r.magnet) {
    downloadBtn.disabled = true;
    copyBtn.disabled = true;
    downloadBtn.title = '该资源没有磁力链接，无法下载';
    copyBtn.title = '该资源没有磁力链接';
  }
  actions.append(downloadBtn, copyBtn);
  actCell.append(actions);
  row.append(actCell);

  on(row, 'click', () => pickResource(r));
  return row;
}

/**
 * 选中一行资源：预填订阅 tab 的 group / resolution，并让筛选条上的「加入订阅」可用
 * （title 显示将订阅什么）；补下载模式只做标记与提示。
 */
function pickResource(resource) {
  const modal = state.modal;
  if (!modal) return;
  modal.picked = resource;
  const key = resourceKey(resource);
  $$('#res-body tr.res-row').forEach((row) => row.classList.toggle('is-selected', row.dataset.key === key));
  refreshResSubscribeBtn();                 // 两种模式都刷新：补下载模式下会被置灰并说明原因

  if (modal.mode === 'backfill') {          // 补下载模式：点行只是标记，下载走该行的按钮
    renderBackfillHint();
    return;
  }

  if (resource.group) setSelectValue($('s-group'), joinGroupValue(resource.source, resource.group));
  if (resource.resolution) setSelectValue($('s-res'), resource.resolution);
  if (resource.lang) setSelectValue($('s-lang'), resource.lang);
  refreshSubGroupSelect();                   // 重建下拉（保留刚写入的「站点::组名」）
  refreshEpisodeSelect();
  renderSubPreview();

  const parts = ['已选中资源'];
  if (resource.source_name || resource.source) parts.push(resource.source_name || sourceDisplayName(resource.source));
  if (resource.group) parts.push(resource.group);
  if (resource.resolution) parts.push(resource.resolution);
  parts.push(fmtSize(resource));
  parts.push('（切到「订阅设置」可微调后加入订阅）');
  showInfo($('sub-state'), parts.join(' · '));
}

/**
 * 「字幕组」列表已并入订阅设置里的 #s-group 下拉，index.html 只保留 hidden 占位容器。
 * 下面两个函数是占位的守卫：容器不可见时一律不碰 DOM（避免每次开弹窗都做无效渲染）。
 */
function groupListVisible() {
  const list = $('group-list');
  if (!list || !list.isConnected) return false;
  return !!(list.offsetParent || list.getClientRects().length);
}

/** 清空字幕组占位（不可见时不做事；可见时同时收起空状态）。 */
function clearGroupList() {
  if (!groupListVisible()) return;
  clear('group-list');
  show('group-empty', false);
}

/**
 * 字幕组卡片列表：只在占位容器真的可见时才渲染（老布局 / 定制页），
 * 卡片已去掉「只从此字幕组下载」按钮 —— 写入限定字幕组这件事由订阅设置里的
 * #s-group 下拉承担；这里只保留「高亮当前已选字幕组」的单向联动。
 * @param {Array} groups /api/groups 或 /api/search 的字幕组
 * @param {string} [emptyText] 空列表 / 失败时的提示文案
 */
function renderGroups(groups, emptyText) {
  const list = $('group-list');
  if (!list || !groupListVisible()) return;      // hidden 占位：不报错、也不渲染

  const items = normalizeGroups(groups);
  list.replaceChildren();
  if (!items.length) {
    setEmptyText('group-empty', emptyText || '没有获取到字幕组（各站可能都没有结果，或站点被限流）');
    show('group-empty', true);
    return;
  }
  show('group-empty', false);

  const active = splitGroupValue(val('s-group')).name || val('f-group');
  items.forEach((g) => {
    const card = el('div', 'group-card');
    if (active && groupMatch(g.name, active)) card.classList.add('is-selected');

    const head = el('div', 'group-head');
    head.append(el('span', 'group-name', g.name));
    head.append(el('span', 'badge', `${fmtInt(g.count)} 条`));
    card.append(head);

    const meta = el('div', 'group-meta');
    const siteText = g.source_name || (g.sources.length ? g.sources.join(' / ') : '');
    if (siteText) meta.append(el('span', null, `来源：${siteText}`));
    if (g.team_id) meta.append(el('span', null, `team_id: ${g.team_id}`));
    if (meta.children.length) card.append(meta);

    list.append(card);
  });
}

/**
 * 加入订阅：POST /api/subscriptions
 *   resource 取值顺序：显式传入（资源行「下载」/ 按筛选取到的一条）→ #s-episode 选中项 → null
 *   带 resource = 同时立即推送下载；不带 = 只建订阅，新集交给后台自动追番
 * options.filters = {source, group, resolution}（「按筛选订阅」时把 #f-* 原样带进来，
 * 优先级高于资源自身字段，保证提交的筛选口径与用户看到的一致）。
 *
 * 字幕组字段（用户要求按资源站分开）：
 *   body.group      = 组名（'ANi'，仍是搜索关键词提示）
 *   body.sub_group  = '<站点>::<组名>'（'dmhy::ANi'，后端据此做「站点 + 组名」精确过滤）
 * 选「不限」时两者都为空。
 */
async function addSubscription(resource, options) {
  const modal = state.modal;
  if (!modal) return;
  const opts = options || {};
  const node = $('sub-state');
  const editing = !!(modal.mode === 'edit');
  const chosen = editing ? null : (resource || episodeResource() || null);
  const wantDownload = !!chosen;

  const subject = modal.subject;
  const download = (state.config && state.config.download) || {};
  const picked = splitGroupValue(val('s-group'));
  const filt = opts.filters || null;

  const chosenGroup = String((chosen && chosen.group) || '').trim();
  const chosenSource = String((chosen && chosen.source) || '').trim();
  // 资源自带组名时以它为准（用户点的就是那一条）；否则用下拉里选的组名
  const groupName = filt ? String(filt.group || '') : (chosenGroup || picked.name);
  // 站点要与组名成对，不能拼出「nyaa::桜都字幕组」这种不存在的组合（自动追新会永远搜不到）：
  //   ① 按筛选订阅 → 用筛选里的站点；
  //   ② 资源带组名 → 组名与下拉一致时用下拉的站点，否则跟资源自己的站点；
  //   ③ 资源没组名信息 → 整对（站点 + 组名）都用下拉里选的。
  let groupSource = (filt && filt.source) || '';
  if (!groupSource) {
    if (chosenGroup) {
      const sameGroup = !!picked.name && groupMatch(chosenGroup, picked.name);
      groupSource = (sameGroup ? picked.source : '') || chosenSource || picked.source;
    } else {
      groupSource = picked.source || chosenSource;
    }
  }

  const body = {
    subject_id: subject.id,
    group: groupName,
    sub_group: joinGroupValue(groupSource, groupName),
    // 手动搜索关键词（订阅设置里可见可改）：存进订阅后，自动追新也只用这个词搜索
    custom_keyword: String(val('s-keyword') || modal.customKeyword || '').trim(),
    // 资源列表里筛了就按筛的存（筛选「全部」＝空，也不偷偷改成所选资源的属性）
    resolution: String(filt ? (filt.resolution || '') : ((chosen && chosen.resolution) || val('s-res') || '')).trim(),
    // 字幕语言：订阅时就把弹窗里选的那一项记下来，自动追新也守它（以前只当搜索筛选，订完就丢）
    lang: String(filt ? (filt.lang || '') : (val('s-lang') || currentLangFilter()
      || (chosen && chosen.lang) || '')).trim().toLowerCase(),
    folder: val('s-folder').trim() || joinPath(download.root, sanitizeName(subjectName(subject))),
    initial_mode: val('s-initial') || 'latest',
    total_episodes: Number(val('s-total')) || totalEpisodesOf(subject),
  };
  // 资源站：资源列表里筛了哪个站就存哪个站（用户要求「筛什么就订阅什么」）
  const pickedSource = String(val('s-source') || '').trim();
  const filterSource = String((filt && filt.source) || '').trim();
  if (filterSource) body.source_ids = [filterSource];
  else if (pickedSource) body.source_ids = [pickedSource];
  else if (!editing) body.source_ids = [];
  else if (modal.subscription && Array.isArray(modal.subscription.source_ids)) {
    body.source_ids = modal.subscription.source_ids;      // 编辑且没动就保留原来的
  }
  if (chosen) body.resource = chosen;

  await withBusy(opts.button, async () => {
    showInfo(node, wantDownload ? '正在加入订阅并推送下载…' : '正在加入订阅…');
    try {
      const data = await request(API.subscriptions, { method: 'POST', body });
      const sub = data.subscription || {};
      subject.subscribed = true;
      rememberSubscription(sub);

      const parts = [editing ? '订阅已更新' : '已加入订阅'];
      if (groupName) parts.push(`（字幕组 ${groupDisplayText(groupSource, groupName)}）`);
      if (body.custom_keyword) parts.push(`（搜索词「${body.custom_keyword}」）`);
      if (data.downloaded_now) parts.push('并已推送到 qBittorrent');
      if (data.queued) parts.push('（qBittorrent 未连接，已排队，连上后自动补下载）');
      if (data.error && !data.queued) parts.push(`（下载失败：${data.error}）`);
      const message = parts.join('');
      if (data.error && !data.queued) showError(node, message);
      else showOk(node, message);
      toast(message, (data.error && !data.queued) ? 'err' : 'ok');
      if (data.queue) renderQueue(data.queue);

      // 修改订阅（edit）时不显示「最近下载记录」：用户只是改设置，不需要这一块
      if (!editing && Array.isArray(sub.history)) renderSubHistory(sub.history);
      else clear('sub-history');
      setSelectValue($('s-episode'), '');    // 复位成「不下载」，避免重复提交同一集
      refreshEpisodeSelect();
      renderSubPreview();
      renderAnime();          // 刷新卡片「已订阅」标记
      refreshStatus();        // 刷新侧栏计数（不阻塞弹窗交互）
      if (editing) await reloadSubsKeepingView(subject.id, opts.button);
    } catch (err) {
      showError(node, `加入订阅失败：${err.message}`);
      toast(`加入订阅失败：${err.message}`, 'err');
    }
  });
}

/* -----------------------------------------------------------------------------
 * 资源列表内直接加入订阅（用户诉求：筛完资源就能直接订阅，不必先切到「订阅设置」）
 * 与订阅设置页的 #btn-sub-add 共用同一个 addSubscription()，只有「资源从哪来」不同。
 * -------------------------------------------------------------------------- */

/** 一条资源的集数描述（按钮 title 与提示用）：第 13 集 / 合集 / 空。 */
function resourceEpisodeLabel(resource) {
  if (!resource) return '';
  if (resource.is_batch) return '合集';
  const episode = Number(resource.episode);
  return Number.isFinite(episode) && episode > 0 ? `第 ${episode} 集` : '';
}

/** 「加入订阅」将提交什么：站点 · 字幕组 · 语言 · 分辨率 · 集数。 */
function subscribePlanLabel(plan) {
  return [
    plan && plan.source ? sourceDisplayName(plan.source) : '',
    plan ? plan.group : '',
    plan ? langFilterText(plan.lang) : '',
    plan ? plan.resolution : '',
    plan ? plan.episode : '',
  ].map((x) => String(x || '').trim()).filter(Boolean).join(' · ');
}

/** 当前资源列表筛选条的值（「按筛选订阅」与按钮 title 共用同一份口径）。 */
function resFilterValues() {
  return {
    source: val('f-source').trim(),
    group: val('f-group').trim(),
    resolution: val('f-res').trim(),
    lang: currentLangFilter(),
  };
}

/** 一行资源对应的订阅计划（含站点，用于按钮 title）。 */
function resourcePlan(resource) {
  return {
    source: String((resource && resource.source) || '').trim(),
    group: String((resource && resource.group) || '').trim(),
    resolution: String((resource && resource.resolution) || '').trim(),
    lang: normalizeLang(resource && resource.lang),
    episode: resourceEpisodeLabel(resource),
  };
}

/**
 * 刷新 #btn-sub-add-res 的可用态与 title，让用户点之前就知道会订阅哪一条。
 *   ① 点选了资源行 / 选了要下载的集数 → 用那一条，title = 「加入订阅：站点 · 字幕组 · 分辨率 · 集数」；
 *   ② 都没选但表里还有行 → 可用：点了就用当前筛选（#f-source/#f-group/#f-res）去后端要排序第一条，
 *      title 照样写清楚会订哪个站点哪个组哪个分辨率；
 *   ③ 表里一条都没有（当前筛选结果为空）→ 置灰并说明下一步（disabled 的按钮连 toast 都弹不出来）。
 */
function refreshResSubscribeBtn() {
  const btn = $('btn-sub-add-res');
  if (!btn) return;
  const modal = state.modal;
  if (!modal) {
    btn.disabled = true;
    btn.title = '';
    return;
  }
  if (modal.mode === 'backfill') {          // 补下载模式：加订阅由订阅页负责，按钮整体不出现
    show('btn-sub-add-res', false);
    btn.disabled = true;
    btn.title = '补下载模式：请用资源行的「下载」把单集推送到这个订阅';
    return;
  }
  show('btn-sub-add-res', true);

  const chosen = modal.picked || episodeResource();
  if (chosen) {
    btn.disabled = false;
    const label = subscribePlanLabel(resourcePlan(chosen));
    const title = String(chosen.title || '').trim();
    btn.title = `加入订阅：${label}${title ? ` — ${title}` : ''}`;
    return;
  }

  const hasRows = $$('#res-body tr.res-row').length > 0;
  if (!hasRows) {
    btn.disabled = true;
    btn.title = modal.resources.length
      ? RES_SUB_NO_PICK_TIP
      : '没有搜索到资源：先点「重新搜索」，或到「订阅设置」里选要下载哪一集';
    return;
  }

  const label = subscribePlanLabel(resFilterValues());
  btn.disabled = false;
  btn.title = label
    ? `加入订阅：${label} · 取当前排序的第一条资源`
    : '加入订阅：取当前排序的第一条资源';
}

/**
 * #btn-sub-add-res：资源取值优先级
 *   ① 资源表里点选的那一行（state.modal.picked）
 *   ② 没点选任何行 → 「订阅设置」里 #s-episode 选中的集数对应资源（episodeResource()）
 *   ③ 都没有 → 用当前筛选（#f-source / #f-group / #f-res）调 POST /api/search，
 *      取返回 items 里排序第一条作为订阅资源；筛选结果为空时给「放宽筛选」的提示。
 * 订阅成功后的收尾（卡片已订阅标记 / 侧栏计数 / 历史 / 复位集数 / toast）
 * 全部由 addSubscription() 完成，与 #btn-sub-add 完全一致。
 */
async function addSubscriptionFromResList(button) {
  const modal = state.modal;
  if (!modal) return;
  if (modal.mode === 'backfill') {
    toast('补下载模式：请用资源行的「下载」把单集推送到这个订阅', 'info');
    return;
  }

  const chosen = modal.picked || episodeResource();
  if (chosen) {
    // resource 非空即「加入订阅 + 立即推送下载」（addSubscription 内部以此决定，无需额外开关）
    await addSubscription(chosen, { button });
    refreshResSubscribeBtn();   // withBusy 还原过 disabled，请求结束后按最新状态再校准一次
    return;
  }

  await subscribeByCurrentFilters(button);
}

/**
 * 按当前筛选订阅：把 #f-source / #f-group / #f-res 交给后端筛，取排序第一条。
 * 服务端筛选是权威口径（本地再核对一次，避免后端 / 缓存口径不一致时订到别的站点）。
 */
/**
 * 「加入订阅」拿不到资源时，把原因说清楚 —— 用户要能分清是**联网搜不到**还是**缓存搜不到**：
 *   live_failed        联网失败（某个站 HTTP 500 / 超时）→ 不是没有资源，是这次没搜着
 *   live_empty         联网搜了，确实 0 条
 *   cache_empty        缓存里就是 0 条（可能这站当时挂了）→ 建议点「重新搜索」
 *   cache_filtered_empty 缓存里有 N 条，但都被当前筛选排除了 → 放宽筛选
 */
function resSubscribeFailText(data, filters) {
  const label = subscribePlanLabel(filters) || '当前筛选';
  const reason = String((data && data.reason) || '');
  const raw = Number((data && data.raw_total) || 0);
  const age = Number((data && data.cache_age) || 0);
  const ageText = age > 0 ? cacheAgeText(age) : '';
  const errs = ((data && data.site_errors) || [])
    .map((e) => `${e.name || e.id}：${e.error || '失败'}`)
    .join('；');

  if (reason === 'live_failed') {
    return `联网搜索失败（${errs || '资源站报错'}）——不是没有资源，是这次没搜着；稍后点「重新搜索」再试`;
  }
  if (reason === 'live_empty') {
    return `联网搜了 ${raw} 条，但按当前筛选（${label}）一条都不剩：放宽筛选后重试`;
  }
  if (reason === 'cache_empty') {
    return `缓存里就是 0 条${ageText ? `（${ageText}搜的）` : ''}：点「重新搜索」联网再搜一次`;
  }
  if (reason === 'cache_filtered_empty') {
    return `缓存里有 ${raw} 条，但都被当前筛选（${label}）排除了：放宽筛选后重试`;
  }
  return `当前筛选下没有可订阅的资源（${label}）：放宽筛选条件后重试`;
}

async function subscribeByCurrentFilters(button) {
  const modal = state.modal;
  if (!modal) return;
  const filters = resFilterValues();
  const node = $('sub-state');
  const summary = subscribePlanLabel(filters) || '当前筛选（不限）';
  await withBusy(button, async () => {
    showInfo(node, `正在按筛选（${summary}）查找可订阅的资源…`);
    let data;
    try {
      const body = { subject_id: modal.subject.id };
      if (filters.source) body.source = filters.source;
      if (filters.group) body.group = filters.group;
      if (filters.resolution) body.resolution = filters.resolution;
      if (filters.lang) body.lang = filters.lang;      // 订阅本身不存语言，取资源这一步按语言筛
      body.force = false;
      data = await request(API.search, { method: 'POST', body });
      if (state.modal !== modal) return;
    } catch (err) {
      showError(node, `按筛选查找资源失败：${err.message}`);
      toast(`按筛选查找资源失败：${err.message}`, 'err');
      return;
    }

    let resource = firstResourceForFilters(data.items, filters);
    if (!resource) {
      // 服务端这次可能因为站点临时报错（例如动漫花园 HTTP 500）没筛出东西，
      // 但表格里明明有行 —— 退回界面上已经渲染出来的结果，别让「表里有、按钮说没有」。
      resource = firstResourceForFilters(modal.resources || [], filters);
    }
    if (!resource) {
      const tip = resSubscribeFailText(data, filters);
      showInfo(node, tip);
      toast(tip, 'err');
      return;
    }
    await addSubscription(resource, { filters });
  });
  refreshResSubscribeBtn();
}

/**
 * 从 /api/search 的返回里取「当前排序的第一条」。
 * 后端已按 source / group / lang / resolution 过滤；这里再宽松核对一遍（防止后端返回未过滤的
 * 结果，例如缓存口径不同），一条都对不上时仍按接口返回顺序取第一条，不静默失败。
 */
function firstResourceForFilters(items, filters) {
  const list = (Array.isArray(items) ? items : []).filter(Boolean);
  if (!list.length) return null;
  const want = filters || {};
  const matched = list.filter((r) => {
    if (want.source && String(r.source || '') !== want.source) return false;
    if (want.group && !groupMatch(r.group, want.group)) return false;
    if (want.lang && !langMatches(r.lang, want.lang)) return false;
    if (want.resolution && String(r.resolution || '').toLowerCase() !== want.resolution.toLowerCase()) return false;
    return true;
  });
  const pool = matched.length ? matched : list;
  const sorted = sortResourceRows(pool.slice());    // 与资源表同一套排序（#f-sort）
  return sorted[0] || null;
}

/**
 * 在「订阅设置」里显式选了要下载的集数时，取消资源表里点选的那一行：
 * 两个入口共用同一份选择，最近一次的显式选择优先，避免按钮 title 与实际提交的不一致。
 * 复位成「不下载」（value 为空）不算显式选择，此时保留点选的行。
 */
function onEpisodeChoiceChanged() {
  const modal = state.modal;
  if (!modal || modal.mode === 'backfill' || !modal.picked) return;
  if (!val('s-episode')) return;
  modal.picked = null;
  $$('#res-body tr.res-row.is-selected').forEach((row) => row.classList.remove('is-selected'));
  refreshResSubscribeBtn();
}

/** 订阅成功后展示下载历史。 */
function renderSubHistory(history) {
  const box = $('sub-history');
  if (!box) return;
  box.replaceChildren();
  const list = Array.isArray(history) ? history : [];
  if (!list.length) {
    box.append(el('p', 'muted small', '该订阅还没有下载记录。'));
    return;
  }
  box.append(el('p', 'muted small', `最近下载记录（${list.length} 条）`));
  const ul = el('ul', 'history-list');
  list.slice(0, 20).forEach((h) => {
    const line = [
      fmtTime(h.time),
      h.episode ? `第 ${h.episode} 集` : '合集',
      h.title || '(无标题)',
      h.size || '',
      h.reason || '',
    ].filter(Boolean).join(' · ');
    ul.append(el('li', null, line));
  });
  box.append(ul);
}


/* =============================================================================
 * 批量订阅设置（规则按优先级依次匹配）
 * ========================================================================== */

/** 规则列表：存 localStorage，刷新页面或重开窗口都还在。 */
const BATCH_RULES_KEY = 'anifetch.batchRules';

function saveBatchRules() {
  try {
    localStorage.setItem(BATCH_RULES_KEY, JSON.stringify(state.batchRules || []));
  } catch (err) { /* 隐私模式等写不进去就算了 */ }
}

function loadBatchRulesFromStorage() {
  try {
    const raw = localStorage.getItem(BATCH_RULES_KEY);
    if (!raw) return null;
    const list = JSON.parse(raw);
    if (!Array.isArray(list) || !list.length) return null;
    return list.map((r) => ({
      source: String(r.source || ''), group: String(r.group || ''),
      lang: String(r.lang || ''), resolution: String(r.resolution || ''),
    }));
  } catch (err) { return null; }
}

function batchRules() {
  if (!Array.isArray(state.batchRules) || !state.batchRules.length) {
    state.batchRules = loadBatchRulesFromStorage() || [{ source: '', group: '', lang: '', resolution: '' }];
  }
  return state.batchRules;
}

const RES_OPTIONS = ['', '2160p', '1080p', '720p', '480p'];
const LANG_OPTIONS = [['', '不限语言'], ['chs', '简体'], ['cht', '繁体'], ['chj', '简日双语'],
                          ['cjt', '繁日双语'], ['both', '简繁/双语'], ['jp', '日文生肉'], ['unknown', '未标注']];

/** 批量订阅用的字幕组候选：从已勾选番剧的缓存结果里汇总（按站点），选了站点就只用该站的组。 */
function batchGroupOptions(sourceId) {
  const list = (state.batchGroups || [])
    .filter((g) => !sourceId || g.source === sourceId)
    .map((g) => ({
      name: g.name,
      label: `${g.name}${sourceId ? '' : `（${sourceDisplayName(g.source)}）`}`,
    }));
  const seen = new Set();
  return list.filter((g) => (seen.has(g.name) ? false : (seen.add(g.name), true)));
}

/**
 * 批量订阅用的字幕组候选（秒回）：直接取「我的订阅」里已经用过的组
 * （订阅里存的是 `站点::组名`），不用逐部去搜，打开弹窗就能选。
 */
async function loadBatchGroups() {
  let merged = [];
  try {
    const data = await request(API.groupsCached);
    merged = (data.groups || []).map((g) => ({
      source: String(g.source || ''), name: String(g.name || ''), count: g.count || 0,
    })).filter((g) => g.name);
  } catch (err) { /* 取不到就不提供候选，仍可按站点/语言/分辨率订阅 */ }
  state.batchGroups = merged;
  renderBatchRules();
}

/** 打开「批量订阅设置」窗口。 */
function openBatchModal() {
  const node = $('batch-modal');
  if (!node) return;
  if (!(state.selected && state.selected.size)) {
    toast('先在列表里勾选要批量订阅的番剧', 'info');
    return;
  }
  renderBatchRules();
  clear('batch-result');
  loadBatchGroups();          // 用缓存里的字幕组填充下拉（不阻塞窗口打开）
  node.hidden = false;
  document.body.classList.add('modal-open');
  refreshBatchRunLabel();
}

function closeBatchModal() {
  const node = $('batch-modal');
  if (node) node.hidden = true;
  document.body.classList.remove('modal-open');
}

/** 渲染规则行：资源站 / 字幕组 / 语言 / 分辨率 + 上移下移删除。 */
function renderBatchRules() {
  const box = $('batch-rules');
  if (!box) return;
  const rules = batchRules();
  box.replaceChildren();
  rules.forEach((rule, idx) => {
    const row = el('div', 'batch-rule');
    row.dataset.index = String(idx);
    row.append(el('span', 'batch-rule-index', String(idx + 1)));

    const sourceSel = el('select', 'batch-source');
    sourceSel.append(new Option('不限站点', ''));
    for (const src of ((state.status && state.status.sources) || state.sources || [])) {
      const id = String(src.id || '').trim();
      if (id) sourceSel.append(new Option(sourceDisplayName(id) || id, id));
    }
    sourceSel.value = rule.source || '';
    on(sourceSel, 'change', () => { rule.source = sourceSel.value; });

    // 字幕组：用缓存里的组名做下拉；选了资源站就只显示该站的组
    const groupSel = el('select', 'batch-group');
    const fillGroups = () => {
      groupSel.replaceChildren(new Option('不限字幕组', ''));
      for (const g of batchGroupOptions(rule.source)) {
        groupSel.append(new Option(g.label, g.name));
      }
      if (rule.group) {
        const exists = [...groupSel.options].some((o) => o.value === rule.group);
        if (!exists) groupSel.append(new Option(`${rule.group}（手动）`, rule.group));
      }
      groupSel.value = rule.group || '';
    };
    fillGroups();
    on(sourceSel, 'change', () => { rule.source = sourceSel.value; rule.group = ''; fillGroups(); saveBatchRules(); });
    on(groupSel, 'change', () => { rule.group = groupSel.value; saveBatchRules(); });

    const langSel = el('select', 'batch-lang');
    for (const [value, label] of LANG_OPTIONS) langSel.append(new Option(label, value));
    langSel.value = rule.lang || '';
    on(langSel, 'change', () => { rule.lang = langSel.value; saveBatchRules(); });

    const resSel = el('select', 'batch-res');
    for (const value of RES_OPTIONS) resSel.append(new Option(value || '不限分辨率', value));
    resSel.value = rule.resolution || '';
    on(resSel, 'change', () => { rule.resolution = resSel.value; saveBatchRules(); });

    const acts = el('div', 'batch-rule-actions');
    const up = el('button', 'icon-btn', '↑');
    attrs(up, { type: 'button', title: '上移（提高优先级）' });
    on(up, 'click', () => moveBatchRule(idx, -1));
    const down = el('button', 'icon-btn', '↓');
    attrs(down, { type: 'button', title: '下移（降低优先级）' });
    on(down, 'click', () => moveBatchRule(idx, 1));
    const del = el('button', 'icon-btn', '✕');
    attrs(del, { type: 'button', title: '删除这条规则' });
    on(del, 'click', () => {
      const list = batchRules();
      if (list.length <= 1) { toast('至少保留一条规则', 'info'); return; }
      list.splice(idx, 1);
      saveBatchRules();
      renderBatchRules();
    });
    acts.append(up, down, del);

    row.append(sourceSel, groupSel, langSel, resSel, acts);
    box.append(row);
  });
  if (typeof enhanceSelects === 'function') enhanceSelects();
}

function moveBatchRule(idx, delta) {
  const list = batchRules();
  const to = idx + delta;
  if (to < 0 || to >= list.length) return;
  const [item] = list.splice(idx, 1);
  list.splice(to, 0, item);
  saveBatchRules();
  renderBatchRules();
}

function refreshBatchRunLabel() {
  const btn = $('batch-run');
  if (!btn) return;
  const n = state.selected ? state.selected.size : 0;
  btn.textContent = `开始批量订阅（${n} 部）`;
  btn.disabled = n === 0;
}

/** 真正执行：POST /api/subscriptions/batch。 */
async function runBatchSubscribe() {
  const rules = batchRules().filter((r) => r.source || r.group || r.lang || r.resolution);
  if (!rules.length) { toast('至少填一条有内容的规则（全空等于不限，可直接只留一条空的）', 'info'); return; }
  const ids = [...(state.selected || [])];
  if (!ids.length) { toast('没有勾选的番剧', 'info'); return; }
  const box = $('batch-result');
  const btn = $('batch-run');
  await withBusy(btn, async () => {
    if (box) box.textContent = '正在按规则逐部匹配并订阅…（有缓存的会很快）';
    let data;
    try {
      data = await request(API.subscriptionBatch, { method: 'POST', body: { subject_ids: ids, rules } });
    } catch (err) {
      if (box) box.textContent = `批量订阅失败：${err.message}`;
      toast(`批量订阅失败：${err.message}`, 'err');
      return;
    }
    const okList = data.subscribed || [];
    const skipList = data.skipped || [];
    if (box) {
      box.replaceChildren();
      if (okList.length) {
        box.append(el('b', null, `已订阅 ${okList.length} 部：`));
        for (const it of okList) {
          box.append(el('div', 'ok',
            `· ${it.name} ← 规则 ${it.rule_index + 1}：第 ${it.episode} 集 · ${it.source || ''} · ${it.group || ''}`));
        }
      }
      if (skipList.length) {
        box.append(el('b', null, `没有订阅 ${skipList.length} 部（所有规则都没匹配到）：`));
        for (const it of skipList) box.append(el('div', 'bad', `· ${it.name} —— ${it.reason}`));
      }
      if (!okList.length && !skipList.length) box.append(el('div', null, '没有任何结果'));
    }
    toast(`批量订阅完成：成功 ${okList.length} 部，未订阅 ${skipList.length} 部`, okList.length ? 'ok' : 'info');
    state.selected.clear();
    renderAnime();
    await loadSubscriptions();
    refreshStatus();
    refreshBatchRunLabel();
  });
}

/* =============================================================================
 * 8. 订阅页
 * ========================================================================== */

/** GET /api/subscriptions：渲染摘要与列表。 */
async function loadSubscriptions() {
  const list = $('sub-list');
  const empty = $('subs-empty');
  try {
    const data = await request(API.subscriptions);
    state.subs = Array.isArray(data.items) ? data.items : [];
    if (data.queue) renderQueue(data.queue);
    renderSubSummary(data.status || {});
    renderSubList();
    renderSidebarUpdates();
    setText('nav-count-subs', String(state.subs.length));
    announce('subs');
  } catch (err) {
    if (list) list.replaceChildren();
    const summary = $('sub-summary');
    if (summary) summary.replaceChildren(el('span', 'state-err', `订阅数据加载失败：${err.message}`));
    setEmptyText('subs-empty', `订阅数据加载失败：${err.message}（请确认后台服务仍在运行，然后点「刷新」重试）`);
    show('subs-empty', true);
    toast(`订阅数据加载失败：${err.message}`, 'err');
    announce('subs');
  }
}

/**
 * 侧栏「最近更新」：列出订阅里**近 2 天内更新过**的番，按「最近一次已播出的时间」从新到旧排。
 * 数据来自 /api/subscriptions 的 airtime（aired_ts / aired_text / episode_no）。
 * 点一条 → 切到「我的订阅」并高亮那张卡片；近两天没有更新（或没有订阅）就整块隐藏。
 */
const SIDEBAR_RECENT_HOURS = 48;      // 用户要求：只显示两天内的更新

function renderSidebarUpdates() {
  const box = $('side-updates');
  const list = $('side-updates-list');
  if (!box || !list) return;
  const now = Date.now() / 1000;
  const windowSec = SIDEBAR_RECENT_HOURS * 3600;
  const rows = (state.subs || [])
    .map((sub) => ({ sub, air: sub.airtime || {} }))
    .filter((r) => {
      const ts = Number(r.air.aired_ts) || 0;
      return ts > 0 && ts <= now + 60 && now - ts <= windowSec;      // 两天内的才算
    })
    .sort((a, b) => Number(b.air.aired_ts) - Number(a.air.aired_ts))
    .slice(0, 3);

  list.replaceChildren();
  if (!rows.length) {
    box.hidden = true;
    return;
  }
  setText('side-updates-hint', `近 ${SIDEBAR_RECENT_HOURS / 24} 天`);
  rows.forEach((row, index) => {
    const sub = row.sub;
    const air = row.air;
    const btn = el('button', 'update-row');
    btn.type = 'button';
    btn.dataset.id = String(sub.subject_id);
    if (index === 0) btn.classList.add('is-next');
    const fresh = now - Number(air.aired_ts) < 24 * 3600;      // 24 小时内更新过 → 标「新」
    if (fresh) btn.classList.add('is-soon');

    const img = el('img', 'update-cover');
    img.loading = 'lazy';
    img.alt = '';
    setCover(img, sub.cover);

    const main = el('span', 'update-main');
    main.append(el('span', 'update-name', subscriptionName(sub) || `#${sub.subject_id}`));
    const ep = Number(air.episode_no) > 0 ? `第 ${air.episode_no} 集 · ` : '';
    main.append(el('span', 'update-time', `${ep}${air.aired_text || ''} · ${relativeAgo(air.aired_ts)}`));
    btn.append(img, main);
    if (fresh) btn.append(el('span', 'update-soon', '新'));
    btn.title = [air.tip || '', '点击跳到「我的订阅」里的这一条'].filter(Boolean).join('\n');
    on(btn, 'click', () => focusSubscription(sub.subject_id));
    list.append(btn);
  });
  box.hidden = false;
}

/**
 * 「更多」弹窗：列出订阅里最近的更新（按最近一集的播出时间从新到旧，**最多 50 条**）。
 * 一条 = 一部订阅的最新一集（含已完结的，排在后面并标「已完结」）。
 */
const UPDATES_MODAL_LIMIT = 50;

function updatesModalRows() {
  return (state.subs || [])
    .map((sub) => ({ sub, air: sub.airtime || {} }))
    .filter((r) => Number(r.air.aired_ts) > 0)
    .sort((a, b) => Number(b.air.aired_ts) - Number(a.air.aired_ts))
    .slice(0, UPDATES_MODAL_LIMIT);
}

function renderUpdatesModal() {
  const list = $('updates-list');
  if (!list) return;
  const rows = updatesModalRows();
  const now = Date.now() / 1000;
  setText('updates-sub', rows.length
    ? `按最近一集的播出时间排序 · 共 ${rows.length} 条（最多 ${UPDATES_MODAL_LIMIT} 条）`
    : '还没有可显示的更新');
  list.replaceChildren();
  if (!rows.length) {
    list.append(el('p', 'updates-empty', '订阅里还没有「已经更新」的记录。'));
    return;
  }
  rows.forEach(({ sub, air }) => {
    const row = el('button', 'updates-row');
    row.type = 'button';
    row.dataset.id = String(sub.subject_id);
    const fresh = now - Number(air.aired_ts) < 24 * 3600;
    if (fresh && !air.finished) row.classList.add('is-new');

    const img = el('img', 'updates-cover');
    img.loading = 'lazy';
    img.alt = '';
    setCover(img, sub.cover);

    const main = el('span', 'updates-main');
    main.append(el('span', 'updates-name', subscriptionName(sub) || `#${sub.subject_id}`));
    const ep = Number(air.episode_no) > 0 ? `第 ${air.episode_no} 集 · ` : '';
    main.append(el('span', 'updates-time',
      `${ep}${air.aired_text || ''} · ${relativeAgo(air.aired_ts)}`));
    row.append(img, main);
    if (air.finished) {
      row.append(el('span', 'updates-tag is-done', '已完结'));
    } else if (fresh) {
      row.append(el('span', 'updates-tag is-new', '新'));
    }
    row.title = [air.tip || '', '点击跳到「我的订阅」里的这一条'].filter(Boolean).join('\n');
    on(row, 'click', () => {
      closeUpdatesModal();
      focusSubscription(sub.subject_id);
    });
    list.append(row);
  });
}

function openUpdatesModal() {
  const box = $('updates-modal');
  if (!box) return;
  renderUpdatesModal();
  box.hidden = false;
  document.body.classList.add('modal-open');
  const first = document.querySelector('#updates-list .updates-row');
  if (first) first.focus();
}

function closeUpdatesModal() {
  const box = $('updates-modal');
  if (!box || box.hidden) return;
  box.hidden = true;
  document.body.classList.remove('modal-open');
}

/** 「今天 / 昨天 / N 天前」这种相对说法（侧栏「最近更新」用）。 */
function relativeAgo(ts) {
  const sec = Number(ts) || 0;
  if (!sec) return '';
  const mins = Math.max(0, Math.round((Date.now() / 1000 - sec) / 60));
  if (mins < 1) return '刚刚';
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.round(hours / 24);
  if (days === 1) return '昨天';
  if (days < 7) return `${days} 天前`;
  const d = new Date(sec * 1000);
  return `${d.getMonth() + 1}-${d.getDate()}`;
}

/** 跳到「我的订阅」并把这部的卡片滚进视野 + 闪一下（侧栏点条目用）。 */
function focusSubscription(subjectId) {
  switchView('subs');
  const wait = (tries) => {
    const card = document.querySelector(`#sub-list .sub-item[data-id="${subjectId}"]`);
    if (!card) {
      if (tries > 0) window.setTimeout(() => wait(tries - 1), 250);
      return;
    }
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    card.classList.add('is-flash');
    window.setTimeout(() => card.classList.remove('is-flash'), 1600);
  };
  wait(12);
}

/** #sub-summary：状态统计 + 全部检查 / 刷新。 */
function renderSubSummary(status) {
  const box = $('sub-summary');
  if (!box) return;
  box.replaceChildren();

  const stat = (label, value) => {
    const wrap = el('div', 'stat');
    wrap.append(el('span', 'stat-label', label));
    wrap.append(el('span', 'stat-value', value));
    return wrap;
  };

  box.append(stat('自动追番', status.enabled ? '已启用' : '已停用'));
  box.append(stat('检查间隔', `${fmtInt(status.interval_minutes, '30')} 分钟`));
  box.append(stat('订阅数', fmtInt(status.subscriptions, '0')));
  const q = state.queue || {};
  const queued = Number(q.count) || 0;
  if (queued > 0) {
    const pendingStat = stat('待下载', `${queued} 集`);
    pendingStat.classList.add('stat-warn');
    pendingStat.title = 'qBittorrent 未连接时先存下来，恢复后自动补下载';
    box.append(pendingStat);
  }
  box.append(el('span', 'muted',
    `上次运行 ${fmtTime(status.last_run)} · 下次运行 ${fmtTime(status.next_run)}（${fmtCountdown(status.next_run)}）` +
    (status.running ? ' · 正在检查…' : '') +
    (status.last_summary ? ` · ${status.last_summary}` : '')));

  const actions = el('div', 'btn-row');
  const checkAllBtn = el('button', 'btn btn-sm', '全部检查');
  attrs(checkAllBtn, { type: 'button', title: '立即检查全部启用的订阅' });
  on(checkAllBtn, 'click', () => checkAll(checkAllBtn));
  if (queued > 0) {
    const retryBtn = el('button', 'btn btn-sm btn-primary', `立即补下载 ${queued} 集`);
    attrs(retryBtn, { type: 'button' });
    retryBtn.title = 'qBittorrent 已恢复的话，点这里马上把这批待下载推送给它';
    on(retryBtn, 'click', () => flushQueue(retryBtn));
    actions.append(retryBtn);
  }
  const refreshBtn = el('button', 'btn btn-sm', '刷新');
  attrs(refreshBtn, { type: 'button' });
  on(refreshBtn, 'click', () => withBusy(refreshBtn, loadSubscriptions));
  actions.append(checkAllBtn, refreshBtn);
  box.append(actions);
}

function renderSubList() {
  const list = $('sub-list');
  const empty = $('subs-empty');
  if (!list) return;
  list.replaceChildren();

  if (!state.subs.length) {
    setEmptyText('subs-empty', '还没有订阅。到「在看番剧」里点开一部番剧，选好字幕组和剧集加入订阅。');
    show('subs-empty', true);
    return;
  }
  show('subs-empty', false);
  state.subs.forEach((sub) => list.append(buildSubItem(sub)));
  syncSubsPickUI();
}

/**
 * 订阅条目（.sub-item 是 3 列 grid：封面 | 正文 | 操作）：
 *   .sub-item > img.sub-cover + .sub-main + .sub-actions
 */
/**
 * 从已下载标题里推断字幕语言（订阅没设语言时用来显示，避免一律「不限」）：
 *   [CHT]/繁体/繁中 → cht；[CHS]/简体/简中 → chs；[CHS&CHT]/简繁/简日双语 → both；[JPN]/生肉 → jp
 */
function detectLangFromHistory(history) {
  const list = Array.isArray(history) ? history.slice(0, 6) : [];
  for (const h of list) {
    const title = String((h && h.title) || '').toLowerCase();
    if (!title) continue;
    if (/简繁|chs.?&.?cht|简日双语|繁日双语/.test(title)) return 'both';
    if (/繁体|繁中|\bcht\b|\[cht\]/.test(title)) return 'cht';
    if (/简体|简中|\bchs\b|\[chs\]/.test(title)) return 'chs';
    if (/生肉|\bjpn\b|raw/.test(title)) return 'jp';
  }
  return '';
}


/* --- 我的订阅：批量操作（全部启用 / 全部停用 / 全部立即检查） ---------------- */

/* 批量操作栏：事件委托（比逐个 on() 更稳，元素只要存在就能响应） */
document.addEventListener('change', (e) => {
  const all = e.target && e.target.id === 'subs-select-all';
  if (!all) return;
  const set = subsSelected();
  set.clear();
  if (e.target.checked) (state.subs || []).forEach((s) => set.add(Number(s.subject_id)));
  syncSubsPickUI();
});

document.addEventListener('click', (e) => {
  const btn = e.target && e.target.closest ? e.target.closest('#sub-batch-bar .btn') : null;
  if (!btn) return;
  if (btn.id === 'btn-subs-batch-toggle') { e.preventDefault(); setSubsSelecting(!subsSelecting()); return; }
  if (btn.id === 'btn-subs-enable-all') { e.preventDefault(); subsBatchEnable(true); }
  else if (btn.id === 'btn-subs-disable-all') { e.preventDefault(); subsBatchEnable(false); }
  else if (btn.id === 'btn-subs-check-all') { e.preventDefault(); subsBatchCheck(); }
  else if (btn.id === 'btn-subs-delete-all') { e.preventDefault(); subsBatchDelete(); }
});

/** 批量操作前先确保订阅列表已加载（刚进页面就点按钮时列表可能还没回来）。 */
/** 批量操作：当前勾选的订阅（subject_id 集合）。 */
/** 是否处于「批量操作」选择模式（只有这时才显示复选框）。 */
function subsSelecting() {
  return Boolean(state.subsSelecting);
}

/** 进入 / 退出批量操作模式。 */
function setSubsSelecting(flag) {
  state.subsSelecting = Boolean(flag);
  const view = $('view-subs');
  if (view) view.classList.toggle('subs-selecting', state.subsSelecting);
  const bar = $('sub-batch-bar');
  if (bar) bar.classList.toggle('is-active', state.subsSelecting);
  if (!state.subsSelecting) {
    subsSelected().clear();
    syncSubsPickUI();
  }
  const toggle = $('btn-subs-batch-toggle');
  if (toggle) toggle.textContent = state.subsSelecting ? '退出批量' : '批量操作';
  syncSubsBatchUI();
}

function subsSelected() {
  if (!(state.subSelected instanceof Set)) state.subSelected = new Set();
  return state.subSelected;
}

/** 同步「全选」状态、按钮可用状态与文案。 */
function syncSubsBatchUI() {
  const set = subsSelected();
  const all = state.subs || [];
  const box = $('subs-select-all');
  if (box) {
    box.checked = all.length > 0 && set.size === all.length;
    box.indeterminate = set.size > 0 && set.size < all.length;
  }
  const n = set.size;
  for (const id of ['btn-subs-enable-all', 'btn-subs-disable-all', 'btn-subs-check-all', 'btn-subs-delete-all']) {
    const btn = $(id);
    if (btn) btn.disabled = n === 0 || !subsSelecting();
  }
  const label = $('sub-batch-count');
  if (label) label.textContent = subsSelecting() ? (n ? `已选 ${n} 部` : '点卡片左上角勾选') : '';
  setText('sub-batch-state', '');
}

/** 把订阅页所有复选框与 state.subSelected 对齐（列表重新渲染后调）。 */
function syncSubsPickUI() {
  const set = subsSelected();
  $$('#sub-list .sub-item').forEach((item) => {
    // 注意：.sub-pick 是 label 包装，勾选状态要设在里面的 input 上
    const pick = item.querySelector('.sub-pick input') || item.querySelector('.sub-pick');
    if (!pick) return;
    const on_ = set.has(Number(item.dataset.id));
    pick.checked = on_;
    item.classList.toggle('is-picked', on_);
  });
  syncSubsBatchUI();
}

async function subsForBatch() {
  if (!Array.isArray(state.subs) || !state.subs.length) {
    await loadSubscriptions();
  }
  return state.subs || [];
}

async function subsBatchEnable(enabled) {
  const all = await subsForBatch();
  const chosen = subsSelected();
  const items = all.filter((s) => chosen.has(Number(s.subject_id)));
  if (!items.length) { toast('先勾选要操作的订阅', 'info'); return; }
  const targets = items.filter((s) => Boolean(s.enabled) !== enabled);
  if (!targets.length) { toast(enabled ? '所有订阅都是启用状态' : '所有订阅都是停用状态', 'info'); return; }
  if (!enabled && !confirm(`确定要停用选中的 ${targets.length} 个订阅吗？停用后不会再自动下载。`)) return;
  const node = $('sub-batch-state');
  let done = 0;
  const btn = enabled ? $('btn-subs-enable-all') : $('btn-subs-disable-all');
  await withBusy(btn, async () => {
    for (const sub of targets) {
      try {
        await request(API.subUpdate(sub.subject_id), { method: 'POST', body: { enabled } });
        done += 1;
        if (node) node.textContent = `${enabled ? '启用' : '停用'}中… ${done}/${targets.length}`;
      } catch (err) { /* 单条失败不影响其它 */ }
    }
    if (node) node.textContent = `已${enabled ? '启用' : '停用'} ${done} 个订阅`;
    subsSelected().clear();
    toast(`已${enabled ? '启用' : '停用'} ${done} 个订阅`, 'ok');
    await reloadSubsKeepingView();
  });
}

/** 批量删除订阅（连带删掉订阅记录，不删已下载文件；先确认再执行）。 */
async function subsBatchDelete() {
  const all = await subsForBatch();
  const chosen = subsSelected();
  const items = all.filter((s) => chosen.has(Number(s.subject_id)));
  if (!items.length) { toast('先勾选要删除的订阅', 'info'); return; }
  const n = items.length;
  if (!confirm(`确定要删除选中的 ${n} 个订阅吗？\n只删订阅记录，已下载的文件不会被删除。`)) return;
  const node = $('sub-batch-state');
  let done = 0;
  await withBusy($('btn-subs-delete-all'), async () => {
    for (const sub of items) {
      try {
        await request(API.subDelete(sub.subject_id), { method: 'DELETE' });
        done += 1;
        if (node) node.textContent = `删除中… ${done}/${n}`;
      } catch (err) { /* 单条失败继续 */ }
    }
    if (node) node.textContent = `已删除 ${done} 个订阅`;
    subsSelected().clear();
    toast(`已删除 ${done} 个订阅`, done ? 'ok' : 'info');
    await reloadSubsKeepingView();
    refreshStatus();
  });
}

async function subsBatchCheck() {
  const chosen = subsSelected();
  const items = (await subsForBatch()).filter((s) => s.enabled && chosen.has(Number(s.subject_id)));
  if (!items.length) { toast('没有启用的订阅可检查', 'info'); return; }
  const node = $('sub-batch-state');
  let ok = 0;
  let found = 0;
  await withBusy($('btn-subs-check-all'), async () => {
    for (const sub of items) {
      if (node) node.textContent = `检查中… ${ok + 1}/${items.length}（第 ${found} 集新下载）`;
      try {
        const data = await request(API.subCheck(sub.subject_id), { method: 'POST', body: {} });
        const res = (data && data.result) || {};
        found += Number(res.downloaded || 0);
        ok += 1;
      } catch (err) { /* 跳过失败的 */ }
    }
    if (node) node.textContent = `检查完成：${ok} 个订阅，新下载 ${found} 集`;
    subsSelected().clear();
    toast(`检查完成：${ok} 个订阅，新下载 ${found} 集`, ok ? 'ok' : 'info');
    await reloadSubsKeepingView();
    refreshStatus();
  });
}

function buildSubItem(sub) {
  const card = el('article', 'sub-item');
  card.dataset.id = String(sub.subject_id);
  if (sub.enabled === false) card.classList.add('is-disabled');

  const cover = el('img', 'sub-cover');
  cover.loading = 'lazy';
  cover.alt = subscriptionName(sub);
  setCover(cover, sub.cover);
  // 封面右上角：跳 Bangumi 详情页（与「在看番剧」卡片同一套按钮，视觉一致）
  const coverWrap = el('div', 'sub-cover-wrap');
  // 批量操作：每张卡一个复选框（只选「要操作哪些订阅」）
  // 勾选框：和「在看番剧」卡片同一套 .card-check 样式（深浅色都适配），
  // 平时不显示，点「批量操作」进入选择模式才出现
  const pickWrap = el('label', 'card-check sub-pick');
  pickWrap.title = '勾选后可批量操作';
  const pick = el('input');
  attrs(pick, { type: 'checkbox', 'aria-label': `选择 ${sub.display_name}` });
  pick.checked = subsSelected().has(Number(sub.subject_id));
  on(pick, 'change', () => {
    const set = subsSelected();
    const id = Number(sub.subject_id);
    if (pick.checked) set.add(id); else set.delete(id);
    // 注意：卡片变量 item 在下面才声明，这里用 closest 取（否则会踩 TDZ 报错）
    const card = pick.closest('.sub-item');
    if (card) card.classList.toggle('is-picked', pick.checked);
    syncSubsBatchUI();
  });
  pickWrap.append(pick);
  coverWrap.append(pickWrap);
  coverWrap.append(cover, bangumiLink(sub.subject_id, 'sub-bgm'));

  /* ---- 正文 ---- */
  const main = el('div', 'sub-main');
  const nameText = subscriptionName(sub) || `subject-${sub.subject_id}`;
  main.append(titled('sub-title ellipsis', nameText));

  const fact = (label, value, valueClass) => {
    const wrap = el('span', 'sub-fact');
    wrap.append(el('span', null, label));
    wrap.append(el('b', valueClass || null, value));
    return wrap;
  };

  // 订阅规则单独一行（用户要求：在订阅条目上专门找一处看「资源站 / 字幕组 / 语言 / 分辨率」）
  const ruleParts = [
    (sub.source_ids && sub.source_ids.length)
      ? sub.source_ids.map((x) => sourceDisplayName(x)).join('/')
      : ((sub.sub_group || '').includes('::') ? sourceDisplayName(String(sub.sub_group).split('::')[0]) : '全部站点'),
    sub.group || '不限字幕组',
    sub.lang ? langFilterText(sub.lang) : '不限语言',
    sub.resolution || '不限分辨率',
  ];
  const rules = el('div', 'sub-rules');
  rules.append(el('span', 'sub-rules-label', '订阅规则'));
  for (const part of ruleParts) {
    if (!part) continue;
    rules.append(el('span', 'sub-rule', part));       // 每项一枚胶囊
  }
  main.append(rules);

  const facts = el('div', 'sub-facts');
  // 字幕组 / 分辨率 / 语言都已在上面「订阅规则」那一行显示，这里不重复（用户要求）
  // 进度以 qBittorrent 里真实存在的种子数为准（后端给 actual_count）；
  // qB 连不上或旧接口没有这个字段时，退回历史累计数
  const downloadedCount = Math.max(0,
    sub.qb_online && sub.actual_count !== undefined && sub.actual_count !== null
      ? Number(sub.actual_count)
      : Number(sub.downloaded_count) || 0);
  facts.append(fact('已下载', `${fmtInt(downloadedCount)} 集`));
  if (Number(sub.total_episodes) > 0) {
    facts.append(fact('进度', `${fmtInt(downloadedCount)} / ${fmtInt(sub.total_episodes)} 集`));
  } else {
    facts.append(fact('进度', `${fmtInt(downloadedCount)} 集`));
  }
  // 下次更新（北京时间）：放在「进度」后面，一眼就能看到什么时候该出新集
  const airItem = airtimeFactItem(sub.airtime);
  if (airItem) facts.append(airItem);
  main.append(facts);

  // 「上次检查 / 结果」单独放第二行（用户要求：这两项移到下一行）
  const facts2 = el('div', 'sub-facts sub-facts-2');
  facts2.append(fact('上次检查', fmtTime(sub.last_check)));
  const resultText = sub.last_result || '尚未检查';
  const resultBad = /失败|错误|异常/.test(resultText);
  facts2.append(fact('结果', resultText, resultBad ? 'state-err' : null));
  main.append(facts2);

  // qBittorrent 掉线期间攒下的待下载项：明确写出来，免得用户以为「这集没下是丢了」
  const queuedN = Number(sub.pending_count) || 0;
  if (queuedN > 0) {
    const eps = (sub.pending_episodes || []).filter((n) => Number(n) > 0).slice(0, 4);
    const hint = el('div', 'sub-pending');
    const ico = el('span', 'sub-pending-ico');
    ico.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/>'
      + '<path d="M12 7.5V12l3 2"/></svg>';
    hint.append(ico);
    const text = el('span', null,
      `待下载 ${queuedN} 集` + (eps.length ? `（第 ${eps.join(' / ')} 集）` : '') +
      '：qBittorrent 恢复后自动补下载');
    hint.append(text);
    const retry = el('button', 'link', '立即重试');
    attrs(retry, { type: 'button' });
    on(retry, 'click', () => flushQueue(retry));
    hint.append(retry);
    hint.title = 'qBittorrent 没开时先把资源存进队列（data/pending.json），连上后自动补下载';
    main.append(hint);
  }

  if (Number(sub.total_episodes) > 0) {
  }

  const path = el('div', 'sub-path', sub.folder || '（未设置下载目录）');
  path.title = sub.folder || '（未设置下载目录）';
  main.append(path);

  // 已下载记录改为弹窗展示（见 #dl-modal），卡片里不再有可展开的区块

  /* ---- 操作区 ---- */
  const actions = el('div', 'sub-actions');

  const switchWrap = el('label', 'switch');
  const toggle = el('input');
  toggle.type = 'checkbox';
  toggle.checked = sub.enabled !== false;
  toggle.setAttribute('aria-label', `启用订阅 ${nameText}`);
  on(toggle, 'change', () => toggleSubscription(sub, toggle.checked, toggle));
  switchWrap.append(toggle, el('span', null, sub.enabled !== false ? '启用' : '已停用'));
  actions.append(switchWrap);

  const btnRow = el('div', 'btn-row');

  const checkBtn = el('button', 'btn btn-sm btn-primary', '立即检查');
  attrs(checkBtn, { type: 'button' });
  on(checkBtn, 'click', () => checkOne(sub, checkBtn));

  const openBtn = el('button', 'btn btn-sm', '打开目录');
  attrs(openBtn, { type: 'button' });
  if (!sub.folder) {
    openBtn.disabled = true;
    openBtn.title = '该订阅还没有下载目录';
  }
  on(openBtn, 'click', () => openFolder(sub.folder, openBtn));

  const detailBtn = el('button', 'btn btn-sm', '已下载文件管理');
  attrs(detailBtn, { type: 'button', title: '查看并删除已下载的剧集' });
  on(detailBtn, 'click', () => openDownloadsModal(sub));

  const editBtn = el('button', 'btn btn-sm', '修改订阅');
  attrs(editBtn, { type: 'button', title: '只改字幕组/分辨率/语言/目录等设置，不重新下载' });
  on(editBtn, 'click', async () => {
    await openModal(subscriptionAsSubject(sub), { mode: 'edit', subscription: sub });
    // openModal 内部还会按默认流程切一次 tab，所以收尾时再强制停在「订阅设置」
    if (state.modal && state.modal.mode === 'edit') switchTab('sub');
  });

  const backfillBtn = el('button', 'btn btn-sm', '补下载单集');
  attrs(backfillBtn, { type: 'button', title: '搜索该番剧的资源，单独补下载某一集或合集' });
  on(backfillBtn, 'click', () => openBackfill(backfillBtn, sub));

  const delBtn = el('button', 'btn btn-sm btn-danger', '删除订阅');
  attrs(delBtn, { type: 'button' });
  on(delBtn, 'click', () => removeSubscription(sub, delBtn));

  btnRow.append(checkBtn, openBtn, detailBtn, editBtn, backfillBtn, delBtn);
  actions.append(btnRow);

  card.append(coverWrap, main, actions);
  return card;
}

/** 订阅对象 -> 弹窗用的番剧结构（补下载模式打开资源列表）。 */
function subscriptionAsSubject(sub) {
  const name = subscriptionName(sub);
  return {
    id: sub.subject_id,
    display_name: name,
    name_cn: name,
    name: sub.name_original || sub.name || '',
    cover: sub.cover || '',
    total_episodes: Number(sub.total_episodes) || 0,
    aliases: Array.isArray(sub.aliases) ? sub.aliases : [],
    airtime: sub.airtime || null,          // 补下载模式也从订阅里带上更新时刻
    subscribed: true,
  };
}

/** 「补下载单集」：以订阅身份打开资源弹窗，资源行「下载」走 /api/subscriptions/{id}/download。 */
async function openBackfill(button, sub) {
  // 不用 withBusy 包整个 openModal：弹窗里的请求一卡，按钮就会永远转圈（用户踩到过）。
  // 打开窗口本身是同步的，这里只给 300ms 的轻量反馈。
  if (button) {
    button.disabled = true;
    setTimeout(() => { button.disabled = false; }, 300);
  }
  try {
    await openModal(subscriptionAsSubject(sub), { mode: 'backfill', subscription: sub });
  } catch (err) {
    toast(`打开补下载窗口失败：${err.message}`, 'err');
  }
}

/** POST /api/subscriptions/{id}/download：把选中的单集 / 合集推送到 qBittorrent。 */
async function downloadForSubscription(sub, resource, button) {
  const name = subscriptionName(sub) || sub.subject_id;
  await withBusy(button, async () => {
    try {
      const data = await request(API.subDownload(sub.subject_id), { method: 'POST', body: { resource } });
      const updated = data.subscription || {};
      if (updated.subject_id !== undefined) Object.assign(sub, updated);
      const episode = Number(resource.episode) > 0
        ? `第 ${resource.episode} 集`
        : (resource.is_batch ? '合集' : '该资源');
      if (data.queued) {
        // qBittorrent 没开：后端已经把它存进待下载队列，恢复后自动补，不是失败
        toast(`qBittorrent 未连接，已排队：${name} ${episode}（连上后自动补下载）`, 'err');
      } else {
        toast(`已推送到 qBittorrent：${name} ${episode}`, 'ok');
      }
      if (data.queue) renderQueue(data.queue);
      if (state.view === 'subs') await loadSubscriptions();
      refreshStatus();
    } catch (err) {
      toast(`下载失败：${err.message}`, 'err');
    }
  });
}

/**
 * 订阅展开区：**管理已下载剧集**（用户要求）。
 * 每行 = 一条下载记录，右侧「删除」会同时删掉本地文件与 qBittorrent 里的做种任务。
 */
/** 「管理已下载」弹窗：打开时按当前订阅渲染记录列表。 */
function openDownloadsModal(sub) {
  const node = $('dl-modal');
  if (!node || !sub) return;
  const body = $('dl-body');
  if (body) renderSubDetail(body, sub);
  // 标题的集数用后端给的真实存活数（qB 里现在的种子数），和列表保持一致
  const hist = Array.isArray(sub.history) ? sub.history : [];
  const uniq = new Set(hist.map((h) => String(h.title || '').trim() || `ep:${h.episode || ''}`));
  const count = sub.qb_online && sub.actual_count !== undefined && sub.actual_count !== null
    ? Number(sub.actual_count) : uniq.size;
  const fileTotal = Array.isArray(sub.files) ? sub.files.length : null;
  setText('dl-sub', fileTotal === null
    ? `${subscriptionName(sub) || sub.subject_id}`
    : `${subscriptionName(sub) || sub.subject_id} · 共 ${fmtInt(fileTotal)} 个文件`);
  state.downloadsSubject = sub.subject_id;
  node.hidden = false;
  document.body.classList.add('modal-open');
}

/** 关闭「管理已下载」弹窗。 */
function closeDownloadsModal() {
  const node = $('dl-modal');
  if (node) node.hidden = true;
  state.downloadsSubject = 0;
  document.body.classList.remove('modal-open');
}

function renderSubDetail(node, sub) {
  node.replaceChildren();
  const files = Array.isArray(sub.files) ? sub.files : [];
  const folder = sub.folder || '';

  if (!files.length) {
    node.append(el('p', 'muted small', '这个文件夹里还没有视频文件。'));
    if (folder) node.append(el('p', 'muted small', `目录：${folder}`));
    return;
  }

  node.append(el('p', 'muted small',
    `文件夹里 ${fmtInt(files.length)} 个视频 · 删除时若有对应种子会连种子一起删（先删种子、再删文件）`));
  node.append(el('p', 'muted small', folder));

  const list = el('div', 'ep-list');
  files.slice(0, 200).forEach((f) => {
    const row = el('div', 'ep-row');
    const info = el('div', 'ep-info');
    const head = el('div', 'ep-head');
    head.append(el('b', null, f.episode ? `第 ${f.episode} 集` : '未知集号'));
    if (f.size) {
      const mb = f.size / 1048576;
      head.append(el('span', 'muted small',
        ` · ${mb >= 1024 ? (mb / 1024).toFixed(2) + ' GB' : mb.toFixed(0) + ' MB'}`));
    }
    if (f.mtime) head.append(el('span', 'muted small', ` · ${fmtTime(f.mtime)}`));
    info.append(head);
    info.append(titled('ep-title', f.name || ''));
    row.append(info);

    const btn = el('button', 'btn btn-sm btn-danger', '删除');
    attrs(btn, { type: 'button', title: '删除这个文件（有种子时会先删种子）' });
    on(btn, 'click', async () => {
      if (!confirm(`确定删除「${f.name}」吗？\n如果 qBittorrent 里有对应种子，会连同做种任务一起删掉。`)) return;
      try {
        const res = await request(API.subFileDelete(sub.subject_id), { method: 'POST', body: { name: f.name } });
        toast(res && res.mode === 'torrent' ? '已删除种子与文件' : '已删除文件', 'ok');
        await reloadSubsKeepingView();
        const fresh = (state.subs || []).find((x) => Number(x.subject_id) === Number(sub.subject_id));
        if (fresh) renderSubDetail(node, fresh);
      } catch (err) {
        toast(`删除失败：${err.message}`, 'err');
      }
    });
    row.append(btn);
    list.append(row);
  });
  node.append(list);
}

function magnetHash(magnet) {
  const m = /btih:([0-9a-zA-Z]{32,40})/.exec(String(magnet || ''));
  return m ? m[1] : '';
}

/**
 * 删除一条已下载剧集：POST /api/subscriptions/{id}/episodes/delete
 * 后端会删 qBittorrent 任务（deleteFiles=true → 本地文件一起没）+ 清下载记录。
 */
async function deleteEpisode(sub, entry, button) {
  const label = entry.title || (entry.episode ? `第 ${entry.episode} 集` : '该条记录');
  const ok = window.confirm(
    `确定删除这一条吗？\n\n${label}\n\n` +
    '会同时删除本地文件 + qBittorrent 里的做种任务，无法恢复。');
  if (!ok) return;
  await withBusy(button, async () => {
    try {
      const data = await request(API.subEpisodeDelete(sub.subject_id), {
        method: 'POST',
        body: { infohash: entry.infohash || '', title: entry.title || '', delete_files: true },
      });
      if (data.removed_torrent) {
        toast(data.deleted_files ? '已删除：本地文件 + qBittorrent 做种任务' : '已删除 qBittorrent 任务', 'ok');
      } else {
        toast(`已清除下载记录（${data.error || 'qB 里没有该任务'}）`, 'info');
      }
      await loadSubscriptions();
      const fresh = (state.subs || []).find((x) => Number(x.subject_id) === Number(sub.subject_id));
      if (fresh) openDownloadsModal(fresh);
      refreshStatus();
    } catch (err) {
      toast(`删除失败：${err.message}`, 'err');
    }
  });
}

/**
 * 重新拉订阅列表，但**保住用户当前看到的画面**：正在展开的「管理已下载」继续展开、滚动位置不动。
 * 用户反馈：删掉一条记录后整页跳回顶部、管理面板自己关掉了。
 */
async function reloadSubsKeepingView(subjectId, withinNode) {
  const panel = withinNode ? withinNode.closest('.sub-downloads') : null;
  const wasOpen = !!panel && !panel.hidden;
  const scrollY = window.scrollY;
  await loadSubscriptions();
  if (!wasOpen) return;
  const card = document.querySelector(`#sub-list .sub-item[data-id="${subjectId}"]`);
  const btn = card ? [...card.querySelectorAll('.sub-actions .btn')]
    .find((b) => b.textContent.trim() === '已下载文件管理') : null;
  if (btn) btn.click();
  window.scrollTo(0, scrollY);
}

/** POST /api/subscriptions/{id}/check */
async function checkOne(sub, button) {
  const name = subscriptionName(sub) || sub.subject_id;
  await withBusy(button, async () => {
    toast(`正在检查「${name}」…`, 'info');
    try {
      const data = await request(API.subCheck(sub.subject_id), { method: 'POST', body: {} });
      const result = data.result || {};
      const text = result.error
        ? `检查出错：${result.error}`
        : `搜索到 ${fmtInt(result.found || 0)} 条，新增下载 ${fmtInt(result.downloaded || 0)} 集`;
      toast(text, result.error ? 'err' : 'ok');
      await reloadSubsKeepingView(sub.subject_id, button);
      refreshStatus();
    } catch (err) {
      toast(`检查失败：${err.message}`, 'err');
    }
  });
}

/** POST /api/subscriptions/{id}/update {enabled} */
async function toggleSubscription(sub, enabled, input) {
  await withBusy(input, async () => {
    try {
      const data = await request(API.subUpdate(sub.subject_id), { method: 'POST', body: { enabled } });
      const updated = data.subscription || {};
      sub.enabled = updated.enabled === undefined ? enabled : updated.enabled;
      toast(sub.enabled ? '已启用该订阅' : '已停用该订阅（不再自动下载新集）', 'ok');
      await reloadSubsKeepingView(sub.subject_id, input);
      refreshStatus();
    } catch (err) {
      if (input) input.checked = sub.enabled !== false;
      toast(`更新失败：${err.message}`, 'err');
    }
  });
}

/** DELETE /api/subscriptions/{id}（需确认） */
async function removeSubscription(sub, button) {
  const name = subscriptionName(sub) || `subject-${sub.subject_id}`;
  if (!window.confirm(`确定删除订阅「${name}」吗？\n已下载的文件不会被删除，只是停止自动追番。`)) return;
  await withBusy(button, async () => {
    try {
      await request(API.subDelete(sub.subject_id), { method: 'DELETE', body: {} });
      toast(`已删除订阅：${name}`, 'ok');
      await loadSubscriptions();
      refreshStatus();
    } catch (err) {
      toast(`删除失败：${err.message}`, 'err');
    }
  });
}

/** POST /api/qb/open-folder {path} */
async function openFolder(path, button) {
  if (!path) {
    toast('该订阅还没有下载目录', 'err');
    return;
  }
  await withBusy(button, async () => {
    try {
      await request(API.openFolder, { method: 'POST', body: { path } });
      toast('已在资源管理器中打开', 'ok');
    } catch (err) {
      toast(`打开目录失败：${err.message}`, 'err');
    }
  });
}

/** POST /api/subscriptions/check-all */
async function checkAll(button) {
  await withBusy(button, async () => {
    toast('正在检查全部订阅…', 'info');
    try {
      const data = await request(API.checkAll, { method: 'POST', body: {} });
      const result = data.result || {};
      if (result.skipped) {
        toast(`未执行：${result.reason || '上一轮检查仍在进行'}`, 'err');
        return;
      }
      toast(`检查完成：${fmtInt(result.checked || 0)} 部，新增下载 ${fmtInt(result.downloaded || 0)} 集`, 'ok');
      const failed = (Array.isArray(result.details) ? result.details : []).filter((d) => d && d.error);
      if (failed.length) toast(`${failed.length} 个订阅出错：${failed[0].error}`, 'err');
      await refreshStatus();
      if (state.view === 'subs') await loadSubscriptions();
    } catch (err) {
      toast(`检查失败：${err.message}`, 'err');
    }
  });
}

/* =============================================================================
 * 9. 设置页
 * ========================================================================== */

/** GET /api/config：回填设置项 + 资源站列表。 */
async function loadConfig() {
  try {
    const cfg = await request(API.config);
    state.config = cfg;
    state.tokenSet = !!cfg.bangumi_token || !!cfg.token_set;
    state.sources = sortSources(cfg.sources);
    fillSettings();
    renderSourceList();
    announce('config');

    const input = $('token-input');
    if (input) {
      input.value = '';
      input.placeholder = state.tokenSet
        ? `已保存（${cfg.bangumi_token_masked || '已配置'}）· 留空表示不修改`
        : '粘贴 Access Token';
    }
    // 配置里的 ui.theme 不再由这里落地：主题模式由 ui.js 权威管理（localStorage 优先），
    // 两边同时写 html[data-theme] 会互相覆盖。
  } catch (err) {
    showError($('token-state'), `读取配置失败：${err.message}`);
    showError($('save-state'), `读取配置失败：${err.message}`);
    toast(`读取配置失败：${err.message}`, 'err');
  }
}

function sortSources(sources) {
  return (Array.isArray(sources) ? sources : [])
    .map((s) => Object.assign({}, s))
    .sort((a, b) => (Number(a.priority) || 99) - (Number(b.priority) || 99));
}

function fillSettings() {
  const cfg = state.config || {};
  const qb = cfg.qbittorrent || {};
  const download = cfg.download || {};
  const proxy = cfg.proxy || {};
  const subscription = cfg.subscription || {};
  const server = cfg.server || {};

  setValue('cfg-qb-url', qb.base_url || '');
  setValue('cfg-qb-user', qb.username || '');
  setValue('cfg-qb-pass', qb.password || '');
  setValue('cfg-qb-cat', qb.category || '');
  setValue('cfg-qb-tags', qb.tags || '');

  setValue('cfg-root', download.root || '');

  setChecked('cfg-proxy-on', !!proxy.enabled);
  setValue('cfg-proxy-url', proxy.url || '');
  setChecked('cfg-proxy-bgm', proxy.for_bangumi !== false);
  setChecked('cfg-proxy-src', proxy.for_sources !== false);

  setChecked('cfg-sub-on', subscription.enabled !== false);
  setValue('cfg-sub-interval', subscription.interval_minutes === undefined ? 30 : subscription.interval_minutes);
  setSelectValue($('cfg-sub-initial'), subscription.initial_mode || 'latest');
  setValue('cfg-sub-max', subscription.max_episodes_per_round === undefined ? 3 : subscription.max_episodes_per_round);

  setValue('cfg-host', server.host || '127.0.0.1');
  setValue('cfg-port', server.port === undefined ? 7788 : server.port);
  setChecked('cfg-lan', !!server.allow_lan);
  setChecked('cfg-openbrowser', server.open_browser_on_start !== false);
  renderLanHint(server);

  setText('config-path', cfg.config_path ? `配置文件：${cfg.config_path}` : '');
  setTitle('config-path', cfg.config_path || '');
}

/**
 * 局域网访问提示：把可用地址显示出来（手机/平板照抄），并说清楚「要重启服务才生效」。
 * 地址来自 /api/status 的 lan_urls（后端过滤掉回环/链路本地/代理 fake-IP 段）。
 */
function renderLanHint(server) {
  const box = $('lan-hint');
  if (!box) return;
  const status = state.status || {};
  const urls = Array.isArray(status.lan_urls) ? status.lan_urls : [];
  const on = !!server.allow_lan || String(server.host || '') === '0.0.0.0';
  box.replaceChildren();
  if (!on) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const live = !!status.lan_enabled;      // 服务当前是否真的监听着局域网（改完没重启时是 false）
  box.append(el('b', null, live ? '局域网地址（同一 Wi-Fi 下用手机/平板打开）：' : '局域网访问：'));
  if (live && urls.length) {
    const list = el('span', 'lan-urls');
    urls.forEach((u) => {
      const a = el('a', 'lan-url', u);
      a.href = u;
      a.target = '_blank';
      a.rel = 'noreferrer';
      list.append(a);
    });
    box.append(list);
    box.append(el('span', 'muted small', '（如果打不开，检查 Windows 防火墙是否放行、或这台电脑的 IP 是否变了）'));
  } else if (live) {
    box.append(el('span', 'muted small', '没找到可用的网卡地址'));
  } else {
    box.append(el('span', 'muted small',
      '已保存，但**需要重启服务**才生效（关掉窗口重新双击 start.bat，或用设置页的「重启」提示）'));
  }
}

/** 资源站列表：编号 + 启用开关 + 上移/下移（保存时按顺序写回 priority）。 */
function renderSourceList() {
  const box = $('source-list');
  if (!box) return;
  box.replaceChildren();

  if (!state.sources.length) {
    box.append(el('p', 'muted small', '没有可用的资源站配置。'));
    return;
  }

  state.sources.forEach((source, index) => {
    const row = el('div', 'source-row');
    if (source.enabled === false) row.classList.add('is-disabled');

    row.append(el('div', 'source-rank', String(index + 1)));

    const info = el('div', 'source-info');
    info.append(el('div', 'source-name', source.name || source.id || '未命名站点'));
    const url = el('div', 'source-url source-base', source.base || '');
    url.title = source.base || '';
    info.append(url);
    row.append(info);

    const switchWrap = el('label', 'switch');
    const toggle = el('input');
    toggle.type = 'checkbox';
    toggle.checked = source.enabled !== false;
    toggle.setAttribute('aria-label', `启用 ${source.name || source.id}`);
    on(toggle, 'change', () => {
      source.enabled = toggle.checked;
      row.classList.toggle('is-disabled', !toggle.checked);
    });
    switchWrap.append(toggle, el('span', null, '启用'));
    row.append(switchWrap);

    const actions = el('div', 'source-actions');
    const upBtn = el('button', 'icon-btn', '↑');
    attrs(upBtn, { type: 'button', title: '上移（更优先）' });
    upBtn.disabled = index === 0;
    on(upBtn, 'click', () => moveSource(index, -1));
    const downBtn = el('button', 'icon-btn', '↓');
    attrs(downBtn, { type: 'button', title: '下移' });
    downBtn.disabled = index === state.sources.length - 1;
    on(downBtn, 'click', () => moveSource(index, 1));
    actions.append(upBtn, downBtn);
    row.append(actions);

    box.append(row);
  });
}

function moveSource(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= state.sources.length) return;
  const moved = state.sources.splice(index, 1)[0];
  state.sources.splice(target, 0, moved);
  renderSourceList();
}

/** 数值收敛（避免把非法值写进配置）。 */
function clampInt(raw, min, max, fallback) {
  const n = parseInt(String(raw), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** #btn-save-config：POST /api/config（后端深度合并，只传改动字段）。 */
async function saveConfig() {
  const node = $('save-state');
  await withBusy($('btn-save-config'), async () => {
    const previous = state.config || {};
    const prevServer = previous.server || {};
    const host = val('cfg-host').trim() || '127.0.0.1';
    const port = clampInt(val('cfg-port'), 1024, 65535, 7788);

    const patch = {
      qbittorrent: {
        base_url: val('cfg-qb-url').trim(),
        username: val('cfg-qb-user').trim(),
        password: val('cfg-qb-pass'),
        category: val('cfg-qb-cat').trim(),
        tags: val('cfg-qb-tags').trim(),
      },
      download: {
        root: val('cfg-root').trim(),
        },
      proxy: {
        enabled: checked('cfg-proxy-on'),
        url: val('cfg-proxy-url').trim(),
        for_bangumi: checked('cfg-proxy-bgm'),
        for_sources: checked('cfg-proxy-src'),
      },
      subscription: {
        enabled: checked('cfg-sub-on'),
        interval_minutes: clampInt(val('cfg-sub-interval'), 5, 1440, 30),
        initial_mode: val('cfg-sub-initial') || 'latest',
        max_episodes_per_round: clampInt(val('cfg-sub-max'), 1, 50, 3),
        },
      server: {
        host,
        port,
        allow_lan: checked('cfg-lan'),
        open_browser_on_start: checked('cfg-openbrowser'),
      },
      sources: state.sources.map((s, i) => ({
        id: s.id,
        name: s.name,
        enabled: s.enabled !== false,
        base: s.base,
        priority: i + 1,
      })),
    };

    const token = val('token-input').trim();
    if (token) patch.bangumi_token = token;   // 留空 = 不改动已保存的 Token

    showInfo(node, '正在保存…');
    try {
      const data = await request(API.config, { method: 'POST', body: patch });
      state.config = data.config || state.config;
      state.sources = sortSources(state.config.sources);
      fillSettings();
      renderSourceList();

      if (token) {
        state.tokenSet = true;
        const input = $('token-input');
        if (input) {
          input.value = '';
          input.placeholder = `已保存（${state.config.bangumi_token_masked || '已配置'}）· 留空表示不修改`;
        }
      }

      const needRestart = String(prevServer.host || '') !== host || Number(prevServer.port || 0) !== port;
      showOk(node, `已保存 ${timeNow()}${needRestart ? '（监听地址/端口将在重启后生效）' : ''}`);
      toast(needRestart ? '设置已保存（监听地址/端口需重启生效）' : '设置已保存', 'ok');
      await refreshStatus();
    } catch (err) {
      showError(node, `保存失败：${err.message}`);
      toast(`保存失败：${err.message}`, 'err');
    }
  });
}

/** #btn-qb-test：GET /api/qb/test。 */
async function testQb() {
  await withBusy($('btn-qb-test'), async () => {
    const node = $('qb-state');
    showInfo(node, '正在连接 qBittorrent…');
    try {
      const info = await request(API.qbTest);
      if (info.ok) {
        const categories = (Array.isArray(info.categories) && info.categories.length)
          ? info.categories.join('、')
          : '（无）';
        showOk(node, `连接成功 · qBittorrent ${info.version || '?'} · WebAPI ${info.webapi_version || '?'}` +
          ` · 默认目录 ${info.default_save_path || '–'} · 分类 ${categories}`);
        toast('qBittorrent 连接正常', 'ok');
      } else {
        showError(node, `连接失败：${info.error || '未知错误'}${info.base_url ? `（${info.base_url}）` : ''}`);
        toast('qBittorrent 连接失败', 'err');
      }
      await refreshStatus();
    } catch (err) {
      showError(node, `测试失败：${err.message}`);
      toast(`测试失败：${err.message}`, 'err');
    }
  });
}

/** #btn-show-folders：GET /api/qb/folders，点击条目调用 open-folder。 */
async function loadFolders() {
  await withBusy($('btn-show-folders'), async () => {
    const box = $('folder-list');
    if (!box) return;
    box.replaceChildren(el('p', 'muted small', '正在读取下载目录…'));
    try {
      const data = await request(API.qbFolders);
      const folders = Array.isArray(data.folders) ? data.folders : [];
      box.replaceChildren();

      if (!data.root_exists) {
        box.append(el('p', 'state-err',
          `下载根目录不存在：${data.root || '（未设置）'}。请先填写正确的下载根目录并保存。`));
        return;
      }
      if (!folders.length) {
        box.append(el('p', 'muted small', `目录 ${data.root} 下还没有番剧文件夹。`));
        return;
      }
      box.append(el('p', 'muted small', `${data.root} 下共 ${folders.length} 个文件夹（点击可在资源管理器中打开）`));
      folders.forEach((folder) => {
        const item = el('button', 'folder-item');
        item.type = 'button';
        item.title = folder.path || '';
        item.append(el('span', 'folder-name', folder.name || ''));
        item.append(el('span', 'folder-size', folder.size || '–'));
        on(item, 'click', () => openFolder(folder.path, item));
        box.append(item);
      });
    } catch (err) {
      box.replaceChildren(el('p', 'state-err', `读取下载目录失败：${err.message}`));
      toast(`读取下载目录失败：${err.message}`, 'err');
    }
  });
}

/* ---------------------------------------------------------------------------
 * 9b. 设置页的「资源缓存」面板（动态注入，index.html 不新增挂载点）
 * ------------------------------------------------------------------------ */

let lastWarmup = null;           // 最近一次预热状态（/api/status 或 /api/cache/status）

/** 在设置页注入「资源缓存」面板：立即预热 / 停止预热 / 清理缓存。幂等。 */
function ensureCachePanel() {
  if ($('cache-panel')) return null;
  const settings = document.querySelector('#view-config .settings');
  if (!settings) return null;

  const panel = el('div', 'panel');
  panel.id = 'cache-panel';
  const head = el('div', 'panel-head');
  head.append(el('h2', null, '资源缓存'));
  head.append(el('span', 'hint', '搜索结果缓存到本机，打开番剧详情秒显示；找新资源时在弹窗里点「重新搜索」联网刷新'));
  panel.append(head);

  const row = el('div', 'btn-row');
  const warmBtn = el('button', 'btn', '立即预热全部番剧');
  attrs(warmBtn, { type: 'button' });
  warmBtn.id = 'btn-cache-warm';
  const stopBtn = el('button', 'btn btn-ghost', '停止预热');
  attrs(stopBtn, { type: 'button' });
  stopBtn.id = 'btn-cache-stop';
  stopBtn.hidden = true;                       // 只在预热进行中出现
  const clearBtn = el('button', 'btn', '清理资源缓存');
  attrs(clearBtn, { type: 'button' });
  clearBtn.id = 'btn-cache-clear';
  row.append(warmBtn, stopBtn, clearBtn);
  panel.append(row);

  const state = el('div', 'inline-state');
  state.id = 'cache-state';
  panel.append(state);

  const saveBar = settings.querySelector('.save-bar');
  if (saveBar) settings.insertBefore(panel, saveBar);
  else settings.append(panel);

  on(warmBtn, 'click', () => cacheWarm(warmBtn));
  on(stopBtn, 'click', () => cacheWarmStop(stopBtn));
  on(clearBtn, 'click', () => cacheClear(clearBtn));
  renderCachePanelState();
  return panel;
}

/** 面板里的状态行 + 「停止预热」按钮显隐（跟随最近一次预热状态）。 */
function renderCachePanelState() {
  const stop = $('btn-cache-stop');
  if (stop) stop.hidden = !(lastWarmup && lastWarmup.running);
}

/** POST /api/cache/warm：手动预热全部番剧资源（后台任务，进度靠轮询）。 */
async function cacheWarm(button) {
  const node = $('cache-state');
  await withBusy(button, async () => {
    showInfo(node, '正在启动预热…');
    try {
      const data = await request(API.cacheWarm, { method: 'POST', body: {} });
      const total = Number(data.total) || 0;
      showOk(node, total ? `已开始预热 ${fmtInt(total)} 部番剧的资源（进度见「在看番剧」页顶部）`
                         : '已开始预热资源（进度见「在看番剧」页顶部）');
      toast('已开始预热资源缓存', 'ok');
      syncWarmupPolling({ running: true });    // 立刻进入 4s 轮询
      refreshCacheStatus();
    } catch (err) {
      showError(node, `预热失败：${err.message}`);
      toast(`预热失败：${err.message}`, 'err');
    }
  });
}

/** POST /api/cache/warm/stop：停止当前预热。 */
async function cacheWarmStop(button) {
  const node = $('cache-state');
  await withBusy(button, async () => {
    try {
      await request(API.cacheWarmStop, { method: 'POST', body: {} });
      showOk(node, '已请求停止预热');
      toast('已停止预热', 'info');
      syncWarmupPolling(null);
      refreshStatus();
      refreshCacheStatus();
    } catch (err) {
      showError(node, `停止预热失败：${err.message}`);
      toast(`停止预热失败：${err.message}`, 'err');
    }
  });
}

/** POST /api/cache/clear {prefix:'search:'}：只清搜索结果缓存，不动其它数据。 */
async function cacheClear(button) {
  const node = $('cache-state');
  await withBusy(button, async () => {
    try {
      const data = await request(API.cacheClear, { method: 'POST', body: { prefix: 'search:' } });
      const removed = Number(data.removed !== undefined ? data.removed : data.count);
      showOk(node, `已清理资源缓存${Number.isFinite(removed) ? `（${fmtInt(removed)} 条）` : ''}`);
      toast('已清理资源缓存', 'ok');
      refreshStatus();
      refreshCacheStatus();
    } catch (err) {
      showError(node, `清理缓存失败：${err.message}`);
      toast(`清理缓存失败：${err.message}`, 'err');
    }
  });
}

/* =============================================================================
 * 10. 日志页
 * ========================================================================== */

async function loadLogs() {
  await withBusy($('btn-reload-logs'), async () => {
    const box = $('logbox');
    if (!box) return;
    try {
      const data = await request(API.logs(LOG_LINES));
      const lines = Array.isArray(data.lines) ? data.lines : [];
      box.textContent = lines.length ? lines.join('\n') : '（暂无日志）';
      box.scrollTop = box.scrollHeight;
    } catch (err) {
      box.textContent = `日志加载失败：${err.message}`;
      toast(`日志加载失败：${err.message}`, 'err');
    }
    announce('logs');
  });
}

/* =============================================================================
 * 11. 「显示噪声项」开关（动态注入 #tab-res .filters，index.html 不改）
 * ========================================================================== */

let noiseToggle = null;      // <input type="checkbox">
let noiseLabelSpan = null;   // 文案节点（带隐藏数量）

function ensureNoiseToggle() {
  if (noiseToggle && document.contains(noiseToggle)) return noiseToggle;
  // 优先挂到第二行（含合集那一行），这样第一个筛选行不会被挤乱
  const filters = document.querySelector('#tab-res .filters-row2')
    || document.querySelector('#tab-res .filters');
  if (!filters) return null;

  const label = el('label', 'check');
  label.title = 'PV / 音乐 / 字幕文件等噪声条目，默认隐藏';
  const box = el('input');
  box.type = 'checkbox';
  box.className = 'f-noise-toggle';
  noiseLabelSpan = el('span', null, NOISE_LABEL);
  label.append(box, noiseLabelSpan);

  const spacer = filters.querySelector('.spacer');
  if (spacer) filters.insertBefore(label, spacer);
  else filters.append(label);

  noiseToggle = box;
  on(box, 'change', renderResources);
  return box;
}

/* =============================================================================
 * 12. 主题与启动引导
 * ========================================================================== */

/**
 * 三态主题（跟随系统 / 深色 / 浅色）由 app/web/ui.js 统一管理，它在 index.html 里
 * 先于本文件加载，负责：写 html[data-theme] 与 html[data-themeMode]、持久化
 * localStorage（anime-auto-dl-theme）、跟随系统主题变化、并在变化时派发
 * document 事件 `theme:changed`（detail: {mode, theme}）以及同步 #btn-theme 文案。
 *
 * 因此这里只做「转发 + 降级」，绝不自己写 html[data-theme]：两份状态互相覆盖正是
 * 之前主题表现不稳定的原因。
 */

/** ui.js 暴露的主题工具；没加载（如精简测试页）时返回 null。 */
function themeApi() {
  const ui = window.__ui;
  return (ui && typeof ui.cycleTheme === 'function' && typeof ui.storedTheme === 'function') ? ui : null;
}

/** 当前模式：'auto' | 'dark' | 'light'；ui.js 缺席时返回 ''。 */
function themeMode() {
  const ui = themeApi();
  if (!ui) return '';
  try {
    return ui.storedTheme() || 'auto';
  } catch (err) {
    return '';
  }
}

/** 模式的中文名（跟随系统 / 深色 / 浅色）；ui.js 缺席时退回模式本身。 */
function themeModeLabel(mode) {
  const ui = themeApi();
  if (!ui || typeof ui.modeLabel !== 'function') return String(mode || '');
  try {
    return ui.modeLabel(mode);
  } catch (err) {
    return String(mode || '');
  }
}

/** 当前生效主题：'dark' | 'light'。只读 html 属性，不写。 */
function currentTheme() {
  const ui = themeApi();
  if (ui && typeof ui.theme === 'string' && ui.theme) return ui.theme;
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}

/**
 * 侧栏「切换主题」：跟随系统 → 深色 → 浅色 → 跟随系统（三态由 ui.js 决定顺序）。
 * ui.js 自己会在 theme:changed 里更新按钮文案，这里只负责提示，不碰按钮文字。
 */
function cycleTheme() {
  const ui = themeApi();
  if (!ui) {
    // 降级：ui.js 缺失时既不接管主题也不报错
    toast('主题组件未加载，暂时无法切换主题', 'err');
    return;
  }
  const theme = ui.cycleTheme();
  const effective = currentTheme() || theme;   // 以 DOM 上的生效值为准（auto 模式下等于系统主题）
  toast(`主题：${themeModeLabel(themeMode())}（当前${effective === 'light' ? '浅色' : '深色'}）`, 'info', 1500);
}

// 主题变化时本文件没有需要重绘的内容：表格 / 卡片 / 弹窗的颜色全部由 styles.css 的
// CSS 变量按 html[data-theme] 切换，下拉框由 ui.js 自己同步，所以不挂 theme:changed 监听。
// 若以后需要联动（例如按主题换占位图），在这里 document.addEventListener('theme:changed', …) 即可。

/** 统一绑定静态事件（元素均来自 index.html）。 */
function bindEvents() {
  // 侧栏
  $$('#nav .nav-item').forEach((btn) => on(btn, 'click', () => switchView(btn.dataset.view)));
  on($('btn-theme'), 'click', cycleTheme);

  // Token 与在看番剧
  on($('btn-save-token'), 'click', saveToken);
  on($('btn-load-anime'), 'click', loadAnime);
  on($('token-input'), 'keydown', (e) => {
    if (e.key === 'Enter') saveToken();
  });
  on($('check-all'), 'change', onCheckAll);
  on($('only-airing'), 'change', renderAnime);
  on($('anime-filter'), 'input', renderAnime);
  // 批量订阅：勾选番剧后 #batch-actions 才出现
  // 「批量订阅」一律打开规则窗口（以前这里直接建订阅，完全绕过筛选，是用户踩到的坑）
  on($('btn-batch-sub'), 'click', openBatchModal);
  on($('btn-batch-fetch'), 'click', () => batchSubscribe('fetch', $('btn-batch-fetch')));
  on($('btn-clear-selection'), 'click', clearSelection);

  // 弹窗
  on($('m-close'), 'click', closeModal);
  on($('modal'), 'click', (e) => {
    if (e.target === $('modal')) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if ($('updates-modal') && !$('updates-modal').hidden) closeUpdatesModal();
    closeModal();
  });
  $$('#m-tabs .tab').forEach((tab) => on(tab, 'click', () => switchTab(tab.dataset.tab)));
  on($('dl-close'), 'click', closeDownloadsModal);
  on($('btn-subs-enable-all'), 'click', () => subsBatchEnable(true));
  on($('btn-subs-disable-all'), 'click', () => subsBatchEnable(false));
  on($('btn-subs-check-all'), 'click', subsBatchCheck);
  on($('btn-subs-delete-all'), 'click', subsBatchDelete);
  // 预取字幕组候选：打开「批量订阅」时下拉已经是满的（只读缓存，很快）
  setTimeout(() => { if (!(state.batchGroups || []).length) loadBatchGroups(); }, 1200);
  on($('batch-close'), 'click', closeBatchModal);
  on($('batch-add-rule'), 'click', () => {
    batchRules().push({ source: '', group: '', lang: '', resolution: '' });
    saveBatchRules();
    renderBatchRules();
  });
  on($('batch-run'), 'click', runBatchSubscribe);
  on($('batch-modal'), 'click', (e) => { if (e.target === $('batch-modal')) closeBatchModal(); });
  on($('dl-modal'), 'click', (e) => { if (e.target === $('dl-modal')) closeDownloadsModal(); });
  ['f-source', 'f-group', 'f-res', 'f-sort', 'f-batch'].forEach((id) => on($(id), 'change', renderResources));
  // 点表头排序（用户要求：搜索结果支持按标签排序）
  $$('#res-table thead th.sortable').forEach((th) => on(th, 'click', () => onHeaderSortClick(th)));
  paintSortIndicators();
  // 语言筛选：本地过滤即可（不强制联网）；整批结果都没标语言时提示一次可「重新搜索」按站内语言过滤
  on($('f-lang'), 'change', () => {
    renderResources();
    promptLangRescan();
  });
  // 「重新搜索」= 强制联网（搜索结果默认走本地缓存，只有这里显式 force）
  on($('f-season'), 'change', () => {
    // 「只看本季」关掉时重新搜一次：后端会返回含上一季的全量结果
    state.onlyCurrentSeason = checked('f-season');
    runSearch({ force: false });
  });
  on($('btn-research'), 'click', () => withBusy($('btn-research'), () => runSearch({ force: true })));
  // 手动搜索：输入框回车 / 点按钮都触发；「恢复自动搜索」清空关键词后按番剧名重搜
  on($('btn-keyword-search'), 'click', () => withBusy($('btn-keyword-search'), () => runSearch({ keyword: val('f-keyword').trim() })));
  on($('f-keyword'), 'keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    runSearch({ keyword: val('f-keyword').trim() });
  });
  on($('f-keyword'), 'input', syncKeywordUI);
  on($('btn-keyword-reset'), 'click', () => {
    setValue('f-keyword', '');
    setValue('s-keyword', '');
    syncKeywordUI();
    runSearch({});
  });
  // 加入订阅：资源来自 #s-episode 选中项（没选即只订阅不下载）
  on($('btn-sub-add'), 'click', () => addSubscription(null, { button: $('btn-sub-add') }));
  // 资源列表筛选条里的「加入订阅」：点选的行 → 选中的集数 → 提示并切到订阅设置
  on($('btn-sub-add-res'), 'click', () => addSubscriptionFromResList($('btn-sub-add-res')));
  // 显式选了要下载的集数时，取消资源列表的点选（最近一次选择优先）
  on($('s-episode'), 'change', onEpisodeChoiceChanged);
  on($('btn-goto-res'), 'click', () => switchTab('res'));
  // 订阅设置：任一字段变化都刷新集数下拉与「当前将订阅什么」预览
  on($('s-group'), 'change', () => {
    updateSubGroupTip();
    refreshEpisodeSelect();
    renderSubPreview();
  });
  on($('s-res'), 'change', () => {
    refreshEpisodeSelect();
    renderSubPreview();
  });
  ['s-episode', 's-initial', 's-total', 's-folder', 's-keyword'].forEach((id) => {
    on($(id), 'change', renderSubPreview);
    on($(id), 'input', renderSubPreview);
  });

  // 设置
  on($('btn-save-config'), 'click', saveConfig);
  // 勾上/取消「允许局域网访问」时马上更新地址提示（保存后才生效，提示里会写清楚）
  on($('cfg-lan'), 'change', () => renderLanHint({
    allow_lan: checked('cfg-lan'),
    host: val('cfg-host'),
  }));
  on($('btn-qb-test'), 'click', testQb);
  on($('btn-show-folders'), 'click', loadFolders);
  on($('btn-check-now'), 'click', () => checkAll($('btn-check-now')));
  // 侧栏「最近更新」的「更多」：弹出窗口列出最近最多 50 条更新
  on($('btn-side-updates'), 'click', () => openUpdatesModal());
  // 侧栏「待下载」那一行：点一下立刻重试补下载
  on($('row-pending'), 'click', () => flushQueue($('row-pending')));
  on($('updates-close'), 'click', () => closeUpdatesModal());
  on($('updates-modal'), 'click', (e) => { if (e.target === $('updates-modal')) closeUpdatesModal(); });
  // 侧栏「近期更新」的「全部」：跳到我的订阅页
  on($('btn-side-updates'), 'click', () => switchView('subs'));

  // 日志
  on($('btn-reload-logs'), 'click', loadLogs);
}

/**
 * mock 模式等待测试页就绪（window.__MOCK_READY__ 可以是 Promise 或布尔值）。
 * 最多等 5 秒，避免测试页忘记注入时一直挂住。
 */
async function waitMockReady() {
  if (!MOCK_MODE) return;
  const isPromise = (v) => v && typeof v.then === 'function';
  if (!window.__MOCK_READY__) {
    const deadline = Date.now() + 5000;
    while (!window.__MOCK_READY__ && Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 50));
    }
  }
  if (isPromise(window.__MOCK_READY__)) {
    try {
      await window.__MOCK_READY__;
    } catch (err) { /* mock 数据准备失败时继续渲染错误态 */ }
  }
}

/** 启动：先渲染骨架与中文空状态，再拉状态与配置。 */
async function boot() {
  // 主题不在这里应用：ui.js 已在它自己的 boot() 里按 localStorage / 系统偏好写好
  // html[data-theme]（index.html 还先用内联脚本抢了一次，避免首屏闪色）。
  ensureNoiseToggle();
  ensureCachePanel();         // 设置页的「资源缓存」面板（动态注入）
  ensureWarmupLine();         // 「在看番剧」页顶部的预热进度行（先建好，有数据才显示）
  bindEvents();
  switchView('anime');
  showAnimeEmpty('还没有数据。填写 Token 后点击「拉取在看番剧」。');
  setText('selected-count', '已选 0 部');
  setText('nav-count-anime', '–');
  setText('nav-count-subs', '–');

  await waitMockReady();      // ?mock 模式下等测试页替换好 fetch
  await Promise.allSettled([loadConfig(), refreshStatus()]);

  // 侧栏「近期更新」：不用先点「我的订阅」也能看到最近会更新哪几部
  await ensureSidebarUpdates();
  window.setInterval(() => { ensureSidebarUpdates(); }, 5 * 60 * 1000);
  // 状态轮询：qBittorrent 掉线时「待下载」行要自己冒出来，恢复后也要自己消失并提示
  window.setInterval(() => {
    if (!document.hidden) refreshStatus();
  }, 30 * 1000);

  // 已有 Token 时自动拉一次在看列表（失败不阻塞，错误由 loadAnime 自行提示）
  if (state.tokenSet) await loadAnime();

  document.body.classList.add('app-ready');
  announce(state.view);
}

/** 侧栏「近期更新」：没数据就先拉一次订阅（失败静默，别影响主流程）。 */
async function ensureSidebarUpdates() {
  if (!(state.subs || []).length) {
    try {
      const data = await request(API.subscriptions);
      state.subs = Array.isArray(data.items) ? data.items : [];
      setText('nav-count-subs', String(state.subs.length));
    } catch (err) {
      /* 侧栏信息拿不到就保持隐藏，不打扰用户 */
    }
  }
  renderSidebarUpdates();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
