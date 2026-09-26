' A股情绪驾驶舱 launcher (no window)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "F:\PythonProject\emotion_dashboard"
WshShell.Run "cmd /c ""启动A股情绪驾驶舱.bat""", 0, False
Set WshShell = Nothing
