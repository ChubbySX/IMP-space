-- ============================================================
-- 03_create_user.sql —— 创建应用账号 env_user
-- 必须在 01_schema.sql 之后执行（需要 fab_implant 库存在）
-- 注意：PyMySQL 直连要求 mysql_native_password；
--       MySQL 8 默认的 caching_sha2_password 需要额外 cryptography 包，
--       为避免"转发出去连不上"，这里显式指定插件。
-- ============================================================

CREATE USER IF NOT EXISTS 'env_user'@'localhost'
  IDENTIFIED WITH mysql_native_password BY 'Env2026!app';

ALTER USER 'env_user'@'localhost'
  IDENTIFIED WITH mysql_native_password BY 'Env2026!app';

GRANT SELECT, INSERT, UPDATE, DELETE ON fab_implant.* TO 'env_user'@'localhost';

FLUSH PRIVILEGES;

-- 回显确认（应输出 env_user / mysql_native_password）
SELECT user, host, plugin FROM mysql.user WHERE user = 'env_user';