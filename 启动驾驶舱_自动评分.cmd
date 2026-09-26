@echo off
REM 5535_DAILY_SCORE_AUTO_MANAGED_LAUNCHER
REM 5535_QUALIFICATION_PRESENTATION_MANAGED_LAUNCHER
REM 5535_DAILY_PERFORMANCE_MANAGED_LAUNCHER
REM PRESERVED_BASE_ENTRY "F:\PythonProject\emotion_dashboard\_5535_runtime\5535_UI_PRESERVED_2_1_8b457d4677495bf3\launch_daily.py"
chcp 65001 >nul
setlocal
set "PY=F:\Python3.13\python.exe"
if not exist "%PY%" (echo BOUND_PYTHON_MISSING & exit /b 3)
"%PY%" -B -X utf8 "F:\PythonProject\emotion_dashboard\_5535_addons\5535_DAILY_PERFORMANCE_1.0\launch.py" "F:\PythonProject\emotion_dashboard"
set "RC=%ERRORLEVEL%"
if not defined S02_NO_PAUSE pause
exit /b %RC%
