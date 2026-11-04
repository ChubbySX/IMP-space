# -*- coding: utf-8 -*-
"""
晶圆离子注入工序数据平台 —— 共享数据库配置
MySQL 连接信息（应用账号 env_user，仅授权 fab_implant.* 与 env_monitor.*）
真实产线中该连接串对应 EAP(Equipment Automation Program) 的数据库连接。
"""
import os
import sys

# 兼容从任意目录运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "env_user",
    "password": "Env2026!app",
    "database": "fab_implant",
    "charset": "utf8mb4",
}

MQTT_CONFIG = {
    "host": "127.0.0.1",
    "port": 1883,
}

# MQTT 主题定义（离子注入工序事件流）
TOPIC_WAFER_DONE = "fab/implant/mc01/wafer/done"   # 逐片工艺完成事件
TOPIC_MACHINE_STATE = "fab/implant/mc01/state"     # 机台状态变化事件
TOPIC_ALARM = "fab/implant/mc01/alarm"             # 报警事件
TOPIC_CMD = "fab/implant/mc01/cmd"                 # 后端→模拟器指令通道（run / stop / repair）