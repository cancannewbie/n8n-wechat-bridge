@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0bridge_folder_watch.py"
pause
