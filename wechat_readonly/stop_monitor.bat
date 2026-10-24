@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist state\monitor.pid (
  set /p P=<state\monitor.pid
  set P=%P: =%
  echo Stopping monitor PID %P% ...
  taskkill /PID %P% /F >nul 2>&1
  del state\monitor.pid >nul 2>&1
)
REM fallback: kill by command line
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process -Filter \"name='python.exe' OR name='pythonw.exe'\" | Where-Object { $_.CommandLine -match 'monitor\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('killed ' + $_.ProcessId) }"
echo Done.