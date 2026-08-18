@echo off
chcp 65001 >nul
REM ================================================
REM   千牛数据抓取工具 - Windows 一键打包脚本
REM   双击运行即可（需联网下载依赖，约 5-15 分钟）
REM   前提：已安装 Python 3.12 并勾选 "Add to PATH"
REM ================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.12：https://www.python.org/downloads/
    echo        安装时务必勾选 "Add python.exe to PATH"
    pause & exit /b 1
)

echo [1/4] 安装依赖...
python -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 (echo [错误] 依赖安装失败 & pause & exit /b 1)

echo [2/4] 下载内置浏览器（约150MB）...
set PLAYWRIGHT_BROWSERS_PATH=browsers
python -m playwright install chromium
if errorlevel 1 (echo [错误] 浏览器下载失败，请检查网络 & pause & exit /b 1)

echo [3/4] 打包 exe（约 3-10 分钟，请耐心等待）...
python -m PyInstaller scraper.spec --noconfirm
if errorlevel 1 (echo [错误] 打包失败，请把报错截图反馈给开发者 & pause & exit /b 1)

echo [4/4] 完成！产物在 dist\千牛数据抓取工具\ 目录，双击 千牛数据抓取工具.exe 即可运行。
pause
