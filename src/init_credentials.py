# -*- coding: utf-8 -*-
"""新建 operator_credentials 凭据表 + 写入默认操作员"""
import pymysql

db = pymysql.connect(host='127.0.0.1', user='root', password='Env2026!root', database='fab_implant', charset='utf8mb4')
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS operator_credentials (
  id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  employee_id VARCHAR(20)  NOT NULL UNIQUE,
  password    VARCHAR(64)  NOT NULL,
  name        VARCHAR(32)  NOT NULL,
  role        VARCHAR(16)  NOT NULL DEFAULT 'OPERATOR',
  active      TINYINT(1)   NOT NULL DEFAULT 1,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
""")

cur.execute("SELECT COUNT(*) FROM operator_credentials")
cnt = cur.fetchone()[0]
if cnt == 0:
    cur.execute("""
    INSERT INTO operator_credentials (employee_id, password, name, role) VALUES
      ('202301020772', '123456',     '张操作',     'OPERATOR'),
      ('202301020001', 'admin888',   '李工程师',   'ENGINEER'),
      ('202301020002', 'super2026',  '王主管',     'SUPERVISOR')
    """)
    db.commit()
    print("inserted 3 operators")
else:
    print(f"table already has {cnt} rows")

cur.execute("SELECT id, employee_id, name, role, active FROM operator_credentials")
for r in cur.fetchall():
    print(f"  id={r[0]} emp={r[1]} name={r[2]} role={r[3]} active={r[4]}")

db.close()
print("done")
