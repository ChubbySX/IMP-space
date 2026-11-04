# -*- coding: utf-8 -*-
"""Grant env_user SELECT on operator_credentials + verify"""
import pymysql
db = pymysql.connect(host='127.0.0.1', user='root', password='Env2026!root', charset='utf8mb4')
cur = db.cursor()
cur.execute("GRANT SELECT ON fab_implant.operator_credentials TO 'env_user'@'localhost'")
cur.execute("FLUSH PRIVILEGES")
db.close()
print("granted SELECT on operator_credentials to env_user")

# 验证 env_user 能查
db2 = pymysql.connect(host='127.0.0.1', user='env_user', password='Env2026!app', database='fab_implant', charset='utf8mb4')
cur2 = db2.cursor()
cur2.execute("SELECT employee_id, name, role FROM operator_credentials WHERE employee_id='202301020772'")
row = cur2.fetchone()
print("verify env_user query:", row)
db2.close()
