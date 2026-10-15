@echo off
rem ===========================================================================
rem  自动下载番剧 - 正常启动（优先无窗口后台运行）
rem  双击本文件即可；也可在命令行执行 start.bat
rem  只预览不启动：先执行  set ANIME_DRYRUN=1  再运行本文件
rem  说明：全部路径都加了引号，因此项目放在含空格 / 中文的目录下也能正常使用。
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 自动下载番剧 - 启动
if not defined ANIME_DRYRUN set "ANIME_DRYRUN=0"
set "PROJDIR=%~dp0"
if "%PROJDIR:~-1%"=="\" set "PROJDIR=%PROJDIR:~0,-1%"

rem ---- 1. 探测 python.exe（控制台版，用于自检与报错） ------------------------
set "PY="
set "PYW="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PY for /f "delims=" %%I in ('where python.exe 2^>nul') do if not defined PY set "PY=%%I"
if not defined PY for /f "delims=" %%I in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PY set "PY=%%I"

rem ---- 2. 探测 pythonw.exe（无窗口版，用于后台启动） -------------------------
if not defined PYW for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%I"
if not defined PYW for /f "delims=" %%I in ('py -3 -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') do if not defined PYW set "PYW=%%I"
if not defined PYW for %%D in ("C:\Program Files\Python312" "C:\Program Files\Python311" "C:\Program Files\Python310") do if not defined PYW if exist "%%~D\pythonw.exe" set "PYW=%%~D\pythonw.exe"
if defined PYW if not exist "%PYW%" set "PYW="
if not defined PY if defined PYW set "PY=%PYW:pythonw.exe=python.exe%"
if defined PY if not exist "%PY%" set "PY="

echo ============================================================
echo   自动下载番剧 - 启动
echo ============================================================
echo   项目目录：%PROJDIR%

if not defined PYW goto :no_python
echo   解释器：  %PYW%

rem ---- 3. 依赖自检：能否导入 app.main -----------------------------------------
if not defined PY goto :skip_preflight
"%PY%" -c "import app.main" 2>"%TEMP%\anime_preflight.txt"
if errorlevel 1 goto :bad_deps
echo [1/3] 依赖自检通过

rem ---- 4. 端口检查：占用则提示（主程序会自动顺延端口） ------------------------
set "PORT="
"%PY%" -c "import json,os;c=json.load(open('data/config.json',encoding='utf-8')) if os.path.exists('data/config.json') else {};print(int((c.get('server') or {}).get('port',7788)))" >"%TEMP%\anime_port.txt" 2>nul
set /p PORT=<"%TEMP%\anime_port.txt"
if not defined PORT set "PORT=7788"
set "PORTOK=1"
"%PY%" -c "import socket,sys;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sys.exit(9 if s.connect_ex(('127.0.0.1',int(sys.argv[1])))==0 else 0)" %PORT%
if errorlevel 9 set "PORTOK=0"
if "%PORTOK%"=="0" echo [2/3] 提示：%PORT% 端口已被占用，可能是本工具已在运行；主程序会自动改用后面的空闲端口
if "%PORTOK%"=="1" echo [2/3] 端口 %PORT% 空闲
goto :preflight_done

:skip_preflight
echo [1/3] 未找到 python.exe，跳过依赖自检
set "PORT=7788"
set "PORTOK=0"

:preflight_done
if "%ANIME_DRYRUN%"=="1" goto :dryrun

rem ---- 5. 后台启动（pythonw + start 分离，控制台窗口不会常驻） ----------------
if not exist "%PROJDIR%\data" mkdir "%PROJDIR%\data"
echo [3/3] 正在后台启动…
start "" /b "%PYW%" -m app.main >> "%PROJDIR%\data\console.log" 2>&1

if not defined PY goto :urlunknown
if "%PORTOK%"=="0" goto :urlunknown
"%PY%" -c "import socket,sys,time;p=int(sys.argv[1]);ok=any([(time.sleep(0.4) or socket.socket().connect_ex(('127.0.0.1',p))==0) for _ in range(15)]);print('READY' if ok else 'TIMEOUT')" %PORT% >"%TEMP%\anime_ready.txt" 2>nul
set "READY="
set /p READY=<"%TEMP%\anime_ready.txt"
if /i "%READY%"=="READY" goto :ready
echo.
echo [提示] 6 秒内没有检测到 %PORT% 端口就绪，可能原因：
echo        1. 启动较慢或端口被顺延 —— 请看 "%PROJDIR%\data\console.log" 里打印的实际地址
echo        2. 缺少运行环境 —— 请在项目目录执行 "%PROJDIR%\start-debug.bat" 查看报错
goto :done

:ready
echo.
echo [成功] 服务已就绪： http://127.0.0.1:%PORT%/
echo        日志文件：   "%PROJDIR%\data\app.log"
goto :done

:urlunknown
echo.
echo [提示] 已发出启动命令，但无法确定最终端口，实际地址请看：
echo        "%PROJDIR%\data\console.log" 里 "打开浏览器访问" 那一行

:done
echo.
echo 服务在后台运行，本窗口可以关闭。
pause
exit /b 0

:dryrun
echo [dry-run] 将要执行： start "" /b "%PYW%" -m app.main
echo [dry-run] 工作目录： %PROJDIR%
echo [dry-run] 未启动任何进程，也没有修改任何文件。
exit /b 0

:no_python
echo.
echo [错误] 没有找到 pythonw.exe，无法启动。
echo        请安装 Python 3.10 或更高版本，安装时勾选 "Add python.exe to PATH"。
echo        下载地址： https://www.python.org/downloads/windows/
echo.
pause
exit /b 1

:bad_deps
echo.
echo [错误] 依赖自检失败：无法导入 app.main。错误输出如下：
type "%TEMP%\anime_preflight.txt"
echo.
echo        请确认本目录下 app 子目录完整，且使用的是标准版 Python 3.10 以上。
echo.
pause
exit /b 1
