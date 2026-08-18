# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：内置 Playwright Chromium，用户无需安装浏览器。

构建前需先执行（build.bat / CI 已内置）：
    set PLAYWRIGHT_BROWSERS_PATH=browsers
    playwright install chromium
"""
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# greenlet（playwright 依赖的 C 扩展）动态库
binaries += collect_dynamic_libs("greenlet")

# 内置浏览器目录（构建机本地 browsers/ 文件夹，随 exe 一起分发）
import os

if os.path.isdir("browsers"):
    datas += [("browsers", "browsers")]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="千牛数据抓取工具",
    console=False,   # 无命令行黑窗口
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="千牛数据抓取工具",
    upx=False,
)
