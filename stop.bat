@echo off
rem ===========================================================================
rem  自动下载番剧 - 停止正在运行的实例
rem  按命令行匹配 app.main，先打印将要结束的 PID，再结束进程。
rem  只预览不结束：先执行  set ANIME_DRYRUN=1  再运行本文件
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 自动下载番剧 - 停止
if not defined ANIME_DRYRUN set "ANIME_DRYRUN=0"

echo ============================================================
echo   停止自动下载番剧
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$dry = $env:ANIME_DRYRUN -eq '1'; $p = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match 'app[\\/]main\.py|app\.main' }; if (-not $p) { Write-Host '[信息] 没有找到正在运行的实例，无需停止。'; exit 3 }; Write-Host '[将要结束的进程]'; $p | ForEach-Object { Write-Host ('  PID ' + $_.ProcessId + '  ' + $_.Name); Write-Host ('      ' + $_.CommandLine) }; if ($dry) { Write-Host ''; Write-Host '[dry-run] 未结束任何进程。'; exit 10 }; Write-Host ''; foreach ($x in $p) { Write-Host ('正在结束 PID ' + $x.ProcessId + ' ...'); Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 600; $left = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and $_.CommandLine -match 'app[\\/]main\.py|app\.main' }; if ($left) { Write-Host '[警告] 仍有进程未结束，请用管理员身份再运行一次。'; exit 1 }; Write-Host '[完成] 实例已全部结束。'; exit 0"
set "RC=%errorlevel%"

if "%RC%"=="0" goto :stopped
if "%RC%"=="10" goto :end
if "%RC%"=="3" goto :none
goto :failed

:stopped
echo.
echo 浏览器里的页面刷新后会提示无法连接，属正常现象。
echo 重启服务：双击 start.bat
echo.
pause
exit /b 0

:none
if "%ANIME_DRYRUN%"=="1" exit /b 0
echo.
pause
exit /b 0

:failed
echo.
echo [警告] 有进程未能结束，请右键本文件选「以管理员身份运行」后重试。
echo.
pause
exit /b 1

:end
exit /b 0
