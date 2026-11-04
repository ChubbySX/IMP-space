@echo off
setlocal
chcp 65001 >nul
title IMP-MC-01 - start services
set "ROOT=%~dp0.."
pushd "%ROOT%"
if not exist "logs" mkdir "logs"
if "%DB_PY%"=="" if exist "%ROOT%\venv\Scripts\python.exe" set "DB_PY=%ROOT%\venv\Scripts\python.exe"
if "%DB_PY%"=="" set "DB_PY=python"

echo ============================================================
echo   IMP-MC-01  implant platform - start services
echo   root      : %ROOT%
echo   python    : %DB_PY%
echo ============================================================
echo.

"%DB_PY%" -c "import flask, pymysql, paho.mqtt" 1>nul 2>nul
if errorlevel 1 (
  echo [ERROR] missing python packages ^(flask / pymysql / paho-mqtt==1.6.1^)
  echo         run:  "%DB_PY%" -m pip install -r requirements.txt
  echo.
  popd
  pause
  exit /b 1
)

echo [1/3] starting implant_to_db.py ...
start "imp_to_db" /min cmd /c ""%DB_PY%" -u "src\implant_to_db.py" > "logs\to_db.log" 2>&1"
timeout /t 2 >nul

echo [2/3] starting implant_app.py ...
start "imp_app" /min cmd /c ""%DB_PY%" -u "src\implant_app.py" > "logs\app.log" 2>&1"
timeout /t 2 >nul

echo [3/3] starting implant_simulator.py ...
start "imp_sim" /min cmd /c ""%DB_PY%" -u "src\implant_simulator.py" --loop --interval 5 > "logs\sim.log" 2>&1"
timeout /t 5 >nul

echo.
netstat -ano | findstr /C:":5001 " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
  echo [WARN] port 5001 is NOT listening - check logs\app.log
  echo        ^(MySQL / EMQX may not be running^)
) else (
  echo [OK] web dashboard : http://127.0.0.1:5001/login
  echo [OK] 2D dashboard  : http://127.0.0.1:5001/2d
  start "" "http://127.0.0.1:5001/login"
)

echo.
echo logs are in: %ROOT%\logs
popd
endlocal
pause