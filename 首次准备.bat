@echo off
chcp 65001 >nul
title IMP-MC-01 - 首次准备（只运行一次）
setlocal
set "ROOT=%~dp0"
pushd "%ROOT%"

echo ============================================================
echo   首次准备：装 Python 依赖 + 建库导数据
echo   这一步【只需要做一次】，之后每次双击「启动.bat」即可
echo ============================================================
echo.

REM ---------- 1/3 Python ----------
where python >nul 2>&1
if errorlevel 1 (
  echo [x] 找不到 python 命令。
  echo     请先安装 Python 3.9 或以上版本，安装时务必勾选 "Add Python to PATH"，
  echo     装完重新打开本窗口再试。
  echo.
  popd
  pause
  exit /b 1
)
for /f "delims=" %%v in ('python -V 2^>^&1') do echo [1/3] 检测到 %%v

REM ---------- 2/3 虚拟环境 + 依赖 ----------
if not exist "venv\Scripts\python.exe" (
  echo [2/3] 创建虚拟环境 venv ...
  python -m venv venv
  if errorlevel 1 (
    echo [x] 创建虚拟环境失败。
    popd
    pause
    exit /b 1
  )
) else (
  echo [2/3] 虚拟环境已存在，跳过创建
)
set "PY=%ROOT%venv\Scripts\python.exe"
echo      安装依赖（Flask / PyMySQL / paho-mqtt）...
"%PY%" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo [x] 依赖安装失败，多半是网络问题。可以换国内镜像重试：
  echo     "%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  popd
  pause
  exit /b 1
)
"%PY%" -c "import flask, pymysql, paho.mqtt" >nul 2>&1
if errorlevel 1 (
  echo [x] 依赖装完但仍导入失败，请把上面的报错发给我。
  popd
  pause
  exit /b 1
)
echo      依赖就绪

REM ---------- 3/3 找 mysql.exe ----------
echo [3/3] 导入数据库
set "MYSQL="
for %%p in (
  "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"
  "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"
  "C:\Program Files\MySQL\MySQL Server 8.1\bin\mysql.exe"
  "D:\mysql\bin\mysql.exe"
  "D:\dbtraining\mysql\bin\mysql.exe"
) do if exist %%p set "MYSQL=%%~p"

if not defined MYSQL (
  for /f "delims=" %%i in ('where mysql 2^>nul') do if not defined MYSQL set "MYSQL=%%i"
)

if not defined MYSQL (
  echo [x] 找不到 mysql.exe。
  echo     请把 MySQL 的 bin 目录加入 PATH，或者手动导入 sql 目录下的 4 个文件：
  echo        mysql -uroot -p ^< sql\00_create_db.sql
  echo        mysql -uroot -p fab_implant ^< sql\01_schema.sql
  echo        mysql -uroot -p fab_implant ^< sql\02_demo_data.sql
  echo        mysql -uroot -p fab_implant ^< sql\03_create_user.sql
  popd
  pause
  exit /b 1
)
echo      使用: %MYSQL%
echo.
echo     请确认 MySQL 服务已经在运行（任务管理器里能看到 mysqld.exe）。
set /p MYSQLPW=     请输入 MySQL root 密码（直接回车则使用默认 Env2026!root）:
if "%MYSQLPW%"=="" set "MYSQLPW=Env2026!root"
echo.

"%MYSQL%" -uroot -p%MYSQLPW% < "sql\00_create_db.sql"
if errorlevel 1 (
  echo [x] 建库失败，请检查 root 密码是否正确、MySQL 是否启动。
  popd
  pause
  exit /b 1
)

"%MYSQL%" -uroot -p%MYSQLPW% fab_implant < "sql\01_schema.sql"
if errorlevel 1 (
  echo [x] 建表失败。
  popd
  pause
  exit /b 1
)

echo      正在导入演示数据（1.7 万条记录，约 10 秒）...
"%MYSQL%" -uroot -p%MYSQLPW% fab_implant < "sql\02_demo_data.sql"
if errorlevel 1 (
  echo [x] 导入数据失败。
  popd
  pause
  exit /b 1
)

"%MYSQL%" -uroot -p%MYSQLPW% fab_implant < "sql\03_create_user.sql"
if errorlevel 1 (
  echo [x] 创建应用账号 env_user 失败。
  popd
  pause
  exit /b 1
)

echo.
echo ============================================================
echo   [OK] 首次准备全部完成
echo ============================================================
echo   接下来：
echo     1. 启动 EMQX（MQTT 消息服务，端口 1883）
echo     2. 双击本目录下的「启动.bat」
echo     3. 浏览器打开 http://127.0.0.1:5001/login
echo        工号 202301020772 / 密码 123456
echo.
echo   以后每次开机只要：启动 EMQX -^> 启动.bat
echo ============================================================
popd
endlocal
pause