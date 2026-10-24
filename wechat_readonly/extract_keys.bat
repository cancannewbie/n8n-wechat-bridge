@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0extract_db_keys.py"
pause
