@echo off
rem ===========================================================================
rem  自动下载番剧 - 取消开机自启动（删除计划任务 AnimeAutoDownloader）
rem  只预览不删除：先执行  set ANIME_DRYRUN=1  再运行本文件
rem ===========================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title 自动下载番剧 - 取消开机自启动
if not defined ANIME_DRYRUN set "ANIME_DRYRUN=0"
set "TASKNAME=AnimeAutoDownloader"

echo ============================================================
echo   取消开机自启动
echo ============================================================
echo.

schtasks /Query /TN "%TASKNAME%" >nul 2>&1
if errorlevel 1 goto :not_found

echo 将要删除的计划任务：
schtasks /Query /TN "%TASKNAME%"
echo.

if "%ANIME_DRYRUN%"=="1" goto :dryrun

schtasks /Delete /TN "%TASKNAME%" /F
if errorlevel 1 goto :delete_failed

echo.
echo [验证] 再次查询该任务：
schtasks /Query /TN "%TASKNAME%" >nul 2>&1
if errorlevel 1 goto :deleted
echo [警告] 删除命令已执行，但任务仍然存在，请以管理员身份重试。
echo.
pause
exit /b 1

:deleted
echo 已确认删除：查询不到 %TASKNAME% 了。
echo.
echo 开机自启动已取消。start.bat 仍然可以随时手动启动。
echo.
pause
exit /b 0

:dryrun
echo [dry-run] 将要执行： schtasks /Delete /TN "%TASKNAME%" /F
echo [dry-run] 未删除任何计划任务。
exit /b 0

:not_found
echo [信息] 没有找到计划任务 %TASKNAME%，无需删除。
echo.
echo 自己确认的命令： schtasks /Query /TN "%TASKNAME%"
echo.
if "%ANIME_DRYRUN%"=="1" exit /b 0
pause
exit /b 0

:delete_failed
echo.
echo [错误] 删除失败，请右键本文件选「以管理员身份运行」后重试。
echo.
pause
exit /b 1
