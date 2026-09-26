@echo off
REM 5535_DAILY_SCORE_AUTO_MANAGED_LAUNCHER
REM 5535_QUALIFICATION_PRESENTATION_MANAGED_LAUNCHER
REM 5535_DAILY_PERFORMANCE_MANAGED_LAUNCHER
chcp 65001 >nul
setlocal
if not exist logs mkdir logs
set "LOG_DIR=logs"
set "PY=F:\Python3.13\python.exe"
if not exist "%PY%" (echo BOUND_PYTHON_MISSING & exit /b 3)
"%PY%" -B -X utf8 "F:\PythonProject\emotion_dashboard\_5535_addons\5535_DAILY_PERFORMANCE_1.0\launch.py" "F:\PythonProject\emotion_dashboard" >> logs\run.log 2>&1
set "RC=%ERRORLEVEL%"
if not defined S02_NO_PAUSE pause
exit /b %RC%
