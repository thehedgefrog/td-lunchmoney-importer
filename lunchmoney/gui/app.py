"""PySide6 GUI application for TD Lunch Money Importer."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ofxparse import OfxParser
from PySide6.QtCore import QDate, QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lunchmoney.api import ImportResult, import_transactions
from lunchmoney.config import ConfigurationState, load_config, save_config
from lunchmoney.qfx import check_new_accounts, format_transactions
from lunchmoney.utils import setup_logging

logger = logging.getLogger(__name__)

_FONT_STACK  = "'Segoe UI', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif"
_MONO_STACK  = "'Cascadia Code', 'JetBrains Mono', 'Consolas', 'Courier New', monospace"
_CHECK_SVG = (Path(__file__).parent.parent.parent / "resources" / "check_blue.svg").resolve().as_uri()


def _bundle_base_path() -> Path:
    """Return base path for source and PyInstaller onefile runs."""
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent.parent


def _build_app_icon() -> QIcon:
    """Build app icon from available resources, with platform-aware fallbacks."""
    base = _bundle_base_path()
    icon = QIcon()

    if sys.platform == "darwin":
        candidates = [
            base / "resources" / "lmfinal-mac.icns",
            base / "resources" / "main.png",
            base / "resources" / "lmfinal-128.ico",
            base / "resources" / "lmfinal-64.ico",
            base / "resources" / "lmfinal-32.ico",
        ]
    else:
        # Avoid loading .icns on Windows/Linux to prevent JP2 decode warnings.
        candidates = [
            base / "resources" / "lmfinal-128.ico",
            base / "resources" / "lmfinal-64.ico",
            base / "resources" / "lmfinal-32.ico",
            base / "resources" / "main.png",
        ]

    for candidate in candidates:
        if candidate.exists():
            icon.addFile(str(candidate))
    return icon


def _set_windows_app_id() -> None:
    """Ensure taskbar groups/pins use this app's identity on Windows."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "td.lunchmoney.importer"
        )
    except Exception:
        logger.exception("Could not set Windows AppUserModelID")

# ---------------------------------------------------------------------------
# Worker infrastructure
# ---------------------------------------------------------------------------


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any):
        super().__init__()
        self._fn = fn
        self._args = args
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self._fn(*self._args)
            self.signals.finished.emit(result)
        except Exception as exc:
            logger.exception("Background worker failed")
            self.signals.error.emit(str(exc))


# ---------------------------------------------------------------------------
# API Key wizard
# ---------------------------------------------------------------------------


class ApiKeyWizard(QDialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Connect to Lunch Money")
        self.setModal(True)
        self.setFixedSize(500, 230)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(28, 24, 28, 20)

        heading = QLabel("Connect your Lunch Money account")
        heading.setObjectName("wizardHeading")
        layout.addWidget(heading)

        desc = QLabel(
            "Enter your API key from <b>Lunch Money → Developer Settings</b>. "
            "It is saved securely and used to reconnect automatically."
        )
        desc.setWordWrap(True)
        desc.setObjectName("wizardDesc")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(8)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("lm-••••••••••••••••••••")
        form.addRow("API key", self.api_key_input)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryButton")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        self.connect_btn = QPushButton("Verify && Connect")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self.connect_btn)
        layout.addLayout(btn_row)

    def _on_connect(self) -> None:
        if not self.api_key_input.text().strip():
            QMessageBox.warning(self, "API Key Required", "Please paste your Lunch Money API key.")
            return
        self.accept()

    def api_key(self) -> str:
        return self.api_key_input.text().strip()


# ---------------------------------------------------------------------------
# Account mapping dialog
# ---------------------------------------------------------------------------


class MappingDialog(QDialog):
    """Guided account-to-asset mapping wizard."""

    def __init__(
        self,
        parent: QWidget,
        qfx_accounts: List[Any],
        api_accounts: List[Any],
        existing_mapping: Dict[str, int],
    ):
        super().__init__(parent)
        self.setObjectName("mappingDialog")
        self.setWindowTitle("Map Accounts")
        self.setModal(True)
        self.resize(560, 380)

        self._mapping: Dict[str, int] = dict(existing_mapping)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        heading = QLabel("Link each TD account to a Lunch Money account")
        heading.setObjectName("wizardHeading")
        layout.addWidget(heading)

        desc = QLabel("This is a one-time setup — your mappings are saved automatically.")
        desc.setObjectName("wizardDesc")
        layout.addWidget(desc)

        form = QFormLayout()
        form.setSpacing(10)

        self._combos: Dict[str, QComboBox] = {}
        seen: set = set()
        asset_options = [(a.id, f"{a.name}  ({a.institution_name})") for a in api_accounts]

        for account in qfx_accounts:
            aid = account.account_id
            if aid in seen:
                continue
            seen.add(aid)

            combo = QComboBox()
            combo.addItem("Select Lunch Money account…", None)
            for asset_id, label in asset_options:
                combo.addItem(label, asset_id)

            if aid in self._mapping:
                idx = combo.findData(self._mapping[aid])
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.currentIndexChanged.connect(
                lambda _i, qid=aid, c=combo: self._on_changed(qid, c)
            )
            self._combos[aid] = combo

            display = f"TD  ···{aid[-6:]}" if len(aid) > 6 else f"TD  {aid}"
            form.addRow(display, combo)

        layout.addLayout(form)
        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        self.save_btn = QPushButton("Save Mapping")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._save)
        btn_row.addWidget(self.save_btn)
        layout.addLayout(btn_row)

    def _on_changed(self, qfx_id: str, combo: QComboBox) -> None:
        data = combo.currentData()
        if data is None:
            self._mapping.pop(qfx_id, None)
        else:
            self._mapping[qfx_id] = int(data)

    def _save(self) -> None:
        missing = [aid for aid in self._combos if aid not in self._mapping]
        if missing:
            QMessageBox.warning(
                self,
                "Incomplete Mapping",
                f"Please map all accounts before saving.\nUnmapped: {', '.join(missing)}",
            )
            return
        self.accept()

    def mapping(self) -> Dict[str, int]:
        return self._mapping


# ---------------------------------------------------------------------------
# Drop zone widget
# ---------------------------------------------------------------------------


class DropZone(QFrame):
    """Pretty drag-and-drop target for .qfx files."""

    filesDropped = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(4)

        self._icon = QLabel("⬆")
        self._icon.setObjectName("dropIcon")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)

        self._hint = QLabel("Drop .qfx files here, or use Add Files below")
        self._hint.setObjectName("dropHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)

    def set_compact(self, compact: bool) -> None:
        """Switch between full drop zone and a slim 'drop more' strip."""
        if compact:
            self._icon.hide()
            self._hint.setText("＋  Drop more .qfx files here")
            self.setFixedHeight(38)
        else:
            self._icon.show()
            self._hint.setText("Drop .qfx files here, or use Add Files below")
            self.setMinimumHeight(80)
            self.setMaximumHeight(16777215)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.setStyleSheet(
                "#dropZone { background:#eff6ff; border:2px solid #3b82f6; border-radius:10px; }"
            )
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        dropped = [
            str(Path(url.toLocalFile()))
            for url in event.mimeData().urls()
            if Path(url.toLocalFile()).exists()
            and url.toLocalFile().lower().endswith(".qfx")
        ]
        if dropped:
            self.filesDropped.emit(dropped)
        event.acceptProposedAction()


class WindowTitleBar(QFrame):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._window = window
        self._drag_offset: Optional[QPoint] = None
        self.setObjectName("windowTitleBar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        title = QLabel("TD → Lunch Money Importer")
        title.setObjectName("windowTitleLabel")
        layout.addWidget(title)
        layout.addStretch()

        self.minimize_btn = QPushButton("−")
        self.minimize_btn.setObjectName("windowControlButton")
        self.minimize_btn.clicked.connect(self._window.showMinimized)
        layout.addWidget(self.minimize_btn)

        self.maximize_btn = QPushButton("□")
        self.maximize_btn.setObjectName("windowControlButton")
        self.maximize_btn.clicked.connect(self._toggle_maximized)
        layout.addWidget(self.maximize_btn)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("windowCloseButton")
        self.close_btn.clicked.connect(self._window.close)
        layout.addWidget(self.close_btn)

    def _toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
            self.maximize_btn.setText("□")
        else:
            self._window.showMaximized()
            self.maximize_btn.setText("❐")

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximized()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            self._drag_offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class StyledCheckBox(QCheckBox):
    def __init__(self, text: str, parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self.text()) + 42, max(28, metrics.height() + 8))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        box_size = 20
        box_x = 4
        box_y = (self.height() - box_size) // 2

        border_color = QColor("#2563eb") if self.isChecked() else QColor("#94a3b8")
        fill_color = QColor("#ffffff")
        if self.underMouse():
            fill_color = QColor("#eff6ff") if self.isChecked() else QColor("#f8fafc")

        painter.setPen(QPen(border_color, 1.6))
        painter.setBrush(fill_color)
        painter.drawRoundedRect(box_x, box_y, box_size, box_size, 5, 5)

        if self.isChecked():
            painter.setPen(QPen(QColor("#2563eb"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawLine(box_x + 4, box_y + 11, box_x + 8, box_y + 15)
            painter.drawLine(box_x + 8, box_y + 15, box_x + 16, box_y + 6)

        painter.setPen(QColor("#1e293b"))
        text_rect = self.rect().adjusted(box_x + box_size + 8, 0, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------


@dataclass
class ParsedInput:
    file_path: str
    accounts: List[Any]


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(self, input_files: Optional[List[str]] = None):
        super().__init__()
        self.setWindowTitle("TD → Lunch Money")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.resize(1440, 960)
        self.setMinimumSize(1100, 720)

        icon = _build_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        setup_logging()
        self.state = ConfigurationState()
        self.thread_pool = QThreadPool.globalInstance()

        self.loaded_files: List[str] = []
        self.parsed_inputs: List[ParsedInput] = []
        self.all_qfx_accounts: List[Any] = []
        self.account_mapping: Dict[str, int] = {}
        self.preview_transactions: List[Any] = []
        self.last_import_result: Optional[ImportResult] = None
        self._preview_request_id = 0
        self._saved_api_key: str = ""
        self._active_workers: List[Worker] = []

        self._build_ui()
        self._apply_styles()
        self._load_saved_state()

        if input_files:
            self.add_files(input_files)

        QTimer.singleShot(0, self._startup_auth_flow)

    # -------------------------------------------------------------------
    # UI construction
    # -------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("centralRoot")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = WindowTitleBar(self)
        root_layout.addWidget(self.title_bar)

        body = QWidget()
        outer = QHBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        root_layout.addWidget(body, 1)

        # ── Sidebar (in a scroll area so window shrink never squishes cards) ──
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(18, 18, 18, 18)
        sb.setSpacing(12)

        # Logo: icon + title text
        logo_header = QWidget()
        logo_header.setObjectName("logoHeader")
        logo_header_layout = QHBoxLayout(logo_header)
        logo_header_layout.setContentsMargins(4, 4, 4, 4)
        logo_header_layout.setSpacing(10)

        logo_icon_lbl = QLabel()
        logo_icon_lbl.setObjectName("logoIcon")
        _icon_path = _bundle_base_path() / "resources" / "icon.png"
        if _icon_path.exists():
            _pix = QPixmap(str(_icon_path)).scaled(
                40, 40,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo_icon_lbl.setPixmap(_pix)
        logo_icon_lbl.setFixedSize(40, 40)
        logo_header_layout.addWidget(logo_icon_lbl)

        logo_text_w = QWidget()
        logo_text_layout = QVBoxLayout(logo_text_w)
        logo_text_layout.setContentsMargins(0, 0, 0, 0)
        logo_text_layout.setSpacing(1)
        logo_title = QLabel("TD → Lunch Money")
        logo_title.setObjectName("logoTitle")
        logo_text_layout.addWidget(logo_title)
        logo_subtitle = QLabel("IMPORTER")
        logo_subtitle.setObjectName("logoSubtitle")
        logo_text_layout.addWidget(logo_subtitle)
        logo_header_layout.addWidget(logo_text_w)
        logo_header_layout.addStretch()
        sb.addWidget(logo_header)

        sb.addWidget(self._make_card("Connection", self._build_conn_content(), "_conn_card"))
        sb.addWidget(self._make_card("Import Files", self._build_files_content(), "_files_card"))
        sb.addWidget(self._make_card("Account Mapping", self._build_mapping_content(), "_mapping_card"))
        sb.addWidget(self._make_card("Options", self._build_options_content(), "_options_card"))

        sb.addStretch()

        self.import_button = QPushButton("Import Transactions")
        self.import_button.setObjectName("ctaButton")
        self.import_button.setMinimumHeight(50)
        self.import_button.clicked.connect(self.on_import)
        sb.addWidget(self.import_button)

        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("sidebarScroll")
        sidebar_scroll.setWidget(sidebar)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        sidebar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sidebar_scroll.setFixedWidth(390)
        outer.addWidget(sidebar_scroll)

        # ── Content area ───────────────────────────────────────────────
        content = QFrame()
        content.setObjectName("contentArea")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24, 20, 24, 0)
        cl.setSpacing(12)

        # Preview header
        ph = QHBoxLayout()
        title_lbl = QLabel("Transaction Preview")
        title_lbl.setObjectName("sectionTitle")
        ph.addWidget(title_lbl)
        ph.addStretch()
        self.preview_summary = QLabel("")
        self.preview_summary.setObjectName("previewSummary")
        ph.addWidget(self.preview_summary)
        cl.addLayout(ph)

        # Preview table
        self.preview_data_table = QTableWidget(0, 5)
        self.preview_data_table.setObjectName("previewTable")
        self.preview_data_table.setHorizontalHeaderLabels(
            ["Date", "Payee", "Amount", "Account", "Reference"]
        )
        hdr = self.preview_data_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.preview_data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview_data_table.setAlternatingRowColors(True)
        self.preview_data_table.setShowGrid(False)
        self.preview_data_table.verticalHeader().setVisible(False)
        self.preview_data_table.verticalHeader().setDefaultSectionSize(36)
        cl.addWidget(self.preview_data_table, 1)

        # Logs bar (collapsible)
        self._log_bar = QFrame()
        self._log_bar.setObjectName("logBar")
        lb = QHBoxLayout(self._log_bar)
        lb.setContentsMargins(12, 6, 12, 6)
        log_lbl = QLabel("Activity Log")
        log_lbl.setObjectName("logBarLabel")
        lb.addWidget(log_lbl)
        lb.addStretch()
        self._refresh_log_btn = QPushButton("↻  Refresh")
        self._refresh_log_btn.setObjectName("logActionBtn")
        self._refresh_log_btn.setFlat(True)
        self._refresh_log_btn.clicked.connect(lambda: self.refresh_logs(expand=False))
        lb.addWidget(self._refresh_log_btn)
        self._log_toggle_btn = QPushButton("▼  Show")
        self._log_toggle_btn.setObjectName("logActionBtn")
        self._log_toggle_btn.setFlat(True)
        self._log_toggle_btn.clicked.connect(self._toggle_logs)
        lb.addWidget(self._log_toggle_btn)
        cl.addWidget(self._log_bar)

        self.logs_text = QPlainTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setObjectName("logsText")
        self.logs_text.setFixedHeight(160)
        self.logs_text.hide()
        cl.addWidget(self.logs_text)

        outer.addWidget(content, 1)

        # Status bar
        self.busy_bar = QProgressBar()
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(120)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.hide()
        self.statusBar().addPermanentWidget(self.busy_bar)
        self.statusBar().showMessage("Ready")

    def _make_card(self, title: str, content: QWidget, attr_name: str = "") -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(10)

        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        layout.addWidget(lbl)
        layout.addWidget(content)

        if attr_name:
            setattr(self, attr_name, card)

        return card

    # -- Connection card -------------------------------------------------

    def _build_conn_content(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.connection_label = QLabel("Not connected")
        self.connection_label.setObjectName("connLabel")
        v.addWidget(self.connection_label)

        self.reconnect_button = QPushButton("Update API Key")
        self.reconnect_button.setObjectName("secondaryButton")
        self.reconnect_button.clicked.connect(self.on_update_api_key)
        v.addWidget(self.reconnect_button)
        return w

    # -- Files card ------------------------------------------------------

    def _build_files_content(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        self.drop_zone = DropZone()
        self.drop_zone.filesDropped.connect(self.add_files)
        v.addWidget(self.drop_zone)

        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.file_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.file_list.setFrameShape(QFrame.Shape.NoFrame)
        self.file_list.setSpacing(4)
        self.file_list.setUniformItemSizes(True)
        self.file_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.file_list.hide()
        v.addWidget(self.file_list)

        btn_row = QHBoxLayout()
        self.add_files_btn = QPushButton("Add Files")
        self.add_files_btn.setObjectName("secondaryButton")
        self.add_files_btn.clicked.connect(self.on_add_files)
        btn_row.addWidget(self.add_files_btn)
        self.clear_files_btn = QPushButton("Clear All")
        self.clear_files_btn.setObjectName("dangerButton")
        self.clear_files_btn.clicked.connect(self.on_clear_files)
        btn_row.addWidget(self.clear_files_btn)
        v.addLayout(btn_row)

        self.parse_status_label = QLabel("")
        self.parse_status_label.setObjectName("statusHint")
        v.addWidget(self.parse_status_label)
        return w

    # -- Mapping card ----------------------------------------------------

    def _build_mapping_content(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        self.mapping_hint = QLabel("Add files to detect accounts.")
        self.mapping_hint.setObjectName("statusHint")
        v.addWidget(self.mapping_hint)

        self.mapping_summary_area = QWidget()
        self._mapping_summary_layout = QVBoxLayout(self.mapping_summary_area)
        self._mapping_summary_layout.setContentsMargins(0, 0, 0, 0)
        self._mapping_summary_layout.setSpacing(4)
        v.addWidget(self.mapping_summary_area)

        self.edit_mapping_btn = QPushButton("Edit Mapping")
        self.edit_mapping_btn.setObjectName("secondaryButton")
        self.edit_mapping_btn.clicked.connect(self.on_edit_mapping)
        self.edit_mapping_btn.hide()
        v.addWidget(self.edit_mapping_btn)
        return w

    # -- Options card ----------------------------------------------------

    def _build_options_content(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        self.import_all_dates = StyledCheckBox("Import all transactions (no date filter)")
        self.import_all_dates.setChecked(True)
        self.import_all_dates.stateChanged.connect(self._on_import_all_dates_changed)
        v.addWidget(self.import_all_dates)

        # Date picker row — hidden by default (checkbox is checked = no filter)
        self.date_filter_row = QWidget()
        dr = QHBoxLayout(self.date_filter_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)
        dr.addWidget(QLabel("From"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setDisplayFormat("MMMM d, yyyy")
        # Force a larger, well-styled calendar popup
        cal_widget = self.start_date_edit.calendarWidget()
        if cal_widget:
            cal_widget.setMinimumSize(340, 280)
            cal_widget.setGridVisible(False)
        dr.addWidget(self.start_date_edit, 1)
        self.date_filter_row.hide()
        v.addWidget(self.date_filter_row)

        self.update_balances_check = StyledCheckBox("Update account balances after import")
        self.update_balances_check.setChecked(True)
        v.addWidget(self.update_balances_check)
        return w

    # -------------------------------------------------------------------
    # Stylesheet
    # -------------------------------------------------------------------

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            /* ── Base ───────────────────────────────────────────────── */
            QMainWindow, #centralRoot {{
                background: #f1f5f9;
            }}
            QWidget {{
                color: #1e293b;
                font-family: {_FONT_STACK};
                font-size: 14px;
            }}
            QDialog {{
                background: #ffffff;
            }}

            /* Transparent pass-through for text/inline elements
               (prevents grey ghost boxes on white cards) */
            QLabel, QCheckBox, QRadioButton {{
                background: transparent;
            }}

            /* ── Sidebar ─────────────────────────────────────────────  */
            #sidebarScroll, #sidebarScroll > QWidget {{
                background: #ffffff;
                border: none;
            }}
            #sidebar {{
                background: #ffffff;
                border-right: 1px solid #e2e8f0;
            }}
            #windowTitleBar {{
                background: #0f172a;
                border-bottom: 1px solid #1e293b;
            }}
            #windowTitleLabel {{
                color: #e2e8f0;
                font-size: 13px;
                font-weight: 600;
            }}
            #windowControlButton, #windowCloseButton {{
                min-width: 34px;
                max-width: 34px;
                min-height: 26px;
                max-height: 26px;
                border-radius: 6px;
                padding: 0px;
                font-size: 13px;
                font-weight: 700;
                background: transparent;
                color: #cbd5e1;
            }}
            #windowControlButton:hover {{
                background: #1e293b;
                color: #ffffff;
            }}
            #windowCloseButton:hover {{
                background: #dc2626;
                color: #ffffff;
            }}
            /* Logo */
            #logoHeader {{
                background: transparent;
            }}
            #logoTitle {{
                color: #0f172a;
                font-size: 15px;
                font-weight: 700;
                letter-spacing: -0.02em;
            }}
            #logoSubtitle {{
                color: #64748b;
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.18em;
            }}
            #fileList {{
                background: transparent;
                border: none;
                outline: 0;
            }}

            /* ── Cards ──────────────────────────────────────────────── */
            #card {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 12px;
            }}
            #cardTitle {{
                font-size: 10.5px;
                font-weight: 700;
                letter-spacing: 0.08em;
                color: #64748b;
                text-transform: uppercase;
            }}

            /* ── Content area ───────────────────────────────────────── */
            #contentArea {{
                background: #f1f5f9;
            }}
            #sectionTitle {{
                font-size: 18px;
                font-weight: 700;
                color: #0f172a;
            }}
            #previewSummary {{
                font-size: 14px;
                font-weight: 700;
                color: #334155;
                letter-spacing: -0.01em;
            }}

            /* ── Buttons ─────────────────────────────────────────────  */
            QPushButton {{
                font-family: {_FONT_STACK};
                font-size: 13px;
                font-weight: 600;
                border-radius: 8px;
                padding: 7px 14px;
                border: none;
                background: #2563eb;
                color: #ffffff;
            }}
            QPushButton:hover   {{ background: #1d4ed8; }}
            QPushButton:pressed  {{ background: #1e40af; }}
            QPushButton:disabled {{ background: #cbd5e1; color: #94a3b8; }}

            #primaryButton             {{ background: #2563eb; color: #ffffff; }}
            #primaryButton:hover       {{ background: #1d4ed8; }}

            #secondaryButton           {{ background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }}
            #secondaryButton:hover     {{ background: #e2e8f0; border-color: #94a3b8; }}
            #secondaryButton:disabled  {{ background: #f8fafc; color: #94a3b8; }}

            #dangerButton              {{ background: #fff1f2; color: #e11d48; border: 1px solid #fecdd3; }}
            #dangerButton:hover        {{ background: #ffe4e6; }}

            #ctaButton {{
                background: #2563eb;
                color: #ffffff;
                font-size: 15px;
                font-weight: 700;
                border-radius: 10px;
                padding: 10px 16px;
            }}
            #ctaButton:hover   {{ background: #1d4ed8; }}
            #ctaButton:pressed  {{ background: #1e40af; }}
            #ctaButton:disabled {{ background: #bfdbfe; color: #93c5fd; }}

            #logActionBtn {{
                background: transparent;
                color: #475569;
                font-size: 12px;
                font-weight: 600;
                padding: 2px 6px;
                border: none;
                border-radius: 4px;
            }}
            #logActionBtn:hover {{ background: #e2e8f0; color: #0f172a; }}

            #chipRemoveBtn {{
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 15px;
                font-weight: 700;
                padding: 0px;
                border-radius: 4px;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }}
            #chipRemoveBtn:hover {{ background: #fee2e2; color: #e11d48; }}

            /* ── Inputs ──────────────────────────────────────────────  */
            QLineEdit, QComboBox, QDateEdit {{
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                padding: 8px 12px;
                font-family: {_FONT_STACK};
                font-size: 14px;
                color: #1e293b;
                selection-background-color: #bfdbfe;
            }}
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus {{
                border: 1.5px solid #2563eb;
                background: #ffffff;
            }}
            QComboBox {{
                padding-right: 34px;
                combobox-popup: 0;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
                background: transparent;
            }}
            QComboBox QAbstractItemView {{
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #cbd5e1;
                border-radius: 10px;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
                outline: 0;
                padding: 6px;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 28px;
                padding: 6px 10px;
                border-radius: 6px;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background: #dbeafe;
                color: #0f172a;
            }}

            /* ── Drop zone ───────────────────────────────────────────  */
            #dropZone {{
                background: #f8fafc;
                border: 2px dashed #cbd5e1;
                border-radius: 10px;
            }}
            #dropZone:hover {{
                border-color: #93c5fd;
                background: #eff6ff;
            }}
            #dropIcon {{ font-size: 22px; color: #94a3b8; }}
            #dropHint {{ font-size: 12px; color: #94a3b8; }}

            /* ── File list ───────────────────────────────────────────  */
            #fileChip {{
                background: #f8fafc;
                border: 1px solid #dbe2ea;
                border-radius: 10px;
            }}
            #fileChipName {{ font-size: 12.5px; color: #334155; font-weight: 500; }}

            /* ── Mapping pills ───────────────────────────────────────  */
            #mappingPillLeft {{
                font-size: 12px;
                font-weight: 600;
                color: #334155;
                background: #f1f5f9;
                border-radius: 4px;
                padding: 2px 7px;
            }}
            #mappingArrow   {{ color: #94a3b8; font-size: 13px; }}
            #mappingPillRight {{
                font-size: 12px;
                color: #1d4ed8;
                background: #eff6ff;
                border-radius: 4px;
                padding: 2px 7px;
            }}
            #mappingPillMissing {{
                font-size: 12px;
                color: #b45309;
                background: #fef3c7;
                border-radius: 4px;
                padding: 2px 7px;
            }}

            /* ── Misc labels ─────────────────────────────────────────  */
            #connLabel     {{ color: #334155; font-size: 13px; }}
            #statusHint    {{ font-size: 12px; color: #64748b; }}
            #wizardHeading {{ font-size: 17px; font-weight: 700; color: #0f172a; }}
            #wizardDesc    {{ font-size: 13px; color: #475569; line-height: 1.6; }}

            /* ── Checkboxes ──────────────────────────────────────────  */
            QCheckBox {{
                font-size: 13px;
                color: #1e293b;
                spacing: 8px;
            }}

            /* ── Preview table ───────────────────────────────────────  */
            #previewTable {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                gridline-color: transparent;
                font-size: 13px;
            }}
            #previewTable QHeaderView::section {{
                background: #f8fafc;
                color: #475569;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                border: none;
                border-bottom: 1px solid #e2e8f0;
                padding: 10px 10px;
            }}
            #previewTable::item {{
                padding: 7px 10px;
                border: none;
            }}
            #previewTable::item:alternate {{
                background: #f8fafc;
            }}
            #previewTable::item:selected {{
                background: #eff6ff;
                color: #1d4ed8;
            }}

            /* ── Log panel ───────────────────────────────────────────  */
            #logBar {{
                background: #f8fafc;
                border-top: 1px solid #e2e8f0;
                min-height: 36px;
            }}
            #logBarLabel {{
                font-size: 11px;
                font-weight: 700;
                color: #334155;
                text-transform: uppercase;
                letter-spacing: 0.08em;
            }}
            #logsText {{
                background: #0f172a;
                color: #94a3b8;
                border: none;
                font-family: {_MONO_STACK};
                font-size: 11.5px;
            }}

            /* ── Scrollbars ──────────────────────────────────────────  */
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #cbd5e1;
                border-radius: 3px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: #94a3b8; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 6px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: #cbd5e1;
                border-radius: 3px;
                min-width: 24px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: #94a3b8; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

            /* ── Calendar popup ──────────────────────────────────────  */
            QCalendarWidget {{
                min-width: 320px;
            }}
            QCalendarWidget QAbstractItemView {{
                background: #ffffff;
                alternate-background-color: #f8fafc;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
                color: #0f172a;
                font-size: 14px;
                outline: 0;
            }}
            QCalendarWidget QAbstractItemView:disabled {{
                color: #cbd5e1;
            }}
            /* Navigation bar — dark for strong contrast */
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background: #1e293b;
                padding: 6px 10px;
                min-height: 46px;
            }}
            QCalendarWidget QToolButton {{
                color: #ffffff;
                background: transparent;
                border: none;
                font-weight: 700;
                font-size: 14px;
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QCalendarWidget QToolButton:hover {{
                background: rgba(255, 255, 255, 0.12);
            }}
            QCalendarWidget QToolButton#qt_calendar_prevmonth,
            QCalendarWidget QToolButton#qt_calendar_nextmonth {{
                font-size: 18px;
                padding: 4px 10px;
            }}
            QCalendarWidget QSpinBox {{
                color: #ffffff;
                background: transparent;
                border: none;
                font-size: 14px;
                font-weight: 700;
            }}
            QCalendarWidget QSpinBox::up-button,
            QCalendarWidget QSpinBox::down-button {{
                width: 0;
            }}
            QCalendarWidget QMenu {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                font-size: 13px;
            }}

            /* Mapping dialog */
            #mappingDialog QComboBox {{
                background: #ffffff;
                border: 1px solid #94a3b8;
                border-radius: 10px;
                min-height: 22px;
                padding: 8px 12px;
                padding-right: 28px;
            }}
            #mappingDialog QComboBox:hover {{
                border-color: #64748b;
            }}
            #mappingDialog QComboBox:focus {{
                border-color: #2563eb;
            }}
            #mappingDialog QComboBox QAbstractItemView {{
                border: 1px solid #94a3b8;
                border-radius: 10px;
            }}

            /* ── Status bar ──────────────────────────────────────────  */
            QStatusBar {{
                background: #f8fafc;
                border-top: 1px solid #e2e8f0;
                color: #475569;
                font-size: 12px;
            }}
            QProgressBar {{
                background: #e2e8f0;
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background: #2563eb;
                border-radius: 3px;
            }}
        """)

    # -------------------------------------------------------------------
    # Saved state
    # -------------------------------------------------------------------

    def _load_saved_state(self) -> None:
        config = load_config()
        if not config:
            return
        mapping = config.get("account_mapping", {})
        if isinstance(mapping, dict):
            self.account_mapping = {str(k): int(v) for k, v in mapping.items()}
        saved_key = config.get("api_key", "")
        if isinstance(saved_key, str):
            self._saved_api_key = saved_key

    # -------------------------------------------------------------------
    # Auth flow
    # -------------------------------------------------------------------

    def _startup_auth_flow(self) -> None:
        if self._saved_api_key:
            self._connect_async(self._saved_api_key, "Reconnecting…")
            return
        self._show_api_key_wizard(mandatory=True)

    def on_update_api_key(self) -> None:
        self._show_api_key_wizard(mandatory=False)

    def _show_api_key_wizard(self, mandatory: bool) -> None:
        wizard = ApiKeyWizard(self)
        if self._saved_api_key:
            wizard.api_key_input.setText(self._saved_api_key)
        while True:
            accepted = wizard.exec() == QDialog.DialogCode.Accepted
            if not accepted:
                if mandatory:
                    QMessageBox.warning(
                        self,
                        "API Key Required",
                        "The importer needs your Lunch Money API key to work.",
                    )
                    continue
                return
            api_key = wizard.api_key()
            if not api_key:
                continue
            self._connect_async(api_key, "Verifying API key…")
            return

    def _connect_async(self, api_key: str, status_message: str) -> None:
        self._run_worker(self._connect, self._on_connected, status_message, api_key)

    def _connect(self, api_key: str) -> Dict[str, Any]:
        if not self.state.initialize(api_key):
            raise RuntimeError("Invalid API key or unable to connect to Lunch Money.")
        self.state.api_accounts = self.state.lunch.get_assets()
        config = load_config() or {"account_mapping": {}}
        config["api_key"] = api_key
        save_config(config)
        self._saved_api_key = api_key
        from lunchmoney.api import get_user_info
        user_name, budget_name = get_user_info(self.state.lunch)
        return {
            "user_name": user_name,
            "budget_name": budget_name,
            "account_count": len(self.state.api_accounts),
        }

    def _on_connected(self, result: Dict[str, Any]) -> None:
        n = result["account_count"]
        self.connection_label.setText(
            f"✓  {result['user_name']}  ·  {result['budget_name']}  ·  "
            f"{n} asset{'s' if n != 1 else ''}"
        )
        self.connection_label.setStyleSheet("color: #16a34a; font-size: 13px; font-weight: 600;")
        self.statusBar().showMessage("Connected")
        if self.loaded_files:
            self._parse_loaded_files_async()

    # -------------------------------------------------------------------
    # File handling
    # -------------------------------------------------------------------

    def on_add_files(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(
            self, "Select QFX files", str(Path.home()), "QFX files (*.qfx);;All files (*)"
        )
        if selected:
            self.add_files(selected)

    def add_files(self, files: List[str]) -> None:
        added = 0
        for fp in files:
            normalized = str(Path(fp))
            if normalized not in self.loaded_files and normalized.lower().endswith(".qfx"):
                self.loaded_files.append(normalized)
                added += 1
        if not added:
            return
        self._refresh_file_chips()
        self.statusBar().showMessage(f"Added {added} file(s)")
        if not self.state.lunch:
            self.parse_status_label.setText("Files queued — will parse after connecting.")
            return
        self._parse_loaded_files_async()

    def on_clear_files(self) -> None:
        self._preview_request_id += 1
        self.loaded_files.clear()
        self.parsed_inputs.clear()
        self.all_qfx_accounts.clear()
        self.preview_transactions.clear()
        self.preview_data_table.setRowCount(0)
        self.preview_summary.setText("")
        self._refresh_file_chips()
        self._refresh_mapping_ui()
        self.parse_status_label.setText("")

    def _refresh_file_chips(self) -> None:
        self.file_list.clear()

        if not self.loaded_files:
            self.file_list.hide()
            self.file_list.setFixedHeight(0)
            self.drop_zone.set_compact(False)
            return

        self.drop_zone.set_compact(True)

        for fp in self.loaded_files:
            chip = QFrame()
            chip.setObjectName("fileChip")
            row = QHBoxLayout(chip)
            row.setContentsMargins(10, 6, 6, 6)
            row.setSpacing(6)
            name_lbl = QLabel(Path(fp).name)
            name_lbl.setObjectName("fileChipName")
            row.addWidget(name_lbl, 1)
            remove_btn = QPushButton("×")
            remove_btn.setObjectName("chipRemoveBtn")
            remove_btn.setFixedSize(20, 20)
            remove_btn.clicked.connect(lambda _checked, f=fp: self._remove_file(f))
            row.addWidget(remove_btn)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 32))
            self.file_list.addItem(item)
            self.file_list.setItemWidget(item, chip)

        visible_rows = min(len(self.loaded_files), 2)
        row_height = 32
        spacing = self.file_list.spacing()
        # spacing is applied around every item (top+bottom), so add it twice per row
        target_height = visible_rows * (row_height + spacing * 2) + 6
        self.file_list.setFixedHeight(target_height)
        self.file_list.show()

    def _remove_file(self, file_path: str) -> None:
        self._preview_request_id += 1
        if file_path in self.loaded_files:
            self.loaded_files.remove(file_path)
        self.parsed_inputs = [p for p in self.parsed_inputs if p.file_path != file_path]
        self.all_qfx_accounts = [acc for p in self.parsed_inputs for acc in p.accounts]
        self._refresh_file_chips()
        self._refresh_mapping_ui()
        if not self.loaded_files:
            self.preview_transactions = []
            self.preview_data_table.setRowCount(0)
            self.preview_summary.setText("")
        else:
            self._maybe_auto_preview()
        n = len(self.loaded_files)
        self.parse_status_label.setText(f"{n} file(s) loaded" if n else "")

    # -------------------------------------------------------------------
    # Parsing
    # -------------------------------------------------------------------

    def _parse_loaded_files_async(self) -> None:
        if not self.loaded_files:
            return
        self.parse_status_label.setText("Parsing…")
        self._run_worker(
            self._parse_files,
            self._on_parsed_files,
            "Parsing QFX files…",
            list(self.loaded_files),
            lock_ui=False,
        )

    def _parse_files(self, files: List[str]) -> Dict[str, Any]:
        parsed_inputs: List[ParsedInput] = []
        all_accounts: List[Any] = []
        errors: List[str] = []
        for fp in files:
            try:
                accounts = self._parse_qfx_file(fp)
                parsed_inputs.append(ParsedInput(file_path=fp, accounts=accounts))
                all_accounts.extend(accounts)
            except Exception as exc:
                errors.append(f"{Path(fp).name}: {exc}")
        new_accounts = check_new_accounts(all_accounts, self.account_mapping)
        return {
            "parsed_inputs": parsed_inputs,
            "all_accounts": all_accounts,
            "new_accounts": new_accounts,
            "errors": errors,
        }

    @staticmethod
    def _parse_qfx_file(file_path: str) -> List[Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        last_err: Optional[Exception] = None
        for text in [content]:
            try:
                return OfxParser.parse(StringIO(text)).accounts
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"Could not parse OFX data: {last_err}")

    def _on_parsed_files(self, result: Dict[str, Any]) -> None:
        self.parsed_inputs = result["parsed_inputs"]
        self.all_qfx_accounts = result["all_accounts"]
        n = len(self.parsed_inputs)
        self.parse_status_label.setText(f"Parsed {n}/{len(self.loaded_files)} file(s)")

        errors = result.get("errors", [])
        if errors:
            QMessageBox.warning(self, "Parse Errors", "\n".join(errors[:8]))

        new_accounts = result.get("new_accounts") or []
        if new_accounts:
            self._open_mapping_dialog(new_accounts)
        else:
            self._refresh_mapping_ui()
            self._maybe_auto_preview()

    # -------------------------------------------------------------------
    # Account mapping
    # -------------------------------------------------------------------

    def _open_mapping_dialog(self, filter_ids: Optional[List[str]] = None) -> None:
        if filter_ids is not None:
            target = [a for a in self.all_qfx_accounts if a.account_id in filter_ids]
        else:
            target = self.all_qfx_accounts

        if not target or not self.state.api_accounts:
            QMessageBox.warning(
                self, "Cannot Map", "Connect and load QFX files before mapping accounts."
            )
            return

        dlg = MappingDialog(self, target, self.state.api_accounts, self.account_mapping)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.account_mapping.update(dlg.mapping())
            config = load_config() or {}
            config["api_key"] = self._saved_api_key
            config["account_mapping"] = self.account_mapping
            save_config(config)

        self._refresh_mapping_ui()
        self._maybe_auto_preview()

    def on_edit_mapping(self) -> None:
        self._open_mapping_dialog()

    def _refresh_mapping_ui(self) -> None:
        while self._mapping_summary_layout.count():
            item = self._mapping_summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.all_qfx_accounts:
            self.mapping_hint.setText("Add files to detect accounts.")
            self.edit_mapping_btn.hide()
            return

        if not self.state.api_accounts:
            self.mapping_hint.setText("Connect to Lunch Money first.")
            self.edit_mapping_btn.hide()
            return

        asset_names = {a.id: f"{a.name} ({a.institution_name})" for a in self.state.api_accounts}
        seen: set = set()
        all_mapped = True

        for account in self.all_qfx_accounts:
            aid = account.account_id
            if aid in seen:
                continue
            seen.add(aid)

            asset_id = self.account_mapping.get(aid)
            chip = QFrame()
            row = QHBoxLayout(chip)
            row.setContentsMargins(0, 2, 0, 2)
            row.setSpacing(6)

            left_lbl = QLabel(f"···{aid[-4:]}" if len(aid) > 4 else aid)
            left_lbl.setObjectName("mappingPillLeft")
            row.addWidget(left_lbl)

            arrow_lbl = QLabel("→")
            arrow_lbl.setObjectName("mappingArrow")
            row.addWidget(arrow_lbl)

            if asset_id and asset_id in asset_names:
                right_lbl = QLabel(asset_names[asset_id])
                right_lbl.setObjectName("mappingPillRight")
            else:
                right_lbl = QLabel("⚠  Not mapped")
                right_lbl.setObjectName("mappingPillMissing")
                all_mapped = False

            row.addWidget(right_lbl, 1)
            self._mapping_summary_layout.addWidget(chip)

        self.mapping_hint.setText("All accounts mapped ✓" if all_mapped else "Some accounts are not mapped.")
        self.edit_mapping_btn.show()

    def _maybe_auto_preview(self) -> None:
        if not self.parsed_inputs:
            return
        missing = [
            a.account_id
            for a in self.all_qfx_accounts
            if a.account_id not in self.account_mapping
        ]
        if missing:
            return
        self._trigger_preview()

    # -------------------------------------------------------------------
    # Preview
    # -------------------------------------------------------------------

    def _trigger_preview(self) -> None:
        start_date = None
        if not self.import_all_dates.isChecked():
            start_date = self.start_date_edit.date().toPython()
        self._preview_request_id += 1
        self._run_worker(
            self._preview_transactions,
            self._on_preview_ready,
            "Generating preview…",
            start_date,
            self._preview_request_id,
        )

    def _preview_transactions(self, start_date: Any, request_id: int) -> Dict[str, Any]:
        txns: List[Any] = []
        for p in self.parsed_inputs:
            txns.extend(format_transactions(p.accounts, self.account_mapping, start_date))
        return {"request_id": request_id, "transactions": txns}

    def _on_preview_ready(self, result: Dict[str, Any]) -> None:
        if result["request_id"] != self._preview_request_id:
            return
        txns = result["transactions"]
        self.preview_transactions = txns
        self._render_preview_table(txns)
        if txns:
            pos = sum(float(t.amount) for t in txns if float(t.amount) > 0)
            neg = sum(float(t.amount) for t in txns if float(t.amount) < 0)
            self.preview_summary.setText(
                f"{len(txns)} transactions  ·  "
                f"<span style='color:#16a34a;font-weight:700'>+{pos:.2f}</span>  "
                f"<span style='color:#dc2626;font-weight:700'>{neg:.2f}</span>"
            )
        else:
            self.preview_summary.setText("No transactions match current filters.")
        self.statusBar().showMessage(f"Preview: {len(txns)} transactions")

    def _render_preview_table(self, txns: List[Any]) -> None:
        self.preview_data_table.setRowCount(len(txns))
        asset_names = {a.id: a.name for a in self.state.api_accounts}

        # Per-column alignment: date center, payee left, amount right, account center, ref left
        col_align = [
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter,
            Qt.AlignmentFlag.AlignRight  | Qt.AlignmentFlag.AlignVCenter,
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            Qt.AlignmentFlag.AlignLeft   | Qt.AlignmentFlag.AlignVCenter,
        ]

        for row_idx, txn in enumerate(txns):
            amount = float(txn.amount)
            values = [
                str(txn.date),
                str(txn.payee),
                f"{amount:+.2f}",
                asset_names.get(txn.asset_id, str(txn.asset_id)),
                txn.external_id or "",
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(col_align[col_idx])
                if col_idx == 2:
                    # Color-code amounts + semi-bold weight
                    item.setForeground(
                        QColor("#16a34a") if amount >= 0 else QColor("#dc2626")
                    )
                    f = QFont()
                    f.setWeight(QFont.Weight.DemiBold)
                    item.setFont(f)
                self.preview_data_table.setItem(row_idx, col_idx, item)

    # -------------------------------------------------------------------
    # Options callbacks
    # -------------------------------------------------------------------

    def _on_import_all_dates_changed(self) -> None:
        self.date_filter_row.setVisible(not self.import_all_dates.isChecked())
        if self.preview_transactions or self.parsed_inputs:
            self._maybe_auto_preview()

    # -------------------------------------------------------------------
    # Import
    # -------------------------------------------------------------------

    def on_import(self) -> None:
        if not self.state.lunch:
            QMessageBox.warning(self, "Not Connected", "Connect to Lunch Money before importing.")
            return
        if not self.preview_transactions:
            missing = [
                a.account_id
                for a in self.all_qfx_accounts
                if a.account_id not in self.account_mapping
            ]
            if not missing and self.parsed_inputs:
                self._trigger_preview()
                QMessageBox.information(
                    self,
                    "Preview Generated",
                    "Preview is being generated. Click Import again once the table is populated.",
                )
                return
            QMessageBox.warning(
                self, "Nothing to Import", "Add files and complete mapping before importing."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Import",
            f"Import {len(self.preview_transactions)} transaction(s) into Lunch Money?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._run_worker(self._import_transactions, self._on_import_finished, "Importing…")

    def _import_transactions(self) -> Dict[str, Any]:
        result = import_transactions(self.state.lunch, self.preview_transactions)
        if not result.success:
            raise RuntimeError("\n".join(result.message_lines or ["Transaction import failed."]))
        updates = 0
        if self.update_balances_check.isChecked():
            updates = self._update_balances()
        return {
            "imported": result.imported_count,
            "requested": len(self.preview_transactions),
            "updates": updates,
            "message_lines": result.message_lines or [],
        }

    def _update_balances(self) -> int:
        updates = 0
        for account in self.all_qfx_accounts:
            asset_id = self.account_mapping.get(account.account_id)
            if not asset_id or not hasattr(account.statement, "available_balance"):
                continue
            balance = float(account.statement.available_balance)
            try:
                self.state.lunch.update_asset(asset_id=asset_id, balance=balance)
                updates += 1
            except Exception:
                logger.exception("Balance update failed for account %s", account.account_id)
        return updates

    def _on_import_finished(self, result: Dict[str, Any]) -> None:
        message_lines = result.get("message_lines") or []
        if message_lines:
            msg = "<br>".join(message_lines)
        else:
            msg = f"<b>{result['imported']}</b> transaction(s) imported."
        if result["updates"]:
            msg += f"<br><br>{result['updates']} account balance(s) updated."
        QMessageBox.information(self, "Import Complete", msg)
        if result["imported"] == 0:
            self.statusBar().showMessage("Import complete: no new transactions")
        else:
            self.statusBar().showMessage(f"Import complete: {result['imported']} imported")
        self.refresh_logs(expand=False)

    # -------------------------------------------------------------------
    # Logs
    # -------------------------------------------------------------------

    def _toggle_logs(self) -> None:
        visible = self.logs_text.isVisible()
        self.logs_text.setVisible(not visible)
        self._log_toggle_btn.setText("▲  Hide" if not visible else "▼  Show")
        if not visible:
            self.refresh_logs(expand=False)

    def refresh_logs(self, expand: bool = False) -> None:
        from lunchmoney.config import LOG_DIR

        if expand and not self.logs_text.isVisible():
            self.logs_text.show()
            self._log_toggle_btn.setText("▲  Hide")

        if not LOG_DIR.exists():
            self.logs_text.setPlainText("No log directory found yet.")
            return

        logs = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            self.logs_text.setPlainText("No log files found.")
            return

        try:
            content = logs[0].read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            self.logs_text.setPlainText(f"Could not read log: {exc}")
            return

        self.logs_text.setPlainText(content)
        bar = self.logs_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -------------------------------------------------------------------
    # Worker infrastructure
    # -------------------------------------------------------------------

    def _set_busy(self, busy: bool, message: str, lock_ui: bool = True) -> None:
        if lock_ui:
            for card in (self._conn_card, self._files_card, self._mapping_card, self._options_card):
                card.setEnabled(not busy)
            self.import_button.setEnabled(not busy)
        if busy:
            self.busy_bar.setRange(0, 0)
            self.busy_bar.show()
        else:
            self.busy_bar.hide()
        self.statusBar().showMessage(message)

    def _run_worker(
        self,
        fn: Callable[..., Any],
        on_success: Callable[[Any], None],
        busy_message: str,
        *args: Any,
        lock_ui: bool = True,
    ) -> None:
        self._set_busy(True, busy_message, lock_ui=lock_ui)
        worker = Worker(fn, *args)
        self._active_workers.append(worker)
        worker.signals.finished.connect(
            lambda result, w=worker: self._finish_worker(w, on_success, result, lock_ui)
        )
        worker.signals.error.connect(
            lambda message, w=worker: self._handle_worker_error(w, message, lock_ui)
        )
        self.thread_pool.start(worker)

    def _finish_worker(
        self,
        worker: Worker,
        on_success: Callable[[Any], None],
        result: Any,
        lock_ui: bool,
    ) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        self._set_busy(False, "Ready", lock_ui=lock_ui)
        on_success(result)

    def _handle_worker_error(self, worker: Worker, message: str, lock_ui: bool) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        self._set_busy(False, "Ready", lock_ui=lock_ui)
        QMessageBox.critical(self, "Error", message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def launch_gui(input_files: Optional[List[str]] = None) -> int:
    _set_windows_app_id()
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("TD Lunch Money Importer")
    app_icon = _build_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    app.setStyle("Fusion")
    window = MainWindow(input_files=input_files)
    window.show()
    return app.exec()
