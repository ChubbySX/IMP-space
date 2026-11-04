# -*- coding: utf-8 -*-
"""
MQTT → MySQL 落库服务（对应真实产线中的 EAP 数据收集模块）
=========================================================
订阅离子注入机的事件流（wafer/done、state、alarm），解析 JSON 后
写入 fab_implant 库三张表。常驻运行：
  python implant_to_db.py
"""
import io
import json
import sys
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import paho.mqtt.client as mqtt
import pymysql

from db_config import DB_CONFIG, MQTT_CONFIG, TOPIC_WAFER_DONE, TOPIC_MACHINE_STATE, TOPIC_ALARM

_SQL_WAFER = (
    "INSERT INTO implant_wafer_records "
    "(machine_id,lot_id,wafer_id,slot_no,recipe_name,species,energy_kev,dose_cm2,"
    "beam_current_ma,tilt_deg,twist_deg,implant_time_s,chamber_pressure_torr,esc_voltage_v,"
    "wafer_temp_c,uniformity_pct,particles_added,process_result,created_at) "
    "VALUES (%(machine_id)s,%(lot_id)s,%(wafer_id)s,%(slot_no)s,%(recipe_name)s,%(species)s,"
    "%(energy_kev)s,%(dose_cm2)s,%(beam_current_ma)s,%(tilt_deg)s,%(twist_deg)s,%(implant_time_s)s,"
    "%(chamber_pressure_torr)s,%(esc_voltage_v)s,%(wafer_temp_c)s,%(uniformity_pct)s,"
    "%(particles_added)s,%(process_result)s,%(created_at)s)"
)
_SQL_STATE = (
    "INSERT INTO implant_machine_state (machine_id,state,reason,state_time) "
    "VALUES (%(machine_id)s,%(state)s,%(reason)s,%(state_time)s)"
)
_SQL_ALARM = (
    "INSERT INTO implant_alarm_events "
    "(machine_id,alarm_code,alarm_level,message,start_time,end_time,component_tag,"
    "param_name,param_from,param_to,param_unit,param_fix) "
    "VALUES (%(machine_id)s,%(alarm_code)s,%(alarm_level)s,%(message)s,%(start_time)s,%(end_time)s,"
    "%(component_tag)s,%(param_name)s,%(param_from)s,%(param_to)s,%(param_unit)s,%(param_fix)s)"
)


_prev_state = {}  # machine_id → 上一次 state，用于检测 DOWN→RUNNING 恢复


def main():
    conn = pymysql.connect(**DB_CONFIG)

    def on_message(client, userdata, msg):
        topic = msg.topic
        try:
            d = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            print("[db] 解析失败 %s: %s" % (topic, e))
            return
        try:
            cur = conn.cursor()
            if topic == TOPIC_WAFER_DONE:
                cur.execute(_SQL_WAFER, d)
                # 收到新晶圆即自动恢复该机台未关闭的 WARN 报警（瞬态剂量告警随下一片良品清除；ERROR 保持需人工恢复）
                cur.execute(
                    "UPDATE implant_alarm_events SET end_time=%s "
                    "WHERE machine_id=%s AND alarm_level='WARN' AND end_time IS NULL",
                    (d.get("created_at"), d.get("machine_id")))
                print("[db] 落库 wafer %s (%s %s %.2fkeV u=%.2f%%)" % (
                    d.get("wafer_id"), d.get("species"), d.get("recipe_name"),
                    d.get("energy_kev", 0), d.get("uniformity_pct", 0)))
            elif topic == TOPIC_MACHINE_STATE:
                cur.execute(_SQL_STATE, d)
                mid = d.get("machine_id")
                prev = _prev_state.get(mid)
                # DOWN → 非 DOWN（IDLE 检修完成 / RUNNING 直接复产）：关闭该机台所有未关闭报警
                if prev == "DOWN" and d.get("state") != "DOWN":
                    cur.execute(
                        "UPDATE implant_alarm_events SET end_time=%s "
                        "WHERE machine_id=%s AND end_time IS NULL",
                        (d.get("state_time"), mid))
                    print("[db] 宕机解除（%s），关闭所有未关闭报警" % d.get("state"))
                _prev_state[mid] = d.get("state")
                print("[db] 落库 state %s -> %s" % (mid, d.get("state")))
            elif topic == TOPIC_ALARM:
                d.setdefault("end_time", None)
                if d.get("end_time"):
                    # 恢复消息：关闭匹配的未关闭报警（而非新增记录）
                    cur.execute(
                        "UPDATE implant_alarm_events SET end_time=%s "
                        "WHERE machine_id=%s AND alarm_code=%s AND end_time IS NULL",
                        (d["end_time"], d.get("machine_id"), d.get("alarm_code")))
                    print("[db] 恢复 alarm %s" % d.get("alarm_code"))
                else:
                    # 报警：额外落「哪台部件 / 哪个参数怎么调」供网页调参向导使用
                    comp = d.get("component")
                    pf = ""
                    if d.get("param_name"):
                        pf = "%s %.3g→%.3g%s" % (
                            d.get("param_name"), d.get("param_from") or 0,
                            d.get("param_to") or 0, d.get("param_unit") or "")
                    d["component_tag"] = comp
                    d["param_fix"] = pf or None
                    # 结构化参数（网页调参向导要分字段显示：参数名 / 当前值 → 目标值 单位）
                    d["param_name"] = d.get("param_name") or None
                    d["param_from"] = None if d.get("param_from") is None else ("%.3g" % d["param_from"])
                    d["param_to"] = None if d.get("param_to") is None else ("%.3g" % d["param_to"])
                    d["param_unit"] = d.get("param_unit") or None
                    cur.execute(_SQL_ALARM, d)
                    print("[db] 落库 alarm [%s] %s @%s" % (
                        d.get("alarm_level"), d.get("alarm_code"), comp or "-"))
            else:
                print("[db] 未处理主题 %s" % topic)
                return
            conn.commit()
            cur.close()
        except Exception as e:
            print("[db] 写入失败: %s" % e)
            conn.rollback()

    client = mqtt.Client(client_id="implant-to-db")
    client.on_message = on_message
    client.connect(MQTT_CONFIG["host"], MQTT_CONFIG["port"], keepalive=60)
    for t in (TOPIC_WAFER_DONE, TOPIC_MACHINE_STATE, TOPIC_ALARM):
        client.subscribe(t)
    print("[db] 已订阅 %s / %s / %s，等待事件..." % (TOPIC_WAFER_DONE, TOPIC_MACHINE_STATE, TOPIC_ALARM))
    client.loop_forever()


if __name__ == "__main__":
    main()