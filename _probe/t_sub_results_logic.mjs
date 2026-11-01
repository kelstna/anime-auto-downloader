/* 订阅设置页「筛选结果」的筛选口径逻辑测试（Node，无第三方依赖、不开浏览器）。
 *
 * 为什么要这个探针：`_probe/t_sub_results_ui.py` 要真的拉起 Chrome，而某些环境
 * （例如 DSH 沙箱里 Chrome 起不来，报 "Error launching CrashSender.exe"）跑不了。
 * 这个脚本不进浏览器，**直接从 app/web/app.js 里抽取真实的函数源码**（不是抄一份），
 * 在最小 DOM 桩上跑，验证「资源站 / 限定字幕组 / 限定分辨率 / 字幕语言 / 含合集」
 * 五个条件筛出来的条数与口径。
 *
 * 用法：node _probe/t_sub_results_logic.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_JS = path.join(HERE, '..', 'app', 'web', 'app.js');
const src = fs.readFileSync(APP_JS, 'utf8');

/** 从源码里抠出 `function name(...) {...}` 的完整文本（跳字符串与注释，按花括号配平）。 */
function extractFn(text, name) {
  const head = new RegExp(`function\\s+${name}\\s*\\(`).exec(text);
  if (!head) throw new Error(`app.js 里找不到函数 ${name}`);
  const start = head.index;
  const i = text.indexOf('{', start);
  if (i < 0) throw new Error(`函数 ${name} 没有函数体`);
  let depth = 0;
  let out = '';
  for (let k = i; k < text.length; k += 1) {
    const ch = text[k];
    const next = text[k + 1];
    if (ch === '/' && next === '/') {                 // 行注释
      const end = text.indexOf('\n', k);
      k = end < 0 ? text.length : end;
      continue;
    }
    if (ch === '/' && next === '*') {                 // 块注释
      const end = text.indexOf('*/', k + 2);
      k = end < 0 ? text.length : end + 1;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') {     // 字符串（含模板串）
      out += ch;
      let k2 = k + 1;
      while (k2 < text.length) {
        out += text[k2];
        if (text[k2] === '\\') { out += text[k2 + 1] || ''; k2 += 2; continue; }
        if (text[k2] === ch) break;
        k2 += 1;
      }
      k = k2;
      continue;
    }
    if (ch === '{') depth += 1;
    if (ch === '}') {
      depth -= 1;
      out += ch;
      if (depth === 0) return text.slice(start, k + 1);   // 连函数头一起返回
      continue;
    }
    out += ch;
  }
  throw new Error(`函数 ${name} 的花括号没有配平`);
}

// ---- 最小 DOM 桩：只看 getElementById(id).value / .checked ----
const controls = {};               // id -> {value, checked}
const document = {
  getElementById(id) { return controls[id] || null; },
};
const state = {
  modal: null,
  config: { sources: [
    { id: 'dmhy', name: '动漫花园', priority: 1 },
    { id: 'kisssub', name: '爱恋动漫', priority: 2 },
    { id: 'nyaa', name: 'Nyaa', priority: 3 },
  ] },
};
const $ = (id) => document.getElementById(id);
const GROUP_VALUE_SEP = '::';

const FN_NAMES = ['val', 'checked', 'normGroup', 'groupMatch', 'splitGroupValue',
                  'rawLang', 'langMatches', 'sourceOrder', 'sourceRank', 'sortResourceRows',
                  'subResFilters', 'filterSubResources'];
// extractFn 返回完整函数文本，原样拼起来即可（不抄写逻辑，测的就是 app.js 里那份）
const sandbox = [`const GROUP_VALUE_SEP = ${JSON.stringify(GROUP_VALUE_SEP)};`,
                 ...FN_NAMES.map((n) => extractFn(src, n))]
  .join('\n');
// eslint-disable-next-line no-new-func
const api = new Function('document', 'state', '$', `${sandbox}\nreturn { filterSubResources, subResFilters };`)(
  document, state, $,
);

// ---- mock 资源：与 _probe/ui_fixture_template.html 里 498378 那 8 条一致 ----
const resources = [
  { source: 'dmhy', group: '桜都字幕组', resolution: '1080p', lang: 'chs', is_batch: false, is_noise: false, episode: 13 },
  { source: 'dmhy', group: '桜都字幕组', resolution: '1080p', lang: 'both', is_batch: false, is_noise: false, episode: 13 },
  { source: 'kisssub', group: '爱恋字幕社', resolution: '1080p', lang: 'cht', is_batch: false, is_noise: false, episode: 12 },
  { source: 'nyaa', group: 'SubsPlease', resolution: '1080p', lang: '', is_batch: false, is_noise: false, episode: 13 },
  { source: 'dmhy', group: '沸班亚马制作组', resolution: '1080p', lang: 'both', is_batch: true, is_noise: false, episode: 1, episode_end: 13 },
  { source: 'dmhy', group: '云光字幕组', resolution: '1080p', lang: 'both', is_batch: false, is_noise: false, episode: 11 },
  { source: 'nyaa', group: 'Erai-raws', resolution: '1080p', lang: 'both', is_batch: false, is_noise: false, episode: 13 },
  { source: 'kisssub', group: '爱恋&猫恋汉化组', resolution: '1080p', lang: 'both', is_batch: false, is_noise: false, episode: 12 },
];
state.modal = { resources };

const PASS = [];
const FAIL = [];
function check(name, cond, extra = '') {
  (cond ? PASS : FAIL).push(name);
  console.log(`  [${cond ? '通过' : '失败'}] ${name}${extra ? `  — ${extra}` : ''}`);
}

/** 设订阅设置页的四个筛选控件 + 含合集开关。 */
function setFilters({ source = '', group = '', res = '', lang = '', batch = false }) {
  controls['s-source'] = { value: source, checked: false };
  controls['s-group'] = { value: group, checked: false };
  controls['s-res'] = { value: res, checked: false };
  controls['s-lang'] = { value: lang, checked: false };
  controls['s-batch'] = { value: '', checked: batch };
  controls['f-sort'] = { value: 'default', checked: false };   // 排序：站点优先级
  return api.filterSubResources();
}

console.log('='.repeat(74));
console.log('订阅设置「筛选结果」的筛选口径（真实源码抽取，Node 跑）');
console.log('='.repeat(74));

console.log('\n【1】默认：不限条件、不勾含合集');
let r = setFilters({});
check('列出 7 条（8 条里 1 条合集被隐藏）', r.rows.length === 7, `${r.rows.length} 条`);
check('总数记成 8 条', r.total === 8, String(r.total));
check('隐藏的合集 = 1 条', r.hiddenBatch === 1, String(r.hiddenBatch));
check('没有噪声项', r.hiddenNoise === 0, String(r.hiddenNoise));
check('第一条是站点优先级最高的 dmhy', r.rows[0].source === 'dmhy', r.rows[0].source);

console.log('\n【2】限定字幕组（站点::组名）');
r = setFilters({ group: 'dmhy::桜都字幕组' });
check('桜都字幕组 → 2 条', r.rows.length === 2, `${r.rows.length} 条`);
check('2 条都是桜都字幕组', r.rows.every((x) => x.group === '桜都字幕组'));

console.log('\n【3】字幕语言（精确匹配，选简体不含简繁）');
r = setFilters({ group: 'dmhy::桜都字幕组', lang: 'chs' });
check('桜都 + 简体 → 1 条', r.rows.length === 1, `${r.rows.length} 条`);
check('留下的那条就是 chs', r.rows[0] && r.rows[0].lang === 'chs');
r = setFilters({ lang: 'unknown' });
check('「未标注」只认空语言（Nyaa SubsPlease 那条）',
  r.rows.length >= 1 && r.rows.every((x) => !x.lang), `${r.rows.length} 条`);

console.log('\n【4】限定分辨率');
r = setFilters({ res: '720p' });
check('锁定 720p（结果里没有）→ 0 条', r.rows.length === 0, `${r.rows.length} 条`);
r = setFilters({ res: '1080P' });
check('分辨率大小写不敏感（1080P 也是 7 条）', r.rows.length === 7, `${r.rows.length} 条`);

console.log('\n【5】资源站（与字幕组的站点必须成对）');
r = setFilters({ source: 'nyaa', group: 'dmhy::桜都字幕组' });
check('资源站=Nyaa 但组是 dmhy 的 → 0 条', r.rows.length === 0, `${r.rows.length} 条`);
r = setFilters({ source: 'nyaa' });
check('只留 Nyaa 的 2 条单集', r.rows.length === 2, `${r.rows.length} 条`);
check('这 2 条都在 nyaa', r.rows.every((x) => x.source === 'nyaa'));

console.log('\n【6】含合集开关');
r = setFilters({ batch: true });
check('勾上「含合集」→ 8 条', r.rows.length === 8, `${r.rows.length} 条`);
check('合集那条真的在里面', r.rows.some((x) => x.is_batch));
r = setFilters({ batch: true, source: 'nyaa' });
check('含合集 + 只 Nyaa → 仍 2 条（合集在 dmhy）', r.rows.length === 2, `${r.rows.length} 条`);

console.log('\n【7】空状态要能分清原因（modal.resources 为空）');
const keep = state.modal.resources;
state.modal.resources = [];
r = setFilters({});
check('整轮没结果时 total=0（界面据此显示「还没有搜索结果」）', r.total === 0 && r.rows.length === 0);
state.modal.resources = keep;

console.log();
console.log(`结果：通过 ${PASS.length} 项，失败 ${FAIL.length} 项`);
for (const f of FAIL) console.log('  [失败]', f);
process.exit(FAIL.length ? 1 : 0);
