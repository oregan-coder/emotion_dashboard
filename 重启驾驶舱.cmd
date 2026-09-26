@echo off
chcp 936 >nul
title 灵境驾驶舱重启工具
echo ======================================
echo  正在重启灵境A股情绪驾驶舱
echo ======================================
echo.
echo [1/3] 正在停止旧web进程...
taskkill /f /im python.exe >nul 2>&1
timeout /t 3 /nobreak >nul
echo [2/3] 正在启动新的web服务...
start "驾驶舱web" /min "F:\Python3.13\python.exe" -X utf8 "F:\PythonProject\emotion_dashboard\web_app.py"
timeout /t 6 /nobreak >nul
echo [3/3] 启动完成！
echo.
echo 访问地址: http://127.0.0.1:5000/
echo 本窗口将在2秒后自动关闭...
timeout /t 2 /nobreak >nul
exit