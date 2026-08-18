"""程序入口。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _setup_playwright_browsers() -> None:
    """打包环境：把 Playwright 内置浏览器目录指向程序自带的 browsers/。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        browsers = base / "browsers"
        if browsers.is_dir():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def main() -> int:
    _setup_playwright_browsers()
    from PySide6.QtWidgets import QApplication

    from app.gui import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
