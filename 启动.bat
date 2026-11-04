@echo off
chcp 65001 >nul
title IMP-MC-01 - 启动
setlocal
set "ROOT=%~dp0"

REM 首次使用请先运行「首次准备.bat」
if not exist "venv\Scripts\python.exe" (
  echo [x] 还没做首次准备：找不到 venv\Scripts\python.exe
  echo     请先双击运行「首次准备.bat」
  echo.
  pause
  exit /b 1
)
if not exist "logs" mkdir "logs"

REM 端口自检：MySQL 3306 / EMQX 1883
netstat -ano | findstr /C:":3306 " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
  echo [x] MySQL 没在运行（3306 端口没监听）
  echo     请先启动 MySQL 服务，再双击本文件。
  echo.
  pause
  exit /b 1
)
netstat -ano | findstr /C:":1883 " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
  echo [x] EMQX 没在运行（1883 端口没监听）
  echo     请先启动 EMQX（bin\emqx start），再双击本文件。
  echo.
  pause
  exit /b 1
)

set "DB_PY=%ROOT%venv\Scripts\python.exe"
call "%ROOT%scripts\start_services.bat"
endlocal