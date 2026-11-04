@echo off
setlocal
chcp 65001 >nul
title IMP-MC-01 - stop services
echo ============================================================
echo   stop implant_app / implant_simulator / implant_to_db
echo ============================================================
echo.

powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'implant_(app|simulator|to_db)\.py' } | ForEach-Object { Write-Host ('[kill] ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

timeout /t 3 >nul

echo.
netstat -ano | findstr /C:":5001 " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
  echo [OK] port 5001 closed
) else (
  echo [WARN] port 5001 is still listening - close the window manually
)

echo.
echo note: MySQL / EMQX are system services and were NOT stopped by this script.
endlocal
pause