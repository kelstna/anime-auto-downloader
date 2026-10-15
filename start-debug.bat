@echo off
rem ===========================================================================
rem  自动下载番剧 - 调试启动（前台运行 + 输出日志 + --verbose）
rem  用途：启动失败、搜索异常时用它看完整报错。
rem  只预览不启动：先执行  set ANIME_DRYRUN=1  再运行本文件
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 自动下载番剧 - 调试模式
if not defined ANIME_DRYRUN set "ANIME_DRYRUN=0"
set "PROJDIR=%~dp0"
if "%PROJDIR:~-1%"=="\" set "PROJDIR=%PROJDIR:~0,-1%"

rem ---- 探测控制台版 python.exe（调试模式必须用 python，不用 pythonw） --------
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%I in ('where python.exe 2^>nul') do if not defined PY set "PY=%%I"
if not defined PY for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%I"
if defined PY if not exist "%PY%" set "PY="
if not defined PY for %%D in ("C:\Program Files\Python312" "C:\Program Files\Python311" "C:\Program Files\Python310") do if not defined PY if exist "%%~D\python.exe" set "PY=%%~D\python.exe"

echo ============================================================
echo   自动下载番剧 - 调试模式，按 Ctrl+C 结束
echo ============================================================
echo   项目目录：%PROJDIR%
if defined PY echo   解释器：  %PY%
echo.

if not defined PY goto :no_python

if "%ANIME_DRYRUN%"=="1" goto :dryrun

"%PY%" -c "import app.main" 2>"%TEMP%\anime_preflight_debug.txt"
if errorlevel 1 goto :bad_deps

echo 正在前台启动，日志会直接显示在本窗口…
echo.
"%PY%" -m app.main --verbose
echo.
echo 程序已退出，退出码 %errorlevel%
echo 完整日志： "%PROJDIR%\data\app.log"
echo.
pause
exit /b 0

:dryrun
echo [dry-run] 将要执行： "%PY%" -m app.main --verbose
echo [dry-run] 工作目录： %PROJDIR%
echo [dry-run] 未启动任何进程。
exit /b 0

:no_python
echo.
echo [错误] 没有找到 python.exe，无法启动调试模式。
echo        请安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
echo        下载地址： https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:bad_deps
echo.
echo [错误] 依赖自检失败：无法导入 app.main。错误输出如下：
type "%TEMP%\anime_preflight_debug.txt"
echo.
echo        请确认本目录下 app 子目录完整，且使用的是标准版 Python 3.10 以上。
echo.
pause
exit /b 1
