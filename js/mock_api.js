// mock_api.js — GitHub Pages 静态版 API 模拟层
// 拦截所有 fetch('/api/...') 调用，返回 JS 实时模拟数据
// 替代 Flask + MySQL + MQTT 后端

(function() {
  'use strict';

  // ====== 内部状态 ======
  const RECIPES = ['IMP-BF2-90keV', 'IMP-P-60keV', 'IMP-As-120keV', 'IMP-B-30keV'];
  const SPECIES = ['BF2', 'P', 'As', 'B'];
  const ALARM_TYPES = [
    {code:'BEAM_DRIFT',  level:'WARN',  msg:'束流漂移'},
    {code:'VAC_RISE',    level:'WARN',  msg:'真空度上升'},
    {code:'TEMP_HIGH',   level:'WARN',  msg:'温度偏高'},
    {code:'DOSE_VAR',    level:'WARN',  msg:'剂量波动'},
    {code:'PRESS_RISE',  level:'WARN',  msg:'气压异常'},
    {code:'ESC_FLUCT',   level:'WARN',  msg:'静电吸盘波动'},
    {code:'COOL_FLOW',   level:'WARN',  msg:'冷却流量低'},
    {code:'BEAM_UNST',   level:'ERROR', msg:'束流不稳定'},
    {code:'VAC_LEAK',    level:'ERROR', msg:'真空泄漏'},
    {code:'HANDLER_JAM', level:'ERROR', msg:'机械手卡死'},
    {code:'POWER_FAULT', level:'ERROR', msg:'电源故障'},
    {code:'COOL_FAIL',   level:'ERROR', msg:'冷却系统故障'},
  ];

  const S = {
    machineState: 'IDLE',
    machineReason: '',
    stateTime: new Date(),
    wafers: [],
    alarms: [],
    alarmSeq: 1,
    waferSeq: 1,
    lot: { lot_id: null, total: 20, start_ts: null, done: 0 },
    lotRecords: [],
    lotSeq: 0,
    alarmEveryMin: 5,
    alarmEveryMax: 10,
    errorEvery: 10,
    wafersSinceAlarm: 0,
    warnOpen: 0,
    errorOpen: 0,
    powered: false,
    processStarted: false,
  };

  // ====== 工具函数 ======
  function now() { return new Date(); }
  function ts(d) { d = d || now(); return d.toISOString().slice(0,19).replace('T',' '); }
  function tsShort(d) { d = d || now(); return (d.getMonth()+1).toString().padStart(2,'0')+'-'+d.getDate().toString().padStart(2,'0')+' '+d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0'); }
  function rnd(a,b) { return a + Math.random()*(b-a); }
  function rndInt(a,b) { return Math.floor(rnd(a,b+1)); }
  function pick(arr) { return arr[rndInt(0, arr.length-1)]; }

  // ====== 预填充历史数据（50 条） ======
  function initHistory() {
    const base = now();
    for (let i = 50; i >= 1; i--) {
      const d = new Date(base.getTime() - i * 120000);
      const ok = Math.random() > 0.12;
      const unif = ok ? rnd(0.8, 1.95) : rnd(2.5, 5.0);
      S.wafers.push({
        id: S.waferSeq++,
        lot_id: 'LOT-HIST',
        wafer_id: 'LOT-HIST-' + String(i).padStart(2,'0'),
        recipe_name: pick(RECIPES),
        species: pick(SPECIES),
        energy_kev: rnd(60, 120),
        dose_cm2: (rnd(0.5, 5.0) * 1e15).toExponential(2),
        beam_current_ma: rnd(2.5, 3.5),
        tilt_deg: 7,
        twist_deg: 0,
        implant_time_s: rnd(6, 9),
        chamber_pressure_torr: rnd(0.00001, 0.00006),
        esc_voltage_v: rnd(1150, 1350),
        wafer_temp_c: rnd(22, 26),
        uniformity_pct: Math.round(unif * 100) / 100,
        particles_added: ok ? rndInt(3, 18) : rndInt(60, 210),
        process_result: ok ? 'PASS' : 'FAIL',
        created_at: ts(d),
      });
    }
  }
  initHistory();

  // ====== 生成一片晶圆 ======
  function genWafer(lotId, seq) {
    const ok = Math.random() > 0.10;
    const unif = ok ? rnd(0.8, 1.95) : rnd(2.5, 5.0);
    const w = {
      id: S.waferSeq++,
      lot_id: lotId,
      wafer_id: lotId + '-' + String(seq).padStart(2,'0'),
      recipe_name: pick(RECIPES),
      species: pick(SPECIES),
      energy_kev: rnd(60, 120),
      dose_cm2: (rnd(0.5, 5.0) * 1e15).toExponential(2),
      beam_current_ma: rnd(2.5, 3.5),
      tilt_deg: 7,
      twist_deg: 0,
      implant_time_s: rnd(6, 9),
      chamber_pressure_torr: rnd(0.00001, 0.00006),
      esc_voltage_v: rnd(1150, 1350),
      wafer_temp_c: rnd(22, 26),
      uniformity_pct: Math.round(unif * 100) / 100,
      particles_added: ok ? rndInt(3, 18) : rndInt(60, 210),
      process_result: ok ? 'PASS' : 'FAIL',
      created_at: ts(),
    };
    S.wafers.push(w);
    if (S.wafers.length > 500) S.wafers.shift();
    return w;
  }

  // ====== 生成报警 ======
  function maybeAlarm() {
    S.wafersSinceAlarm++;
    if (S.wafersSinceAlarm < S.alarmEveryMin) return;
    if (S.wafersSinceAlarm > S.alarmEveryMax) {
      // 强制触发
    } else if (Math.random() > 0.3) return;

    // 决定 WARN 还是 ERROR
    const doError = (S.wafersSinceAlarm >= S.errorEvery) && (Math.random() < 0.4);
    const pool = doError ? ALARM_TYPES.filter(a => a.level === 'ERROR') : ALARM_TYPES.filter(a => a.level === 'WARN');
    const a = pick(pool);
    const alarm = {
      alarm_id: S.alarmSeq++,
      alarm_code: a.code,
      alarm_level: a.level,
      message: a.msg,
      machine_id: 'IMP-MC-01',
      start_time: ts(),
      end_time: null,
    };
    S.alarms.push(alarm);
    if (S.alarms.length > 200) S.alarms.shift();

    if (a.level === 'WARN') {
      S.warnOpen++;
      S.machineState = 'WARN';
      S.machineReason = a.msg;
      S.stateTime = now();
      // 7 秒后自动恢复
      setTimeout(() => {
        if (alarm.end_time) return;
        alarm.end_time = ts();
        S.warnOpen = Math.max(0, S.warnOpen - 1);
        if (S.warnOpen === 0 && S.errorOpen === 0 && S.processStarted) {
          S.machineState = 'RUNNING';
          S.machineReason = '';
          S.stateTime = now();
        }
      }, 7000);
    } else {
      S.errorOpen++;
      S.machineState = 'DOWN';
      S.machineReason = a.msg;
      S.stateTime = now();
      S.processStarted = false;
    }
    S.wafersSinceAlarm = 0;
    S.alarmEveryMin = rndInt(5, 8);
    S.alarmEveryMax = S.alarmEveryMin + rndInt(2, 5);
  }

  // ====== KPI 计算 ======
  function kpis() {
    const todayStr = now().toDateString();
    const todayWafers = S.wafers.filter(w => new Date(w.created_at).toDateString() === todayStr && !w.lot_id.startsWith('PILOT')).length;
    const totalWafers = S.wafers.filter(w => !w.lot_id.startsWith('PILOT')).length;
    const todayAll = S.wafers.filter(w => new Date(w.created_at).toDateString() === todayStr).length;
    const totalAll = S.wafers.length;
    const last7 = S.wafers.filter(w => (now() - new Date(w.created_at)) < 7*24*3600*1000 && !w.lot_id.startsWith('PILOT'));
    const fail7 = last7.filter(w => w.process_result === 'FAIL').length;
    const passRate = last7.length ? Math.round((last7.length - fail7) / last7.length * 1000) / 10 : null;
    const unifVals = last7.map(w => w.uniformity_pct).filter(v => v != null);
    const avgUnif = unifVals.length ? Math.round(unifVals.reduce((s,v)=>s+v,0) / unifVals.length * 100) / 100 : null;
    const openAlarms = S.alarms.filter(a => !a.end_time).length;
    const activeLot = (S.machineState === 'RUNNING' || S.machineState === 'WARN') ? S.lot.lot_id : null;

    return {
      today_wafers: todayWafers,
      total_wafers: totalWafers,
      today_wafers_all: todayAll,
      total_wafers_all: totalAll,
      avg_uniformity_7d: avgUnif,
      fail_7d: fail7,
      pass_rate_7d: passRate,
      open_alarms: openAlarms,
      warn_open: S.warnOpen,
      error_open: S.errorOpen,
      machine_state: S.machineState,
      machine_reason: S.machineReason,
      state_time: ts(S.stateTime),
      active_lot: activeLot,
      box_total: S.lot.total,
      box_done: S.lot.done,
      now: ts(),
    };
  }

  // ====== 构件参数 ======
  function components() {
    const lastW = S.wafers[S.wafers.length - 1];
    const energy = lastW ? lastW.energy_kev : 80;
    const beam = lastW ? lastW.beam_current_ma : 12.3;
    const dose = lastW ? lastW.dose_cm2 : '5.00E+15';
    const temp = lastW ? lastW.wafer_temp_c : 25.3;
    const pressure = lastW ? lastW.chamber_pressure_torr : 0.00003;
    const unif = lastW ? lastW.uniformity_pct : 1.5;
    const lot = S.lot.lot_id || '—';
    const isDown = S.machineState === 'DOWN';
    const fl = (b, p) => Math.round(b * (1 + (Math.random()*2-1)*p) * 100) / 100;
    const stStr = s => ({RUNNING:'运行',DOWN:'故障',IDLE:'待机',WARN:'预警'}[s] || s);
    const st = stStr(S.machineState);
    const openAlarms = S.alarms.filter(a => !a.end_time).length;

    return {
      ION_SOURCE: {title:'离子源 Ion Source',desc:'电离 BF₃/PH₃ 气体产生正离子束流',params:{能量:energy+' keV',束流:fl(beam,0.03)+' mA',剂量:dose+' cm⁻²',气压:fl(2.1,0.05).toFixed(2)+'e-1 Pa'},status:st,level:isDown?'ERROR':'OK'},
      MAGNET: {title:'分析磁铁 Analyzer',desc:'90°偏转质量分析器，按荷质比选择离子',params:{磁场:fl(1.2,0.02)+' T',偏转角:'90°',分辨力:'±0.5 amu'},status:st,level:isDown?'ERROR':'OK'},
      ACCEL: {title:'加速管 Accelerator',desc:'多级静电加速管，决定离子注入深度',params:{高压:energy+' kV',绝缘:'SF₆',级数:'8 级',纹波:'<'+fl(0.01,0.3).toFixed(4)+'%'},status:st,level:isDown?'ERROR':'OK'},
      SCANNER: {title:'扫描器 Scanner',desc:'静电偏转板，束流 X/Y 匀速扫描覆盖晶圆',params:{X频率:fl(1024,0.01)+' Hz',Y频率:fl(64,0.02)+' Hz',扫描范围:'300 mm'},status:st,level:isDown?'ERROR':'OK'},
      TARGET: {title:'靶室 Target Chamber',desc:'晶圆在此接受离子束注入',params:{真空:pressure.toExponential(1)+' Torr',温度:fl(temp,0.02)+' °C',倾斜:'7°',转速:fl(120,0.03)+' rpm'},status:st,level:isDown?'ERROR':'OK'},
      VACUUM: {title:'真空泵 Vacuum',desc:'干式机械泵+涡轮分子泵机组',params:{前级:fl(0.5,0.1)+' Pa',分子泵:pressure.toExponential(1)+' Torr',转速:fl(90000,0.01)+' rpm'},status:st,level:isDown?'ERROR':'OK'},
      HV: {title:'高压电源 HV Supply',desc:'为加速管提供稳定直流高压',params:{输出:energy+' kV',纹波:'<'+fl(0.01,0.3).toFixed(4)+'%',保护:isDown?'已触发':'过流锁定'},status:st,level:isDown?'ERROR':'OK'},
      COOLING: {title:'冷却单元 Chiller',desc:'去离子水循环冷却系统',params:{水温:fl(22,0.05)+' °C',流量:fl(15,0.03)+' L/min',压力:fl(2,0.04)+' bar'},status:st,level:isDown?'ERROR':'OK'},
      ROBOT: {title:'晶圆传输 Robot',desc:'机械臂在晶圆口与靶室间传输晶圆',params:{臂长:'350 mm',重复精度:'±0.1 mm',速度:fl(0.8,0.1)+' s/wafer'},status:S.machineState==='IDLE'?'待机':st,level:openAlarms>0?'WARN':'OK'},
      CONTROL: {title:'控制柜 Controller',desc:'SECS/GEM 通讯模块，对接 MES',params:{通讯:'HSMS',协议:'SECS-II',批次:lot,报警:String(openAlarms)},status:st,level:isDown?'ERROR':(openAlarms>0?'WARN':'OK')},
    };
  }

  // ====== JSON Response helper ======
  function jsonRes(data, status) {
    return Promise.resolve(new Response(JSON.stringify(data), {
      status: status || 200,
      headers: {'Content-Type': 'application/json'}
    }));
  }

  // ====== 路由匹配 ======
  function handleApi(url, opts) {
    const method = (opts && opts.method) || 'GET';
    const body = opts && opts.body ? JSON.parse(opts.body) : {};
    const u = new URL(url, 'http://mock');
    const path = u.pathname;
    const q = u.searchParams;

    // GET endpoints
    if (path === '/api/kpis') return jsonRes(kpis());
    if (path === '/api/components') return jsonRes(components());
    if (path === '/api/wafers') {
      const limit = parseInt(q.get('limit') || '15');
      const rows = S.wafers.slice(-limit).reverse().map(w => ({...w}));
      return jsonRes(rows);
    }
    if (path === '/api/trend') {
      const limit = parseInt(q.get('limit') || '40');
      const param = q.get('param') || 'uniformity_pct';
      const rows = S.wafers.slice(-limit).map(w => ({
        id: w.id, created_at: tsShort(new Date(w.created_at)),
        val: w[param] || w.uniformity_pct,
        process_result: w.process_result, recipe_name: w.recipe_name
      }));
      return jsonRes(rows);
    }
    if (path === '/api/alarms') {
      const limit = parseInt(q.get('limit') || '50');
      return jsonRes(S.alarms.slice(-limit).reverse());
    }
    if (path === '/api/alarms/open') {
      return jsonRes(S.alarms.filter(a => !a.end_time));
    }
    if (path === '/api/lot/records') {
      const limit = parseInt(q.get('limit') || '5');
      return jsonRes(S.lotRecords.slice(-limit).reverse());
    }

    // POST endpoints
    if (path === '/api/machine/cmd' && method === 'POST') {
      const action = body.action || '';
      if (action === 'run') {
        S.machineState = 'RUNNING';
        S.machineReason = '';
        S.stateTime = now();
        S.processStarted = true;
      } else if (action === 'stop') {
        S.machineState = 'IDLE';
        S.machineReason = '';
        S.stateTime = now();
        S.processStarted = false;
      }
      return jsonRes({ok: true, action: action, ts: ts()});
    }
    if (path === '/api/pilot' && method === 'POST') {
      const force = (body.force || '').toLowerCase();
      const ok = force === 'fail' ? false : (force === 'pass' ? true : Math.random() < 0.5);
      const unif = ok ? rnd(1.05, 1.95) : rnd(4.20, 9.50);
      const beam = ok ? rnd(2.60, 3.40) : rnd(4.60, 6.20);
      const particles = ok ? rndInt(3, 18) : rndInt(60, 210);
      const lot = 'PILOT-' + now().toISOString().slice(5,14).replace(/[-T:]/g,'');
      const w = genWafer(lot, 0);
      w.recipe_name = 'PILOT-CHECK';
      w.uniformity_pct = Math.round(unif * 100) / 100;
      w.process_result = ok ? 'PASS' : 'FAIL';
      const msg = ok
        ? '✔ 试片合格：均匀度 ' + unif.toFixed(2) + '%，束流密度 ' + beam.toFixed(3) + ' mA，可启动工艺'
        : '✘ 试片不合格：均匀度 ' + unif.toFixed(2) + '%（规格 ≤2.00%），束流密度 ' + beam.toFixed(3) + ' mA 偏离，请在操作电脑上「一键重新调束」后继续试片';
      return jsonRes({pass: ok, uniformity: Math.round(unif*100)/100, beam_current: Math.round(beam*1000)/1000, particles, lot, wafer_id: lot+'-00', result: ok?'PASS':'FAIL', message: msg, checked_at: now().toTimeString().slice(0,8)});
    }
    if (path === '/api/reticle_adjust' && method === 'POST') {
      return jsonRes({ok: true, message: '调束完成，可重新试片', ts: ts()});
    }
    if (path === '/api/lot/start' && method === 'POST') {
      const total = Math.max(1, Math.min(parseInt(body.total || '20'), 100));
      S.lotSeq++;
      const lotId = 'LOT-' + now().toISOString().slice(5,10).replace('-','') + '-' + String(S.lotSeq).padStart(2,'0');
      S.lot = {lot_id: lotId, total, start_ts: now(), done: 0};
      S.lotRecords.push({lot_id: lotId, total, pass: 0, fail: 0, yield_rate: null, warn_count: 0, error_count: 0, state: 'RUNNING', start_ts: ts(), end_ts: null});
      return jsonRes({ok: true, lot_id: lotId, total, start_ts: ts()});
    }
    if (path === '/api/lot/reset' && method === 'POST') {
      const old = S.lot.lot_id;
      if (old) {
        const rec = S.lotRecords.find(r => r.lot_id === old);
        if (rec) { rec.state = 'ABORTED'; rec.end_ts = ts(); }
      }
      S.lot = {lot_id: null, total: 20, start_ts: null, done: 0};
      S.machineState = 'IDLE';
      S.machineReason = '';
      S.processStarted = false;
      return jsonRes({ok: true, cleared_lot: old, message: '已重新装盒：换新料盒，需重新上电→调束→试片'});
    }
    if (path === '/api/wafer/emit' && method === 'POST') {
      const lotId = body.lot_id || S.lot.lot_id || 'LOT-GUEST';
      S.lot.done = (S.lot.done || 0) + 1;
      const seq = S.lot.done;
      genWafer(lotId, seq);
      maybeAlarm();
      // 更新 lot record
      const rec = S.lotRecords.find(r => r.lot_id === lotId);
      if (rec) {
        const lastW = S.wafers[S.wafers.length-1];
        if (lastW.process_result === 'PASS') rec.pass++; else rec.fail++;
        rec.yield_rate = Math.round(rec.pass / (rec.pass+rec.fail) * 1000) / 10;
      }
      return jsonRes({ok: true, lot_id: lotId, ts: ts()});
    }
    if (path === '/api/alarm/ack' && method === 'POST') {
      // 关闭匹配的 WARN 报警
      const alarmId = body.alarm_id;
      const alarmCode = body.alarm_code;
      let closed = 0;
      S.alarms.forEach(a => {
        if (a.end_time) return;
        if ((alarmId && a.alarm_id == alarmId) || (alarmCode && a.alarm_code === alarmCode) || (!alarmId && !alarmCode && a.alarm_level === 'WARN')) {
          a.end_time = ts();
          closed++;
          if (a.alarm_level === 'WARN') S.warnOpen = Math.max(0, S.warnOpen - 1);
          if (a.alarm_level === 'ERROR') S.errorOpen = Math.max(0, S.errorOpen - 1);
        }
      });
      if (S.warnOpen === 0 && S.errorOpen === 0 && S.machineState !== 'RUNNING') {
        S.machineState = S.processStarted ? 'RUNNING' : 'IDLE';
        S.machineReason = '';
        S.stateTime = now();
      }
      return jsonRes({ok: true, closed: closed, ts: ts()});
    }
    if (path === '/api/lot/close' && method === 'POST') {
      const lid = body.lot_id || S.lot.lot_id;
      const rec = S.lotRecords.find(r => r.lot_id === lid);
      if (rec) {
        rec.state = 'CLOSED';
        rec.end_ts = ts();
      }
      S.lot = {lot_id: null, total: 20, start_ts: null, done: 0};
      S.machineState = 'IDLE';
      S.processStarted = false;
      return jsonRes({ok: true, lot_id: lid, message: '批次已关闭', ts: ts()});
    }
    if (path === '/api/repair' && method === 'POST') {
      // 模拟检修：5 秒后恢复
      setTimeout(() => {
        S.alarms.forEach(a => {
          if (!a.end_time && a.alarm_level === 'ERROR') {
            a.end_time = ts();
          }
        });
        S.errorOpen = 0;
        S.warnOpen = 0;
        S.machineState = 'IDLE';
        S.machineReason = '';
        S.stateTime = now();
      }, 5000);
      return jsonRes({ok: true, delivered: true, state: 'IDLE', state_before: 'DOWN', waited_ms: 5000, message: '设备工程师已完成检修（5 秒），请重新调束并试片后复产', ts: ts()});
    }

    // 兜底
    return jsonRes({ok: false, error: 'mock: unknown endpoint ' + path}, 404);
  }

  // ====== 拦截 fetch ======
  const _origFetch = window.fetch;
  window.fetch = function(input, opts) {
    let url = typeof input === 'string' ? input : (input && input.url ? input.url : String(input));
    if (url.indexOf('/api/') !== -1) {
      // 提取 /api/... 部分（去掉域名前缀）
      const idx = url.indexOf('/api/');
      const apiPath = url.substring(idx);
      return handleApi(apiPath, opts);
    }
    // 非 API 请求 → 交给原始 fetch
    return _origFetch.call(window, input, opts);
  };

  // 暴露调试接口
  window.__mockState = S;
  window.__mockKpis = kpis;
  console.log('[mock_api] API 模拟层已加载，' + S.wafers.length + ' 条历史数据');
})();
