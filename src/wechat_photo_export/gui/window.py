"""Qt Widgets 界面只管理选择和呈现；耗时工作调用后台服务。"""
import threading
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog, QDialog)

from .. import __version__
from ..core.errors import MESSAGES, error_code
from ..core.files import write_json
from ..platforms.decoder import Decoder
from ..platforms.windows import decoder_path, image_keys, wechat_version
from ..services.accounts import account_at, default_output, discover_accounts
from ..services.catalog import refresh_names, sessions
from ..services.jobs import build_plan, export
from ..services.state import State


class Worker(QThread):
    update = Signal(object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.cancel = threading.Event()
        self.last_update = 0.0

    def progress(self, value):
        now = time.monotonic()
        if isinstance(value, str) or now-self.last_update >= 0.1:
            self.last_update = now
            self.update.emit(value)

    def run(self):
        try:
            value = self.operation(self.cancel.is_set, self.progress)
            self.done.emit(value)
        except Exception as exc:
            self.failed.emit(error_code(exc))


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"微信照片导出助手 {__version__}")
        self.resize(1020, 760)
        self.worker = None
        self.plan = None
        self.accounts = []
        self.rows = []
        self.selected = set()
        self.last_error = ""
        self.last_result = None
        self.closing = False
        self.population = False
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("把微信里的照片，保存到自己的文件夹")
        title.setStyleSheet("font-size:20px;font-weight:600")
        layout.addWidget(title)
        self.capability = QLabel("Windows 4.x · 仅导出高清 / 大图 · 本机处理")
        layout.addWidget(self.capability)
        account_row = QHBoxLayout()
        account_row.addWidget(QLabel("微信账号"))
        self.account_box = QComboBox()
        self.account_box.setMinimumWidth(360)
        self.account_box.addItem("请选择账号", None)
        self.account_box.currentIndexChanged.connect(self.account_changed)
        account_row.addWidget(self.account_box, 1)
        self.choose_account = QPushButton("选择账号目录")
        self.choose_account.clicked.connect(self.pick_account)
        account_row.addWidget(self.choose_account)
        self.refresh = QPushButton("刷新群名 / 用户名")
        self.refresh.clicked.connect(self.refresh_catalog)
        account_row.addWidget(self.refresh)
        layout.addLayout(account_row)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索群名、备注或会话编号")
        self.search.textChanged.connect(self.filter_rows)
        filters.addWidget(self.search, 1)
        self.kind = QComboBox()
        self.kind.addItems(["全部类型", "群聊", "单聊", "待识别"])
        self.kind.currentTextChanged.connect(self.filter_rows)
        filters.addWidget(self.kind)
        self.select_all = QPushButton("勾选全部会话")
        self.select_all.clicked.connect(lambda: self.set_selection(True))
        filters.addWidget(self.select_all)
        self.clear = QPushButton("清空选择")
        self.clear.clicked.connect(lambda: self.set_selection(False))
        filters.addWidget(self.clear)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["导出", "会话名称", "类型", "名称来源", "会话编号"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(4, 170)
        self.table.itemChanged.connect(self.selection_changed)
        layout.addWidget(self.table, 1)
        self.count = QLabel("请选择账号，再勾选需要导出的会话。")
        layout.addWidget(self.count)
        manual_row = QHBoxLayout()
        self.rename = QPushButton("人工确认当前会话名称")
        self.rename.clicked.connect(self.confirm_name)
        manual_row.addWidget(self.rename)
        self.photo_preview = QPushButton("预览当前会话照片")
        self.photo_preview.clicked.connect(self.preview_photos)
        manual_row.addWidget(self.photo_preview)
        manual_row.addWidget(QLabel("未识别的会话按编号保存；勾选全部会包含单聊。"), 1)
        layout.addLayout(manual_row)
        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("保存位置"))
        self.output = QLineEdit()
        self.output.textChanged.connect(self.invalidate_plan)
        output_row.addWidget(self.output, 1)
        self.choose_output = QPushButton("浏览…")
        self.choose_output.clicked.connect(self.pick_output)
        output_row.addWidget(self.choose_output)
        layout.addLayout(output_row)
        self.status = QLabel("正在发现本机账号…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        actions = QHBoxLayout()
        self.preview = QPushButton("1. 预览导出")
        self.preview.clicked.connect(self.preview_export)
        actions.addWidget(self.preview)
        self.start = QPushButton("2. 开始导出 / 继续")
        self.start.clicked.connect(self.start_export)
        actions.addWidget(self.start)
        self.cancel = QPushButton("取消")
        self.cancel.clicked.connect(self.cancel_work)
        actions.addWidget(self.cancel)
        actions.addStretch()
        self.open_output = QPushButton("打开保存目录")
        self.open_output.clicked.connect(lambda: self.open_path(Path(self.output.text())))
        actions.addWidget(self.open_output)
        self.open_index = QPushButton("照片索引")
        self.open_index.clicked.connect(lambda: self.open_path(Path(self.output.text())/"_索引.html"))
        actions.addWidget(self.open_index)
        layout.addLayout(actions)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("源文件只读 · 已有照片保留 · 取消后可继续"), 1)
        self.diagnostics = QPushButton("导出脱敏诊断")
        self.diagnostics.clicked.connect(self.save_diagnostics)
        footer.addWidget(self.diagnostics)
        layout.addLayout(footer)
        self.controls = [self.account_box, self.choose_account, self.refresh, self.search, self.kind,
                         self.select_all, self.clear, self.rename, self.photo_preview, self.output, self.choose_output,
                         self.preview, self.table, self.open_output, self.open_index, self.diagnostics]
        self.busy_controls(False)
        self.run_task(lambda cancel, progress: (discover_accounts(), wechat_version()), self.discovered)

    def account(self):
        return self.account_box.currentData()

    def busy_controls(self, busy):
        for control in self.controls:
            control.setEnabled(not busy)
        self.cancel.setEnabled(busy)
        self.start.setEnabled(not busy and self.plan is not None and bool(self.plan.items))

    def run_task(self, operation, success):
        if self.worker:
            return
        self.busy_controls(True)
        self.progress_bar.setRange(0, 0)
        worker = Worker(operation, self)
        self.worker = worker
        worker.update.connect(self.update_progress)
        worker.done.connect(success)
        worker.failed.connect(self.show_error)
        worker.finished.connect(self.task_finished)
        worker.start()

    def task_finished(self):
        worker = self.worker
        self.worker = None
        worker.deleteLater()
        self.busy_controls(False)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(1)
        if self.closing:
            self.close()

    def discovered(self, value):
        accounts, version = value
        self.accounts = accounts
        self.population = True
        for account in accounts:
            self.account_box.addItem(account.label, account)
            self.account_box.setItemData(self.account_box.count()-1, str(account.root), Qt.ItemDataRole.ToolTipRole)
        self.population = False
        self.capability.setText(f"Windows 微信 {version} · 仅导出高清 / 大图 · 本机处理")
        self.status.setText("请选择要导出的账号。" if accounts else "未自动找到账号，请选择微信账号目录。")

    def account_changed(self):
        if self.population:
            return
        self.selected.clear()
        self.rows.clear()
        self.invalidate_plan()
        self.populate([])
        account = self.account()
        if not account:
            return
        self.output.setText(str(default_output(account)))
        def load(cancel, progress):
            with State(account) as state:
                return sessions(account, state)
        self.run_task(load, self.populate)

    def populate(self, rows):
        self.rows = rows
        self.population = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            check.setData(Qt.ItemDataRole.UserRole, row.full_hash)
            check.setCheckState(Qt.CheckState.Checked if row.full_hash in self.selected else Qt.CheckState.Unchecked)
            self.table.setItem(row_index, 0, check)
            for column, value in enumerate([row.name, row.kind, {"db": "数据库", "user": "人工确认", "none": "待确认"}.get(row.source, "待确认"), row.full_hash[:16]], 1):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, row.full_hash)
                item.setToolTip(" / ".join(row.aliases))
                self.table.setItem(row_index, column, item)
        self.table.setSortingEnabled(True)
        self.population = False
        self.filter_rows()
        self.update_count()
        self.status.setText("会话已加载。首次使用请刷新名称，然后勾选会话。")

    def filter_rows(self):
        query, kind = self.search.text().strip().casefold(), self.kind.currentText()
        by_hash = {row.full_hash: row for row in self.rows}
        for index in range(self.table.rowCount()):
            row = by_hash[self.table.item(index, 0).data(Qt.ItemDataRole.UserRole)]
            visible = (kind == "全部类型" or row.kind == kind) and (not query or
                query in " ".join((row.name, row.full_hash, *row.aliases)).casefold())
            self.table.setRowHidden(index, not visible)

    def selection_changed(self, item):
        if self.population or item.column() != 0:
            return
        full_hash = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.selected.add(full_hash)
        else:
            self.selected.discard(full_hash)
        self.invalidate_plan()
        self.update_count()

    def set_selection(self, checked):
        for index in range(self.table.rowCount()):
            self.table.item(index, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def update_count(self):
        self.count.setText(f"共 {len(self.rows)} 个会话，已选 {len(self.selected)} 个（包含搜索后隐藏的已选项）。")

    def invalidate_plan(self):
        self.plan = None
        self.start.setEnabled(False)

    def pick_account(self):
        path = QFileDialog.getExistingDirectory(self, "选择微信账号目录（其下有 msg/attach）")
        if not path:
            return
        try:
            account = account_at(path)
        except Exception as exc:
            self.show_error(error_code(exc))
            return
        index = next((i for i in range(1, self.account_box.count()) if self.account_box.itemData(i).uid == account.uid), None)
        if index is None:
            self.account_box.addItem(account.label, account)
            index = self.account_box.count()-1
        self.account_box.setCurrentIndex(index)

    def pick_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择照片保存目录", self.output.text())
        if path:
            self.output.setText(path)

    def refresh_catalog(self):
        account = self.account()
        if not account:
            self.status.setText("请先选择账号。")
            return
        self.invalidate_plan()
        def refresh(cancel, progress):
            with State(account) as state:
                return refresh_names(account, state, cancel, progress)
        self.run_task(refresh, self.populate)

    def confirm_name(self):
        account, row = self.account(), self.table.currentRow()
        if account is None or row < 0:
            self.status.setText("请先点击需要确认名称的会话行。")
            return
        full_hash = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        name, accepted = QInputDialog.getText(self, "人工确认名称", "请核对微信中的会话名称，编号："+full_hash[:16])
        if not accepted or not name.strip():
            return
        self.invalidate_plan()
        def confirm(cancel, progress):
            with State(account) as state:
                state.confirm_name(full_hash, name)
                return sessions(account, state)
        self.run_task(confirm, self.populate)

    def preview_photos(self):
        account, row = self.account(), self.table.currentRow()
        if account is None or row < 0:
            self.status.setText("请先点击需要查看照片的会话行。")
            return
        full_hash = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        def preview(cancel, progress):
            from ..services.preview import preview_images
            with State(account) as state:
                return preview_images(account, state, full_hash, cancel, progress)
        self.run_task(preview, self.show_photos)

    def show_photos(self, images):
        if not images:
            self.status.setText("此会话在本机没有可预览的高清 / 大图。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("当前会话照片预览")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("少量高清照片预览，仅在内存中显示。"))
        strip = QHBoxLayout()
        for data in images:
            pixmap = QPixmap()
            pixmap.loadFromData(data, "PNG")
            label = QLabel()
            label.setPixmap(pixmap.scaled(280, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
            strip.addWidget(label)
        layout.addLayout(strip)
        dialog.show()
        self.status.setText("会话照片预览已打开；没有生成缩略图文件。")

    def preview_export(self):
        account = self.account()
        if account is None or not self.selected or not self.output.text().strip():
            self.status.setText("请选择账号、勾选会话，并指定保存位置。")
            return
        selected, output = tuple(self.selected), self.output.text()
        def preview(cancel, progress):
            with State(account) as state:
                return build_plan(account, state, selected, output, cancel, progress)
        self.run_task(preview, self.plan_ready)

    def plan_ready(self, plan):
        self.plan = plan
        self.status.setText(f"预览：{len(plan.directories)} 个会话，{len(plan.items)} 张高清 / 大图，"
            f"源文件 {plan.source_bytes/1024**3:.2f} GB。转换后容量可能增加；已完成且未变的图片会跳过。")

    def start_export(self):
        account, plan = self.account(), self.plan
        if account is None or plan is None:
            return
        def run(cancel, progress):
            with State(account) as state:
                keys = image_keys(account, state, cancel, progress)
                decoder = Decoder(decoder_path())
                try:
                    return export(plan, state, keys, decoder, cancel, progress)
                finally:
                    decoder.close()
        self.run_task(run, self.export_done)

    def update_progress(self, value):
        if isinstance(value, str):
            self.status.setText(value)
        else:
            done = value.completed+value.skipped+value.failed+value.pending_conversion
            self.progress_bar.setRange(0, max(1, value.total))
            self.progress_bar.setValue(done)
            self.status.setText(f"已处理 {done}/{value.total} · 新导出 {value.completed} · 已完成 {value.skipped} · "
                                f"失败 {value.failed} · 待转换 {value.pending_conversion}")

    def export_done(self, result):
        self.last_result = result
        self.update_progress(result)
        suffix = "任务已取消，可重新预览后继续。" if result.cancelled else "已完成本轮处理。重新预览后可重试失败项。"
        errors = " ".join(MESSAGES[code]+f"（{count}项）" for code, count in result.errors.items())
        self.status.setText(self.status.text()+"\n"+suffix+("\n"+errors if errors else ""))
        self.invalidate_plan()

    def show_error(self, code):
        self.last_error = code
        self.status.setText(MESSAGES.get(code, MESSAGES["unexpected"])+" 错误码："+code)

    def cancel_work(self):
        if self.worker:
            self.worker.cancel.set()
            self.cancel.setEnabled(False)
            self.status.setText("正在取消，已完成的文件会保留…")

    def closeEvent(self, event):
        if self.worker:
            self.closing = True
            self.cancel_work()
            event.ignore()
        else:
            event.accept()

    def open_path(self, path):
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.absolute())))

    def save_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存脱敏诊断", "wechat-photo-diagnostics.json", "JSON (*.json)")
        if path:
            try:
                # 白名单字段：不附带目录、账号、名称、会话 hash、密钥或照片。
                report = {"app_version": __version__, "platform": "windows-x64", "last_error": self.last_error}
                if self.last_result:
                    report["counts"] = {key: value for key, value in asdict(self.last_result).items()
                                        if key != "errors"}
                    report["error_codes"] = self.last_result.errors
                write_json(path, report)
                self.status.setText("诊断报告已保存，内容仅含版本、计数及错误码。")
            except Exception as exc:
                self.show_error(error_code(exc))


def launch():
    from ..platforms.windows import require_windows
    require_windows()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("WeChatPhotoExport")
    app.setOrganizationName("WeChatPhotoExport")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = Window()
    window.show()
    return app.exec()
