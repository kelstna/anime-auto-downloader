@echo off
rem ===========================================================================
rem  自动下载番剧 - 重装系统后的一步配置
rem  做四件事：
rem    1. 检查 Python 3.10+（缺失则给出中文提示并打开下载页）
rem    2. 若 data\config.json 不存在，从 data\config.example.json 复制一份
rem    3. 提示需要改的三项：qBittorrent 地址 / 下载目录 / Bangumi Token
rem    4. 询问是否立即注册开机自启动
rem  只预览不修改：先执行  set ANIME_DRYRUN=1  再运行本文件
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 自动下载番剧 - 一步配置
if not defined ANIME_DRYRUN set "ANIME_DRYRUN=0"
set "PROJDIR=%~dp0"
if "%PROJDIR:~-1%"=="\" set "PROJDIR=%PROJDIR:~0,-1%"
set "PYVER="

echo ============================================================
echo   自动下载番剧 - 一步配置
echo ============================================================
echo   项目目录：%PROJDIR%
echo.

rem ---- 1. 检查 Python 3.10+ ---------------------------------------------------
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY for /f "delims=" %%I in ('where python.exe 2^>nul') do if not defined PY set "PY=%%I"
if not defined PY for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%I"
if defined PY if not exist "%PY%" set "PY="
if not defined PY for %%D in ("C:\Program Files\Python312" "C:\Program Files\Python311" "C:\Program Files\Python310") do if not defined PY if exist "%%~D\python.exe" set "PY=%%~D\python.exe"
if not defined PY goto :no_python

"%PY%" -c "import sys;print(sys.version.split()[0])" >"%TEMP%\anime_pyver.txt" 2>nul
if errorlevel 1 goto :bad_python
set /p PYVER=<"%TEMP%\anime_pyver.txt"
if not defined PYVER set "PYVER=未知版本"
"%PY%" -c "import sys;raise SystemExit(0 if sys.version_info>=(3,10) else 3)" >nul 2>&1
if errorlevel 3 goto :old_python
echo [1/4] Python 检查通过： %PYVER%   "%PY%"

rem ---- 2. 生成 data\config.json -------------------------------------------------
if not exist "%PROJDIR%\data" mkdir "%PROJDIR%\data"
if exist "%PROJDIR%\data\config.json" goto :keep_config
if not exist "%PROJDIR%\data\config.example.json" goto :no_template
if "%ANIME_DRYRUN%"=="1" goto :dry_copy
copy /y "%PROJDIR%\data\config.example.json" "%PROJDIR%\data\config.json" >nul
echo [2/4] 已从模板生成 data\config.json
goto :config_ready

:dry_copy
echo [dry-run] 将要执行： copy /y "data\config.example.json" "data\config.json"
goto :config_ready

:keep_config
echo [2/4] data\config.json 已存在，保留不覆盖

:config_ready
rem ---- 3. 提示需要改的三项 ------------------------------------------------------
echo [3/4] 请检查 data\config.json 这三项是否与本机一致：
echo        1. qbittorrent.base_url  qBittorrent 的 WebUI 地址，本机默认 http://127.0.0.1:8080
echo        2. download.root         番剧下载根目录，本机默认 <下载根目录>
echo        3. bangumi_token         Bangumi 访问令牌，留空也能用，之后可在网页里填
echo.
if "%ANIME_DRYRUN%"=="1" goto :skip_edit
choice /c YN /n /t 30 /d N /m "现在用记事本打开 data\config.json 修改吗？[Y/N] "
if errorlevel 2 goto :skip_edit
start "" notepad "%PROJDIR%\data\config.json"
echo        已打开记事本，改完保存并关闭即可。
:skip_edit
echo.

rem ---- 4. 询问是否注册开机自启动 -------------------------------------------------
set "AUTO=N"
if "%ANIME_DRYRUN%"=="1" goto :auto_done
choice /c YN /n /t 30 /d N /m "现在注册开机自动启动吗？[Y/N] "
if errorlevel 2 goto :auto_done
set "AUTO=Y"
:auto_done
if "%AUTO%"=="Y" call "%~dp0install-autostart.bat"
if not "%AUTO%"=="Y" echo [4/4] 已跳过注册开机自启。以后随时可以双击 install-autostart.bat 注册。

echo.
echo 配置完成：双击 start.bat 启动，浏览器会自动打开控制台页面。
echo.
echo 如果启动失败，双击 start-debug.bat 可以看到完整报错。
echo.
if "%ANIME_DRYRUN%"=="1" echo [dry-run] 到此结束，本次没有修改任何文件，也没有注册计划任务。
if "%ANIME_DRYRUN%"=="1" exit /b 0
pause
exit /b 0

:no_python
echo [1/4] [错误] 没有检测到 Python。请先安装 Python 3.10 或更高版本。
echo        安装时务必勾选 "Add python.exe to PATH"。
echo        即将打开下载页面： https://www.python.org/downloads/windows/
echo.
if "%ANIME_DRYRUN%"=="1" echo [dry-run] 不打开浏览器。
if "%ANIME_DRYRUN%"=="1" exit /b 1
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:old_python
echo [1/4] [错误] 检测到的 Python 版本过低： %PYVER%
echo        需要 3.10 或更高版本。即将打开下载页面： https://www.python.org/downloads/windows/
echo.
if "%ANIME_DRYRUN%"=="1" exit /b 1
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:bad_python
echo [1/4] [错误] 找到了 python.exe，但无法运行它： "%PY%"
echo        常见原因：Microsoft Store 的 python 占位程序、PATH 指向了无效路径。
echo        请安装标准版 Python 3.10 以上版本： https://www.python.org/downloads/windows/
echo.
if "%ANIME_DRYRUN%"=="1" exit /b 1
pause
exit /b 1

:no_template
echo [2/4] [错误] 缺少模板文件 "%PROJDIR%\data\config.example.json"
echo        请确认项目文件完整后重新运行本脚本。
echo.
if "%ANIME_DRYRUN%"=="1" exit /b 1
pause
exit /b 1
