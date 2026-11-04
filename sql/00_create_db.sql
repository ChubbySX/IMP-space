-- ============================================================
-- 00_create_db.sql —— 建库（必须最先执行）
-- 后面两个 mysqldump 出来的文件里没有 USE 语句，
-- 所以导入 01/02 时必须把 fab_implant 作为库名传给 mysql 命令。
-- ============================================================

CREATE DATABASE IF NOT EXISTS fab_implant
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;

SHOW DATABASES LIKE 'fab_implant';