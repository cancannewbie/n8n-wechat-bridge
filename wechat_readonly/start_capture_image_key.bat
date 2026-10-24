@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "%~dp0capture_image_key.py"
pause
