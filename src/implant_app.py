# -*- coding: utf-8 -*-
"""
离子注入工序数据看板 —— Flask 应用（端口 5001）
================================================
接口：
  /                 看板页面
  /api/kpis         机台状态/今日产能/平均均匀度/未处理报警/良率
  /api/wafers       最近晶圆工艺记录
  /api/trend        趋势序列（uniformity/beam_current_ma/energy_kev/dose_cm2）
  /api/alarms       最近报警
启动：python implant_app.py   （由 Nginx 反代到 80 端口）
"""
import io
import sys
import random
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from flask import Flask, jsonify, render_template, request, session, redirect
from flask.json.provider import DefaultJSONProvider
from decimal import Decimal
import pymysql

from db_config import DB_CONFIG, MQTT_CONFIG, TOPIC_CMD

MQTT_CMD_CLIENT = None

# ===== 当前批次状态（网页「一盒 20 片」的批次上下文）=====
# 网页启动工艺时调用 /api/lot/start 生成批次号并下发模拟器；
# 停机时 /api/lot/close 按「开始→结束」时间窗统计，一盒只写一条记录（幂等）。
LOT_CTX = {"lot_id": None, "start_ts": None, "total": 20}


def publish_cmd(action, extra=None):
    """向后端→模拟器的指令通道发一条指令（run / stop / repair）。
    模拟器据此暂停/恢复生产，保证数据库里的晶圆数量只在机台加工时增长。"""
    global MQTT_CMD_CLIENT
    try:
        import json as _json
        import paho.mqtt.publish as _pub
        payload = {"action": action, "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        if extra:
            payload.update(extra)
        _pub.single(TOPIC_CMD, _json.dumps(payload, ensure_ascii=False),
                    qos=1, hostname=MQTT_CONFIG["host"], port=MQTT_CONFIG["port"])
        return True
    except Exception as e:  # EMQX 未启动时不要让页面崩
        print("[app] publish_cmd 失败:", e)
        return False

EMPLOYEE_ID = "202301020772"   # 默认操作员工号（兼容旧逻辑，实际验证走 DB）
EMPLOYEE_PWD = "123456"        # 默认密码（DB 不可用时的兜底）

def verify_credentials(eid, pwd):
    """从 operator_credentials 表验证工号密码，DB 不可用时兜底硬编码。"""
    try:
        c = db()
        cur = c.cursor()
        cur.execute(
            "SELECT employee_id FROM operator_credentials WHERE employee_id=%s AND password=%s AND active=1",
            (eid, pwd))
        row = cur.fetchone()
        c.close()
        if row:
            return True
    except Exception as e:
        print("[app] verify_credentials DB 查询失败，兜底硬编码:", e)
    return eid == EMPLOYEE_ID and pwd == EMPLOYEE_PWD


class FloatJSONProvider(DefaultJSONProvider):
    """让 MySQL DECIMAL 字段以数字（而非字符串）输出到 JSON，前端 toFixed/Math.min 才能正常工作。"""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


app = Flask(__name__)
app.json = FloatJSONProvider(app)
app.secret_key = "implant-fab-2026-secret-key"
# 模板改动即时生效（否则 Jinja 会缓存旧模板，改 HTML 后刷新看不到变化）
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def no_cache(resp):
    """禁止浏览器缓存 HTML 页面，确保用户始终看到最新版本（修复“无数据”缓存问题）。"""
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

TREND_WHITELIST = {"uniformity_pct", "beam_current_ma", "energy_kev", "dose_cm2"}


def db():
    return pymysql.connect(**DB_CONFIG)


def safe_limit(default=15, hi=200):
    """安全解析 limit 参数：非数字或越界时返回默认值。"""
    try:
        return max(1, min(int(request.args.get("limit", default)), hi))
    except (TypeError, ValueError):
        return default


@app.errorhandler(500)
def handle_500(e):
    return jsonify({"error": "服务内部错误", "detail": str(e)}), 500


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        eid = request.form.get("employee_id", "").strip()
        pwd = request.form.get("password", "").strip()
        if verify_credentials(eid, pwd):
            session["user"] = eid
            return redirect("/3d")
        return render_template("login3d.html", error="工号或密码错误，请重试")
    return render_template("login3d.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")


@app.route("/")
def index():
    if session.get("user") != EMPLOYEE_ID:
        return redirect("/login")
    return redirect("/3d")


@app.route("/2d")
def view_2d():
    """保留 2D 数据看板（顶部导航已移除，此地址仍可直接访问）。每次刷新必须登录。"""
    if session.get("user") != EMPLOYEE_ID:
        return redirect("/login")
    return render_template("implant_index.html")


@app.route("/3d")
def view_3d():
    if session.get("user") != EMPLOYEE_ID:
        return redirect("/login")
    session.pop("user", None)
    return render_template("implant_3d.html")


def lotCycleDone():
    """当前批次已完成的片数（按「批次号 + 开始时间」统计，避免把上一盒算进来）。"""
    lid, st = LOT_CTX.get("lot_id"), LOT_CTX.get("start_ts")
    if not lid or not st:
        return 0
    try:
        c = db()
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM implant_wafer_records "
                    "WHERE lot_id=%s AND created_at>=%s", (lid, st))
        n = cur.fetchone()[0]
        cur.close()
        c.close()
        return int(n)
    except Exception:
        return 0


def _finalize_lot(lot_id, state="CLOSED", note=None):
    """把一批收尾：按时间窗统计晶圆/报警 → 写（或更新）lot_records → 会话置 state。

    目的是消灭「孤儿批次」：任何时候中断（重新装盒、后端重启、浏览器关掉）都有一条批次记录，
    否则 implant_wafer_records 里会留下大量找不到批次报告的 lot_id。
    """
    if not lot_id:
        return None
    try:
        c = db()
        cur = c.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT total, start_ts FROM implant_lot_sessions WHERE lot_id=%s", (lot_id,))
        s = cur.fetchone()
        t0 = s["start_ts"] if s else None
        if t0 is None and lot_id == LOT_CTX.get("lot_id"):
            t0 = LOT_CTX.get("start_ts")
        t1 = datetime.now()
        if t0 is None:
            cur.execute("SELECT MIN(created_at) t FROM implant_wafer_records WHERE lot_id=%s", (lot_id,))
            row = cur.fetchone()
            t0 = (row["t"] if row and row["t"] else t1)
        cur.execute("SELECT COUNT(*) n, SUM(process_result='PASS') p, AVG(uniformity_pct) u "
                    "FROM implant_wafer_records WHERE lot_id=%s AND lot_id NOT LIKE 'PILOT%%'", (lot_id,))
        r = cur.fetchone() or {}
        n = int(r.get("n") or 0)
        p = int(r.get("p") or 0)
        uf = round(float(r.get("u") or 0), 2) if n else 0.0
        cur.execute("SELECT SUM(alarm_level='WARN') w, SUM(alarm_level='ERROR') e "
                    "FROM implant_alarm_events WHERE start_time BETWEEN %s AND %s", (t0, t1))
        a = cur.fetchone() or {}
        w = int(a.get("w") or 0)
        e = int(a.get("e") or 0)
        cur.execute("UPDATE implant_lot_sessions SET state=%s, end_ts=%s WHERE lot_id=%s",
                    (state, t1, lot_id))
        if n:
            yield_pct = round(p * 100.0 / n, 1)
            cur.execute(
                "INSERT INTO implant_lot_records (lot_id, wafer_count, pass_count, yield_pct, "
                "uniformity_avg, alarm_count, alarm_warn, alarm_error, cycle_mode, note, archived) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'NORMAL',%s,0) "
                "ON DUPLICATE KEY UPDATE wafer_count=VALUES(wafer_count), pass_count=VALUES(pass_count), "
                "yield_pct=VALUES(yield_pct), uniformity_avg=VALUES(uniformity_avg), "
                "alarm_count=VALUES(alarm_count), alarm_warn=VALUES(alarm_warn), "
                "alarm_error=VALUES(alarm_error), note=VALUES(note)",
                (lot_id, n, p, yield_pct, uf, w + e, w, e, note))
        c.commit()
        cur.close()
        c.close()
        print("[app] 批次收尾 %s state=%s 片数=%d 合格=%d 报警=%d/%d" % (lot_id, state, n, p, w, e))
        return {"lot_id": lot_id, "wafer_count": n, "pass_count": p, "state": state}
    except Exception as exc:
        print("[app] 批次收尾失败:", exc)
        return None


def _sweep_lot_sessions():
    """后端启动时收尾上次遗留的 RUNNING 批次（防止刷新/重启把批次号弄丢）。"""
    try:
        c = db()
        cur = c.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT lot_id FROM implant_lot_sessions WHERE state='RUNNING'")
        stale = [row["lot_id"] for row in cur.fetchall()]
        cur.close()
        c.close()
        for lid in stale:
            _finalize_lot(lid, "ABORTED", "后端重启自动收尾")
        if stale:
            print("[app] 已收尾遗留批次 %d 个: %s" % (len(stale), ", ".join(stale)))
    except Exception as exc:
        print("[app] 遗留批次收尾失败:", exc)


@app.route("/api/kpis")
def kpis():
    # 只统计「有批次记录且未归档」的批次：早期压测留下的大量随机批次不进今日/7 天 KPI
    LOTF = "lot_id IN (SELECT lot_id FROM implant_lot_records WHERE archived=0)"
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT COUNT(*) n FROM implant_wafer_records WHERE DATE(created_at)=CURDATE() AND " + LOTF)
    today = cur.fetchone()["n"]
    cur.execute(
        "SELECT COUNT(*) n, AVG(uniformity_pct) u, SUM(process_result='FAIL') f "
        "FROM implant_wafer_records WHERE created_at >= NOW() - INTERVAL 7 DAY AND " + LOTF)
    r = cur.fetchone()
    cur.execute("SELECT COUNT(*) n FROM implant_alarm_events WHERE end_time IS NULL")
    open_alarms = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) n FROM implant_alarm_events WHERE end_time IS NULL AND alarm_level='WARN'")
    warn_open = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) n FROM implant_alarm_events WHERE end_time IS NULL AND alarm_level='ERROR'")
    error_open = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) n FROM implant_wafer_records WHERE " + LOTF)
    total = cur.fetchone()["n"]
    # 机台总产出（不过滤）：与「正规批次产量」并列展示，避免口径切换让人误以为数据丢了
    cur.execute("SELECT COUNT(*) n FROM implant_wafer_records WHERE DATE(created_at)=CURDATE()")
    today_all = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) n FROM implant_wafer_records")
    total_all = cur.fetchone()["n"]
    cur.execute("SELECT state, reason, state_time FROM implant_machine_state ORDER BY state_time DESC LIMIT 1")
    st = cur.fetchone()
    cur.execute("SELECT lot_id FROM implant_wafer_records ORDER BY created_at DESC LIMIT 1")
    lot = cur.fetchone()
    cur.close()
    c.close()
    pass_rate = None
    if r["n"]:
        pass_rate = round((r["n"] - (r["f"] or 0)) / r["n"] * 100, 1)
    state = st["state"] if st else "UNKNOWN"
    # 只有机台真正在跑（RUNNING）时才对外显示「当前批次」，停机/待机不挂历史批次号
    active_lot = None
    if state == "RUNNING":
        active_lot = LOT_CTX.get("lot_id") or (lot["lot_id"] if lot else None)
    box_done = lotCycleDone()
    return jsonify({
        "today_wafers": today,
        "total_wafers": total,
        "today_wafers_all": today_all,
        "total_wafers_all": total_all,
        "avg_uniformity_7d": round(r["u"], 2) if r["u"] else None,
        "fail_7d": r["f"] or 0,
        "pass_rate_7d": pass_rate,
        "open_alarms": open_alarms,
        "warn_open": warn_open,
        "error_open": error_open,
        "machine_state": state,
        "machine_reason": (st["reason"] if st else ""),
        "state_time": (st["state_time"].strftime("%Y-%m-%d %H:%M:%S") if st and st["state_time"] else ""),
        "active_lot": active_lot,
        "box_total": LOT_CTX.get("total", 20),
        "box_done": box_done,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/wafers")
def wafers():
    limit = safe_limit(15, 200)
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        "SELECT id, lot_id, wafer_id, recipe_name, species, energy_kev, dose_cm2, beam_current_ma, "
        "tilt_deg, twist_deg, implant_time_s, chamber_pressure_torr, esc_voltage_v, wafer_temp_c, "
        "uniformity_pct, particles_added, process_result, created_at "
        "FROM implant_wafer_records ORDER BY created_at DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    cur.close()
    c.close()
    for r in rows:
        r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        r["dose_cm2"] = "%.2E" % r["dose_cm2"]
    return jsonify(rows)


@app.route("/api/trend")
def trend():
    param = request.args.get("param", "uniformity_pct")
    if param not in TREND_WHITELIST:
        param = "uniformity_pct"
    limit = safe_limit(80, 500)
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        "SELECT id, created_at, %s AS val, process_result, recipe_name FROM implant_wafer_records "
        "ORDER BY created_at DESC LIMIT %%s" % param, (limit,))
    rows = cur.fetchall()
    rows = list(rows)
    rows.reverse()   # DESC 取最新 N 条，再反转为时间正序（折线图从左到右）
    cur.close()
    c.close()
    for r in rows:
        r["created_at"] = r["created_at"].strftime("%m-%d %H:%M")
    return jsonify(rows)


@app.route("/api/alarms")
def alarms():
    limit = safe_limit(20, 200)
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        "SELECT id, machine_id, alarm_code, alarm_level, message, start_time, end_time, "
        "component_tag, param_name, param_from, param_to, param_unit, param_fix "
        "FROM implant_alarm_events ORDER BY start_time DESC LIMIT %s", (limit,))
    rows = cur.fetchall()
    cur.close()
    c.close()
    for r in rows:
        r["start_time"] = r["start_time"].strftime("%Y-%m-%d %H:%M:%S")
        r["end_time"] = r["end_time"].strftime("%Y-%m-%d %H:%M:%S") if r["end_time"] else None
    return jsonify(rows)


@app.route("/api/alarms/open")
def alarms_open():
    """未处理的报警（网页「调参向导」用）：WARN 需调参恢复，ERROR 需工程师检修。"""
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        "SELECT id, alarm_code, alarm_level, message, start_time, component_tag, "
        "param_name, param_from, param_to, param_unit, param_fix "
        "FROM implant_alarm_events WHERE end_time IS NULL ORDER BY start_time DESC LIMIT 5")
    rows = cur.fetchall()
    cur.close()
    c.close()
    for r in rows:
        r["start_time"] = r["start_time"].strftime("%H:%M:%S")
    return jsonify(rows)


@app.route("/api/components")
def components():
    """构件级实时参数——从最新晶圆记录 + 机台状态派生，带随机微扰模拟传感器读数。"""
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    cur.execute(
        "SELECT energy_kev, beam_current_ma, dose_cm2, wafer_temp_c, "
        "chamber_pressure_torr, uniformity_pct, tilt_deg, lot_id "
        "FROM implant_wafer_records ORDER BY created_at DESC LIMIT 1")
    w = cur.fetchone()
    cur.execute("SELECT state, reason FROM implant_machine_state ORDER BY state_time DESC LIMIT 1")
    st = cur.fetchone()
    cur.execute("SELECT COUNT(*) n FROM implant_alarm_events WHERE end_time IS NULL")
    open_alarms = cur.fetchone()["n"]
    cur.execute("SELECT alarm_code, alarm_level, message FROM implant_alarm_events ORDER BY start_time DESC LIMIT 1")
    la = cur.fetchone()
    cur.close()
    c.close()

    state = st["state"] if st else "UNKNOWN"
    is_down = state == "DOWN"
    fl = lambda base, pct: round(base * (1 + random.uniform(-pct, pct)), 2)

    energy = float(w["energy_kev"]) if w else 80.0
    beam = float(w["beam_current_ma"]) if w else 12.3
    dose = float(w["dose_cm2"]) if w else 5e15
    temp = float(w["wafer_temp_c"]) if w else 25.3
    pressure = float(w["chamber_pressure_torr"]) if w else 5e-6
    unif = float(w["uniformity_pct"]) if w else 1.5
    lot = w["lot_id"] if w else "—"

    def st_str(s):
        return {"RUNNING": "运行", "DOWN": "故障", "IDLE": "待机", "WARN": "预警"}.get(s, s)

    comps = {
        "ION_SOURCE": {
            "title": "离子源 Ion Source",
            "desc": "电离 BF₃/PH₃ 气体产生正离子束流",
            "params": {"能量": f"{energy} keV", "束流": f"{fl(beam, 0.03)} mA", "剂量": f"{dose:.1E} cm⁻²", "气压": f"{fl(2.1, 0.05):.2e} Pa"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "MAGNET": {
            "title": "分析磁铁 Analyzer",
            "desc": "90°偏转质量分析器，按荷质比选择离子",
            "params": {"磁场": f"{fl(1.2, 0.02)} T", "偏转角": "90°", "分辨力": "±0.5 amu"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "ACCEL": {
            "title": "加速管 Accelerator",
            "desc": "多级静电加速管，决定离子注入深度",
            "params": {"高压": f"{energy} kV", "绝缘": "SF₆", "级数": "8 级", "纹波": f"<{fl(0.01, 0.3):.4f}%"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "SCANNER": {
            "title": "扫描器 Scanner",
            "desc": "静电偏转板，束流 X/Y 匀速扫描覆盖晶圆",
            "params": {"X频率": f"{fl(1024, 0.01)} Hz", "Y频率": f"{fl(64, 0.02)} Hz", "扫描范围": "300 mm"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "TARGET": {
            "title": "靶室 Target Chamber",
            "desc": "晶圆在此接受离子束注入",
            "params": {"真空": f"{pressure:.1e} Torr", "温度": f"{fl(temp, 0.02)} °C", "倾斜": f"{float(w['tilt_deg']) if w else 7}°", "转速": f"{fl(120, 0.03)} rpm"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "VACUUM": {
            "title": "真空泵 Vacuum",
            "desc": "干式机械泵+涡轮分子泵机组",
            "params": {"前级": f"{fl(0.5, 0.1)} Pa", "分子泵": f"{pressure:.1e} Torr", "转速": f"{fl(90000, 0.01)} rpm"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "HV": {
            "title": "高压电源 HV Supply",
            "desc": "为加速管提供稳定直流高压",
            "params": {"输出": f"{energy} kV", "纹波": f"<{fl(0.01, 0.3):.4f}%", "保护": "过流锁定" if not is_down else "已触发"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "COOLING": {
            "title": "冷却单元 Chiller",
            "desc": "去离子水循环冷却系统",
            "params": {"水温": f"{fl(22, 0.05)} °C", "流量": f"{fl(15, 0.03)} L/min", "压力": f"{fl(2, 0.04)} bar"},
            "status": st_str(state),
            "level": "ERROR" if is_down else "OK",
        },
        "ROBOT": {
            "title": "晶圆传输 Robot",
            "desc": "机械臂在晶圆口与靶室间传输晶圆",
            "params": {"臂长": "350 mm", "重复精度": "±0.1 mm", "速度": f"{fl(0.8, 0.1)} s/wafer"},
            "status": "待机" if state == "IDLE" else st_str(state),
            "level": "WARN" if open_alarms > 0 else "OK",
        },
        "CONTROL": {
            "title": "控制柜 Controller",
            "desc": "SECS/GEM 通讯模块，对接 MES",
            "params": {"通讯": "HSMS", "协议": "SECS-II", "批次": lot, "报警": str(open_alarms)},
            "status": st_str(state),
            "level": "ERROR" if is_down else ("WARN" if open_alarms > 0 else "OK"),
        },
    }
    return jsonify(comps)


@app.route("/api/pilot", methods=["POST"])
def api_pilot():
    """试片（Pilot check）：每次通电后必须先做一次。固定 50% 概率通过。

    合格 → 允许启动工艺；不合格 → 需在操作电脑上「一键重新调束」后继续试片。
    结果写入 implant_wafer_records（lot_id 以 PILOT- 开头），供追溯与看板统计。
    """
    conn = db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    # 取当前工艺配方，让试片数据与真实批次同源
    cur.execute(
        "SELECT recipe_name, species, energy_kev, dose_cm2, tilt_deg, twist_deg "
        "FROM implant_wafer_records ORDER BY id DESC LIMIT 1")
    base = cur.fetchone() or {
        "recipe_name": "PILOT-CHECK", "species": "BF2", "energy_kev": 90.0,
        "dose_cm2": 1.2e13, "tilt_deg": 25.0, "twist_deg": 0.0,
    }
    # 调试/演示用：force=fail|pass 可强制试片结论（仅用于自动化验收，正常使用不带此参数）
    _body = request.get_json(silent=True) or {}
    _force = (_body.get("force") or "").lower()
    if _force == "fail":
        ok = False
    elif _force == "pass":
        ok = True
    else:
        ok = random.random() < 0.5
    uniformity = round(random.uniform(1.05, 1.95), 2) if ok else round(random.uniform(4.20, 9.50), 2)
    beam = round(random.uniform(2.60, 3.40), 3) if ok else round(random.uniform(4.60, 6.20), 3)
    particles = random.randint(3, 18) if ok else random.randint(60, 210)
    lot = "PILOT-" + datetime.now().strftime("%m%d%H%M%S") + "%02d" % random.randint(0, 99)
    wafer_id = lot + "-00"

    cur.execute(
        "INSERT INTO implant_wafer_records "
        "(machine_id, lot_id, wafer_id, slot_no, recipe_name, species, energy_kev, dose_cm2, "
        " beam_current_ma, tilt_deg, twist_deg, implant_time_s, chamber_pressure_torr, "
        " esc_voltage_v, wafer_temp_c, uniformity_pct, particles_added, process_result) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        ("IMP-MC-01", lot, wafer_id, 0, "PILOT-CHECK", base["species"], base["energy_kev"],
         base["dose_cm2"], beam, base["tilt_deg"], base["twist_deg"],
         round(random.uniform(6.0, 9.0), 1), round(random.uniform(0.00001, 0.00006), 5),
         round(random.uniform(1150, 1350), 1), round(random.uniform(22.0, 26.5), 2),
         uniformity, particles, "PASS" if ok else "FAIL"))
    conn.commit()
    cur.close()
    conn.close()

    msg = ("✔ 试片合格：均匀度 %.2f%%，束流密度 %.3f mA，可启动工艺"
           % (uniformity, beam)) if ok else (
        "✘ 试片不合格：均匀度 %.2f%%（规格 ≤2.00%%），束流密度 %.3f mA 偏离，"
        "请在操作电脑上「一键重新调束」后继续试片" % (uniformity, beam))
    return jsonify({
        "pass": ok, "uniformity": uniformity, "beam_current": beam,
        "particles": particles, "lot": lot, "wafer_id": wafer_id,
        "result": "PASS" if ok else "FAIL", "message": msg,
        "checked_at": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/reticle_adjust", methods=["POST"])
def api_reticle_adjust():
    """一键重新调束：重标能量/剂量/束流密度（对应调束台的四极透镜与扫描线圈修正）。"""
    beam = round(random.uniform(2.45, 3.15), 3)
    energy = round(random.uniform(89.6, 90.4), 2)
    dose = round(1.2e13 * random.uniform(0.998, 1.002), 0)
    return jsonify({
        "ok": True, "beam_current": beam, "energy_kev": energy, "dose": dose,
        "adjust_count": 1,
        "message": "已重新调束：束流密度 %.3f mA / 能量 %.2f keV / 剂量 %.3e ions·cm⁻²" % (beam, energy, dose),
        "adjust_at": datetime.now().strftime("%H:%M:%S"),
    })


@app.route("/api/lot/close", methods=["POST"])
def api_lot_close():
    """一盒工艺结束：按「本盒开始时间 → 现在」的时间窗统计 → 写一条 lot 记录 → 返回停机报告。

    与旧实现的区别（修 3 个真问题）：
      1. 时间窗不再取「最近 20 片里最早一片」（可跨数小时），而是本盒 LOT_CTX.start_ts；
      2. 报警数按同一时间窗分别统计 WARN（报警）与 ERROR（宕机），不再混成一个数；
      3. 用唯一索引 uq_lot 做 upsert：同一盒反复点停机只会更新一条记录，不再刷出 4 条重复。
    """
    data = request.get_json(silent=True) or {}
    try:
        n = max(1, min(int(data.get("count", 20)), 100))
    except (TypeError, ValueError):
        n = 20
    mode = (data.get("mode") or "NORMAL").upper()
    if mode not in ("NORMAL", "FAST"):
        mode = "NORMAL"

    lot_id = (data.get("lot_id") or LOT_CTX.get("lot_id") or "").strip()
    win_start = None
    if lot_id and lot_id == LOT_CTX.get("lot_id"):
        win_start = LOT_CTX.get("start_ts")

    conn = db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    if win_start is None and lot_id:
        cur.execute("SELECT MIN(created_at) t FROM implant_wafer_records WHERE lot_id=%s", (lot_id,))
        win_start = cur.fetchone()["t"]

    if lot_id:
        cur.execute(
            "SELECT lot_id, wafer_id, process_result, uniformity_pct, created_at "
            "FROM implant_wafer_records WHERE lot_id=%s AND lot_id NOT LIKE 'PILOT%%' "
            "AND (%s IS NULL OR created_at >= %s) ORDER BY id ASC LIMIT 500",
            (lot_id, win_start, win_start))
        rows = cur.fetchall()
    else:
        cur.execute(
            "SELECT lot_id, wafer_id, process_result, uniformity_pct, created_at "
            "FROM implant_wafer_records WHERE lot_id NOT LIKE 'PILOT%%' "
            "ORDER BY id DESC LIMIT %s", (n,))
        rows = cur.fetchall()
        rows.reverse()
    if not rows:
        # 时间窗内没有晶圆：不是错误，而是「开了盒但一片都没产」（例如被报警拦住）
        # 仍要把会话收尾，避免遗留 RUNNING 会话
        if lot_id:
            cur.execute("UPDATE implant_lot_sessions SET state='ABORTED', end_ts=%s WHERE lot_id=%s",
                        (datetime.now(), lot_id))
            conn.commit()
        cur.close(); conn.close()
        return jsonify({"ok": False, "lot_id": lot_id, "wafer_count": 0,
                        "error": "本盒没有任何晶圆记录（可能被报警拦住未开工），会话已置 ABORTED"}), 200

    lot_id = lot_id or rows[0]["lot_id"] or ("LOT-" + datetime.now().strftime("%m%d%H%M%S"))
    wafer_count = len(rows)
    pass_count = sum(1 for r in rows if r["process_result"] == "PASS")
    uf_avg = round(sum(float(r["uniformity_pct"]) for r in rows) / wafer_count, 2)
    win_start = win_start or rows[0]["created_at"]
    win_end = datetime.now()

    # 同窗口内：报警(WARN) / 宕机(ERROR) 分开统计
    cur.execute(
        "SELECT SUM(alarm_level='WARN') w, SUM(alarm_level='ERROR') e, COUNT(*) n "
        "FROM implant_alarm_events WHERE start_time BETWEEN %s AND %s",
        (win_start, win_end))
    al = cur.fetchone()
    warn_cnt = int(al["w"] or 0)
    err_cnt = int(al["e"] or 0)
    alarm_count = int(al["n"] or 0)
    yield_pct = round(pass_count / wafer_count * 100, 1)
    note = ("%s 片 / 合格 %d / 良率 %.1f%% / 报警 %d 次 / 宕机 %d 次"
            % (wafer_count, pass_count, yield_pct, warn_cnt, err_cnt))
    if mode == "FAST":
        note += "（快速演示）"

    cur.execute(
        "INSERT INTO implant_lot_records "
        "(lot_id, machine_id, wafer_count, pass_count, yield_pct, uniformity_avg, "
        " alarm_count, alarm_warn, alarm_error, cycle_mode, note) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE machine_id=VALUES(machine_id), wafer_count=VALUES(wafer_count), "
        " pass_count=VALUES(pass_count), yield_pct=VALUES(yield_pct), "
        " uniformity_avg=VALUES(uniformity_avg), alarm_count=VALUES(alarm_count), "
        " alarm_warn=VALUES(alarm_warn), alarm_error=VALUES(alarm_error), "
        " cycle_mode=VALUES(cycle_mode), note=VALUES(note)",
        (lot_id, "IMP-MC-01", wafer_count, pass_count, yield_pct, uf_avg,
         alarm_count, warn_cnt, err_cnt, mode, note))
    conn.commit()
    # 会话收尾：批次记录写成功即把 lot_sessions 置 CLOSED（避免下次启动被当成「遗留批次」）
    try:
        cur.execute("UPDATE implant_lot_sessions SET state='CLOSED', end_ts=%s WHERE lot_id=%s",
                    (win_end, lot_id))
        conn.commit()
    except Exception as _e:
        print("[app] 会话收尾标记失败:", _e)
    cur.execute("SELECT id FROM implant_lot_records WHERE lot_id=%s", (lot_id,))
    rec = cur.fetchone()
    rec_id = rec["id"] if rec else None
    cur.close()
    conn.close()

    return jsonify({
        "ok": True, "id": rec_id, "lot_id": lot_id, "wafer_count": wafer_count,
        "pass_count": pass_count, "fail_count": wafer_count - pass_count,
        "yield_pct": yield_pct, "uniformity_avg": uf_avg,
        "alarm_count": alarm_count, "alarm_warn": warn_cnt, "alarm_error": err_cnt,
        "cycle_mode": mode,
        "window_start": win_start.strftime("%Y-%m-%d %H:%M:%S"),
        "closed_at": win_end.strftime("%Y-%m-%d %H:%M:%S"),
        "message": "批次 %s 停机报告：%s" % (lot_id, note),
    })


@app.route("/api/lot/records")
def api_lot_records():
    """最近批次记录（停机报告页「历史批次」用）；默认过滤掉已归档的早期压测批次。"""
    try:
        limit = max(1, min(int(request.args.get("limit", 5)), 50))
    except (TypeError, ValueError):
        limit = 5
    show_all = (request.args.get("all") or "") in ("1", "true", "yes")
    c = db()
    cur = c.cursor(pymysql.cursors.DictCursor)
    sql = ("SELECT lot_id, wafer_count, pass_count, yield_pct, uniformity_avg, "
           "alarm_count, alarm_warn, alarm_error, cycle_mode, note, archived, created_at "
           "FROM implant_lot_records ")
    if not show_all:
        sql += "WHERE archived=0 "
    sql += "ORDER BY id DESC LIMIT %s"
    cur.execute(sql, (limit,))
    rows = cur.fetchall()
    cur.close()
    c.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M:%S")
        if r.get("yield_pct") is not None:
            r["yield_pct"] = float(r["yield_pct"])
    return jsonify(rows)


@app.route("/api/machine/cmd", methods=["POST"])
def api_machine_cmd():
    """网页上的「启动工艺 / 停止工艺」→ 指令模拟器 run / stop。
    这样数据库里的晶圆加工记录只会在机台真正加工时增长。"""
    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip().lower()
    if action not in ("run", "stop"):
        return jsonify({"ok": False, "error": "action 只能是 run 或 stop"}), 400
    extra = {"source": data.get("source") or "web"}
    if data.get("lot_id"):
        extra["lot_id"] = data.get("lot_id")
    ok = publish_cmd(action, extra)
    return jsonify({"ok": ok, "action": action,
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/lot/start", methods=["POST"])
def api_lot_start():
    """一盒开工：生成批次号并下发模拟器。

    批次号由网页侧（=生产指挥侧）产生并整盒共用，不再让模拟器每批随机新编号
    （否则看板里会出现上千个「各 10 片」的假批次）。
    """
    data = request.get_json(silent=True) or {}
    try:
        total = max(1, min(int(data.get("total", 20)), 100))
    except (TypeError, ValueError):
        total = 20
    now = datetime.now()
    seq = (LOT_CTX.get("seq") or 0) + 1
    LOT_CTX["seq"] = seq
    lot_id = "LOT-%s-%02d" % (now.strftime("%m%d"), seq)
    LOT_CTX.update({"lot_id": lot_id, "start_ts": now, "total": total})
    # 批次上下文落库（修「Flask 重启/刷新后批次号丢失，晶圆记录变成孤儿」的根因）
    try:
        c = db()
        cur = c.cursor()
        cur.execute(
            "INSERT INTO implant_lot_sessions (lot_id, total, start_ts, state) "
            "VALUES (%s, %s, %s, 'RUNNING') "
            "ON DUPLICATE KEY UPDATE total=VALUES(total), start_ts=VALUES(start_ts), "
            "end_ts=NULL, state='RUNNING'",
            (lot_id, total, now))
        c.commit(); cur.close(); c.close()
    except Exception as e:
        print("[app] 批次会话落库失败:", e)
    ok = publish_cmd("run", {"source": "web-lot-start", "lot_id": lot_id})
    return jsonify({"ok": ok, "lot_id": lot_id, "total": total,
                    "start_ts": now.strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/lot/reset", methods=["POST"])
def api_lot_reset():
    """重新装盒：清空当前批次上下文并确保模拟器停线（网页侧同时回到「未通电」初始态）。"""
    old = LOT_CTX.get("lot_id")
    rec = _finalize_lot(old, "ABORTED", "重新装盒（批次中断收尾）") if old else None
    LOT_CTX.update({"lot_id": None, "start_ts": None})
    ok = publish_cmd("stop", {"source": "web-lot-reset"})
    return jsonify({"ok": ok, "cleared_lot": old, "finalized": rec,
                    "message": "已重新装盒：换新料盒，需重新上电→调束→试片"})


@app.route("/api/wafer/emit", methods=["POST"])
def api_wafer_emit():
    """网页每完成一片 → 让模拟器即时产出这 1 片，数据库产量与动画 1:1 对齐。

    这是解决「画面 11.7 秒/片、库里 5 秒/片」两个时钟不同步的接口。
    """
    data = request.get_json(silent=True) or {}
    lot_id = data.get("lot_id") or LOT_CTX.get("lot_id")
    ok = publish_cmd("emit", {"lot_id": lot_id, "seq": data.get("seq")})
    return jsonify({"ok": ok, "lot_id": lot_id,
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/alarm/ack", methods=["POST"])
def api_alarm_ack():
    """报警处理：操作员在操作电脑上「调整参数并继续」→ 解除 WARN 拦截、恢复传片。

    ④A：只关闭**这一条**报警（按 id 或 alarm_code 精确定位），不再把当时挂着的所有 WARN 一起关掉。
    """
    data = request.get_json(silent=True) or {}
    aid = data.get("alarm_id")
    acode = (data.get("alarm_code") or "").strip()
    ok = publish_cmd("warn_ack", {"source": "web-operator",
                                  "alarm_id": aid, "alarm_code": acode})
    closed = 0
    try:
        c = db()
        cur = c.cursor()
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if aid:
            closed = cur.execute(
                "UPDATE implant_alarm_events SET end_time=%s "
                "WHERE id=%s AND end_time IS NULL", (now_s, int(aid)))
        elif acode:
            closed = cur.execute(
                "UPDATE implant_alarm_events SET end_time=%s "
                "WHERE alarm_code=%s AND alarm_level='WARN' AND end_time IS NULL",
                (now_s, acode))
        c.commit(); cur.close(); c.close()
    except Exception as e:
        print("[app] alarm ack 落库失败:", e)
    msg = "参数已调整，恢复传片" if ok else "指令下发失败（模拟器离线？）"
    if not closed:
        msg += "（未匹配到待处理报警，未做关闭）"
    return jsonify({"ok": ok, "closed": closed, "alarm_id": aid, "alarm_code": acode,
                    "message": msg})


def _current_machine_state():
    """读取数据库里最新的机台状态（网页据此判断是否还在宕机）。"""
    try:
        c = db()
        cur = c.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT state FROM implant_machine_state ORDER BY state_time DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        c.close()
        return (row["state"] if row else "UNKNOWN")
    except Exception:
        return "UNKNOWN"


@app.route("/api/repair", methods=["POST"])
def api_repair():
    """宕机后「呼叫设备工程师」→ 下派工指令 → 等机台真的离开 DOWN 才回复成功。

    之前的实现只要 MQTT publish 没抛异常就回 {"ok": true, "state": "IDLE"}，
    模拟器没在跑时也会这么回 → 网页显示「检修完成」但机台永远不恢复（用户踩到的坑）。
    """
    data = request.get_json(silent=True) or {}
    engineer = data.get("engineer") or "EE-01 设备工程师"
    delivered = publish_cmd("repair", {"engineer": engineer})
    if not delivered:
        return jsonify({"ok": False, "delivered": False, "state": None,
                        "error": "MQTT 未连通（EMQX 未启动？）",
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    before = _current_machine_state()
    t0 = time.time()
    state = before
    changed = False
    waited = 0
    # 最多等 15 秒，等模拟器把状态从 DOWN 切回 IDLE
    while time.time() - t0 < 15.0:
        state = _current_machine_state()
        waited = int((time.time() - t0) * 1000)
        if state not in ("DOWN", "UNKNOWN"):
            changed = True
            break
        time.sleep(0.5)
    if changed:
        msg = "设备工程师 %s 已完成检修（%d 秒），请重新调束并试片后复产" % (engineer, max(1, waited // 1000))
    else:
        msg = "派工指令已下发，但机台 15 秒内仍为 DOWN：请确认模拟器进程在线（双击 start_demo.bat）"
    return jsonify({"ok": changed, "delivered": True, "state": state,
                    "state_before": before, "waited_ms": waited, "message": msg,
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


if __name__ == "__main__":
    _sweep_lot_sessions()
    print("离子注入工序数据看板 listening on http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, debug=False)