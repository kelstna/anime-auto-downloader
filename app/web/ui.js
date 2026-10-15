/* SPDX-FileCopyrightText: Copyright (C) 2026 kelstna (AI-assisted, see NOTICE.md)
   SPDX-License-Identifier: GPL-3.0-only */
/* =============================================================================
 * 自动下载番剧 · UI 增强（app/web/ui.js）
 * -----------------------------------------------------------------------------
 * 1. 自绘下拉框（替代原生 select 的弹层）
 *    原生 <select> 展开后的选项面板由操作系统绘制，CSS 无法设置圆角/间距/悬停，
 *    所以这里保留原生 select 作为「真值来源 + 键盘与无障碍载体」，在其上覆盖一层
 *    自绘面板。语义、value、change 事件与原生完全一致，app.js 无需任何改动。
 * 2. 主题：深色 / 浅色 / 跟随系统，系统主题变化时实时跟随。
 *
 * 无第三方依赖。所有样式在 styles.css 的「自绘下拉框」与主题区块中定义。
 * ========================================================================== */
'use strict';

(function () {
  const THEME_KEY = 'anime-auto-dl-theme';
  const ENHANCED = new WeakMap();          // select -> api
  const instances = [];                    // 已增强的实例（用于全局关闭/重排）
  let openInstance = null;
  let activeScrollCloser = null;
  let seq = 0;

  // 尺寸/填充直接写在属性上：SVG 若在没有 CSS 的情况下渲染，
  // 会按默认 300x150 画布铺开成「白色大方块 + 巨大黑箭头」（样式表没加载/被旧缓存命中时必现）。
  // 属性是兜底，CSS 仍可覆盖。踩过这个坑，所以不依赖样式表。
  const CHEVRON_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" '
    + 'style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2.4;'
    + 'stroke-linecap:round;stroke-linejoin:round">'
    + '<path d="M6 9l6 6 6-6"/></svg>';

  /* ==========================================================================
   * 1. 自绘下拉框
   * ======================================================================== */

  function isEnhanceable(sel) {
    if (!sel || sel.tagName !== 'SELECT') return false;
    if (sel.dataset.nativeSelect === 'true') return false;      // 显式要求用原生
    if (sel.multiple || Number(sel.size) > 1) return false;     // 多选/列表型不接管
    return true;
  }

  /**
   * select 当前是否可见。
   *
   * 注意：这里**不作为是否接管的门槛**。曾经用它做门禁（隐藏视图里的 select 不接管、
   * 靠 20×500ms 重试等它出现），结果是「用户超过 10 秒才打开弹窗/切到设置页时，
   * 里面的下拉永远是原生样式」——很难复现但一定会被用户撞到。
   * 隐藏元素也能安全地建好自绘控件（不依赖布局），容器一显示就是自绘样式。
   * 该函数仅保留给测试/调试判断用。
   */
  function isVisible(sel) {
    return !!(sel.offsetParent || sel.getClientRects().length);
  }

  function enhance(sel) {
    if (ENHANCED.has(sel) || !isEnhanceable(sel)) return;

    const id = sel.id || `sel-${++seq}`;
    const listId = `${id}-listbox`;

    const wrap = document.createElement('div');
    wrap.className = 'sel';

    const display = document.createElement('button');
    display.type = 'button';
    display.className = 'sel-display';
    display.id = `${id}-display`;
    display.setAttribute('role', 'combobox');
    display.setAttribute('aria-haspopup', 'listbox');
    display.setAttribute('aria-expanded', 'false');
    display.setAttribute('aria-controls', listId);
    if (sel.getAttribute('aria-label')) display.setAttribute('aria-label', sel.getAttribute('aria-label'));

    const label = document.createElement('span');
    label.className = 'sel-label';
    const chev = document.createElement('span');
    chev.className = 'sel-chevron';
    chev.innerHTML = CHEVRON_SVG;
    display.append(label, chev);

    const panel = document.createElement('div');
    panel.className = 'sel-panel';
    panel.id = listId;
    panel.setAttribute('role', 'listbox');
    panel.hidden = true;

    let search = null;                       // 选项多时出现的筛选框
    let list = document.createElement('div');
    list.className = 'sel-list';

    wrap.append(display, panel);
    sel.classList.add('sel-native');
    sel.setAttribute('tabindex', '-1');
    sel.setAttribute('aria-hidden', 'true');
    // 原生 select 在 DOM 里紧邻自绘控件，位置一致便于脚本查找
    sel.parentNode.insertBefore(wrap, sel.nextSibling);

    const api = {
      sel, wrap, display, panel, list, label, id,
      get value() { return sel.value; },
      set value(v) {
        if (sel.value === v) { sync(); return; }
        sel.value = v;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
      },
      close, rebuild, sync, open,
    };
    ENHANCED.set(sel, api);
    instances.push(api);

    /* ---------- 结构与选项 ---------- */
    /** 展平 select.options（含 optgroup 里的），保留真实索引以便回写 selectedIndex。 */
    function optionRows() {
      return Array.from(sel.options).map((o, i) => ({ o, i }));
    }

    /**
     * 选项按 optgroup 分组的结构：[{label, rows:[{o,i}]}, ...]。
     * 没有 optgroup 时返回单组 label=null，渲染时就不画分组标题。
     * 用途：字幕组按资源站分组展示（用户明确要求不要跨站合并）。
     */
    function optionGroups() {
      const groups = [];
      Array.from(sel.children).forEach((child) => {
        if (child.tagName === 'OPTGROUP') {
          const rows = Array.from(child.children)
            .filter((c) => c.tagName === 'OPTION')
            .map((o) => ({ o, i: o.index }));
          if (rows.length) groups.push({ label: child.label || '', rows, disabled: child.disabled });
        } else if (child.tagName === 'OPTION') {
          let g = groups.find((x) => x.label === null);
          if (!g) { g = { label: null, rows: [] }; groups.push(g); }
          g.rows.push({ o: child, i: child.index });
        }
      });
      return groups;
    }

    function matches(o, q) {
      if (!q) return true;
      return String(o.textContent || '').toLowerCase().includes(q);
    }

    function rebuild() {
      const rows = optionRows();
      const needSearch = rows.length > 12;
      panel.replaceChildren();

      if (needSearch) {
        search = document.createElement('div');
        search.className = 'sel-search';
        const input = document.createElement('input');
        input.type = 'search';
        input.placeholder = '筛选…';
        input.setAttribute('aria-label', '筛选选项');
        input.autocomplete = 'off';
        input.addEventListener('input', () => paint(input.value.trim().toLowerCase()));
        input.addEventListener('keydown', onSearchKey);
        search.append(input);
        panel.append(search);
      } else {
        search = null;
      }

      list = document.createElement('div');
      list.className = 'sel-list';
      list.setAttribute('role', 'presentation');
      panel.append(list);
      paint('');
      sync();
    }

    /** 渲染选项；有 optgroup 时画分组标题与分隔线。 */
    function paint(query) {
      list.replaceChildren();
      const groups = optionGroups();
      let shown = 0;
      const hasGroupLabel = groups.some((g) => g.label !== null);

      groups.forEach((g) => {
        const rows = g.rows.filter(({ o }) => matches(o, query));
        if (!rows.length) return;
        if (hasGroupLabel && g.label) {
          const head = document.createElement('div');
          head.className = 'sel-group';
          head.setAttribute('role', 'presentation');
          head.textContent = g.label;
          list.append(head);
        }
        rows.forEach(({ o, i }) => {
          shown++;
          const item = document.createElement('div');
          item.className = 'sel-option';
          item.setAttribute('role', 'option');
          item.dataset.index = String(i);
          item.setAttribute('aria-selected', o.selected ? 'true' : 'false');
          if (o.selected) item.classList.add('is-selected');
          if (o.disabled || g.disabled) { item.classList.add('is-disabled'); item.setAttribute('aria-disabled', 'true'); }

          const text = document.createElement('span');
          text.className = 'sel-option-text';
          text.textContent = o.textContent;
          item.append(text);
          item.title = o.title || o.textContent;

          item.addEventListener('mouseenter', () => setActive(i));
          item.addEventListener('click', (ev) => {
            ev.preventDefault();
            if (o.disabled || g.disabled) return;
            choose(i);
          });
          list.append(item);
        });
      });

      if (!shown) {
        const empty = document.createElement('div');
        empty.className = 'sel-empty';
        empty.textContent = '没有匹配的选项';
        list.append(empty);
        return;
      }
      const cur = list.querySelector('.sel-option.is-selected') || list.querySelector('.sel-option:not(.is-disabled)');
      if (cur) activeIndex = Number(cur.dataset.index);
    }

    function optionNode(i) {
      return list.querySelector(`.sel-option[data-index="${i}"]`);
    }

    let activeIndex = -1;

    function setActive(i) {
      activeIndex = i;
      list.querySelectorAll('.sel-option').forEach((n) => n.classList.toggle('is-active', Number(n.dataset.index) === i));
    }

    function scrollActiveIntoView() {
      const node = optionNode(activeIndex);
      if (node && node.scrollIntoView) node.scrollIntoView({ block: 'nearest' });
    }

    /** 把 select 的状态同步到自绘控件 */
    function sync() {
      const o = sel.selectedOptions && sel.selectedOptions[0];
      label.textContent = o ? o.textContent : '';
      const disabled = sel.disabled || sel.options.length === 0;
      display.disabled = !!sel.disabled;
      wrap.classList.toggle('is-disabled', disabled);
      const rows = optionRows();
      if (rows.length > 12) {
        // 选项很多时，标题上补一个数量提示，避免用户以为只有几条
        display.title = `${label.textContent}（共 ${rows.length} 项）`;
      } else {
        display.title = label.textContent;
      }
      list.querySelectorAll('.sel-option').forEach((n) => {
        const isSel = Number(n.dataset.index) === sel.selectedIndex;
        n.classList.toggle('is-selected', isSel);
        n.setAttribute('aria-selected', isSel ? 'true' : 'false');
      });
    }

    function choose(i) {
      const opt = sel.options[i];
      if (!opt) return;
      sel.selectedIndex = i;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      sync();
      close();
      display.focus();
    }

    /* ---------- 开关 ---------- */
    function open() {
      if (wrap.classList.contains('is-disabled')) return;
      if (openInstance && openInstance !== api) openInstance.close();
      openInstance = api;
      if (!panel.childElementCount) rebuild();
      else paint('');
      sync();
      panel.hidden = false;
      wrap.classList.add('is-open');
      display.setAttribute('aria-expanded', 'true');
      setActive(sel.selectedIndex);
      scrollActiveIntoView();
      const input = search && search.querySelector('input');
      if (input) { input.value = ''; window.setTimeout(() => input.focus(), 0); }
      document.addEventListener('pointerdown', onDocPointerDown, true);
      window.addEventListener('resize', close, true);
      // 面板滚动祖先滚动时收起（避免面板与控件脱节）。
      // 注意：滚轮在面板里滚动时，滚到尽头会「链式滚动」到祖先，于是面板自己被关掉
      // （用户报的「在这个下拉栏滚动滚轮会自动关闭下拉栏」）。这里判断事件源，
      // 只要滚动发生在面板/控件内部就不收起；再配合 CSS 的 overscroll-behavior: contain 彻底断开链式滚动。
      const scroller = panel.closest('.tab-body') || panel.closest('.modal');
      if (scroller) {
        activeScrollCloser = (ev) => {
          const t = ev && ev.target;
          if (t && (panel === t || wrap === t || panel.contains(t) || wrap.contains(t))) return;
          close();
        };
        scroller.addEventListener('scroll', activeScrollCloser, { passive: true });
      }
    }

    function close() {
      if (panel.hidden) return;
      panel.hidden = true;
      wrap.classList.remove('is-open');
      display.setAttribute('aria-expanded', 'false');
      document.removeEventListener('pointerdown', onDocPointerDown, true);
      window.removeEventListener('resize', close, true);
      if (activeScrollCloser) {
        const scrollers = document.querySelectorAll('.tab-body, .modal');
        scrollers.forEach((s) => s.removeEventListener('scroll', activeScrollCloser));
        activeScrollCloser = null;
      }
      if (openInstance === api) openInstance = null;
    }

    function onDocPointerDown(ev) {
      if (!wrap.contains(ev.target)) close();
    }

    /* ---------- 键盘 ---------- */
    display.addEventListener('click', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();                 // 避免触发外层 label / 卡片点击
      if (panel.hidden) open(); else close();
    });
    display.addEventListener('keydown', (ev) => {
      const k = ev.key;
      if (panel.hidden) {
        if (k === 'Enter' || k === ' ' || k === 'ArrowDown' || k === 'ArrowUp') {
          ev.preventDefault();
          open();
        }
        return;
      }
      if (k === 'Escape') { ev.preventDefault(); close(); display.focus(); return; }
      if (k === 'Tab') { close(); return; }
      if (k === 'Enter' || k === ' ') { ev.preventDefault(); choose(activeIndex); return; }
      if (k === 'ArrowDown' || k === 'ArrowUp') {
        ev.preventDefault();
        const step = k === 'ArrowDown' ? 1 : -1;
        let i = activeIndex;
        for (let n = 0; n < sel.options.length; n++) {
          i += step;
          if (i < 0) i = sel.options.length - 1;
          if (i >= sel.options.length) i = 0;
          if (!sel.options[i].disabled) break;
        }
        setActive(i);
        scrollActiveIntoView();
        return;
      }
      if (k === 'Home') { ev.preventDefault(); setActive(0); scrollActiveIntoView(); return; }
      if (k === 'End') { ev.preventDefault(); setActive(sel.options.length - 1); scrollActiveIntoView(); }
    });

    function onSearchKey(ev) {
      if (ev.key === 'Escape') { ev.preventDefault(); close(); display.focus(); }
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp' || ev.key === 'Enter') {
        ev.preventDefault();
        const step = ev.key === 'ArrowUp' ? -1 : 1;
        const nodes = Array.from(list.querySelectorAll('.sel-option'));
        if (!nodes.length) return;
        let pos = nodes.findIndex((n) => Number(n.dataset.index) === activeIndex);
        pos = Math.min(Math.max(pos + (ev.key === 'Enter' ? 0 : step), 0), nodes.length - 1);
        setActive(Number(nodes[pos].dataset.index));
        scrollActiveIntoView();
        if (ev.key === 'Enter') choose(activeIndex);
      }
    }

    // 选项/禁用状态被脚本改动时自动同步（app.js 用 replaceChildren 重建 options）
    const mo = new MutationObserver(() => { sync(); if (!panel.hidden) rebuild(); });
    mo.observe(sel, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'selected', 'label'] });
    sel.addEventListener('change', sync);

    rebuild();
  }

  /** 扫描并接管页面上所有可增强的 select（幂等，可在任意时刻重复调用） */
  function enhanceAll(root) {
    // data-native：这类 select 保持浏览器原生下拉（自绘面板会被弹窗滚动区裁掉）
    (root || document).querySelectorAll('select:not([data-native])').forEach((s) => enhance(s));
  }

  /* ==========================================================================
   * 2. 主题：深色 / 浅色 / 跟随系统
   * ======================================================================== */

  const media = window.matchMedia('(prefers-color-scheme: light)');

  function storedTheme() {
    try { return localStorage.getItem(THEME_KEY) || 'auto'; } catch (e) { return 'auto'; }
  }

  function systemTheme() {
    return media.matches ? 'light' : 'dark';
  }

  function applyTheme(mode) {
    const m = (mode === 'light' || mode === 'dark') ? mode : 'auto';
    const effective = m === 'auto' ? systemTheme() : m;
    document.documentElement.dataset.theme = effective;
    document.documentElement.dataset.themeMode = m;
    try { localStorage.setItem(THEME_KEY, m); } catch (e) { /* 隐私模式下忽略 */ }
    document.dispatchEvent(new CustomEvent('theme:changed', {
      detail: { mode: m, theme: effective },
    }));
    return effective;
  }

  function cycleTheme() {
    const order = ['auto', 'dark', 'light'];
    const cur = storedTheme();
    const next = order[(order.indexOf(cur) + 1) % order.length];
    return applyTheme(next);
  }

  // 系统主题变化时，仅当处于「跟随系统」才重新应用
  const onSystemChange = () => { if (storedTheme() === 'auto') applyTheme('auto'); };
  if (media.addEventListener) media.addEventListener('change', onSystemChange);
  else if (media.addListener) media.addListener(onSystemChange);

  /* ==========================================================================
   * 3. 启动
   * ======================================================================== */

  function boot() {
    // 主题要在首屏尽早应用（index.html 里的内联脚本已先做一次，这里做权威接管）
    applyTheme(storedTheme());

    enhanceAll(document);

    // 视图/tab 切换会显示原本隐藏的 select；只在确实新增了 select 时才重新扫描，
    // 且忽略自绘控件内部的变化，避免观察器自激。
    let pending = false;
    const mo = new MutationObserver((records) => {
      let need = false;
      for (const r of records) {
        if (r.target && r.target.closest && r.target.closest('.sel')) continue;
        for (const n of r.addedNodes) {
          if (n.nodeType !== 1) continue;
          if (n.tagName === 'SELECT' || (n.querySelector && n.querySelector('select'))) { need = true; break; }
        }
        if (need) break;
      }
      if (!need || pending) return;
      pending = true;
      window.requestAnimationFrame(() => { pending = false; enhanceAll(document); });
    });
    mo.observe(document.body, { childList: true, subtree: true });

    // 让 app.js / 测试脚本也能拿到主题工具
    window.__ui = {
      applyTheme, cycleTheme, storedTheme, systemTheme, enhanceAll,
      modeLabel(mode) {
        return { auto: '跟随系统', dark: '深色', light: '浅色' }[mode] || '跟随系统';
      },
      get themeMode() { return storedTheme(); },
      get theme() { return document.documentElement.dataset.theme; },
    };

    // 主题按钮文案：显示当前模式（跟随系统 / 深色 / 浅色）
    const syncThemeButton = () => {
      const btn = document.getElementById('btn-theme');
      if (!btn) return;
      const mode = storedTheme();
      btn.textContent = `主题：${window.__ui.modeLabel(mode)}`;
      btn.title = mode === 'auto'
        ? `当前跟随系统（${systemTheme() === 'light' ? '浅色' : '深色'}），点击切换`
        : '点击切换：跟随系统 → 深色 → 浅色';
    };
    // app.js 自己绑定了 #btn-theme 的点击，这里只在主题真正变化后同步文案
    document.addEventListener('theme:changed', syncThemeButton);
    syncThemeButton();
    window.setTimeout(syncThemeButton, 300);

    document.body.classList.add('ui-ready');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
