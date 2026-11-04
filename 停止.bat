@echo off
chcp 65001 >nul
title IMP-MC-01 - 停止
setlocal
set "ROOT=%~dp0"
call "%ROOT%scripts\stop_services.bat"
endlocal