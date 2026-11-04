# -*- coding: utf-8 -*-
"""
历史数据回填：生成过去 7 天的离子注入生产数据（约 200 片晶圆）
用于让数据看板一打开就有完整的趋势图与统计。

数据语义（中束流离子注入机 IMP-MC-01）：
- 每天两班（08:00-12:00, 13:00-20:00），每班处理约 14~15 片 → 每天约 28~29 片
- 4 个常用配方（NLDD 低剂量浅结 / P-Well 深结 / S/D 源漏重掺杂 / HALO 晕环）
- 均匀度规格 <=2.5%，颗粒增量规格 <=50；超规格记 FAIL（判 OOC）
- 机台状态：RUNNING / IDLE / DOWN / PM（E10 设备状态规范）
- 报警：与 DOWN 时段对应的 ERROR 报警 + 若干 WARN 报警
"""
import io
import random
import sys
import time
from datetime import datetime, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import pymysql
from db_config import DB_CONFIG

random.seed(42)  # 可复现

MACHINE = "IMP-MC-01"

# 配方表：(recipe, species, energy_kev, dose_cm2, tilt, beam均值, 均匀度均值)
RECIPES = [
    ("IM-NLDD-P30",   "P",   30.0, 1.0e13, 7.0,  4.0, 1.45),
    ("IM-PWEL-B180",  "B",  180.0, 5.0e14, 0.0,  3.2, 1.60),
    ("IM-SD-AS70",    "As",  70.0, 3.0e15, 7.0,  5.0, 1.50),
    ("IM-HALO-BF2-90","BF2", 90.0, 1.2e13, 25.0, 2.6, 1.75),
]


def gauss(mu, sigma, lo, hi):
    v = random.gauss(mu, sigma)
    return max(lo, min(hi, v))


def gen_wafer(recipe, lot_id, slot, ts):
    name, species, energy, dose, tilt, beam, u_mean = recipe
    uniform = round(gauss(u_mean, 0.22, 0.9, 4.2), 2)
    particles = int(gauss(14, 8, 0, 200))
    if random.random() < 0.02:
        particles = random.randint(55, 90)   # 偶发颗粒超标
    if random.random() < 0.05:
        uniform = round(random.uniform(2.6, 3.2), 2)  # 偶发均匀度漂移
    result = "PASS" if (uniform <= 2.5 and particles <= 50) else "FAIL"
    beam_cur = round(gauss(beam, 0.4, 0.5, 8.0), 3)
    p = round(random.uniform(1.5e-5, 4.0e-5), 7)
    esc = round(random.uniform(1200, 1450), 1)
    temp = round(22 + energy / 30.0 + random.uniform(-1.5, 3.0), 2)
    t_impl = round(dose * 706.9 / (beam_cur * 6.24e15) + random.uniform(-2, 3), 1)  # 300mm 晶圆面积 706.9cm²
    t_impl = max(3.0, round(t_impl, 1))
    return {
        "machine_id": MACHINE, "lot_id": lot_id, "wafer_id": "%s-%02d" % (lot_id, slot),
        "slot_no": slot, "recipe_name": name, "species": species, "energy_kev": energy,
        "dose_cm2": dose, "beam_current_ma": beam_cur, "tilt_deg": tilt,
        "twist_deg": round(random.uniform(0, 30), 2), "implant_time_s": t_impl,
        "chamber_pressure_torr": p, "esc_voltage_v": esc, "wafer_temp_c": temp,
        "uniformity_pct": uniform, "particles_added": particles,
        "process_result": result, "created_at": ts,
    }


def main():
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    now = datetime.now().replace(microsecond=0)

    wafers, states, alarms = [], [], []
    lot_no = 2660

    for day in range(6, -1, -1):
        date = (now - timedelta(days=day)).date()
        # 两个班次
        for (start_h, end_h) in ((8, 12), (13, 20)):
            t = datetime(date.year, date.month, date.day, start_h, 0, 0)
            end = datetime(date.year, date.month, date.day, end_h, 0, 0)
            if end > now - timedelta(hours=1):
                continue  # 班次尚未完全过去 → 留给模拟器实时产生
            lot_no += 1
            lot_id = "LOT-%05d" % lot_no
            n = random.randint(12, 15)
            states.append((MACHINE, "RUNNING", "正常生产, 批次 %s" % lot_id, t))
            cur_t = t
            for slot in range(1, n + 1):
                cur_t = cur_t + timedelta(seconds=random.randint(55, 130))
                r = RECIPES[(lot_no + slot) % len(RECIPES)]
                wafers.append(gen_wafer(r, lot_id, slot, cur_t))
            states.append((MACHINE, "IDLE", "批次完成", cur_t + timedelta(seconds=10)))
            # 偶发停机（下午班多一些）
            if random.random() < 0.18:
                down_t = end - timedelta(minutes=random.randint(30, 90))
                if down_t > cur_t:
                    code = random.choice([("AIM-VAC-HI", "ERROR", "腔体真空度高于上限 5E-5 Torr"),
                                          ("AIM-BEAM-UNST", "ERROR", "束流波动超 10%，注入中止"),
                                          ("AIM-ESC-CURR", "WARN", "静电吸盘电流异常偏高")])
                    states.append((MACHINE, "DOWN", code[2].split("，")[0], down_t))
                    alarms.append((MACHINE, code[0], code[1], code[2], down_t,
                                   down_t + timedelta(minutes=random.randint(20, 70))))
                    states.append((MACHINE, "PM", "恢复后例检保养", down_t + timedelta(minutes=5)))
                    states.append((MACHINE, "RUNNING", "恢复生产", down_t + timedelta(minutes=40)))
            # 偶尔 WARN 报警（不打断生产）
            if random.random() < 0.3 and len(alarms) < 40:
                w_t = cur_t + timedelta(minutes=random.randint(2, 90))
                alarms.append((MACHINE, "AIM-DOSE-WARN", "WARN",
                               "法拉第杯剂量读数偏低 3%，建议核对", w_t, w_t + timedelta(minutes=5)))

    for st in states:
        cur.execute(
            "INSERT INTO implant_machine_state (machine_id,state,reason,state_time) VALUES (%s,%s,%s,%s)", st)
    for al in alarms:
        cur.execute(
            "INSERT INTO implant_alarm_events (machine_id,alarm_code,alarm_level,message,start_time,end_time) "
            "VALUES (%s,%s,%s,%s,%s,%s)", al)
    batch = 200
    for i in range(0, len(wafers), batch):
        rows = wafers[i:i + batch]
        cur.executemany(
            "INSERT INTO implant_wafer_records "
            "(machine_id,lot_id,wafer_id,slot_no,recipe_name,species,energy_kev,dose_cm2,"
            "beam_current_ma,tilt_deg,twist_deg,implant_time_s,chamber_pressure_torr,esc_voltage_v,"
            "wafer_temp_c,uniformity_pct,particles_added,process_result,created_at) "
            "VALUES (%(machine_id)s,%(lot_id)s,%(wafer_id)s,%(slot_no)s,%(recipe_name)s,%(species)s,"
            "%(energy_kev)s,%(dose_cm2)s,%(beam_current_ma)s,%(tilt_deg)s,%(twist_deg)s,%(implant_time_s)s,"
            "%(chamber_pressure_torr)s,%(esc_voltage_v)s,%(wafer_temp_c)s,%(uniformity_pct)s,"
            "%(particles_added)s,%(process_result)s,%(created_at)s)", rows)
    conn.commit()
    cur.execute("SELECT COUNT(*), SUM(process_result='FAIL'), MIN(created_at), MAX(created_at) FROM implant_wafer_records")
    total, fails, t0, t1 = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM implant_machine_state")
    nst = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM implant_alarm_events")
    nal = cur.fetchone()[0]
    print("seed done: wafers=%d (fail=%d) states=%d alarms=%d" % (total, fails, nst, nal))
    print("time range: %s ~ %s" % (t0, t1))
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()