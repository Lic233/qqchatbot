@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHONDONTWRITEBYTECODE=1
set QQCHATBOT_LOG=logs/bot.log
title QQ official bot
echo Starting QQ official bot. Press Ctrl+C to stop.
echo Log file: logs/bot.log
echo.
python official_bot.py
echo.
echo Bot exited. Press any key to close.
pause >nul
