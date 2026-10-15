"""
CDP 表单一致性测试：直接量测「设置页」与「弹窗订阅页」的实际渲染几何，
验证用户反馈的「UI 不统一」问题（控件宽高/标签基线/列对齐/间距）。

不依赖 app.js，只测 CSS + 真实 DOM 结构（_probe/ui_components.html）。
用法：python _probe/cdp_forms.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "_probe"))

from cdp_test import WS, free_port, wait_cdp, open_page   # noqa: E402

BROWSER = next((p for p in (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)
SHOTS = os.path.join(ROOT, "_probe", "shots")
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'通过' if cond else '失败'}] {name}{(' — ' + str(extra)) if extra else ''}")


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


MEASURE = r"""
(() => {
  const q = s => document.querySelector(s);
  const qa = s => [...document.querySelectorAll(s)];
  const box = el => { const b = el.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), t:+b.top.toFixed(1), b:+b.bottom.toFixed(1),
            w:+b.width.toFixed(1), h:+b.height.toFixed(1)}; };
  const out = {};

  function gridStats(sel, label) {
    const grids = qa(sel);
    if (!grids.length) return null;
    const res = { label, grids: grids.length, cells: [], rows: [] };
    grids.forEach((g, gi) => {
      const cs = [...g.children].filter(c => c.classList.contains('form-cell'));
      res.cells.push(cs.length);
      // 每个单元格：label 顶边、控件顶边/高度、提示顶边
      const info = cs.map(c => {
        const lab = c.querySelector(':scope > label, :scope > .label-ghost');
        const ctl = c.querySelector(':scope > input, :scope > select, :scope > .btn');
        const tip = c.querySelector(':scope > .field-tip');
        return {
          gi,
          labTop: lab ? box(lab).t : null,
          labH: lab ? box(lab).h : null,
          ctlTop: ctl ? box(ctl).t : null,
          ctlH: ctl ? box(ctl).h : null,
          ctlW: ctl ? box(ctl).w : null,
          ctlTag: ctl ? ctl.tagName : null,
          ctlCls: ctl ? ctl.className : null,
          tipTop: tip ? box(tip).t : null,
          cellBox: box(c),
          span: getComputedStyle(c).gridColumn,
        };
      });
      res.rows.push(info);
      // 同一行（相同 ctlTop）内的控件高度与宽度
      const byTop = {};
      info.forEach(x => { if (x.ctlTop != null) { const k = x.ctlTop.toFixed(0); (byTop[k] = byTop[k] || []).push(x); } });
      res.sameRow = Object.values(byTop).map(row => ({
        n: row.length,
        heights: [...new Set(row.map(x => x.ctlH))],
        widths: [...new Set(row.map(x => Math.round(x.ctlW)))],
        tags: [...new Set(row.map(x => x.ctlTag))],
        labTops: [...new Set(row.map(x => x.labTop))],
      }));
    });
    return res;
  }

  out.subForm = gridStats('#tab-sub .form-grid', 'modal-sub');
  out.cfgForms = gridStats('#view-config .form-grid', 'config');

  // 全局控件尺寸一致性（同类控件宽高应一致）
  const sizes = {};
  qa('input:not([type=checkbox]):not([type=search]), select').forEach(el => {
    if (!el.offsetParent) return;                 // 跳过隐藏视图
    const b = box(el);
    const k = el.tagName + '.' + (el.className || '-');
    (sizes[k] = sizes[k] || new Set()).add(Math.round(b.h));
  });
  out.controlHeights = Object.fromEntries(Object.entries(sizes).map(([k, v]) => [k, [...v]]));

  // 按钮高度一致性（按「使用场景」分组：表格行内更紧凑是刻意设计，不算不一致）
  const btns = {};
  qa('button.btn, button.icon-btn').forEach(el => {
    if (!el.offsetParent) return;
    const scope = el.closest('.data-table') ? '表格行内' : (el.closest('.sub-item') ? '订阅条目' : '面板/其他');
    const k = scope + ' · ' + (el.className.split(' ').filter(c => c.startsWith('btn')).join('.') || 'icon-btn');
    (btns[k] = btns[k] || new Set()).add(Math.round(box(el).h));
  });
  out.buttonHeights = Object.fromEntries(Object.entries(btns).map(([k, v]) => [k, [...v]]));

  // 控件高度（按容器分组，跳过隐藏视图）
  const ctrlByScope = {};
  qa('input:not([type=checkbox]), select').forEach(el => {
    if (!el.offsetParent) return;
    const scope = el.closest('.data-table') ? '表格内'
      : el.closest('.filters') ? '筛选条'
      : el.closest('.toolbar') ? '工具栏'
      : '表单';
    (ctrlByScope[scope] = ctrlByScope[scope] || new Set()).add(Math.round(box(el).h));
  });
  out.controlHeightsByScope = Object.fromEntries(
    Object.entries(ctrlByScope).map(([k, v]) => [k, [...v]]));

  // 面板内边距一致性
  out.panelPaddings = [...new Set(qa('.panel').map(p => getComputedStyle(p).padding))];
  // 面板间距
  out.panelGaps = (() => {
    const ps = qa('#view-config .panel');
    const gaps = [];
    for (let i = 1; i < ps.length; i++) gaps.push(Math.round(box(ps[i]).t - box(ps[i - 1]).b));
    return [...new Set(gaps)];
  })();
  // 字号一致性（同级文本）
  out.fontSizes = {
    panelH2: [...new Set(qa('.panel-head h2').map(e => getComputedStyle(e).fontSize))],
    label: [...new Set(qa('.form-cell > label').map(e => getComputedStyle(e).fontSize))],
    input: [...new Set(qa('.form-cell > input, .form-cell > select').map(e => getComputedStyle(e).fontSize))],
    btn: [...new Set(qa('.panel .btn').map(e => getComputedStyle(e).fontSize))],
    tip: [...new Set(qa('.field-tip').map(e => getComputedStyle(e).fontSize))],
  };
  // 圆角一致性
  out.radii = {
    input: [...new Set(qa('.form-cell > input, .form-cell > select').map(e => getComputedStyle(e).borderRadius))],
    btn: [...new Set(qa('.panel .btn').map(e => getComputedStyle(e).borderRadius))],
    panel: [...new Set(qa('.panel').map(e => getComputedStyle(e).borderRadius))],
  };
  // 批量操作条
  const ba = q('#batch-actions');
  out.batchActions = ba ? { hidden: ba.hidden, h: box(ba).h, btns: ba.querySelectorAll('button').length } : null;
  // 订阅预览
  const sp = q('#s-preview');
  out.preview = sp ? { h: Math.round(box(sp).h), text: sp.textContent.replace(/\s+/g, ' ').trim().slice(0, 120) } : null;
  // 溢出
  out.overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  return out;
})()
"""


def main() -> int:
    print("=" * 76)
    print("CDP 表单/UI 一致性测试（真实 Chrome 量测）")
    print("=" * 76)
    assert BROWSER

    port = free_port()
    cdp = free_port()
    handler = lambda *a, **kw: Quiet(*a, directory=ROOT, **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    profile = os.path.join(tempfile.gettempdir(), f"form-{int(time.time())}")
    proc = subprocess.Popen(
        [BROWSER, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
         "--no-first-run", "--disable-extensions", "--force-device-scale-factor=1",
         "--window-size=1600,1200", f"--user-data-dir={profile}",
         f"--remote-debugging-port={cdp}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        wait_cdp(cdp)
        ws = WS(open_page(cdp, f"http://127.0.0.1:{port}/_probe/ui_components.html"))
        ws.call("Runtime.enable")
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": 1600, "height": 1200, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1.6)
        d = ws.call("Runtime.evaluate", {"expression": MEASURE, "returnByValue": True})["result"]["value"]

        # ---------- 弹窗订阅页 ----------
        print("\nA. 弹窗「订阅设置」页（新结构）")
        sf = d.get("subForm")
        check("订阅页使用 form-grid + form-cell", bool(sf) and sf["cells"] and sf["cells"][0] >= 6,
              f"格子数 {sf['cells'] if sf else '-'}")
        if sf:
            allcells = [c for row in sf["rows"] for c in row]
            ctl = [c for c in allcells if c["ctlH"] is not None]
            print(f"    控件：{[(c['ctlTag'], c['ctlH']) for c in ctl]}")
            heights = {c["ctlH"] for c in ctl}
            check("所有控件高度一致（输入框/下拉/按钮同高）", len(heights) == 1, f"高度集合 {heights}")
            # 标签基线：同一行内 label 顶边一致
            bad = []
            for row in sf.get("sameRow", []):
                if len(row["labTops"]) > 1:
                    bad.append(row["labTops"])
            check("同一行内 label 顶边一致（文字对齐）", not bad, f"不一致行 {bad}")
            # 同行控件宽度一致（不等宽会导致观感不统一，span-2 单独看）
            for row in sf.get("sameRow", []):
                if row["n"] >= 2 and len(row["widths"]) > 1:
                    print(f"    同行宽度差异：{row['widths']}（span-2 属正常）")
            # label 高度一致
            lab_h = {c["labH"] for c in allcells if c["labH"] is not None}
            check("label 行高一致", len(lab_h) == 1, f"{lab_h}")
            # 按钮在 .sub-actions / .form-cell-btn 里，不应与输入框强行等宽
            btn_cells = [c for c in allcells if c["ctlTag"] == "BUTTON"]
            grid_direct_btns = [c for c in allcells if c["ctlTag"] == "BUTTON" and c["ctlW"]]
            check("按钮不与输入框强行等宽（按需自适应）",
                  all(c["ctlW"] < 400 for c in grid_direct_btns) if grid_direct_btns else True,
                  f"按钮宽度 {[round(c['ctlW']) for c in grid_direct_btns]}")
            # span-2 单元格应占两列宽
            spans = [c for c in allcells if "span 2" in (c.get("span") or "")]
            normal = [c for c in allcells if (c.get("span") or "").startswith("auto") and c["ctlW"]]
            if spans and normal:
                check("跨两列的单元格确实约为单列两倍宽",
                      spans[0]["ctlW"] > max(n["ctlW"] for n in normal) * 1.6,
                      f"span2={round(spans[0]['ctlW'])} 单列={round(max(n['ctlW'] for n in normal))}")
            # 预览区
            pv = d.get("preview")
            check("订阅预览区已渲染且高度合理", bool(pv) and 24 <= pv["h"] <= 80, str(pv)[:110])

        # ---------- 设置页 ----------
        print("\nB. 设置页（6 个 form-grid 面板）")
        cf = d.get("cfgForms")
        check("设置页全部使用 form-grid", bool(cf) and cf["grids"] >= 5, f"{cf['grids'] if cf else 0} 个面板")
        if cf:
            allcells = [c for row in cf["rows"] for c in row]
            ctl = [c for c in allcells if c["ctlH"] is not None]
            heights = {}
            for c in ctl:
                heights.setdefault(round(c["ctlH"]), []).append(c["ctlTag"])
            print(f"    控件高度分布：{ {k: len(v) for k, v in heights.items()} }")
            check("设置页控件高度统一", len(heights) == 1, f"高度集合 {sorted(heights)}")
            lab_h = {c["labH"] for c in allcells if c["labH"] is not None}
            check("设置页 label 行高统一", len(lab_h) == 1, f"{lab_h}")
            bad = [row["labTops"] for row in cf.get("sameRow", []) if len(row["labTops"]) > 1]
            check("设置页同一行 label 顶边一致", not bad, f"不一致行 {bad}")
            # 每行控件宽度：同一行的普通格子应等宽
            for gi, row in enumerate(cf["rows"], 1):
                bytop = {}
                for c in row:
                    if c["ctlTop"] is not None:
                        bytop.setdefault(round(c["ctlTop"]), []).append(c)
                for top, cells in bytop.items():
                    if len(cells) >= 2:
                        widths = sorted({round(c["ctlW"]) for c in cells})
                        if len(widths) > 1:
                            print(f"    面板{gi} 同行宽度 {widths}（若含 span-2/按钮属正常）")

        print("\nC. 全局一致性")
        ch = d.get("controlHeightsByScope", {})
        print(f"    按场景的控件高度：{ch}")
        flat = {k: v for k, v in ch.items() if len(v) > 1}
        check("同一场景内控件高度一致", not flat, f"不一致：{flat}")
        bh = d.get("buttonHeights", {})
        print(f"    按钮高度集合：{bh}")
        multi = {k: v for k, v in bh.items() if len(v) > 1}
        check("同一场景内同类按钮高度一致", not multi, f"不一致：{multi}")
        check("面板内边距一致", len(d.get("panelPaddings", [])) == 1, str(d.get("panelPaddings")))
        check("面板间距一致", len(d.get("panelGaps", [])) <= 1, str(d.get("panelGaps")))
        fs = d.get("fontSizes", {})
        print(f"    字号：{fs}")
        bad_fs = {k: v for k, v in fs.items() if len(v) > 1}
        check("同类文字字号一致", not bad_fs, f"不一致：{bad_fs}")
        rd = d.get("radii", {})
        bad_rd = {k: v for k, v in rd.items() if len(v) > 1}
        check("同类元素圆角一致", not bad_rd, f"不一致：{bad_rd} {rd}")

        print("\nD. 批量操作与溢出")
        ba = d.get("batchActions")
        check("批量操作条存在于工具栏", bool(ba), str(ba))
        check("无横向溢出", (d.get("overflowX") or 0) <= 1, f"{d.get('overflowX')}px")

        # 截图
        try:
            shot = ws.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True},
                           timeout=90)
            import base64
            p = os.path.join(SHOTS, "08_forms_consistency.png")
            open(p, "wb").write(base64.b64decode(shot["data"]))
            print(f"\n    截图 -> {p}")
        except Exception as e:      # noqa: BLE001
            print("    截图失败:", e)
        ws.close()
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:      # noqa: BLE001
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        httpd.shutdown()

    print()
    print("=" * 76)
    print(f"结果：通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    print("=" * 76)
    for f in FAIL:
        print("  [失败]", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
