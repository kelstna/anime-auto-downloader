@echo off
rem ===========================================================================
rem  自动下载番剧 - 注册开机自启动（Windows 任务计划程序，不依赖 AlwaysUp）
rem  双击运行；若提示权限不足，请右键「以管理员身份运行」。
rem  只预览不注册：先执行  set ANIME_DRYRUN=1  再运行本文件
rem
rem  为什么 /TR 不是直接写 pythonw：
rem    计划任务的默认工作目录是 C:\Windows\System32，而 `python -m app.main`
rem    需要在项目根目录下执行（否则报 No module named app）。
rem    schtasks 无法直接指定工作目录，所以用 cmd /c cd /d 包一层，
rem    命令行里的引号按 \" 形式转义后再交给 schtasks。
rem ===========================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title 自动下载番剧 - 注册开机自启动
if not defined ANIME_DRYRUN set "ANIME_DRYRUN=0"
set "TASKNAME=AnimeAutoDownloader"
set "Q=""
set BS=\
set "PROJDIR=%~dp0"
if "%PROJDIR:~-1%"=="\" set "PROJDIR=%PROJDIR:~0,-1%"

rem ---- 探测 pythonw.exe 的绝对路径 -------------------------------------------
set "PYW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
if not defined PYW for /f "delims=" %%I in ('py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do if not defined PYW set "PYW=%%I"
if not defined PYW for %%D in ("C:\Program Files\Python312" "C:\Program Files\Python311" "C:\Program Files\Python310") do if not defined PYW if exist "%%~D\pythonw.exe" set "PYW=%%~D\pythonw.exe"
if defined PYW if not exist "%PYW%" set "PYW="
if not defined PYW goto :no_pyw

rem ---- 构造 /TR 的命令行：先 cd 到项目目录，再用 pythonw 起后台服务 ---------
set "TR=cmd /c cd /d !BS!!Q!%PROJDIR%!BS!!Q! && !BS!!Q!%PYW%!BS!!Q! -m app.main --no-browser"

echo ============================================================
echo   注册开机自启动
echo ============================================================
echo   任务名：  %TASKNAME%
echo   计划：    登录时 ONLOGON，权限普通用户 LIMITED，当前用户 %USERNAME%
echo   解释器：  %PYW%
echo   工作目录：%PROJDIR%
echo   启动参数：-m app.main --no-browser
echo.

if "%ANIME_DRYRUN%"=="1" goto :dryrun

echo 正在注册…
schtasks /Create /TN "%TASKNAME%" /TR "!TR!" /SC ONLOGON /RL LIMITED /RU "%USERNAME%" /IT /F
if errorlevel 1 goto :retry_no_ru
goto :verify

:retry_no_ru
echo.
echo [提示] 带 /RU 的方式注册失败，改用系统默认的当前用户身份重试…
schtasks /Create /TN "%TASKNAME%" /TR "!TR!" /SC ONLOGON /RL LIMITED /F
if errorlevel 1 goto :create_failed

:verify
echo.
echo [验证 1/2] schtasks /Query 结果：
schtasks /Query /TN "%TASKNAME%"
echo.
echo [验证 2/2] 计划任务里实际保存的命令行：
schtasks /Query /TN "%TASKNAME%" /XML | findstr /i "Command Arguments"
echo.
echo 注册成功：下次登录 Windows 时会在后台自动启动，不打开浏览器。
echo 运行日志： "%PROJDIR%\data\app.log"
echo 取消自启动：双击 uninstall-autostart.bat
echo.
pause
exit /b 0

:dryrun
echo [dry-run] 将要执行：
echo   schtasks /Create /TN "%TASKNAME%" /TR "!TR!" /SC ONLOGON /RL LIMITED /RU "%USERNAME%" /IT /F
echo [dry-run] 未注册任何计划任务，未修改任何配置。
exit /b 0

:create_failed
echo.
echo [错误] 注册计划任务失败。常见原因与处理：
echo        1. 权限不足 —— 右键本文件选「以管理员身份运行」后重试
echo        2. 同名任务已存在且属于其他账户 —— 先运行 uninstall-autostart.bat
echo        3. 系统策略禁止创建计划任务 —— 请联系管理员
echo.
pause
exit /b 1

:no_pyw
echo.
echo [错误] 没有找到 pythonw.exe（Python 3.10+ 可能未安装）。
echo        请安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
echo        下载地址： https://www.python.org/downloads/windows/
echo.
pause
exit /b 1
