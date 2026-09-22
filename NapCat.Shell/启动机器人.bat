@echo off
chcp 65001 >nul
title QQ机器人启动器

echo ================================
echo       QQ机器人启动器
echo ================================
echo.

REM ===== 配置区域 =====

REM NapCat.Shell 文件夹（当前脚本所在目录）
set "NAPCAT_DIR=%~dp0"

REM QQ账号
set "QQ_NUMBER=3486113519"

REM Python 3.12
set "PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"

REM Python机器人目录（NapCat.Shell 的同级目录）
set "BOT_DIR=%~dp0..\qqchatbot"

REM OneBot WebSocket端口
set "WS_PORT=3001"

REM ====================

echo [1/3] 启动 NapCat...
echo.

if not exist "%NAPCAT_DIR%\launcher.bat" (
    echo 找不到 NapCat 启动文件：%NAPCAT_DIR%\launcher.bat
    pause
    exit /b 1
)

if not exist "%PYTHON%" (
    echo 找不到 Python 3.12：%PYTHON%
    pause
    exit /b 1
)

if not exist "%BOT_DIR%\bot.py" (
    echo 找不到机器人代码：%BOT_DIR%\bot.py
    pause
    exit /b 1
)

cd /d "%NAPCAT_DIR%"

start "NapCatQQ" cmd /k "launcher.bat %QQ_NUMBER%"

echo NapCat 已启动。
echo.

echo [2/3] 等待 OneBot WebSocket 启动...
echo.

:WAIT_WS

powershell -NoProfile -Command ^
"$c = New-Object System.Net.Sockets.TcpClient; ^
try { ^
    $task = $c.ConnectAsync('127.0.0.1', %WS_PORT%); ^
    if ($task.Wait(500) -and $c.Connected) { exit 0 } else { exit 1 } ^
} catch { ^
    exit 1 ^
} finally { ^
    $c.Close() ^
}"

if errorlevel 1 (
    echo WebSocket %WS_PORT% 尚未启动，2秒后继续检查...
    timeout /t 2 /nobreak >nul
    goto WAIT_WS
)

echo.
echo WebSocket %WS_PORT% 已启动！
echo.

echo [3/3] 启动 Python QQ机器人...
echo.

cd /d "%BOT_DIR%"

"%PYTHON%" bot.py

echo.
echo Python机器人已退出。
pause