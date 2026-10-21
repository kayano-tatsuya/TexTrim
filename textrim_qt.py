#!/usr/bin/env python3
"""
TexTrim - PySide6 edition.

Find oversized DDS textures in mod folders and downscale them with texconv.
Features: drag-and-drop a folder, sortable + filterable table, per-row checkboxes,
cancel button, remembered settings, right-click menu.

Run:  python textrim_qt.py
"""

import html
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QSettings,
                            QSortFilterProxyModel, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QSpinBox, QStackedWidget, QTableView,
                               QVBoxLayout,
                               QWidget)

from textrim_core import (APP_NAME, Cancelled, Tex, app_dir, data_dir, default_backup_root, ensure_texconv, human,
                     restore_backups, run_mode, scan, shrink_one, startup_log)

C = dict(
    bg="#111318", card="#1a1d24", card2="#232733", line="#2c313d", text="#e8eaf0",
    muted="#8a91a3", accent="#7c6cff", accent_hov="#9285ff", accent_dim="#37316b",
    sel="#2f2a63", stripe="#1e222a", ok="#3ddc97", bad="#ff6b6b",
)

QSS = f"""
QWidget {{ color: {C['text']}; font-size: 10pt; }}
QMainWindow, QWidget#root {{ background: {C['bg']}; }}
QLabel#title {{ font-size: 21pt; font-weight: 700; }}
QLabel[muted="true"] {{ color: {C['muted']}; }}
QLabel[stat="true"] {{ color: {C['muted']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[statnum="true"] {{ font-size: 17pt; font-weight: 700; }}
QFrame#card {{ background: {C['card']}; border: 1px solid {C['line']}; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QLineEdit, QSpinBox {{
    background: {C['card2']}; border: 1px solid {C['line']}; border-radius: 6px;
    padding: 7px 10px; selection-background-color: {C['accent']};
}}
QLineEdit:focus, QSpinBox:focus {{ border-color: {C['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
QPushButton {{
    background: {C['card2']}; border: 1px solid {C['line']}; border-radius: 6px; padding: 8px 16px;
}}
QPushButton:hover {{ background: {C['line']}; }}
QPushButton:disabled {{ color: {C['muted']}; background: {C['card']}; }}
QPushButton[primary="true"] {{ background: {C['accent']}; border-color: {C['accent']}; color: white; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {C['accent_hov']}; border-color: {C['accent_hov']}; }}
QPushButton[primary="true"]:disabled {{ background: {C['accent_dim']}; border-color: {C['accent_dim']}; color: #9a95c9; }}
QPushButton[ghost="true"] {{ background: transparent; color: {C['muted']}; }}
QPushButton[ghost="true"]:hover {{ background: {C['card2']}; }}
QPushButton[seg="true"] {{ padding: 7px 14px; color: {C['muted']}; }}
QPushButton[seg="true"]:checked {{ background: {C['accent_dim']}; border-color: {C['accent']}; color: white; font-weight: 600; }}
QTableView {{
    background: {C['card']}; alternate-background-color: {C['stripe']}; border: none;
    selection-background-color: {C['sel']}; selection-color: white; outline: 0;
}}
QHeaderView::section {{
    background: {C['card2']}; color: {C['muted']}; border: none; padding: 9px 10px;
    font-size: 8pt; font-weight: 700;
}}
QScrollBar:vertical {{ background: {C['card']}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {C['line']}; border-radius: 5px; min-height: 30px; margin: 2px; }}
QScrollBar::handle:vertical:hover {{ background: {C['muted']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressBar {{ background: {C['card2']}; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 3px; }}
QPlainTextEdit {{
    background: {C['card2']}; border: 1px solid {C['line']}; border-radius: 8px; padding: 6px;
    font-family: Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace; font-size: 9pt;
}}
QMenu {{ background: {C['card2']}; border: 1px solid {C['line']}; padding: 4px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {C['accent_dim']}; }}
QToolTip {{ background: {C['card2']}; color: {C['text']}; border: 1px solid {C['line']}; }}
"""

HEADERS = ["FILE", "CURRENT", "NEW", "SIZE", "AFTER (EST.)"]


def build_qss() -> str:
    """Base stylesheet plus checkbox styling (needs a drawn check-mark image, so call after QApplication exists)."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#ffffff"), 4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(8, 17, 14, 23)
    painter.drawLine(14, 23, 24, 10)
    painter.end()
    icon_path = data_dir() / "check.png"
    pm.save(str(icon_path), "PNG")
    url = icon_path.as_posix()

    pm2 = QPixmap(32, 32)
    pm2.fill(Qt.GlobalColor.transparent)
    p2 = QPainter(pm2)
    p2.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen2 = QPen(QColor(C["muted"]), 3.5)
    pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p2.setPen(pen2)
    p2.drawLine(9, 13, 16, 20)
    p2.drawLine(16, 20, 23, 13)
    p2.end()
    chevron_path = data_dir() / "chevron.png"
    pm2.save(str(chevron_path), "PNG")
    chevron = chevron_path.as_posix()
    return QSS + f"""
QTableView::indicator, QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid #4b5266; border-radius: 4px; background: {C['card2']};
}}
QTableView::indicator:hover, QCheckBox::indicator:hover {{ border-color: {C['accent_hov']}; }}
QTableView::indicator:checked, QCheckBox::indicator:checked {{
    background: {C['accent']}; border-color: {C['accent']}; image: url("{url}");
}}
QCheckBox {{ spacing: 8px; }}
QComboBox {{
    background: {C['card2']}; border: 1px solid {C['line']}; border-radius: 6px; padding: 7px 10px;
    min-width: 200px;
}}
QComboBox:focus, QComboBox:on {{ border-color: {C['accent']}; }}
QComboBox:disabled {{ color: {C['muted']}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {C['card2']}; border: 1px solid {C['line']}; selection-background-color: {C['accent_dim']};
    selection-color: white; outline: 0; padding: 4px;
}}
"""


def apply_palette(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    R = QPalette.ColorRole
    for role, col in ((R.Window, C["bg"]), (R.WindowText, C["text"]), (R.Base, C["card"]),
                      (R.AlternateBase, C["stripe"]), (R.Text, C["text"]), (R.Button, C["card2"]),
                      (R.ButtonText, C["text"]), (R.Highlight, C["accent"]), (R.HighlightedText, "#ffffff"),
                      (R.ToolTipBase, C["card2"]), (R.ToolTipText, C["text"]), (R.PlaceholderText, C["muted"])):
        p.setColor(role, QColor(col))
    for role in (R.Text, R.ButtonText, R.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(C["muted"]))
    app.setPalette(p)


# --------------------------------------------------------------------------- model

class TexModel(QAbstractTableModel):
    checksChanged = Signal()

    def __init__(self):
        super().__init__()
        self.rows: list[Tex] = []
        self.checked: set[str] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return HEADERS[section]
            if role == Qt.ItemDataRole.TextAlignmentRole:
                a = Qt.AlignmentFlag.AlignLeft if section == 0 else (
                    Qt.AlignmentFlag.AlignHCenter if section in (1, 2) else Qt.AlignmentFlag.AlignRight)
                return int((a | Qt.AlignmentFlag.AlignVCenter).value)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        t, c = self.rows[index.row()], index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return (str(t.rel), f"{t.w}\u00d7{t.h}", f"{t.new_w}\u00d7{t.new_h}",
                    human(t.size), human(t.est_new_size))[c]
        if role == Qt.ItemDataRole.UserRole:  # numeric sort keys
            return (str(t.rel).lower(), t.w * t.h, t.new_w * t.new_h, t.size, t.est_new_size)[c]
        if role == Qt.ItemDataRole.CheckStateRole and c == 0:
            return Qt.CheckState.Checked if str(t.path) in self.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.TextAlignmentRole:
            a = Qt.AlignmentFlag.AlignLeft if c == 0 else (
                Qt.AlignmentFlag.AlignHCenter if c in (1, 2) else Qt.AlignmentFlag.AlignRight)
            return int((a | Qt.AlignmentFlag.AlignVCenter).value)
        if role == Qt.ItemDataRole.ToolTipRole:
            if t.grows:
                return (f"{t.path}\n\nWould grow on disk: the original is RLE-compressed and TexTrim saves "
                        "TGA files uncompressed. Unchecked by default; the texture itself would still use less memory in-game.")
            return str(t.path)
        return None

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            key = str(self.rows[index.row()].path)
            on = value == Qt.CheckState.Checked or value == 2
            (self.checked.add if on else self.checked.discard)(key)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            self.checksChanged.emit()
            return True
        return False

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.checked = {str(t.path) for t in self.rows if not t.grows}  # don't pre-check files that would get bigger
        self.endResetModel()
        self.checksChanged.emit()

    def remove_keys(self, keys):
        """Remove many rows at once, in contiguous runs (one Qt notification per run)."""
        keys = set(keys)
        if not keys:
            return
        idx = [i for i, t in enumerate(self.rows) if str(t.path) in keys]
        runs = []
        for i in idx:
            if runs and i == runs[-1][1] + 1:
                runs[-1][1] = i
            else:
                runs.append([i, i])
        for first, last in reversed(runs):
            self.beginRemoveRows(QModelIndex(), first, last)
            del self.rows[first:last + 1]
            self.endRemoveRows()
        self.checked -= keys
        self.checksChanged.emit()

    def set_checked(self, keys, on):
        for k in keys:
            (self.checked.add if on else self.checked.discard)(k)
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0),
                                  [Qt.ItemDataRole.CheckStateRole])
        self.checksChanged.emit()


# --------------------------------------------------------------------------- thread bridge

class Bus(QObject):
    """Lives in the GUI thread; worker threads emit these and Qt queues them safely."""
    scan_done = Signal(list, int)
    progress = Signal(int, int)
    current = Signal(int, int, str)       # index, total, description of texture being processed
    result = Signal(str, bool, str)       # key, ok, log line
    log = Signal(str)
    finished = Signal(int, int, str)      # bytes saved, failures, backup folder
    error = Signal(str)


# --------------------------------------------------------------------------- main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.bus = Bus()
        self.cancel = threading.Event()
        self.busy = False
        self.settings = QSettings("TexTrim", "TexTrim")
        if not self.settings.allKeys():  # first run after the rename: carry over old settings
            old = QSettings("ZZTextureShrinker", "TextureShrinker")
            for k in old.allKeys():
                self.settings.setValue(k, old.value(k))

        self.model = TexModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.proxy.setFilterKeyColumn(0)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self._pending_remove = set()
        self._cur_text = ""
        self._cur_start = 0.0
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(300)
        self._flush_timer.timeout.connect(self._flush_removals)
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.setInterval(30)
        self._stats_timer.timeout.connect(self._do_update_stats)
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self._build()
        self._load_settings()

        b = self.bus
        b.scan_done.connect(self._on_scan_done)
        b.progress.connect(self._on_progress)
        b.current.connect(self._on_current)
        b.result.connect(self._on_result)
        b.log.connect(self._log)
        b.finished.connect(self._on_finished)
        b.error.connect(self._on_error)
        self.model.checksChanged.connect(self._update_stats)
        self.proxy.rowsRemoved.connect(lambda *a: self._update_stats())
        self.proxy.rowsInserted.connect(lambda *a: self._update_stats())
        self.proxy.modelReset.connect(self._update_stats)
        self._update_stats()
        self._refresh_ui()

    # ------------------------------------------------------------------ layout
    def _label(self, text, **props):
        lab = QLabel(text)
        for k, v in props.items():
            lab.setProperty(k, v)
        return lab

    def _button(self, text, slot=None, **props):
        btn = QPushButton(text)
        for k, v in props.items():
            btn.setProperty(k, v)
        if slot:
            btn.clicked.connect(slot)
        return btn

    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(22, 18, 22, 14)
        v.setSpacing(0)

        title = QLabel("TexTrim")
        title.setObjectName("title")
        v.addWidget(title)
        v.addWidget(self._label("Find oversized textures in your mods and downscale them. "
                                "Drop a folder anywhere on this window.", muted=True))
        v.addSpacing(14)

        # settings card
        card = QFrame()
        card.setObjectName("card")
        g = QGridLayout(card)
        g.setContentsMargins(16, 14, 16, 14)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(10)
        g.setColumnStretch(1, 1)

        g.addWidget(self._label("Mods folder", muted=True), 0, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose or drop your Mods folder")
        g.addWidget(self.folder_edit, 0, 1, 1, 2)
        g.addWidget(self._button("Browse", self._browse), 0, 3)

        g.addWidget(self._label("Max texture side", muted=True), 1, 0)
        seg = QHBoxLayout()
        seg.setSpacing(4)
        self.preset_btns = {}
        for n in (512, 1024, 2048, 4096):
            b = self._button(str(n), lambda _=False, n=n: self.max_spin.setValue(n), seg=True)
            b.setCheckable(True)
            seg.addWidget(b)
            self.preset_btns[n] = b
        self.max_spin = QSpinBox()
        self.max_spin.setRange(8, 16384)
        self.max_spin.setSingleStep(256)
        self.max_spin.setSuffix(" px")
        self.max_spin.setValue(2048)
        self.max_spin.setFixedWidth(100)
        self.max_spin.valueChanged.connect(self._sync_presets)
        seg.addSpacing(10)
        seg.addWidget(self.max_spin)
        seg.addStretch(1)
        g.addLayout(seg, 1, 1, 1, 3)

        g.addWidget(self._label("Skip paths containing", muted=True), 2, 0)
        self.exclude_edit = QLineEdit()
        self.exclude_edit.setPlaceholderText("comma-separated, e.g. normal, light")
        g.addWidget(self.exclude_edit, 2, 1, 1, 3)

        g.addWidget(self._label("Encoding", muted=True), 3, 0)
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("Fast (quicker, slightly lower quality)", "fast")
        self.quality_combo.addItem("Balanced (default)", "balanced")
        self.quality_combo.addItem("Best (slowest)", "best")
        self.quality_combo.setCurrentIndex(1)
        enc = QHBoxLayout()
        enc.setSpacing(12)
        enc.addWidget(self.quality_combo)
        enc.addWidget(self._label("Speed vs. quality when re-encoding BC7 textures", muted=True))
        enc.addStretch(1)
        g.addLayout(enc, 3, 1, 1, 3)

        checks = QVBoxLayout()
        checks.setSpacing(8)
        self.backup_check = QCheckBox("Back up originals before changing them (recommended)")
        self.backup_check.setChecked(True)
        checks.addWidget(self.backup_check)
        trow = QHBoxLayout()
        trow.setSpacing(12)
        self.tga_check = QCheckBox("Also scan .tga textures")
        trow.addWidget(self.tga_check)
        trow.addWidget(self._label("TGA files are saved back uncompressed", muted=True))
        trow.addStretch(1)
        checks.addLayout(trow)
        g.addLayout(checks, 4, 1, 1, 3)
        v.addWidget(card)
        v.addSpacing(12)

        # stat tiles
        row = QHBoxLayout()
        row.setSpacing(10)
        self.stat_vals = []
        for name in ("Over the limit", "Checked", "Savings (checked)"):
            tile = QFrame()
            tile.setObjectName("card")
            tv = QVBoxLayout(tile)
            tv.setContentsMargins(14, 10, 14, 10)
            tv.setSpacing(0)
            tv.addWidget(self._label(name.upper(), stat=True))
            val = self._label("0", statnum=True)
            tv.addWidget(val)
            self.stat_vals.append(val)
            row.addWidget(tile, 1)
        v.addLayout(row)
        v.addSpacing(12)

        # filter row
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter results (e.g. hair, body, mod name)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter)
        frow.addWidget(self.filter_edit, 1)
        self.btn_all = self._button("Check all", lambda: self._check_visible(True))
        self.btn_none = self._button("Uncheck all", lambda: self._check_visible(False))
        frow.addWidget(self.btn_all)
        frow.addWidget(self.btn_none)
        v.addLayout(frow)
        v.addSpacing(8)

        # table / empty state
        self.stack = QStackedWidget()
        self.empty_label = QLabel()
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setTextFormat(Qt.TextFormat.RichText)
        self.empty_label.setStyleSheet(
            f"background: {C['card']}; border: 2px dashed {C['line']}; border-radius: 10px;")
        self.stack.addWidget(self.empty_label)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setMinimumSectionSize(90)
        hh.setHighlightSections(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.stack.addWidget(self.table)
        v.addWidget(self.stack, 1)
        v.addSpacing(12)

        # actions
        arow = QHBoxLayout()
        arow.setSpacing(8)
        self.btn_scan = self._button("Scan", self._scan)
        self.btn_shrink = self._button("Shrink checked", self._shrink)
        self.btn_cancel = self._button("Cancel", self._cancel)
        self.btn_restore = self._button("Restore backups", self._restore, ghost=True)
        arow.addWidget(self.btn_scan)
        arow.addWidget(self.btn_shrink)
        arow.addWidget(self.btn_cancel)
        arow.addStretch(1)
        arow.addWidget(self.btn_restore)
        v.addLayout(arow)
        v.addSpacing(10)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        v.addWidget(self.progress)
        v.addSpacing(6)

        srow = QHBoxLayout()
        self.status = self._label("Choose your mods folder and press Scan.", muted=True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.btn_log = self._button("Show log", self._toggle_log, ghost=True)
        self.btn_log.setStyleSheet("padding: 2px 8px;")
        srow.addWidget(self.status, 1)
        srow.addWidget(self.btn_log)
        v.addLayout(srow)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMaximumHeight(140)
        self.log_view.hide()
        v.addWidget(self.log_view)

        self._set_empty("default")
        self._sync_presets()

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        s = self.settings
        self.folder_edit.setText(s.value("root", "", str))
        self.max_spin.setValue(int(s.value("max", 2048)))
        self.exclude_edit.setText(s.value("exclude", "", str))
        self.backup_check.setChecked(str(s.value("backup", "true")).lower() != "false")
        self.tga_check.setChecked(str(s.value("tga", "false")).lower() == "true")
        qi = self.quality_combo.findData(str(s.value("quality", "balanced")))
        self.quality_combo.setCurrentIndex(qi if qi >= 0 else 1)
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1020, 820)
        self.setMinimumSize(860, 640)

    def _save_settings(self):
        s = self.settings
        s.setValue("root", self.folder_edit.text())
        s.setValue("max", self.max_spin.value())
        s.setValue("exclude", self.exclude_edit.text())
        s.setValue("backup", "true" if self.backup_check.isChecked() else "false")
        s.setValue("tga", "true" if self.tga_check.isChecked() else "false")
        s.setValue("quality", self.quality_combo.currentData())
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, e):
        self.cancel.set()
        self._save_settings()
        super().closeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if sys.platform == "win32":  # dark title bar
            try:
                import ctypes
                hwnd = int(self.winId())
                val = ctypes.c_int(1)
                for attr in (20, 19):
                    if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                        break
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and not self.busy:
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if not urls:
            return
        p = Path(urls[0])
        folder = p if p.is_dir() else p.parent
        self.folder_edit.setText(str(folder))
        if len(urls) > 1:
            self._log("Several items dropped; using the first folder only.")
        self._scan()

    # ------------------------------------------------------------------ helpers
    def _set_primary(self, btn, on):
        btn.setProperty("primary", on)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _set_empty(self, kind, extra=""):
        msgs = {
            "default": ("Drop a mods folder here", "or click Browse, then Scan"),
            "scanning": ("Scanning\u2026", "Reading DDS headers"),
            "none": ("Nothing over the limit", extra or "Everything is already small enough"),
            "done": ("All done", extra),
            "error": ("Something went wrong", extra),
        }
        head, sub = msgs[kind]
        self.empty_label.setText(
            f"<div style='font-size:15pt; font-weight:600;'>{html.escape(head)}</div>"
            f"<div style='color:{C['muted']}; font-size:10pt;'>{html.escape(sub)}</div>")

    def _sync_presets(self, *_):
        val = self.max_spin.value()
        for n, b in self.preset_btns.items():
            b.blockSignals(True)
            b.setChecked(n == val)
            b.blockSignals(False)

    def _refresh_ui(self):
        has = self.model.rowCount() > 0
        self.stack.setCurrentIndex(1 if has else 0)
        busy = self.busy
        self.btn_scan.setEnabled(not busy)
        self.btn_restore.setEnabled(not busy)
        self.btn_shrink.setEnabled(not busy and self._checked_count() > 0)
        self.btn_all.setEnabled(not busy and has)
        self.btn_none.setEnabled(not busy and has)
        self.btn_cancel.setVisible(busy)
        for w in (self.folder_edit, self.exclude_edit, self.max_spin, self.backup_check, self.quality_combo,
                  self.tga_check):
            w.setEnabled(not busy)
        for b in self.preset_btns.values():
            b.setEnabled(not busy)
        self._set_primary(self.btn_scan, not has)
        self._set_primary(self.btn_shrink, has)

    def _visible_tex(self, ordered=True):
        if not ordered and not self.filter_edit.text().strip():
            return self.model.rows  # no filter: every row is visible, skip the slow proxy lookups
        out = []
        for r in range(self.proxy.rowCount()):
            src = self.proxy.mapToSource(self.proxy.index(r, 0)).row()
            out.append(self.model.rows[src])
        return out

    def _targets(self, ordered=True):
        return [t for t in self._visible_tex(ordered) if str(t.path) in self.model.checked]

    def _checked_count(self):
        return len(self._targets(ordered=False))

    def _update_stats(self):
        self._stats_timer.start()  # coalesce bursts of changes into one refresh

    def _do_update_stats(self):
        total = self.model.rowCount()
        tg = self._targets(ordered=False)
        self.stat_vals[0].setText(str(total))
        self.stat_vals[1].setText(str(len(tg)))
        saved = sum(t.size - t.est_new_size for t in tg)
        self.stat_vals[2].setText(f"~{human(saved)}" if tg else "-")
        self.btn_shrink.setText(f"Shrink checked ({len(tg)})" if tg else "Shrink checked")
        self.btn_shrink.setEnabled(not self.busy and len(tg) > 0)

    def _check_visible(self, on):
        self.model.set_checked([str(t.path) for t in self._visible_tex()], on)

    def _on_filter(self, text):
        self.proxy.setFilterFixedString(text.strip())
        self._update_stats()

    def _log(self, msg):
        color = C["bad"] if msg.startswith("FAIL") else (C["ok"] if msg.startswith("OK") else C["muted"])
        self.log_view.appendHtml(f"<span style='color:{color}; white-space:pre;'>{html.escape(msg)}</span>")
        if msg.startswith("FAIL") and self.log_view.isHidden():
            self._toggle_log()

    def _toggle_log(self):
        show = self.log_view.isHidden()
        self.log_view.setVisible(show)
        self.btn_log.setText("Hide log" if show else "Show log")

    def _set_busy(self, busy, indeterminate=False):
        self.busy = busy
        if busy:
            self.progress.setRange(0, 0 if indeterminate else 1)
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
        self._refresh_ui()

    # ------------------------------------------------------------------ actions
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Choose your mods folder", self.folder_edit.text() or "")
        if d:
            self.folder_edit.setText(d)

    def _get_root(self):
        text = self.folder_edit.text().strip()
        p = Path(text) if text else None
        if not p or not p.is_dir():
            QMessageBox.warning(self, APP_NAME, "Choose a valid mods folder first.")
            return None
        return p.resolve()

    def _excludes(self):
        return [e.strip() for e in self.exclude_edit.text().split(",") if e.strip()]

    def _scan(self):
        root = self._get_root()
        if not root or self.busy:
            return
        mx, excludes = self.max_spin.value(), self._excludes()
        include_tga = self.tga_check.isChecked()
        self._save_settings()
        self.model.set_rows([])
        self.cancel.clear()
        self.status.setText("Scanning\u2026")
        self._set_empty("scanning")
        self._set_busy(True, indeterminate=True)

        def work():
            try:
                res = scan(root, mx, excludes, should_stop=self.cancel.is_set, include_tga=include_tga)
                self.bus.scan_done.emit(res, mx)
            except Exception as e:  # noqa: BLE001
                self.bus.error.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_scan_done(self, results, mx):
        cancelled = self.cancel.is_set()
        self.model.set_rows(results)
        self.table.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        self._set_busy(False)
        if results:
            grow = sum(1 for t in results if t.grows)
            msg = (f"{len(results)} texture(s) over {mx}px"
                   f"{' (partial, scan cancelled)' if cancelled else ''}. Uncheck any you want to keep.")
            if grow:
                msg = (f"{len(results)} texture(s) over {mx}px. {grow} RLE TGA(s) would grow on disk "
                       "and start unchecked.")
            self.status.setText(msg)
        else:
            self._set_empty("none", f"No texture is larger than {mx}px.")
            self.status.setText("Scan cancelled." if cancelled else "Scan complete.")

    def _shrink(self):
        root = self._get_root()
        targets = self._targets()
        if not root or not targets or self.busy:
            return
        backup = default_backup_root(root) if self.backup_check.isChecked() else None
        if backup is None and QMessageBox.question(
                self, APP_NAME, "Backups are off. Originals will be overwritten permanently.\n\nContinue?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._save_settings()
        self.cancel.clear()
        self.status.setText(f"Shrinking {len(targets)} texture(s)\u2026")
        self._set_busy(True)
        self.progress.setRange(0, len(targets))
        self.progress.setValue(0)
        self._cur_text = ""
        self._tick_timer.start()
        bus, cancel = self.bus, self.cancel
        quality = self.quality_combo.currentData()

        def work():
            try:
                texconv = ensure_texconv(bus.log.emit)
            except Exception as e:  # noqa: BLE001
                bus.error.emit(f"Could not get texconv.exe: {e}")
                return
            saved = fails = 0
            if quality != "balanced":
                bus.log.emit(f"Encoding mode: {quality}")
            for i, t in enumerate(targets, 1):
                if cancel.is_set():
                    bus.log.emit("Cancelled.")
                    break
                rel = str(t.rel)
                rel = rel if len(rel) <= 70 else "\u2026" + rel[-69:]
                bus.current.emit(i, len(targets), f"{rel}  ({t.w}\u00d7{t.h}, {human(t.size)})")
                try:
                    b, a = shrink_one(t, texconv, backup, Path(tempfile.gettempdir()), cancel=cancel,
                                  quality=quality, log=bus.log.emit)
                    saved += b - a
                    bus.result.emit(str(t.path), True, f"OK   {t.rel}: {human(b)} -> {human(a)}")
                except Cancelled:
                    bus.log.emit(f"Cancelled while processing {t.rel} (that file was left unchanged).")
                    break
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    bus.result.emit(str(t.path), False, f"FAIL {t.rel}: {e}")
                bus.progress.emit(i, len(targets))
            bus.finished.emit(saved, fails, str(backup) if backup else "")
        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, i, n):
        self.progress.setValue(i)

    def _on_current(self, i, n, text):
        self._cur_text = f"Shrinking {i} / {n}: {text}"
        self._cur_start = time.time()
        self.status.setText(self._cur_text)

    def _tick(self):
        if self.busy and self._cur_text:
            self.status.setText(f"{self._cur_text}  \u00b7  {int(time.time() - self._cur_start)}s")

    def _on_result(self, key, ok, line):
        self._log(line)
        if ok:
            self._pending_remove.add(key)
            if not self._flush_timer.isActive():
                self._flush_timer.start()

    def _flush_removals(self):
        keys, self._pending_remove = self._pending_remove, set()
        self.model.remove_keys(keys)

    def _on_finished(self, saved, fails, backup):
        self._flush_timer.stop()
        self._flush_removals()
        self._tick_timer.stop()
        self._cur_text = ""
        self._set_busy(False)
        msg = f"Done. Saved about {human(saved)}."
        if fails:
            msg += f" {fails} failed (still listed)."
        if self.cancel.is_set():
            msg = "Cancelled. " + msg
        self.status.setText(msg)
        if backup:
            self._log(f"Originals backed up to: {backup}")
        if self.model.rowCount() == 0:
            self._set_empty("done", f"Saved about {human(saved)}. Scan again to check for more.")
        self._refresh_ui()

    def _on_error(self, text):
        self._tick_timer.stop()
        self._set_busy(False)
        self.status.setText("Something went wrong.")
        self._set_empty("error", text[:200])
        self._refresh_ui()
        QMessageBox.critical(self, APP_NAME, text)

    def _cancel(self):
        self.cancel.set()
        self.status.setText("Cancelling\u2026")

    def _restore(self):
        root = self._get_root()
        if not root:
            return
        backup = default_backup_root(root)
        if not backup.is_dir():
            QMessageBox.information(self, APP_NAME, f"No backup folder found at:\n{backup}")
            return
        if QMessageBox.question(
                self, APP_NAME,
                f"Copy all backed-up textures from\n{backup}\nback into the mods folder?"
        ) != QMessageBox.StandardButton.Yes:
            return
        n = restore_backups(root, backup, self._log)
        self.status.setText(f"Restored {n} texture(s) from backup. Scan again to refresh the list.")

    # ------------------------------------------------------------------ context menu
    def _context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        src = self.proxy.mapToSource(idx).row()
        t = self.model.rows[src]
        menu = QMenu(self)
        a_open = menu.addAction("Show in folder")
        a_skip = menu.addAction("Skip this mod from now on")
        a_rem = menu.addAction("Remove from list")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is a_open:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(t.path.parent)))
        elif chosen is a_rem:
            self.model.remove_keys([str(t.path)])
        elif chosen is a_skip:
            token = t.rel.parts[0] if len(t.rel.parts) > 1 else t.rel.stem
            current = self._excludes()
            if token not in current:
                self.exclude_edit.setText(", ".join(current + [token]))
            gone = [str(x.path) for x in self.model.rows if token.lower() in str(x.rel).lower()]
            self.model.remove_keys(gone)
            self.status.setText(f"Skipping \"{token}\" (added to the skip list).")


# --------------------------------------------------------------------------- entry

def install_excepthook():
    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        startup_log("CRASH:\n" + text)
        for folder in (app_dir(), data_dir()):
            try:
                (folder / "crash.log").write_text(text, encoding="utf-8")
                break
            except OSError:
                continue
        try:
            QMessageBox.critical(None, APP_NAME + " error", text[-1500:])
        except Exception:  # noqa: BLE001
            pass
    sys.excepthook = hook


def main():
    startup_log(f"qt start: python {sys.version.split()[0]}, mode={run_mode()}")
    install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_palette(app)
    app.setStyleSheet(build_qss())
    win = MainWindow()
    win.show()
    startup_log("qt: window shown")
    code = app.exec()
    startup_log("qt: exited normally")
    sys.exit(code)


if __name__ == "__main__":
    main()
