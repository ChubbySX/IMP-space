# -*- coding: utf-8 -*-
"""
离子注入机工艺事件模拟器（替代真实机台 SECS/GEM 数据源）
=========================================================
真实产线中，离子注入机通过 SECS/GEM 接口(SEMI E37/HSMS)把工艺数据上抛给
EAP/MES；本脚本在同一语义层模拟 IMP-MC-01（中束流离子注入机）的事件流：

  fab/implant/mc01/wafer/done   —— 每片晶圆注入完成事件（配方+工艺参数+结果）
  fab/implant/mc01/state        —— 机台状态变化（RUNNING/IDLE/DOWN/PM，E10 规范）
  fab/implant/mc01/alarm        —— 报警事件

用法：
  python implant_simulator.py                 # 默认产 10 片后退出
  python implant_simulator.py --wafers 5 --interval 1.5
  python implant_simulator.py --force-alarm   # 保证产生一条 ERROR 报警（演示用）
  python implant_simulator.py --loop          # 无限循环持续生产（演示/产线仿真，杀进程或 Ctrl+C 停止）
"""
import argparse
import io
import json
import random
import sys
import threading
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import paho.mqtt.client as mqtt

from db_config import (MQTT_CONFIG, TOPIC_WAFER_DONE, TOPIC_MACHINE_STATE,
                      TOPIC_ALARM, TOPIC_CMD)

MACHINE = "IMP-MC-01"

# ===== 生产闸门（由网页/后端通过 MQTT cmd 通道控制）=====
# PROD_RUN  clear → 机台停止加工，不再产出晶圆（数据库数量冻结）
# REPAIR_EVT set  → 设备工程师检修完成
PROD_RUN = threading.Event()          # 默认 clear：机台待机，等网页「启动束流」才开产（DB 数量随机台状态更新）
REPAIR_EVT = threading.Event()
# 距上次大故障已生产的片数（按片数触发故障，见 run_batch）
WAFERS_SINCE_ERROR = [0]
# 累计产片数（报警按片数触发：加工 5-10 片报一次，见 alarm_manager）
WAFERS_TOTAL = [0]
# 宕机事件句柄（列表包装，便于在回调函数里共享同一个 threading.Event）
MACHINE_DOWN = [None]

# ===== 事件驱动节拍（2026-10-30）=====
# 网页「一盒 20 片」每走完一片就通过 cmd 通道请求产 1 片（action=emit），
# 这样数据库的晶圆记录与页面动画严格 1:1，不再出现「画面 11.7s/片、库里 5s/片」。
WAFER_REQ = [0]                      # 待产片请求计数：网页 emit 一次 +1、产一片 -1（1:1，不丢不合并）
WARN_HOLD = threading.Event()       # WARN 报警未处理（未调参）→ 停止传片
WARN_ACK = threading.Event()        # 网页点了「调整参数并继续」→ 结束当前 WARN
LOT_ID = [""]                       # 当前批次号（由网页下发，整盒共用）
WAFER_SEQ = [0]                     # 当前批次内已产片数
AUTO_PACE = [True]                  # True=按 --interval 自动节拍；False=网页驱动（收到 emit 才产片）


def _pub_state(client, state, reason):
    """向 state 主题发布机台状态（网页/看板据此显示）。

    注意：本函数也会在 MQTT 回调线程里被调用，此时【不能】用 wait_for_publish()
    —— 实际发包要靠同一条网络线程，回调里等它完成会自锁（曾导致指令收到后整机卡死）。
    """
    try:
        client.publish(TOPIC_MACHINE_STATE,
                       json.dumps({"machine_id": MACHINE, "state": state,
                                   "reason": reason, "state_time": now_iso()}), qos=0)
    except Exception as e:
        print("[sim] state 发布失败: %s" % e)


def cmd_on_message(client, userdata, msg):
    """接收后端下发指令：run / stop / emit / warn_ack / repair / lot。"""
    print("[sim] 收到 MQTT 消息 %s: %s" % (msg.topic, msg.payload[:80]))
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception:
        return
    action = (payload.get("action") or "").strip().lower()
    if action == "run":
        # 宕机期间拒绝开工：否则会把机台状态刷成 RUNNING，导致看板误以为已恢复、
        # 运维也不会去点「呼叫设备工程师」（曾真实踩到：气体泄漏后仍显示 RUNNING 且在制）。
        if MACHINE_DOWN[0].is_set():
            _pub_state(client, "DOWN", "机台宕机中，需先呼叫设备工程师检修")
            print("[sim] 收到指令 run 但机台处于宕机状态 → 拒绝开工，请先检修")
            return
        lot = (payload.get("lot_id") or "").strip()
        if lot:
            LOT_ID[0] = lot
            WAFER_SEQ[0] = 0
        AUTO_PACE[0] = False          # 网页驱动节拍：等 emit
        WAFER_REQ[0] = 0              # 新批次从零开始（清掉上一批的残留请求）
        PROD_RUN.set()
        _pub_state(client, "RUNNING", "网页启动束流 → 开始加工（批次 %s，Web 驱动节拍）" % (LOT_ID[0] or "-"))
        print("[sim] 收到指令 run → 开始加工，批次=%s（等网页 emit 逐片产出）" % (LOT_ID[0] or "-"))
    elif action == "stop":
        PROD_RUN.clear()
        WAFER_REQ[0] = 0              # 停线即清空待产请求，避免停机后补产
        _pub_state(client, "IDLE", "网页停止工艺/关闭束流 → 暂停产出（数量冻结）")
        print("[sim] 收到指令 stop → 停止加工（数量冻结，清空待产请求）")
    elif action == "emit":
        # 网页一片完成 → 请求机台产出这一片的工艺事件（计数式：请求不丢、不合并）
        if payload.get("lot_id"):
            LOT_ID[0] = payload.get("lot_id")
        WAFER_REQ[0] += 1
        print("[sim] 收到指令 emit → 待产请求 +1（当前待产 %d，批次 %s）" % (WAFER_REQ[0], LOT_ID[0] or "-"))
    elif action == "warn_ack":
        print("[sim] 收到指令 warn_ack → 参数已调整，恢复传片")
        WARN_ACK.set()
    elif action == "repair":
        print("[sim] 收到指令 repair → 设备工程师检修")
        REPAIR_EVT.set()

RECIPES = [
    ("IM-NLDD-P30",    "P",  30.0, 1.0e13, 7.0,  4.0, 1.45),
    ("IM-PWEL-B180",   "B", 180.0, 5.0e14, 0.0,  3.2, 1.60),
    ("IM-SD-AS70",     "As", 70.0, 3.0e15, 7.0,  5.0, 1.50),
    ("IM-HALO-BF2-90", "BF2", 90.0, 1.2e13, 25.0, 2.6, 1.75),
]

# ===== 报警类型库 =====
# WARN：小故障预警，操作员上手电脑调参数即可恢复（不停机）
# ERROR：大故障宕机，需停机维护
ALARM_TYPES = [
    # WARN — 7 种
    ("AIM-BEAM-WARN",   "WARN",  "束流轻微波动 ±5%，参数微调中"),
    ("AIM-VAC-WARN",    "WARN",  "真空度偏高 0.3mTorr，已调节节流阀"),
    ("AIM-TEMP-WARN",   "WARN",  "冷却水温偏高 2°C，已加大冷却流量"),
    ("AIM-DOSE-WARN",   "WARN",  "法拉第杯剂量读数偏低 3%，已校准"),
    ("AIM-PRESS-WARN",  "WARN",  "腔体压力波动，已稳定"),
    ("AIM-ESC-WARN",    "WARN",  "静电卡盘电压微漂，已补偿"),
    ("AIM-COOL-WARN",   "WARN",  "冷却水流量偏低，已调节泵速"),
    # ERROR — 11 种（宕机）
    ("AIM-BEAM-UNST",   "ERROR", "束流波动超 10%，注入中止，需停机检查"),
    ("AIM-VAC-LEAK",    "ERROR", "真空腔体泄漏，需停机检漏"),
    ("AIM-HANDLER-JAM", "ERROR", "晶圆传输机械手卡死，需停机处理"),
    ("AIM-POWER-FAULT", "ERROR", "高压电源模块故障，需停机更换"),
    ("AIM-COOL-FAIL",   "ERROR", "冷却系统泵故障，温控失效，需停机维修"),
    ("AIM-TURBO-FAIL",  "ERROR", "涡轮分子泵转速异常跌落，需停机更换轴承"),
    ("AIM-FILAMENT",    "ERROR", "离子源灯丝断路，需停机开腔更换灯丝"),
    ("AIM-GAS-LEAK",    "ERROR", "工艺气体管路泄漏，需停机处理并复检"),
    ("AIM-INTERLOCK",   "ERROR", "安全联锁触发（防护门异常），需停机复位"),
    ("AIM-ESD-FAULT",   "ERROR", "静电卡盘高压打火，需停机清洁并更换绝缘件"),
    ("AIM-ROBOT-ENC",   "ERROR", "机械手编码器失步，需停机重新标定"),
]

# ===== WARN 报警的「部件 / 参数」指引 =====
# 用户要求：报警的处理方式是「停止传片 → 找到部件参数问题 → 调整参数 → 继续传片」。
# 每条 WARN 都带：部件名、参数名、当前值 → 目标值、单位，网页据此显示「调参向导」。
WARN_DETAIL = {
    "AIM-BEAM-WARN":  ("离子源 / 束流光学", "弧电流 Arc Current",      12.4, 13.1, "A"),
    "AIM-VAC-WARN":   ("真空系统 / 分子泵",  "节流阀开度",             38.0, 44.0, "%"),
    "AIM-TEMP-WARN":  ("冷却系统 / 水温",    "冷却水流量",             11.2, 13.0, "L/min"),
    "AIM-DOSE-WARN":  ("法拉第杯 / 剂量计",  "剂量标定系数",            0.972, 1.000, "×"),
    "AIM-PRESS-WARN": ("工艺腔体 / 压力",    "腔体压力设定",            2.60, 2.40, "mTorr"),
    "AIM-ESC-WARN":   ("静电卡盘 / 高压",    "卡盘吸附电压",            2.55, 2.70, "kV"),
    "AIM-COOL-WARN":  ("冷却系统 / 循环泵",  "循环泵转速",              62.0, 70.0, "%"),
}


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def gauss(mu, sigma, lo, hi):
    v = random.gauss(mu, sigma)
    return max(lo, min(hi, v))


def gen_wafer(lot_id, slot):
    name, species, energy, dose, tilt, beam, u_mean = random.choice(RECIPES)
    uniform = round(gauss(u_mean, 0.2, 0.9, 4.2), 2)
    particles = int(gauss(14, 8, 0, 200))
    if random.random() < 0.04:
        particles = random.randint(55, 90)
    if random.random() < 0.06:
        uniform = round(random.uniform(2.6, 3.2), 2)
    result = "PASS" if (uniform <= 2.5 and particles <= 50) else "FAIL"
    beam_cur = round(gauss(beam, 0.35, 0.5, 8.0), 3)
    t_impl = round(dose * 706.9 / (beam_cur * 6.24e15) + random.uniform(-2, 3), 1)
    return {
        "machine_id": MACHINE, "lot_id": lot_id, "wafer_id": "%s-%02d" % (lot_id, slot),
        "slot_no": slot, "recipe_name": name, "species": species, "energy_kev": energy,
        "dose_cm2": dose, "beam_current_ma": beam_cur, "tilt_deg": tilt,
        "twist_deg": round(random.uniform(0, 30), 2), "implant_time_s": max(3.0, t_impl),
        "chamber_pressure_torr": round(random.uniform(1.5e-5, 4.0e-5), 7),
        "esc_voltage_v": round(random.uniform(1200, 1450), 1),
        "wafer_temp_c": round(22 + energy / 30.0 + random.uniform(-1.5, 3.0), 2),
        "uniformity_pct": uniform, "particles_added": particles,
        "process_result": result, "created_at": now_iso(),
    }


def _raise_error(client, args, machine_down, code, message):
    """触发一次大故障（宕机）：报警 + DOWN + 冻结生产 + 等设备工程师检修 + 恢复 IDLE。

    返回 True 表示已检修完成、可继续生产。
    """
    print("[sim] %s 报警 ERROR %s: %s → 机台 DOWN（等待设备工程师检修）" % (
        now_iso(), code, message))
    try:
        client.publish(TOPIC_ALARM, json.dumps({
            "machine_id": args.machine, "alarm_code": code, "alarm_level": "ERROR",
            "message": message, "start_time": now_iso()})).wait_for_publish()
    except Exception as e:
        print("[sim] ERROR 报警发布失败: %s" % e)
    machine_down.set()
    PROD_RUN.clear()                       # 冻结生产：数据库晶圆数不再增长
    REPAIR_EVT.clear()
    _pub_state(client, "DOWN", message)
    # 等后端下发 repair（网页：呼叫设备工程师 → 检修完成）
    while not REPAIR_EVT.is_set():
        time.sleep(0.3)
    machine_down.clear()
    # 检修完成不自动复产：必须重新调束 + 试片，再由网页下发 run
    _pub_state(client, "IDLE", "检修完成，等待重新调束/试片")
    print("[sim] %s 检修完成 → IDLE（等待重新调束+试片后复产）" % now_iso())
    return True


def produce_wafer(client, args, slot):
    """产出 1 片晶圆事件（发布时间戳由 now_iso 生成，供 to_db 落库）。"""
    lot = LOT_ID[0] or ("LOT-%05d" % random.randint(90000, 99999))
    w = gen_wafer(lot, slot)
    client.publish(TOPIC_WAFER_DONE, json.dumps(w)).wait_for_publish()
    flag = "OK " if w["process_result"] == "PASS" else "FAIL"
    print("[sim] %s 片%02d %s %s %s %.2fkeV dose=%.3E u=%.2f%% beam=%.3fmA" % (
        now_iso(), slot, flag, w["species"], w["recipe_name"], w["energy_kev"],
        w["dose_cm2"], w["uniformity_pct"], w["beam_current_ma"]))
    return w


def run_batch(client, args, machine_down):
    """生产循环。

    节拍两种模式：
      - 网页驱动（默认 --loop）：网页「一盒 20 片」每走完一片下发 emit，本机就产 1 片，
        数据库产量与页面动画严格 1:1；
      - 自动节拍（--auto-pace 或单次模式）：按 --interval 秒/片自动产。
    闸门：machine_down（宕机）/ PROD_RUN（网页 run-stop）/ WARN_HOLD（报警未调参）任一拦住就不产片。
    """
    lot_id = LOT_ID[0]
    # 严格节拍：网页未启动束流（PROD_RUN clear）或机台宕机时，不进入生产、不发布 RUNNING
    while machine_down.is_set() or not PROD_RUN.is_set():
        time.sleep(0.5)
        lot_id = LOT_ID[0] or lot_id
    if not lot_id:
        lot_id = "LOT-%05d" % random.randint(90000, 99999)
        LOT_ID[0] = lot_id
    client.publish(TOPIC_MACHINE_STATE,
                   json.dumps({"machine_id": args.machine, "state": "RUNNING",
                               "reason": "正常生产, 批次 %s" % lot_id, "state_time": now_iso()})).wait_for_publish()
    print("[sim] %s 状态 RUNNING 批次 %s（%s）" % (
        now_iso(), lot_id, "自动节拍 %.1fs/片" % args.interval if AUTO_PACE[0] else "网页驱动节拍"))

    while True:
        if not PROD_RUN.is_set() or machine_down.is_set():
            return
        if WARN_HOLD.is_set():
            # WARN 报警未调参 → 停止传片（用户要求：报警=停止传片→调参→继续）
            time.sleep(0.3)
            continue
        if AUTO_PACE[0]:
            time.sleep(args.interval)
            if not PROD_RUN.is_set() or machine_down.is_set() or WARN_HOLD.is_set():
                continue
        else:
            # 网页驱动节拍：等「待产请求」，按请求数 1:1 产出（不丢、不合并）
            waited = 0.0
            while WAFER_REQ[0] <= 0 and waited < 0.3:
                if not PROD_RUN.is_set() or machine_down.is_set():
                    return
                time.sleep(0.05)
                waited += 0.05
            if WAFER_REQ[0] <= 0:
                continue
            # 有请求但闸门被拦（报警/宕机/停线）→ 请求保留，恢复后继续补产
            if not PROD_RUN.is_set() or machine_down.is_set() or WARN_HOLD.is_set():
                continue
            WAFER_REQ[0] -= 1

        WAFER_SEQ[0] += 1
        produce_wafer(client, args, WAFER_SEQ[0])

        # ===== 故障率：按产片数触发（默认每 10 片一次大故障），而不是按时间随机 =====
        WAFERS_SINCE_ERROR[0] += 1
        WAFERS_TOTAL[0] += 1          # 报警节拍按累计片数推进（见 alarm_manager）
        every = max(1, int(getattr(args, "error_every", 10)))
        if WAFERS_SINCE_ERROR[0] >= every:
            WAFERS_SINCE_ERROR[0] = 0
            code, level, message = random.choice(
                [a for a in ALARM_TYPES if a[1] == "ERROR"])
            _raise_error(client, args, machine_down, code, message)
            # 检修完成后，本次工艺按「刚开机」重来：等网页重新调束+试片再开产
            print("[sim] 检修完成，等待重新调束/试片后继续生产")
            while machine_down.is_set() or not PROD_RUN.is_set():
                time.sleep(0.5)

        if getattr(args, "wafers", 0) and not getattr(args, "loop", False) \
                and WAFER_SEQ[0] >= args.wafers:
            break

    client.publish(TOPIC_MACHINE_STATE,
                   json.dumps({"machine_id": args.machine, "state": "IDLE",
                               "reason": "批次 %s 完成" % lot_id, "state_time": now_iso()})).wait_for_publish()
    print("[sim] %s 批次 %s 完成，共产出 %d 片" % (now_iso(), lot_id, WAFER_SEQ[0]))


def alarm_manager(client, args, machine_down, stop_event):
    """后台线程：WARN 报警改为「按产片数」触发（加工 5-10 片一次），不再按秒随机。
    WARN：发布后停止传片，等操作员手动调参（20 分钟超时兜底），然后继续传片。
    ERROR（大故障宕机）由 run_batch 按产片数触发（--error-every，默认每 10 片一次）。
    --force-error 时第一次报警确定性走一遍 ERROR。"""
    warn_every = max(0, int(getattr(args, "alarm_every", 0) or 0))

    def _next_gap():
        # --alarm-every N 固定 N 片一次；否则 5-10 片随机一次（用户要求降频）
        return warn_every if warn_every > 0 else random.randint(5, 10)

    warns = [a for a in ALARM_TYPES if a[1] == "WARN"]
    errors = [a for a in ALARM_TYPES if a[1] == "ERROR"]

    gap = _next_gap()
    next_at = WAFERS_TOTAL[0] + gap
    print("[sim] 报警节拍：每 %s 片一次（WARN 小故障；ERROR 每 %s 片）" % (
        ("%d" % warn_every) if warn_every > 0 else "5-10",
        getattr(args, "error_every", 10)))

    while not stop_event.is_set():
        # 等到「再产 gap 片」才报一次警（产线没开工就不报）
        while not stop_event.is_set() and WAFERS_TOTAL[0] < next_at:
            time.sleep(0.2)
        if stop_event.is_set():
            return

        if getattr(args, "force_error", False):
            # 验收/演示用：第一次报警强制为 ERROR，确定性走一遍宕机→检修→重调
            args.force_error = False
            code, level, message = random.choice(errors)
            _raise_error(client, args, machine_down, code, message)
            gap = _next_gap()
            next_at = WAFERS_TOTAL[0] + gap
            continue

        code, level, message = random.choice(warns)
        start_time = now_iso()
        comp, param, cur_v, tgt_v, unit = WARN_DETAIL.get(code, ("机台", "参数", 0, 0, ""))
        al = {"machine_id": args.machine, "alarm_code": code,
              "alarm_level": level, "message": message, "start_time": start_time,
              # 供网页显示「哪台部件、哪个参数、从多少调到多少」
              "component": comp, "param_name": param, "param_from": cur_v,
              "param_to": tgt_v, "param_unit": unit}
        client.publish(TOPIC_ALARM, json.dumps(al)).wait_for_publish()

        # 用户要求：报警 → 停止传片 → 操作员手动找参数调参 → 调整完成 → 继续传片
        # 注意：这里必须一直等操作员手动调参（不再有「30 秒自动调完」的兜底，
        #       否则现场没人操作时也会自己恢复，等于跳过手动流程）
        WARN_HOLD.set()
        WARN_ACK.clear()
        print("[sim] %s 报警 WARN %s: %s → 停止传片（部件=%s 参数=%s %.3g→%.3g%s），等操作员手动调参" % (
            now_iso(), code, message, comp, param, cur_v, tgt_v, unit))
        # ⑤A：保留「必须手动调参」，但加 20 分钟超时兜底 —— 现场人走了不能让产线永久卡死；
        #      超时恢复会在日志与报警消息里注明「超时自动调参」，便于追溯责任。
        WARN_TIMEOUT = 1200.0          # 20 分钟
        waited = 0.0
        timed_out = False
        while not WARN_ACK.is_set() and not stop_event.is_set():
            time.sleep(0.2)
            waited += 0.2
            if waited >= WARN_TIMEOUT:
                timed_out = True
                break
            if abs(waited % 30.0) < 0.2:      # 每 30 秒提示一次仍在等待
                print("[sim] %s 仍在等待手动调参（已等 %d 秒 / 超时 %d 秒）：%s %s" % (
                    now_iso(), int(waited), int(WARN_TIMEOUT), comp, param))
        acked = WARN_ACK.is_set()
        WARN_HOLD.clear()
        WARN_ACK.clear()
        if timed_out:
            print("[sim] %s 警告：等待手动调参超过 %.0f 分钟 → 超时自动调参（已记入日志）" % (
                now_iso(), WARN_TIMEOUT / 60.0))
        recovery = {"machine_id": args.machine, "alarm_code": code,
                    "alarm_level": level, "message": message,
                    "start_time": start_time, "end_time": now_iso(),
                    "recovered_by": ("operator" if acked else
                                     ("timeout" if timed_out else "sim-stop"))}
        client.publish(TOPIC_ALARM, json.dumps(recovery)).wait_for_publish()
        print("[sim] %s WARN %s 已恢复（%s，等待 %.0f 秒），继续传片" % (
            now_iso(), code,
            "操作员手动调参完成" if acked else ("超时自动调参" if timed_out else "模拟器停止"),
            waited))

        # 下次报警：再产 5-10 片（--alarm-every N 时固定 N 片）
        gap = _next_gap()
        next_at = WAFERS_TOTAL[0] + gap
        print("[sim] 下次报警：再过 %d 片（当前累计 %d 片）" % (gap, WAFERS_TOTAL[0]))


def main():
    ap = argparse.ArgumentParser(description="离子注入机工艺事件模拟器")
    ap.add_argument("--machine", default=MACHINE)
    ap.add_argument("--wafers", type=int, default=10, help="每个批次模拟生产的晶圆片数")
    ap.add_argument("--interval", type=float, default=5.0, help="每片间隔秒数（演示默认 5 秒/片）")
    ap.add_argument("--force-alarm", action="store_true", help="单次模式结束后强制产出一条 ERROR 报警")
    ap.add_argument("--loop", action="store_true", help="无限循环持续生产（数据源常驻，杀进程或 Ctrl+C 停止）")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-alarm", action="store_true",
                    help="不启动随机报警线程（自动化验收用：让流程可复现，避免随机 ERROR 宕机打断验证）")
    ap.add_argument("--error-every", type=int, default=10,
                    help="每生产多少片触发一次大故障（宕机），默认 10 片")
    ap.add_argument("--alarm-every", type=int, default=0,
                    help="WARN 小故障节拍：每生产多少片报一次；0=随机 5-10 片一次（默认，已降频）")
    ap.add_argument("--force-error", action="store_true",
                    help="第一次报警强制为 ERROR（演示/验收：确定性走一遍宕机→呼叫检修→重调束流程）")
    ap.add_argument("--auto-pace", action="store_true",
                    help="按 --interval 自动节拍产片（默认在 --loop 下改为「网页驱动」：收到 emit 才产 1 片）")
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    # 网页驱动节拍：--loop 下默认关闭自动节拍，由网页逐片 emit 触发，保证 DB 产量与动画 1:1
    AUTO_PACE[0] = bool(args.auto_pace) or (not args.loop)

    client = mqtt.Client(client_id="implant-sim-mc01")
    client.on_message = cmd_on_message

    def _on_connect(c, u, flags, rc):
        print("[sim] on_connect rc=%s → 重新订阅 %s" % (rc, TOPIC_CMD))
        try:
            c.subscribe(TOPIC_CMD, qos=1)
        except Exception as e:
            print("[sim] 订阅失败: %s" % e)

    def _on_disconnect(c, u, rc):
        print("[sim] on_disconnect rc=%s（将自动重连）" % rc)

    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.connect(MQTT_CONFIG["host"], MQTT_CONFIG["port"], keepalive=60)
    client.loop_start()
    print("[sim] 已连接 EMQX %s:%d，开始模拟 %s 生产（指令通道 %s 订阅由 on_connect 完成）" % (
        MQTT_CONFIG["host"], MQTT_CONFIG["port"], args.machine, TOPIC_CMD))

    if args.loop:
        machine_down = threading.Event()
        MACHINE_DOWN[0] = machine_down   # 供 MQTT 回调（run 指令）判断是否宕机中
        stop_event = threading.Event()
        # 待机态：等网页「启动束流」下发 run 后才开产（数据库数量随机台状态更新）
        _pub_state(client, "IDLE", "机台待机，等待网页启动束流/工艺")
        # 启动报警管理线程（按产片数触发：WARN 每 5-10 片一次 / ERROR 每 --error-every 片）
        if getattr(args, "no_alarm", False):
            print("[sim] --no-alarm：随机报警线程已关闭（自动化验收模式）")
        else:
            alarm_thread = threading.Thread(
                target=alarm_manager, args=(client, args, machine_down, stop_event), daemon=True)
            alarm_thread.start()
        print("[sim] 无限循环模式：网页驱动节拍（emit 一片产一片）。报警按片数触发（WARN 每 %s 片一次），"
              "WARN=停止传片等操作员手动调参（20 分钟超时兜底）/ ERROR=停机等待设备工程师检修"
              % (("%d" % args.alarm_every) if getattr(args, "alarm_every", 0) else "5-10"))
        try:
            while True:
                run_batch(client, args, machine_down)
                time.sleep(2.0)
        except KeyboardInterrupt:
            stop_event.set()
            print("[sim] 收到退出信号，停止模拟")
    else:
        run_batch(client, args, threading.Event())
        if args.force_alarm:
            al = {"machine_id": args.machine, "alarm_code": "AIM-BEAM-UNST", "alarm_level": "ERROR",
                  "message": "束流波动超 10%，注入中止，机台停机检查", "start_time": now_iso()}
            client.publish(TOPIC_ALARM, json.dumps(al)).wait_for_publish()
            client.publish(TOPIC_MACHINE_STATE,
                           json.dumps({"machine_id": args.machine, "state": "DOWN",
                                       "reason": "束流不稳停机", "state_time": now_iso()})).wait_for_publish()
            print("[sim] 报警 ERROR AIM-BEAM-UNST → 机台 DOWN")
        print("[sim] 模拟结束，共产出 %d 片晶圆事件" % args.wafers)

    client.loop_stop()


if __name__ == "__main__":
    main()
