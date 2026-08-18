"""后台工作线程：asyncio 事件循环 + Playwright 生命周期 + 停止与清理。

停止语义（保证"不留后台残留进程"）：
1. GUI 线程调用 stop() → 置停止标志 + call_soon_threadsafe 关闭浏览器；
2. 正在执行的步骤在下一次检查点（_check_stop）抛出 TaskStopped；
3. finally 中依次关闭 context/browser/playwright 驱动；
4. 兜底：kill_orphan_browsers 按"可执行文件位于本程序目录内"精确清理
   残留 chromium 进程——绝不误杀用户自装的 Chrome。
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import psutil
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
from PySide6.QtCore import QObject, QThread, Signal

from .config import AppConfig
from .excel_export import build_output_path, export_to_excel
from .steps import StepsContext, TaskStopped, run_builtin_flow


class WorkerSignals(QObject):
    log = Signal(str, str)          # (级别, 消息)
    finished = Signal(bool, str)    # (是否成功, 摘要/错误信息)


class ScrapeWorker(QThread):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._signals = WorkerSignals()
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._temp_dir: Path | None = None

    @property
    def signals(self) -> WorkerSignals:
        return self._signals

    def stop(self) -> None:
        """线程安全停止：置停止标志 + 在主事件循环中关闭浏览器。"""
        self._log("warn", "收到停止指令，正在关闭浏览器…")
        self._stop_event.set()
        loop = self._loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._close_browser(), loop)

    def _log(self, level: str, msg: str) -> None:
        self._signals.log.emit(level, msg)

    # ---------- 线程体 ----------

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._run_async())
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            finally:
                self._loop.close()
                self._loop = None

    async def _run_async(self) -> None:
        try:
            self._log("info", "正在启动内置浏览器（首次启动稍慢，请稍候）…")
            sink: list = []  # 中途停止时尽力导出的已抓数据
            self._temp_dir = Path(tempfile.mkdtemp(prefix="qn-scraper-"))
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=False,  # 有头模式：用户可见并可手动处理验证码
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1440, "height": 900},
                locale="zh-CN",
            )
            page = await self._context.new_page()
            page.set_default_timeout(self._cfg.page_timeout * 1000)

            ctx = StepsContext(
                log=self._log,
                stop_event=self._stop_event,
                timeout_ms=self._cfg.page_timeout * 1000,
                context=self._context,
                temp_dir=self._temp_dir,
                rows_sink=sink,
            )
            result = await run_builtin_flow(page, self._cfg, ctx)

            if result.rows:
                out = build_output_path(self._cfg.export_dir)
                export_to_excel(result.rows, out)
                self._log("success", f"导出成功：共 {len(result.rows)} 条数据 → {out}")
                self._signals.finished.emit(True, f"任务完成！共抓取 {len(result.rows)} 条数据。\nExcel 已保存到：{out}")
            else:
                self._log("warn", "未抓到任何数据，未生成 Excel 文件。")
                self._signals.finished.emit(False, "任务结束，但未抓到任何数据。请检查页面状态或联系开发者调整定位器。")
        except TaskStopped:
            self._log("warn", "任务已停止。")
            n = export_partial_rows(sink, self._cfg.export_dir, self._log)
            msg = "任务已停止。" + (f"已导出停止前抓取的 {n} 条数据。" if n else "")
            self._signals.finished.emit(False, msg)
        except Exception as e:
            if self._stop_event.is_set():
                self._log("warn", "任务已停止。")
                self._signals.finished.emit(False, "任务已停止。")
            else:
                self._log("error", f"任务失败：{type(e).__name__}: {e}")
                self._signals.finished.emit(False, f"任务失败：{e}")
        finally:
            await self._cleanup()

    async def _close_browser(self) -> None:
        """在事件循环线程内关闭浏览器（触发在途操作报错 → 流程退出）。"""
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass

    async def _cleanup(self) -> None:
        """关闭浏览器 + 清理临时图片目录 + 兜底清理残留进程。"""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        if self._temp_dir:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
        # 兜底：清理本程序目录下的残留 chromium 进程
        app_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        killed = kill_orphan_browsers(app_dir)
        if killed:
            self._log("info", f"已清理 {killed} 个残留浏览器进程。")
        else:
            self._log("info", "浏览器已关闭，后台进程已清理。")


# ---------- 进程清理（纯函数 + 扫描） ----------

_BROWSER_NAME_PREFIXES = ("chrome", "headless", "msedge")


def is_our_browser_proc(name: str, exe: str, app_dir: Path) -> bool:
    """判断进程是否为本程序内置的浏览器：名称像浏览器 且 可执行文件位于 app_dir 内。"""
    if not name or not exe:
        return False
    if not name.lower().startswith(_BROWSER_NAME_PREFIXES):
        return False
    try:
        # 归一化分隔符：Windows 部署下 psutil 返回 Windows 路径（Path 原生支持）；
        # 在 POSIX 开发机/测试机上反斜杠只是普通字符，统一替换为平台分隔符后可
        # 与跨平台路径字符串正确比较（Windows 上替换是无害的 no-op）。
        exe_path = Path(exe.replace("\\", os.sep))
        app_path = Path(str(app_dir).replace("\\", os.sep))
        return app_path.resolve() in exe_path.resolve().parents
    except Exception:
        return False


def kill_orphan_browsers(app_dir: Path) -> int:
    """杀掉可执行文件位于本程序目录内的浏览器进程（不误伤用户自装浏览器）。"""
    killed = 0
    try:
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = proc.info
                if is_our_browser_proc(info.get("name") or "", info.get("exe") or "", app_dir):
                    proc.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return killed


def export_partial_rows(sink: list, export_dir: str, log) -> int:
    """停止时尽力导出已抓数据。返回导出条数；空则 0 且不生成文件。"""
    if not sink:
        return 0
    try:
        out = build_output_path(export_dir)
        export_to_excel(sink, out)
        log("success", f"已导出停止前抓取的 {len(sink)} 条数据 → {out}")
        return len(sink)
    except Exception as e:
        log("warn", f"停止时导出失败：{e}")
        return 0
