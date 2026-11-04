// screen_ui.js —— 操作电脑屏幕内容层
// 两套实现：CanvasTexture（画进 3D 贴图）与 HTML 覆盖层（DOM 精确投影贴合屏幕）
// 同一份数据模型 dashboardModel() 驱动两者，保证对比公平。
import * as THREE from 'three';

const PAL = {
  bg: '#0B1322', bg2: '#16233A', line: 'rgba(255,255,255,0.15)',
  cyan: '#E4B863', green: '#4ade80', amber: '#E4B863', red: '#ff6b6b',
  text: '#ffffff', muted: 'rgba(255,255,255,0.50)', white: '#ffffff',
  champagne: '#E4B863', moonlight: '#7C9CC4',
};
const FONT = "'Segoe UI', 'Microsoft YaHei', Consolas, monospace";

/* ---------- 数据模型：从现有 API 组装四宫格 ---------- */
export async function dashboardModel() {
  const j = async (u) => { try { const r = await fetch(u); return await r.json(); } catch (e) { return null; } };
  const [kpis, trend, wafers, comps] = await Promise.all([
    j('/api/kpis'), j('/api/trend?param=uniformity_pct&limit=40'),
    j('/api/wafers?limit=6'), j('/api/components'),
  ]);
  const k = kpis || {};
  const comp = (comps && comps.components) || comps || {};
  const listOf = (v) => Array.isArray(v) ? v : (v && v.data) || [];
  const T = listOf(trend), W = listOf(wafers);

  // /api/components 结构兜底：既支持 {components:{ID:{...}}} 也支持数组
  const pick = (id, keys) => {
    const c = Array.isArray(comp) ? comp.find(x => x.id === id) : comp[id];
    if (!c) return keys.map(() => '—');
    return keys.map(key => {
      const v = (c.params && (c.params[key] ?? c.params[key.toLowerCase()])) ?? c[key];
      return (v === undefined || v === null) ? '—' : v;
    });
  };

  return {
    now: k.now || '',
    kpi: [
      ['机台状态', k.machine_state || '—', k.machine_state === 'RUNNING' ? PAL.green : (k.machine_state === 'DOWN' ? PAL.red : PAL.amber)],
      ['今日晶圆', k.today_wafers ?? '—', PAL.cyan],
      ['累计晶圆', k.total_wafers ?? '—', PAL.text],
      ['7日良率', k.pass_rate_7d != null ? k.pass_rate_7d + '%' : '—', PAL.green],
      ['7日均匀度', k.avg_uniformity_7d != null ? k.avg_uniformity_7d + '%' : '—', PAL.cyan],
      ['未关闭报警', k.open_alarms ?? 0, (k.open_alarms ? PAL.red : PAL.green)],
    ],
    lot: k.active_lot || '—',
    trend: T.map(r => Number(r.val)).filter(v => !isNaN(v)),
    wafers: W.map(w => ({
      id: w.wafer_id, lot: w.lot_id,
      uni: w.uniformity_pct != null ? Number(w.uniformity_pct) : null,
      par: w.particles_added,
      res: (w.process_result || '').toUpperCase(),
    })),
    proc: [
      ['离子源', ...pick('ION_SOURCE', ['束流', '剂量'])],
      ['分析磁铁', ...pick('MAGNET', ['磁场', '分辨力'])],
      ['加速管', ...pick('ACCEL', ['高压', '级数'])],
      ['扫描器', ...pick('SCANNER', ['扫描范围', 'X频率'])],
      ['靶室', ...pick('TARGET', ['真空', '温度'])],
    ],
  };
}

/* ---------- Canvas 版：把四宫格画进贴图 ---------- */
export function drawDashboardCanvas(ctx, W, H, d) {
  const S = W / 2048; // 以 2048 宽为设计基准，按比例缩放
  const px = (v) => v * S;
  ctx.save();
  ctx.textBaseline = 'middle';
  // 背景
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, PAL.bg2); g.addColorStop(1, PAL.bg);
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  // 顶栏
  ctx.fillStyle = 'rgba(77,195,255,0.10)'; ctx.fillRect(0, 0, W, px(86));
  ctx.strokeStyle = PAL.line; ctx.lineWidth = px(2);
  ctx.beginPath(); ctx.moveTo(0, px(86)); ctx.lineTo(W, px(86)); ctx.stroke();
  ctx.fillStyle = PAL.cyan; ctx.font = `700 ${px(40)}px ${FONT}`;
  ctx.fillText('IMP-MC-01  工艺控制台', px(36), px(44));
  ctx.fillStyle = PAL.muted; ctx.font = `${px(24)}px ${FONT}`;
  ctx.textAlign = 'right';
  ctx.fillText(`LOT ${d.lot}   ${d.now}`, W - px(36), px(44));
  ctx.textAlign = 'left';

  const gap = px(22), pad = px(22);
  const top = px(86) + pad;
  const cw = (W - pad * 3) / 2, ch = (H - top - pad * 2 - gap) / 2;

  const panel = (col, row, title) => {
    const x = pad + col * (cw + pad), y = top + row * (ch + gap);
    ctx.fillStyle = 'rgba(12,26,44,0.92)';
    ctx.strokeStyle = PAL.line; ctx.lineWidth = px(2);
    roundRect(ctx, x, y, cw, ch, px(10)); ctx.fill(); ctx.stroke();
    ctx.fillStyle = PAL.muted; ctx.font = `600 ${px(24)}px ${FONT}`;
    ctx.fillText(title, x + px(20), y + px(30));
    ctx.strokeStyle = PAL.line; ctx.beginPath();
    ctx.moveTo(x + px(16), y + px(50)); ctx.lineTo(x + cw - px(16), y + px(50)); ctx.stroke();
    return { x, y, w: cw, h: ch };
  };

  // 1 工艺汇总 KPI
  let b = panel(0, 0, '工艺汇总  PRODUCTION');
  const kx = b.x + px(24), ky = b.y + px(74);
  const cellW = (b.w - px(48)) / 3, cellH = (b.h - px(90)) / 2;
  d.kpi.forEach(([label, val, color], i) => {
    const cx = kx + (i % 3) * cellW, cy = ky + Math.floor(i / 3) * cellH;
    ctx.fillStyle = PAL.muted; ctx.font = `${px(21)}px ${FONT}`;
    ctx.fillText(label, cx, cy + px(16));
    ctx.fillStyle = color; ctx.font = `700 ${px(48)}px ${FONT}`;
    ctx.fillText(String(val), cx, cy + px(62));
  });

  // 2 趋势曲线
  b = panel(1, 0, '均匀度趋势  UNIFORMITY (最近40片)');
  const vals = d.trend.length ? d.trend : [0, 0];
  const gx = b.x + px(46), gy = b.y + px(70), gw = b.w - px(70), gh = b.h - px(100);
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const span = Math.max(mx - mn, 0.6);
  ctx.strokeStyle = 'rgba(21,48,77,0.9)'; ctx.lineWidth = px(1.5);
  for (let i = 0; i <= 3; i++) {
    const yy = gy + gh * i / 3;
    ctx.beginPath(); ctx.moveTo(gx, yy); ctx.lineTo(gx + gw, yy); ctx.stroke();
    ctx.fillStyle = PAL.muted; ctx.font = `${px(17)}px ${FONT}`;
    ctx.fillText((mx - span * i / 3).toFixed(2), gx - px(42), yy);
  }
  ctx.beginPath();
  vals.forEach((v, i) => {
    const xx = gx + gw * (vals.length === 1 ? 0.5 : i / (vals.length - 1));
    const yy = gy + gh * (1 - (v - mn) / span);
    i ? ctx.lineTo(xx, yy) : ctx.moveTo(xx, yy);
  });
  ctx.strokeStyle = PAL.cyan; ctx.lineWidth = px(3);
  ctx.shadowColor = PAL.cyan; ctx.shadowBlur = px(12); ctx.stroke(); ctx.shadowBlur = 0;
  const last = vals[vals.length - 1];
  ctx.fillStyle = PAL.cyan; ctx.font = `700 ${px(30)}px ${FONT}`; ctx.textAlign = 'right';
  ctx.fillText(last.toFixed(2) + '%', b.x + b.w - px(24), b.y + px(34));
  ctx.textAlign = 'left';

  // 3 单晶圆质量追溯
  b = panel(0, 1, '晶圆质量追溯  WAFER TRACE');
  const cols = ['片号', '批次', '均匀度', '颗粒', '结果'];
  const tw = b.w - px(44), cx0 = b.x + px(22);
  const colX = [cx0, cx0 + tw * 0.26, cx0 + tw * 0.50, cx0 + tw * 0.70, cx0 + tw * 0.85];
  ctx.fillStyle = PAL.muted; ctx.font = `600 ${px(20)}px ${FONT}`;
  cols.forEach((c, i) => ctx.fillText(c, colX[i], b.y + px(68)));
  const rowH = Math.min(px(38), (b.h - px(86)) / Math.max(d.wafers.length, 1));
  d.wafers.forEach((w, r) => {
    const yy = b.y + px(96) + r * rowH;
    if (r % 2 === 0) { ctx.fillStyle = 'rgba(77,195,255,0.045)'; ctx.fillRect(cx0 - px(8), yy - rowH * 0.42, tw + px(16), rowH); }
    ctx.font = `${px(20)}px ${FONT}`;
    ctx.fillStyle = PAL.text;
    ctx.fillText(String(w.id ?? '—'), colX[0], yy);
    ctx.fillStyle = PAL.muted; ctx.fillText(String(w.lot ?? '—').slice(-8), colX[1], yy);
    if (w.uni != null) {
      ctx.fillStyle = w.uni >= 1.8 && w.uni <= 2.4 ? PAL.green : PAL.amber;
      ctx.fillText(w.uni.toFixed(2) + '%', colX[2], yy);
    } else { ctx.fillStyle = PAL.muted; ctx.fillText('—', colX[2], yy); }
    ctx.fillStyle = PAL.text; ctx.fillText(String(w.par ?? '—'), colX[3], yy);
    const ok = w.res === 'PASS';
    ctx.fillStyle = ok ? PAL.green : PAL.red;
    ctx.fillText(ok ? '● PASS' : '● ' + (w.res || '—'), colX[4], yy);
  });

  // 4 工序实时参数
  b = panel(1, 1, '工序实时参数  PROCESS LIVE');
  const py0 = b.y + px(70);
  const prh = (b.h - px(84)) / 5;
  d.proc.forEach(([name, v1, v2], i) => {
    const yy = py0 + i * prh;
    ctx.fillStyle = 'rgba(77,195,255,0.06)';
    ctx.fillRect(b.x + px(16), yy, b.w - px(32), prh - px(6));
    ctx.fillStyle = PAL.text; ctx.font = `600 ${px(22)}px ${FONT}`;
    ctx.fillText(name, b.x + px(28), yy + prh / 2 - px(2));
    ctx.fillStyle = PAL.cyan; ctx.font = `${px(22)}px ${FONT}`; ctx.textAlign = 'right';
    ctx.fillText(`${v1}`, b.x + b.w * 0.72, yy + prh / 2 - px(2));
    ctx.fillStyle = PAL.amber;
    ctx.fillText(`${v2}`, b.x + b.w - px(28), yy + prh / 2 - px(2));
    ctx.textAlign = 'left';
  });
  ctx.restore();
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

/* ---------- HTML 版：图标切页（汇总 / 晶圆 / 参数 / 操作）+ DOM 渲染 ---------- */
export const PAGES = [
  ['sum', '▦ 工艺汇总'],
  ['wafer', '▤ 晶圆质量'],
  ['param', '⚙ 工序参数'],
  ['act', '▶ 操作'],
  ['rep', '📄 停机报告'],
];

// 本盒预计时间文本（dashboardHtml 与逐帧补丁共用）
export function fmtMMSS(s) {
  s = Math.max(0, Math.round(s || 0));
  const m = Math.floor(s / 60);
  return m + ':' + String(s % 60).padStart(2, '0');
}
export function lotEtaText(lp) {
  if (!lp) return '—';
  if (lp.done >= lp.total) return '已完成';
  if (!(lp.etaSec > 0)) return '—';
  return fmtMMSS(lp.etaSec) + (lp.clock ? '（约 ' + lp.clock + ' 完成）' : '');
}

export function dashboardHtml(d, st, page) {
  st = st || {};
  page = page || 'sum';
  const kpi = d.kpi.map(([l, v, c]) =>
    `<div class="sw-kpi"><i>${l}</i><b style="color:${c}">${v}</b></div>`).join('');
  const vals = d.trend.length ? d.trend : [0, 0];
  const mn = Math.min(...vals), mx = Math.max(...vals), span = Math.max(mx - mn, 0.6);
  const pts = vals.map((v, i) => {
    const x = vals.length === 1 ? 50 : i / (vals.length - 1) * 100;
    const y = 100 - (v - mn) / span * 100;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(' ');
  const rows = d.wafers.map(w => {
    const ok = w.res === 'PASS';
    return `<tr><td>${w.id ?? '—'}</td><td class="dim">${String(w.lot ?? '—').slice(-8)}</td>
      <td style="color:${w.uni != null && w.uni <= 2.0 ? PAL.green : PAL.amber}">${w.uni != null ? w.uni.toFixed(2) + '%' : '—'}</td>
      <td>${w.par ?? '—'}</td>
      <td style="color:${ok ? PAL.green : PAL.red}">● ${ok ? 'PASS' : (w.res || '—')}</td></tr>`;
  }).join('');
  const proc = d.proc.map(([n, a, b]) =>
    `<div class="sw-proc"><span>${n}</span><b>${a}</b><em>${b}</em></div>`).join('');

  const tabs = PAGES.map(([id, label]) =>
    `<button class="sw-tab${id === page ? ' on' : ''}" data-page="${id}">${label}</button>`).join('');

  // ---- 各页内容 ----
  // 本盒进度：加工数量 + 预计剩余/完成时刻（数据来自页面 lotProgress()）
  const lp = st.lot || null;
  const lotDone = lp ? lp.done : 0, lotTotal = lp ? lp.total : 20, lotPct = lp ? lp.pct : 0;
  const etaTxt = lotEtaText(lp);
  const lotBlock = `
    <div class="sw-lot">
      <div class="sw-lot-l"><span class="dim">本盒批次</span><b>${(lp && lp.lotId) ? lp.lotId : '未开工'}</b></div>
      <div class="sw-lot-l"><span class="dim">本盒已加工</span><b class="big" data-done>${lotDone} / ${lotTotal} 片</b></div>
      <div class="sw-bar"><i data-bar style="width:${lotPct}%"></i></div>
      <div class="sw-lot-l"><span class="dim">预计剩余</span><b data-eta>${etaTxt}</b></div>
      <div class="sw-lot-l"><span class="dim">单片节拍</span><b>${lp ? lp.perWafer : '—'} s/片</b></div>
      ${lp && lp.hold ? `<div class="sw-lot-h">⏸ ${lp.hold} —— 计时不计入</div>` : ''}
    </div>`;
  const pageSum = `
    <div class="sw-grid">
      <div class="sw-panel"><div class="sw-pt">工艺汇总 PRODUCTION</div>${lotBlock}<div class="sw-kpis">${kpi}</div></div>
      <div class="sw-panel"><div class="sw-pt">均匀度趋势 UNIFORMITY (最近40片)<b class="sw-last">${vals[vals.length - 1].toFixed(2)}%</b></div>
        <svg class="sw-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
          <g stroke="rgba(21,48,77,.9)" stroke-width=".4">
            <line x1="0" y1="0" x2="100" y2="0"/><line x1="0" y1="33" x2="100" y2="33"/>
            <line x1="0" y1="66" x2="100" y2="66"/><line x1="0" y1="100" x2="100" y2="100"/></g>
          <polyline points="${pts}" fill="none" stroke="${PAL.cyan}" stroke-width="1.6"
            vector-effect="non-scaling-stroke" style="filter:drop-shadow(0 0 3px ${PAL.cyan})"/>
        </svg>
        <div class="sw-axis"><span>${mx.toFixed(2)}</span><span>((mx+mn)/2)</span><span>${mn.toFixed(2)}</span></div>
      </div>
      <div class="sw-panel"><div class="sw-pt">晶圆质量追溯 WAFER TRACE</div>
        <table class="sw-tbl"><thead><tr><th>片号</th><th>批次</th><th>均匀度</th><th>颗粒</th><th>结果</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="dim">暂无记录</td></tr>'}</tbody></table></div>
      <div class="sw-panel"><div class="sw-pt">工序实时参数 PROCESS LIVE</div><div class="sw-procs">${proc}</div></div>
    </div>`.replace('((mx+mn)/2)', ((mx + mn) / 2).toFixed(2));

  const pageWafer = `
    <div class="sw-full">
      <div class="sw-pt">晶圆质量追溯 · 单片明细（最近 ${d.wafers.length} 片）</div>
      <table class="sw-tbl sw-tbl-lg"><thead><tr><th>片号</th><th>批次</th><th>均匀度</th><th>颗粒增量</th><th>判定</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5" class="dim">暂无记录</td></tr>'}</tbody></table>
      <div class="sw-note">判定规格：均匀度 ≤ 2.00% 且颗粒增量 ≤ 20 → PASS；否则 FAIL（自动路由至废料仓）</div>
    </div>`;

  // 手动调参向导：确认报警 → 本页出现待调整参数 → 点「调整」→ 回操作页启动工艺
  const pk = st.pendingParam || null;
  const adjBlock = pk ? `
      <div class="sw-warn sw-adj">
        <div class="sw-warn-h">⚠ 待调整参数 · 报警 ${(pk.alarm_code || '')}</div>
        <div class="sw-adj-row">
          <span class="sw-adj-n">${(pk.param_name || '工艺参数')}</span>
          <span class="sw-adj-v">${pk.param_from}${(pk.param_unit || '')} <i>→</i> <b>${pk.param_to}${(pk.param_unit || '')}</b></span>
          <button class="sw-btn amber" data-act="adjustparam"${pk.adjusted ? ' disabled' : ''}>${pk.adjusted ? '✔ 已调整' : '🔧 调整'}</button>
        </div>
        <div class="sw-warn-n">${pk.adjusted
          ? '参数已修正 → 请切到「▶ 操作」页点击「启动工艺」继续传片'
          : '点击「调整」把该参数改到目标值（手动流程，机台不会自己恢复）'}</div>
      </div>` : '';
  const pageParam = `
    <div class="sw-full">
      ${adjBlock}
      <div class="sw-pt">工序实时参数 PROCESS LIVE · 五大构件</div>
      <div class="sw-procs sw-procs-lg">${proc}</div>
      <div class="sw-grid2">
        ${d.kpi.map(([l, v, c]) => `<div class="sw-kpi2"><i>${l}</i><b style="color:${c}">${v}</b></div>`).join('')}
      </div>
      <div class="sw-note">数据源：/api/components（5s 刷新）· 与落库记录同源</div>
    </div>`;

  const beamTxt = st.beamOn ? '束流 ON' : '束流 OFF';
  const procTxt = st.processRunning ? '停止工艺' : '启动工艺';
  const pilotCls = st.pilotPassed ? 'ok' : (st.pilotInfo ? 'bad' : 'idle');
  const pilotTxt = st.pilotBusy ? '试片检测中…'
    : st.pilotPassed ? `试片合格 ${st.pilotInfo && st.pilotInfo.uniformity != null ? st.pilotInfo.uniformity + '%' : ''}`
      : (st.pilotInfo ? `试片不合格 ${st.pilotInfo.uniformity}%` : '未试片');
  const cyc = st.cycle || {};
  const tuneTxt = st.tuneDone ? '已调束' : '未调束';
  const downTag = st.machineDown ? '<span class="sw-lamp bad">⛔ 机台宕机 · 待检修</span>' : '';
  // 宕机提示直接显示在屏幕里（报警原因 + 检修进度 + 呼叫按钮），不再弹独立窗口
  const downPanel = st.machineDown ? `
      <div class="sw-down">
        <div class="sw-down-h">⛔ 机台宕机 · 工艺已中断 · 晶圆计数停止</div>
        <div class="sw-down-r">报警原因：<b>${(st.downReason || '设备异常')}</b></div>
        <div class="sw-down-p">${(st.repairPhase || '待处理：请呼叫设备工程师')}</div>
        <button class="sw-btn red sw-down-b" data-act="repair"${st.repairBusy ? ' disabled' : ''}>${st.repairBusy ? '🔧 检修中…' : '📞 呼叫设备工程师 EE-01'}</button>
        <div class="sw-down-n">检修完成后必须重新「调束 → 试片」，合格后方可复产</div>
      </div>` : (st.repairPhase ? `<div class="sw-note sw-rep-done">${st.repairPhase}</div>` : '');
  // 小故障（WARN）：不停机，停传片 → 操作员按向导调参数 → 继续传片
  const wi = st.warnInfo || null;
  const warnPanel = (wi && !st.machineDown) ? `
      <div class="sw-warn">
        <div class="sw-warn-h">⚠ 小故障预警 · 已停止传片（无需停机）</div>
        <div class="sw-warn-c">部件：<b>${(wi.component_tag || '—')}</b></div>
        <div class="sw-warn-p">调整参数：<b>${(wi.param_fix || wi.message || '—')}</b></div>
        <button class="sw-btn amber" data-act="confirmwarn">📋 确认报警内容 → 去调参</button>
        <div class="sw-warn-n">报警代码 ${(wi.alarm_code || '')} · 起 ${(wi.start_time || '')} · 该报警已停止传片，机台未停机</div>
      </div>` : '';
  // 停机报告（原居中弹窗已删）：跑完自动停机后在「操作」页底部展示
  const lr = st.lotReport || null;
  const repBlock = lr ? `
      <div class="sw-panel sw-rep">
        <div class="sw-pt">停机报告 LOT REPORT · ${(lr.lot_id || '')}</div>
        <div class="sw-rep-grid">
          <div><i>晶圆片数</i><b>${(lr.wafer_count ?? '—')} 片</b></div>
          <div><i>良品 / 不良</i><b>${(lr.pass_count ?? '—')} / ${(lr.fail_count ?? '—')}</b></div>
          <div><i>良率</i><b>${(lr.yield_pct ?? '—')} %</b></div>
          <div><i>均匀度均值</i><b>${(lr.uniformity_avg ?? '—')} %</b></div>
          <div><i>工艺期间报警</i><b>${(lr.alarm_count ?? '—')} 次</b></div>
          <div><i>循环模式</i><b>${lr.cycle_mode === 'FAST' ? '快速演示 ×8' : '正常节奏'}</b></div>
        </div>
        <div class="sw-note">统计窗口 ${(lr.window_start || '—')} → 停机 ${(lr.closed_at || '—')}</div>
      </div>` : '';

  const pageRep = `
    <div class="sw-full">
      <div class="sw-pt">停机报告 · LOT REPORT</div>
      ${repBlock || '<div class="sw-note">本盒尚未结束，暂无停机报告。跑完一盒（20 片）自动停机后，这里会生成报告。</div>'}
      ${(window.__lotRecords && window.__lotRecords.length) ? `
      <div class="sw-panel">
        <div class="sw-pt">历史批次 HISTORY</div>
        ${window.__lotRecords.map(x => `<div class="sw-note">${x.lot_id} · ${x.wafer_count} 片 · 良率 ${x.yield_pct}% · 报警 ${x.alarm_count} 次</div>`).join('')}
      </div>` : ''}
    </div>`;

  const pageAct = `
    <div class="sw-full">
      <div class="sw-pt">操作 · 机台控制 PANEL</div>
      ${downPanel}
      ${warnPanel}
      <div class="sw-act-row">
        <span class="sw-lamp ${st.power ? 'on' : 'off'}">${st.power ? '电源 ON' : '电源 OFF'}</span>
        <span class="sw-lamp ${st.tuneDone ? 'ok' : 'idle'}">${tuneTxt}</span>
        <span class="sw-lamp ${pilotCls}">${pilotTxt}</span>
        <span class="sw-lamp ${st.processRunning ? 'on' : 'idle'}">${st.processPaused ? '工艺已暂停' : (st.processRunning ? '工艺运行中' : '工艺待机')}</span>
        ${downTag}
      </div>
      <div class="sw-btns">
        <button class="sw-btn" data-act="tune"${st.power && !st.machineDown ? '' : ' disabled'}>🔧 调束</button>
        <button class="sw-btn" data-act="pilot"${st.tuneDone && !st.machineDown ? '' : ' disabled'}>🧪 试片</button>
        <button class="sw-btn" data-act="retune"${st.pilotInfo && !st.pilotPassed ? '' : ' disabled'}>🔧 一键重新调束</button>
        <button class="sw-btn" data-act="beam"${st.processRunning ? '' : ' disabled'}>${beamTxt}</button>
        <button class="sw-btn ${st.processRunning ? 'red' : 'cyan'}" data-act="process"${st.pilotPassed && !st.machineDown ? '' : ' disabled'}>${procTxt}</button>
        <button class="sw-btn ${st.processPaused ? 'on' : ''}" data-act="pause"${st.processRunning ? '' : ' disabled'}>${st.processPaused ? '▶ 继续' : '⏸ 暂停'}</button>
        <button class="sw-btn ${st.fast ? 'on' : ''}" data-act="fast">⚡ 快速演示 ${st.fast ? '开' : '关'}</button>
        <button class="sw-btn" data-act="reload">📦 重新装盒</button>
      </div>
      <div class="sw-note">
        流程：通电 → 调束 → 试片（不合格再调束，直到合格）→ 启动工艺 → 启动束流 → 开始传片加工
        · 20 片循环：已完成 ${cyc.done || 0}/${cyc.total || 20} 片${cyc.active ? '（运行中）' : ''}
        · 断电入口在机台旁配电柜
      </div>
    </div>`;

  const body = page === 'wafer' ? pageWafer : (page === 'param' ? pageParam : (page === 'act' ? pageAct : (page === 'rep' ? pageRep : pageSum)));

  return `
  <div class="sw-root">
    <div class="sw-head"><span class="sw-title">IMP-MC-01 工艺控制台</span>
      <span class="sw-tabs">${tabs}</span>
      <span class="sw-clock">LOT ${d.lot} · ${d.now}</span></div>
    ${body}
  </div>`;
}

export const SCREEN_CSS = `
.sw-root{width:100%;height:100%;background:#0B1322;color:#fff;font-family:${FONT};display:flex;flex-direction:column;overflow:hidden}
.sw-head{height:9%;display:flex;align-items:center;justify-content:space-between;
  padding:0 2%;background:rgba(255,255,255,0.04);backdrop-filter:blur(40px) saturate(180%);
  border-bottom:1px solid rgba(255,255,255,0.15)}
.sw-title{font-size:1.55em;font-weight:700;color:#E4B863;letter-spacing:.4px}
.sw-clock{font-size:1.05em;color:rgba(255,255,255,0.50)}
.sw-grid{flex:1;display:grid;grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr;
  gap:1.4%;padding:1.4%}
.sw-panel{background:rgba(255,255,255,0.06);backdrop-filter:blur(40px) saturate(180%);
  border:1px solid rgba(255,255,255,0.15);border-radius:16px;
  box-shadow:0 8px 24px rgba(3,7,18,0.45),inset 0 1px 0 rgba(255,255,255,0.18);
  padding:1.6% 1.8%;display:flex;flex-direction:column;min-height:0;overflow:hidden}
.sw-pt{font-size:1.02em;font-weight:600;color:rgba(255,255,255,0.80);
  padding-bottom:.7%;margin-bottom:1.6%;display:flex;justify-content:space-between;align-items:center;flex:0 0 auto;
  border-bottom:1px solid rgba(255,255,255,0.10)}
.sw-last{color:#E4B863;font-size:1.35em}
.sw-kpis{flex:1;display:grid;grid-template-columns:1fr 1fr 1fr;grid-template-rows:1fr 1fr;gap:1%}
.sw-kpi{display:flex;flex-direction:column;justify-content:center;
  background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.10);border-radius:10px;padding:4px 6px}
.sw-lot{flex:0 0 auto;margin-bottom:1.6%;padding-bottom:1.4%}
.sw-lot-l{display:flex;justify-content:space-between;align-items:baseline;font-size:.92em;line-height:1.5}
.sw-lot-l b{color:#E4B863;font-weight:600}
.sw-lot-l b.big{font-size:1.5em}
.sw-bar{height:.55em;background:rgba(255,255,255,0.06);border-radius:3px;margin:.5em 0;overflow:hidden}
.sw-bar i{display:block;height:100%;background:linear-gradient(90deg,#33517A,#7C9CC4);
  border-radius:3px;transition:width .3s}
.sw-lot-h{font-size:.85em;color:#E4B863;margin-top:.3em}
.sw-kpi i{font-style:normal;font-size:.86em;color:rgba(255,255,255,0.50)}
.sw-kpi b{font-size:1.9em;font-weight:700;line-height:1.25;color:#E4B863;font-family:'SF Mono','Consolas',monospace}
.sw-chart{flex:1;width:100%;min-height:0}
.sw-axis{display:flex;flex-direction:column;justify-content:space-between;position:absolute;right:2.2%;bottom:3%;font-size:.8em;color:rgba(255,255,255,0.40);text-align:right}
.sw-tbl{width:100%;font-size:.92em;border-collapse:collapse}
.sw-tbl th{text-align:left;color:rgba(255,255,255,0.50);font-weight:600;padding-bottom:1.5%}
.sw-tbl td{padding:.9% 0;color:rgba(255,255,255,0.85)}
.sw-tbl .dim{color:rgba(255,255,255,0.35)}
.sw-procs{flex:1;display:flex;flex-direction:column;justify-content:space-between}
.sw-proc{display:grid;grid-template-columns:1fr auto auto;gap:2%;align-items:center;
  background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.10);padding:1.4% 2.2%;border-radius:10px;font-size:.95em}
.sw-proc span{color:#fff;font-weight:600}
.sw-proc b{color:#E4B863;font-weight:400}
.sw-proc em{color:#E4B863;font-style:normal}
.sw-tabs{display:flex;gap:.5%;flex:1;justify-content:center}
.sw-tab{background:transparent;color:rgba(255,255,255,0.50);border:1px solid transparent;border-radius:10px;
  padding:.35em .9em;font-size:.92em;cursor:pointer;font-family:${FONT};transition:all 500ms cubic-bezier(0.16,1,0.3,1)}
.sw-tab:hover{background:rgba(255,255,255,0.06);color:rgba(255,255,255,0.80)}
.sw-tab.on{background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.15);color:#E4B863;font-weight:700;backdrop-filter:blur(20px)}
.sw-full{flex:1;display:flex;flex-direction:column;gap:1.2%;padding:1.6% 2%;min-height:0;overflow:hidden}
.sw-tbl-lg{font-size:1.08em}
.sw-tbl-lg td{padding:1.4% 0}
.sw-note{font-size:.86em;color:rgba(255,255,255,0.40);padding-top:1%;flex:0 0 auto}
.sw-grid2{display:grid;grid-template-columns:repeat(3,1fr);gap:1%;flex:0 0 auto}
.sw-kpi2{display:flex;flex-direction:column;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.10);border-radius:10px;padding:.8% 1.2%}
.sw-kpi2 i{font-style:normal;font-size:.82em;color:rgba(255,255,255,0.50)}
.sw-kpi2 b{font-size:1.5em;font-weight:700;color:#E4B863;font-family:'SF Mono','Consolas',monospace}
.sw-procs-lg{flex:1;gap:1%}
.sw-act-row{display:flex;gap:1%;flex:0 0 auto}
.sw-lamp{flex:1;text-align:center;font-size:.95em;padding:.6% 0;border-radius:10px;
  background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.10);color:rgba(255,255,255,0.50)}
.sw-lamp.on{color:#4ade80}
.sw-lamp.off{color:#ff6b6b}
.sw-lamp.ok{color:#4ade80}
.sw-lamp.bad{color:#ff6b6b}
.sw-lamp.idle{color:rgba(255,255,255,0.40)}
.sw-btns{display:flex;flex-wrap:wrap;gap:1.2%;flex:0 0 auto}
.sw-btn{background:rgba(255,255,255,0.08);color:#fff;border:1px solid rgba(255,255,255,0.15);border-radius:12px;
  padding:.9em 1.4em;font-size:1em;cursor:pointer;font-family:${FONT};
  backdrop-filter:blur(20px);transition:all 500ms cubic-bezier(0.16,1,0.3,1)}
.sw-btn:hover:not([disabled]){background:rgba(255,255,255,0.12);border-color:rgba(255,255,255,0.30)}
.sw-btn:active:not([disabled]){transform:scale(0.97)}
.sw-btn[disabled]{opacity:.42;cursor:not-allowed}
.sw-btn.cyan{background:rgba(228,184,99,0.15);border-color:rgba(228,184,99,0.40);color:#F3DCA8;font-weight:700;box-shadow:0 4px 20px rgba(228,184,99,0.15),inset 0 1px 0 rgba(243,220,168,0.35)}
.sw-btn.red{background:rgba(255,107,107,0.12);border-color:rgba(255,107,107,0.30);color:#ff6b6b;font-weight:700}
.sw-btn.amber{background:rgba(228,184,99,0.12);border-color:rgba(228,184,99,0.30);color:#E4B863;font-weight:700}
.sw-down{flex:0 0 auto;border:1px solid rgba(255,107,107,0.25);border-radius:12px;
  background:rgba(255,107,107,0.06);backdrop-filter:blur(20px);padding:1.6% 1.8%;margin-bottom:1.2%}
@keyframes sw-down-blink{0%,100%{background:rgba(255,107,107,0.06)}50%{background:rgba(255,107,107,0.12)}}
.sw-down-h{color:#ff6b6b;font-weight:700;font-size:1.06em;letter-spacing:1px;margin-bottom:.5em}
.sw-down-r{font-size:.94em;color:rgba(255,255,255,0.85);margin-bottom:.35em}
.sw-down-r b{color:#ff6b6b}
.sw-down-p{font-size:.9em;color:rgba(255,255,255,0.50);margin-bottom:.7em}
.sw-down-b{margin-bottom:.4em}
.sw-down-n{font-size:.82em;color:rgba(255,255,255,0.35)}
.sw-warn{margin-bottom:1.2%;padding:1.4% 1.6%;background:rgba(228,184,99,0.06);
  border:1px solid rgba(228,184,99,0.20);border-radius:12px;backdrop-filter:blur(20px)}
@keyframes sw-warn-blink{0%,100%{background:rgba(228,184,99,0.06)}50%{background:rgba(228,184,99,0.12)}}
.sw-warn-h{color:#E4B863;font-weight:700;margin-bottom:.45em}
.sw-warn-c,.sw-warn-p{font-size:.94em;color:rgba(255,255,255,0.85);margin-bottom:.3em}
.sw-warn-p b{color:#E4B863}
.sw-warn-n{font-size:.8em;color:rgba(255,255,255,0.35);margin-top:.4em}
.sw-adj{background:rgba(228,184,99,0.06);border-color:rgba(228,184,99,0.20)}
.sw-adj-row{display:flex;align-items:center;gap:1.2%;margin:.5em 0 .2em}
.sw-adj-n{flex:0 0 34%;font-size:.95em;color:#fff;font-weight:700}
.sw-adj-v{flex:1;font-size:1.05em;color:#E4B863;letter-spacing:.02em}
.sw-adj-v i{color:rgba(255,255,255,0.40);font-style:normal;margin:0 .25em}
.sw-adj-v b{color:#4ade80}
.sw-adj .sw-btn{flex:0 0 auto}
.sw-rep-done{color:#4ade80}
.sw-rep{margin-top:2px}
.sw-rep-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:3px 8px;margin:4px 0}
.sw-rep-grid div{display:flex;justify-content:space-between;font-size:10px;padding:3px 6px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.10);border-radius:6px}
.sw-rep-grid i{color:rgba(255,255,255,0.35);font-style:normal}
.sw-rep-grid b{color:#fff}
.sw-btn.on{color:#4ade80}
`;

/* ---------- 四角投影 → CSS matrix3d ---------- */
export function quadToMatrix3d(p0, p1, p2, p3, w, h) {
  // 单位正方形 → 四边形（标准闭式解）
  const [x0, y0] = p0, [x1, y1] = p1, [x2, y2] = p2, [x3, y3] = p3;
  const dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3;
  const dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
  let a, b, c, d, e, f, g, hh;
  if (Math.abs(dx3) < 1e-9 && Math.abs(dy3) < 1e-9) {
    a = x1 - x0; b = x2 - x1; c = x0; d = y1 - y0; e = y2 - y1; f = y0; g = 0; hh = 0;
  } else {
    const det = dx1 * dy2 - dx2 * dy1;
    g = (dx3 * dy2 - dx2 * dy3) / det;
    hh = (dx1 * dy3 - dx3 * dy1) / det;
    a = x1 - x0 + g * x1; b = x3 - x0 + hh * x3; c = x0;
    d = y1 - y0 + g * y1; e = y3 - y0 + hh * y3; f = y0;
  }
  // 元素像素坐标 (s,t) ∈ [0,w]×[0,h]：先归一化 u=s/w, v=t/h，故乘 diag(1/w,1/h,1)
  const A = a / w, B = b / h, C = c;
  const D = d / w, E = e / h, F = f;
  const G = g / w, H = hh / h;
  return `matrix3d(${A},${D},0,${G}, ${B},${E},0,${H}, 0,0,1,0, ${C},${F},0,1)`;
}

/* ---------- 安装器：把两种实现挂到场景里 ---------- */
export function installScreenOverlay(opts) {
  const { scene, camera, screenMesh, mode = 'html', designW = 1000, designH = 574, onReady, actions = null, getState = null } = opts;
  let page = opts.page || 'sum';
  let pageInit = false;
  screenMesh.updateWorldMatrix(true, false);
  const box = new THREE.Box3().setFromObject(screenMesh);
  const ctr = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const w = size.x, h = size.y, zFront = box.max.z + Math.max(size.z * 0.6, 0.0012);
  const corners = [
    new THREE.Vector3(ctr.x - w / 2, ctr.y + h / 2, zFront), // 左上
    new THREE.Vector3(ctr.x + w / 2, ctr.y + h / 2, zFront), // 右上
    new THREE.Vector3(ctr.x + w / 2, ctr.y - h / 2, zFront), // 右下
    new THREE.Vector3(ctr.x - w / 2, ctr.y - h / 2, zFront), // 左下
  ];

  let overlay = null, canvasTex = null, plane = null, texCanvas = null, texCtx = null;
  let lastModel = null;
  let operating = false;          // 混合模式：是否进入「操作态」（HTML 层接管）
  const hybrid = (mode === 'hybrid');

  if (mode === 'html' || hybrid) {
    overlay = document.createElement('div');
    overlay.id = 'screen-overlay';
    overlay.style.cssText = `position:fixed;left:0;top:0;width:${designW}px;height:${designH}px;
      transform-origin:0 0;pointer-events:none;z-index:30;border-radius:3px;overflow:hidden;
      box-shadow:0 0 22px rgba(77,195,255,.35),inset 0 0 40px rgba(0,0,0,.5)`;
    if (hybrid) overlay.style.opacity = '0';
    const st = document.createElement('style');
    st.textContent = SCREEN_CSS;
    document.head.appendChild(st);
    document.body.appendChild(overlay);
  }
  if (mode === 'tex' || hybrid) {
    texCanvas = document.createElement('canvas');
    texCanvas.width = 2048; texCanvas.height = Math.round(2048 * h / w);
    texCtx = texCanvas.getContext('2d');
    canvasTex = new THREE.CanvasTexture(texCanvas);
    canvasTex.colorSpace = THREE.SRGBColorSpace;
    canvasTex.anisotropy = 8;
    const geo = new THREE.PlaneGeometry(w, h);
    const mat = new THREE.MeshBasicMaterial({ map: canvasTex, toneMapped: false });
    plane = new THREE.Mesh(geo, mat);
    plane.position.set(ctr.x, ctr.y, zFront);
    plane.name = 'SCREEN_UI_PLANE';
    plane.renderOrder = 5;
    scene.add(plane);
  }

  const v = new THREE.Vector3();
  function project(p) {
    v.copy(p).project(camera);
    return [(v.x * 0.5 + 0.5) * innerWidth, (-v.y * 0.5 + 0.5) * innerHeight];
  }

  function update(model) {
    if (model) lastModel = model;
    if (!lastModel) return;
    const st = getState ? (getState() || {}) : {};
    if (mode === 'html' || hybrid) {
      const p = corners.map(project);
      overlay.style.transform = quadToMatrix3d(p[0], p[1], p[2], p[3], designW, designH);
      // 背面剔除：屏幕背对相机时隐藏
      const back = (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0]);
      if (mode === 'html') {
        overlay.style.opacity = back > 0 ? '1' : '0';
      } else {
        // 混合：仅操作态显示 HTML 层，其余用贴图（保证与柜体同层、被遮挡正确）
        overlay.style.opacity = (operating && back > 0) ? '1' : '0';
        overlay.style.pointerEvents = operating ? 'auto' : 'none';
        if (plane) plane.visible = !operating;
      }
      const html = dashboardHtml(lastModel, st, page);
      // 只在与内容真正相关的变化时重建 DOM（时钟/ETA 单独打补丁，避免打断鼠标交互）
      const stSig = Object.assign({}, st, {
        lot: st.lot ? Object.assign({}, st.lot, { etaSec: 0, clock: '' }) : null,
        repairPhase: (st.repairPhase || '').replace(/剩余 \d+ 秒/, '剩余 N 秒'),
      });
      const sig = [
        page,
        lastModel.lot,
        lastModel.kpi.map(x => x[0] + '=' + x[1]).join(','),
        lastModel.trend.slice(-8).join(','),
        lastModel.wafers.map(w => w.id + ':' + w.res + ':' + w.uni).join(','),
        lastModel.proc.map(p => p.join(':')).join(','),
        JSON.stringify(stSig),
      ].join('|');
      if (overlay.dataset.sig !== sig) {
        overlay.innerHTML = html;
        overlay.dataset.sig = sig;
        wire();
      } else {
        const ck = overlay.querySelector('.sw-clock');
        if (ck) ck.textContent = 'LOT ' + lastModel.lot + ' · ' + lastModel.now;
        // 逐帧补丁：本盒数量 / 进度条 / 预计剩余（不重建 DOM）
        const lp = st.lot || null;
        if (lp) {
          const eEta = overlay.querySelector('[data-eta]');
          if (eEta) eEta.textContent = lotEtaText(lp);
          const eDone = overlay.querySelector('[data-done]');
          if (eDone) eDone.textContent = lp.done + ' / ' + lp.total + ' 片';
          const eBar = overlay.querySelector('[data-bar]');
          if (eBar) eBar.style.width = lp.pct + '%';
        }
        const eRp = overlay.querySelector('.sw-rep-done');
        if (eRp && st.repairPhase) eRp.textContent = st.repairPhase;
      }
    }
    if (mode === 'tex' || (hybrid && !operating)) {
      drawDashboardCanvas(texCtx, texCanvas.width, texCanvas.height, lastModel);
      canvasTex.needsUpdate = true;
    }
  }

  // 交互接线：页签切换 + 操作按钮
  function wire() {
    if (!overlay) return;
    overlay.querySelectorAll('[data-page]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        setPage(btn.dataset.page);
      });
    });
    overlay.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (btn.disabled) return;
        const fn = actions && actions[btn.dataset.act];
        if (typeof fn === 'function') { fn(); setTimeout(() => update(null), 60); }
      });
    });
  }

  function setPage(p) {
    if (!PAGES.some(x => x[0] === p)) return page;
    page = p;
    if (overlay) { overlay.dataset.sig = ''; }
    update(null);
    return page;
  }

  function setOperating(v) {
    operating = !!v;
    if (mode === 'hybrid') update(null);
    return operating;
  }

  return {
    update, mode, corners, plane, overlay, size: { w, h }, center: ctr,
    getModel: () => lastModel,
    setOperating, isOperating: () => operating,
    setPage, getPage: () => page,
  };
}
