"""主窗口界面（PySide6，纯中文）。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config import DEFAULT_URL, AppConfig, load_config, save_config
from .worker import ScrapeWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("千牛数据抓取工具")
        self.resize(820, 640)
        self._worker: ScrapeWorker | None = None
        self._build_ui()
        self._try_auto_load()

    # ---------- 界面搭建 ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        form_box = QGroupBox("运行参数")
        form = QFormLayout(form_box)
        self.url_edit = QLineEdit(DEFAULT_URL)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("淘宝登录账号（支持 主账号:子账号 格式）")
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)  # 密码掩码，不显示明文
        self.pwd_edit.setPlaceholderText("登录密码")
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Excel 导出文件夹")
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._choose_dir)
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 600)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setSuffix(" 秒")
        form.addRow("目标网站URL", self.url_edit)
        form.addRow("登录账号", self.user_edit)
        form.addRow("登录密码", self.pwd_edit)
        form.addRow("导出路径", path_row)
        form.addRow("页面加载超时", self.timeout_spin)
        root.addWidget(form_box)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始执行")
        self.stop_btn = QPushButton("停止任务")
        self.save_btn = QPushButton("保存配置")
        self.load_btn = QPushButton("加载配置")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn.clicked.connect(self._on_stop)
        self.save_btn.clicked.connect(self._on_save_config)
        self.load_btn.clicked.connect(self._on_load_config)
        self.stop_btn.setEnabled(False)
        for b in (self.start_btn, self.stop_btn, self.save_btn, self.load_btn):
            b.setMinimumHeight(36)
            btn_row.addWidget(b)
        root.addLayout(btn_row)

        log_box = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setStyleSheet("background:#ffffff; color:#1a1a1a;")
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box, stretch=1)

    # ---------- 目录选择 ----------

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "选择 Excel 导出文件夹", self.path_edit.text() or str(Path.home())
        )
        if d:
            self.path_edit.setText(d)

    # ---------- 任务控制 ----------

    def _on_start(self) -> None:
        url = self.url_edit.text().strip()
        user = self.user_edit.text().strip()
        pwd = self.pwd_edit.text()
        out = self.path_edit.text().strip()
        if not url:
            return self._warn("请填写目标网站 URL")
        if not user:
            return self._warn("请填写登录账号")
        if not pwd:
            return self._warn("请填写登录密码")
        if not out or not Path(out).is_dir():
            return self._warn("请选择有效的导出文件夹")
        cfg = AppConfig(
            url=url,
            username=user,
            password=pwd,
            export_dir=out,
            page_timeout=self.timeout_spin.value(),
        )
        self._append_log("info", "任务启动。")
        self._set_running(True)
        self._worker = ScrapeWorker(cfg)
        self._worker.signals.log.connect(self._append_log)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    def _on_finished(self, success: bool, message: str) -> None:
        self._set_running(False)
        if success:
            QMessageBox.information(self, "任务结束", message)
        else:
            QMessageBox.warning(self, "任务结束", message)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        for w in (
            self.url_edit, self.user_edit, self.pwd_edit, self.path_edit,
            self.timeout_spin, self.save_btn, self.load_btn,
        ):
            w.setEnabled(not running)

    # ---------- 配置 ----------

    def _on_save_config(self) -> None:
        cfg = AppConfig(
            url=self.url_edit.text().strip() or DEFAULT_URL,
            username=self.user_edit.text().strip(),
            password=self.pwd_edit.text(),
            export_dir=self.path_edit.text().strip(),
            page_timeout=self.timeout_spin.value(),
        )
        path = save_config(cfg)
        self._append_log("success", f"配置已保存：{path}（密码已加密存储，仅保存在本机）")

    def _on_load_config(self) -> None:
        cfg = load_config()
        if cfg is None:
            self._append_log("warn", "未找到本地配置文件。")
            return
        self.url_edit.setText(cfg.url)
        self.user_edit.setText(cfg.username)
        self.pwd_edit.setText(cfg.password)
        self.path_edit.setText(cfg.export_dir)
        self.timeout_spin.setValue(cfg.page_timeout)
        self._append_log("success", "配置已加载并回填表单。")

    def _try_auto_load(self) -> None:
        """启动时自动加载本地配置（若存在）。"""
        cfg = load_config()
        if cfg is None:
            return
        self.url_edit.setText(cfg.url)
        self.user_edit.setText(cfg.username)
        self.pwd_edit.setText(cfg.password)
        self.path_edit.setText(cfg.export_dir)
        self.timeout_spin.setValue(cfg.page_timeout)

    # ---------- 日志 ----------

    _LEVEL_COLORS = {"info": "#333333", "success": "#1e7d32", "warn": "#b26a00", "error": "#c62828"}

    def _append_log(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self._LEVEL_COLORS.get(level, "#333333")))
        self.log_view.setCurrentCharFormat(fmt)
        self.log_view.appendPlainText(f"[{ts}][{level.upper()}] {message}")

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "提示", text)

    # ---------- 退出清理 ----------

    def closeEvent(self, event) -> None:
        if self._worker and self._worker.isRunning():
            ret = QMessageBox.question(
                self, "确认退出",
                "任务仍在运行，退出将停止任务并关闭浏览器。确定退出吗？",
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.stop()
            self._worker.wait(15000)
        event.accept()
