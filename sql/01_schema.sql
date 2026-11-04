
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
DROP TABLE IF EXISTS `implant_alarm_events`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `implant_alarm_events` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `machine_id` varchar(20) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'IMP-MC-01' COMMENT '机台编号',
  `alarm_code` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '报警代码',
  `alarm_level` varchar(10) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'WARN' COMMENT '等级 WARN/ERROR',
  `message` varchar(128) COLLATE utf8mb4_general_ci NOT NULL COMMENT '报警描述',
  `start_time` datetime NOT NULL COMMENT '报警开始时间',
  `end_time` datetime DEFAULT NULL COMMENT '恢复时间(NULL=未恢复)',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `component_tag` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `param_name` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `param_from` varchar(32) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `param_to` varchar(32) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `param_unit` varchar(16) COLLATE utf8mb4_general_ci DEFAULT NULL,
  `param_fix` varchar(128) COLLATE utf8mb4_general_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_open` (`end_time`),
  KEY `idx_time` (`start_time`)
) ENGINE=InnoDB AUTO_INCREMENT=2450 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='机台报警事件';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `implant_lot_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `implant_lot_records` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `lot_id` varchar(32) NOT NULL,
  `machine_id` varchar(20) NOT NULL DEFAULT 'IMP-MC-01',
  `wafer_count` int unsigned NOT NULL,
  `pass_count` int unsigned NOT NULL,
  `yield_pct` decimal(5,1) NOT NULL,
  `uniformity_avg` decimal(5,2) NOT NULL,
  `alarm_count` int unsigned NOT NULL DEFAULT '0',
  `alarm_warn` int unsigned NOT NULL DEFAULT '0',
  `alarm_error` int unsigned NOT NULL DEFAULT '0',
  `cycle_mode` varchar(16) NOT NULL DEFAULT 'NORMAL',
  `note` varchar(128) DEFAULT NULL,
  `archived` tinyint(1) NOT NULL DEFAULT '0',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_lot` (`lot_id`),
  KEY `idx_lot` (`lot_id`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=47 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `implant_lot_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `implant_lot_sessions` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `lot_id` varchar(32) NOT NULL,
  `total` int unsigned NOT NULL DEFAULT '20',
  `start_ts` datetime NOT NULL,
  `end_ts` datetime DEFAULT NULL,
  `state` varchar(16) NOT NULL DEFAULT 'RUNNING',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_lot_session` (`lot_id`)
) ENGINE=InnoDB AUTO_INCREMENT=39 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `implant_machine_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `implant_machine_state` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `machine_id` varchar(20) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'IMP-MC-01' COMMENT '机台编号',
  `state` varchar(16) COLLATE utf8mb4_general_ci NOT NULL COMMENT '状态 RUNNING/IDLE/DOWN/PM',
  `reason` varchar(64) COLLATE utf8mb4_general_ci DEFAULT NULL COMMENT '状态原因/备注',
  `state_time` datetime NOT NULL COMMENT '状态生效时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_machine_time` (`machine_id`,`state_time`)
) ENGINE=InnoDB AUTO_INCREMENT=5057 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='机台状态时间线(E10)';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `implant_wafer_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `implant_wafer_records` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `machine_id` varchar(20) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'IMP-MC-01' COMMENT '注入机编号',
  `lot_id` varchar(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `wafer_id` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '晶圆编号',
  `slot_no` tinyint unsigned NOT NULL COMMENT '片槽位',
  `recipe_name` varchar(32) COLLATE utf8mb4_general_ci NOT NULL COMMENT '工艺配方',
  `species` varchar(8) COLLATE utf8mb4_general_ci NOT NULL COMMENT '注入杂质元素(P/B/As/BF2)',
  `energy_kev` decimal(8,2) NOT NULL COMMENT '注入能量 keV',
  `dose_cm2` double NOT NULL COMMENT '注入剂量 atoms/cm2',
  `beam_current_ma` decimal(8,3) NOT NULL COMMENT '束流 mA',
  `tilt_deg` decimal(4,2) NOT NULL COMMENT '注入角(倾斜角) 度',
  `twist_deg` decimal(4,2) NOT NULL COMMENT '扭转角 度',
  `implant_time_s` decimal(8,1) NOT NULL COMMENT '注入耗时 s',
  `chamber_pressure_torr` decimal(10,5) NOT NULL COMMENT '腔体真空度 Torr',
  `esc_voltage_v` decimal(8,1) NOT NULL COMMENT '静电吸盘电压 V',
  `wafer_temp_c` decimal(5,2) NOT NULL COMMENT '晶圆温度 ℃',
  `uniformity_pct` decimal(5,2) NOT NULL COMMENT '片内均匀度 %(规格<=2.5)',
  `particles_added` int unsigned NOT NULL DEFAULT '0' COMMENT '颗粒增量(规格<=50)',
  `process_result` varchar(10) COLLATE utf8mb4_general_ci NOT NULL DEFAULT 'PASS' COMMENT '工艺结果 PASS/FAIL/ALARM',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '完成时间',
  PRIMARY KEY (`id`),
  KEY `idx_lot` (`lot_id`),
  KEY `idx_created` (`created_at`),
  KEY `idx_machine` (`machine_id`,`created_at`)
) ENGINE=InnoDB AUTO_INCREMENT=17305 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='离子注入逐片工艺记录';
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `operator_credentials`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `operator_credentials` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `employee_id` varchar(20) NOT NULL,
  `password` varchar(64) NOT NULL,
  `name` varchar(32) NOT NULL,
  `role` varchar(16) NOT NULL DEFAULT 'OPERATOR',
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `employee_id` (`employee_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

