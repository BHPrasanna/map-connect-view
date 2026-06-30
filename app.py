"""
Modbus Mapping GUI
------------------
PyQt5 desktop app:
  * Left navigation (Connection / Mapping / Parameters / Debug Console)
  * Connection is the default landing page
  * CSV import for parameter mapping (with S.No column, editable cells)
  * Live parameter values once connected, reorder rows up/down per row
  * Debug console showing RX/TX messages

Run:
    pip install PyQt5 pymodbus
    python app.py

CSV columns (case-insensitive, S.No optional — auto-numbered if missing):
    s.no, address, parameter, data_type, scaling, unit
"""

import csv
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap, QImage, QColor, QIcon, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
    QPushButton, QLabel, QStackedWidget, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QLineEdit, QDialog, QDialogButtonBox, QFrame,
    QSizePolicy, QAbstractItemView, QPlainTextEdit, QToolButton, QMenu, QAction,
)

# ---------- Optional Modbus backend -----------------------------------------
try:
    from pymodbus.client import ModbusTcpClient
    HAS_PYMODBUS = True
except Exception:
    HAS_PYMODBUS = False


# ---------- Data model ------------------------------------------------------
@dataclass
class Parameter:
    address: int
    name: str
    data_type: str  # u16 / u32 / s16
    scaling: float
    unit: str
    value: Optional[float] = None


# ---------- Stylesheet ------------------------------------------------------
STYLE = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #1f2937; }
QMainWindow { background: #f6f7fb; }
QStackedWidget, QStackedWidget > QWidget { background: #f6f7fb; }

/* Sidebar — fully dark, all children transparent */
#Sidebar { background: #0b1220; border: none; }
#Sidebar QWidget { background: transparent; }
#Sidebar QLabel { background: transparent; color: #e5e7eb; }
#Sidebar QLabel#Brand {
    color: #f3f4f6; font-size: 14px; font-weight: 700;
    padding: 6px 12px 2px 12px;
}
#Sidebar QLabel#BrandSub {
    color: #9ca3af; font-size: 11px; padding: 0 12px 16px 12px;
}
#Sidebar QLabel#LogoLabel { background: transparent; padding: 22px 0 8px 0; }
#Sidebar QLabel#Footer { color: #6b7280; padding: 16px 20px; background: transparent; }

QListWidget#NavList {
    background: transparent; border: none; outline: 0; padding: 8px;
}
QListWidget#NavList::item {
    color: #cbd5e1; padding: 12px 16px; margin: 2px 6px;
    border-radius: 8px; font-weight: 600; background: transparent;
}
QListWidget#NavList::item:hover { background: #1f2937; color: #ffffff; }
QListWidget#NavList::item:selected { background: #2563eb; color: #ffffff; }

#PageTitle { font-size: 22px; font-weight: 700; color: #0f172a; background: transparent; }
#PageSubtitle { color: #6b7280; font-size: 13px; background: transparent; }

QFrame#Card {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px;
}
QFrame#Card QLabel { background: transparent; }
QLabel#FieldLabel { background: transparent; font-weight: 700; color: #0f172a; font-size: 13px; }
QLabel#StatusDot { background: transparent; font-size: 18px; }
QLabel#StatusText { background: transparent; color: #374151; font-weight: 600; }

QPushButton {
    background: #2563eb; color: white; border: none;
    padding: 9px 18px; border-radius: 8px; font-weight: 600;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton:disabled { background: #9ca3af; }
QPushButton#Secondary {
    background: #ffffff; color: #1f2937; border: 1px solid #d1d5db;
}
QPushButton#Secondary:hover { background: #f3f4f6; }
QPushButton#Danger { background: #dc2626; }
QPushButton#Danger:hover { background: #b91c1c; }

QLineEdit, QComboBox {
    background: #ffffff; border: 1px solid #d1d5db; border-radius: 8px;
    padding: 8px 10px; min-height: 20px;
    selection-background-color: #2563eb;
}
QComboBox::drop-down { border: none; width: 22px; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }

QTableWidget {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px;
    gridline-color: #f1f5f9; selection-background-color: #dbeafe;
    selection-color: #1e3a8a;
}
QHeaderView::section {
    background: #f9fafb; color: #374151; padding: 8px; border: none;
    border-bottom: 1px solid #e5e7eb; font-weight: 600;
}
QTableWidget::item { padding: 2px 6px; }

QPlainTextEdit#Console {
    background: #0b1020; color: #d1d5db; border: 1px solid #1f2937;
    border-radius: 10px; padding: 12px;
    font-family: 'Consolas', 'Menlo', monospace; font-size: 12px;
}

QLabel#DragHandle {
    background: transparent; color: #9ca3af; font-size: 16px;
    font-weight: 700; padding: 0 8px;
}
QLabel#DragHandle:hover { color: #2563eb; }
"""


# ---------- Utilities -------------------------------------------------------
def make_transparent_pixmap(path: str, max_w: int = 140, tol: int = 18) -> QPixmap:
    """Load image and turn near-white pixels transparent so it blends on dark bg."""
    img = QImage(path)
    if img.isNull():
        return QPixmap()
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    for y in range(h):
        for x in range(w):
            c = QColor(img.pixel(x, y))
            if c.red() > 255 - tol and c.green() > 255 - tol and c.blue() > 255 - tol:
                img.setPixelColor(x, y, QColor(0, 0, 0, 0))
    pm = QPixmap.fromImage(img)
    if pm.width() > max_w:
        pm = pm.scaledToWidth(max_w, Qt.SmoothTransformation)
    return pm


# ---------- Add Parameter dialog -------------------------------------------
class AddParameterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Parameter")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Add Parameter")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.name_edit = QLineEdit()
        self.address_edit = QLineEdit(); self.address_edit.setPlaceholderText("e.g. 40001")
        self.type_combo = QComboBox(); self.type_combo.addItems(["u16", "u32", "s16"])
        self.scaling_edit = QLineEdit(); self.scaling_edit.setPlaceholderText("e.g. 0.1")
        self.unit_edit = QLineEdit(); self.unit_edit.setPlaceholderText("e.g. V, A, kWh")

        form.addRow("Parameter Name", self.name_edit)
        form.addRow("Address", self.address_edit)
        form.addRow("Data Type", self.type_combo)
        form.addRow("Scaling Factor", self.scaling_edit)
        form.addRow("Unit", self.unit_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.try_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText("Add")
        layout.addWidget(buttons)

    def try_accept(self):
        try:
            self._param = Parameter(
                address=int(self.address_edit.text().strip()),
                name=self.name_edit.text().strip(),
                data_type=self.type_combo.currentText(),
                scaling=float(self.scaling_edit.text().strip() or "1"),
                unit=self.unit_edit.text().strip(),
            )
            if not self._param.name:
                raise ValueError("Name required")
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Invalid input", f"Please check the fields.\n\n{e}")

    def parameter(self) -> Parameter:
        return self._param


# ---------- Mapping page ----------------------------------------------------
class MappingPage(QWidget):
    csv_imported = pyqtSignal()
    mapping_changed = pyqtSignal()

    COLS = ["S.No", "Parameter", "Address", "Data Type", "Scaling", "Unit"]

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._suspend = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Parameter Mapping")
        title.setObjectName("PageTitle")
        sub = QLabel("Import a CSV file or add parameters manually. Double-click any cell to edit.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout(); bar.setSpacing(10)
        self.import_btn = QPushButton("Import CSV")
        self.import_btn.clicked.connect(self.import_csv)
        self.add_btn = QPushButton("✎  + Add Parameter")
        self.add_btn.setObjectName("Secondary")
        self.add_btn.clicked.connect(self.add_parameter)
        self.del_btn = QPushButton("🗑  Delete Row")
        self.del_btn.setObjectName("Secondary")
        self.del_btn.clicked.connect(self.delete_selected)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Secondary")
        self.clear_btn.clicked.connect(self.clear_all)
        bar.addWidget(self.import_btn)
        bar.addWidget(self.add_btn)
        bar.addWidget(self.del_btn)
        bar.addStretch()
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        # Compact fixed row height so editor doesn't grow the row
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(30)
        # Editable on double-click
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.itemChanged.connect(self._on_item_changed)
        cl.addWidget(self.table)

        root.addWidget(card, 1)

    # ---- actions ----
    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            params: List[Parameter] = []
            with open(path, newline="") as f:
                reader = csv.DictReader(f)
                fmap = {k.lower().strip(): k for k in reader.fieldnames or []}

                def col(row, *names):
                    for n in names:
                        if n in fmap:
                            return row[fmap[n]]
                    return ""

                for row in reader:
                    name = col(row, "parameter", "parameter name", "name").strip()
                    if not name:
                        continue
                    params.append(Parameter(
                        address=int(float(col(row, "address"))),
                        name=name,
                        data_type=(col(row, "data_type", "type", "datatype") or "u16").strip().lower(),
                        scaling=float(col(row, "scaling", "scaling factor") or 1),
                        unit=col(row, "unit").strip(),
                    ))
            if not params:
                raise ValueError("No valid rows found.")
            self.store.parameters = params
            self.refresh()
            self.csv_imported.emit()
            self.mapping_changed.emit()
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def add_parameter(self):
        dlg = AddParameterDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self.store.parameters.append(dlg.parameter())
            self.refresh()
            self.mapping_changed.emit()

    def delete_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        for r in rows:
            if 0 <= r < len(self.store.parameters):
                del self.store.parameters[r]
        self.refresh()
        self.mapping_changed.emit()

    def clear_all(self):
        if not self.store.parameters:
            return
        if QMessageBox.question(self, "Clear", "Remove all parameters?") == QMessageBox.Yes:
            self.store.parameters.clear()
            self.refresh()
            self.mapping_changed.emit()

    def refresh(self):
        self._suspend = True
        self.table.setRowCount(len(self.store.parameters))
        for r, p in enumerate(self.store.parameters):
            vals = [str(r + 1), p.name, str(p.address), p.data_type, str(p.scaling), p.unit]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if c != 1:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
        self._suspend = False

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._suspend:
            return
        r, c = item.row(), item.column()
        if r >= len(self.store.parameters):
            return
        p = self.store.parameters[r]
        text = item.text().strip()
        try:
            if c == 1:
                p.name = text or p.name
            elif c == 2:
                p.address = int(float(text))
            elif c == 3:
                if text.lower() not in ("u16", "u32", "s16"):
                    raise ValueError("Data type must be u16, u32 or s16")
                p.data_type = text.lower()
            elif c == 4:
                p.scaling = float(text)
            elif c == 5:
                p.unit = text
            self.mapping_changed.emit()
        except Exception as e:
            QMessageBox.warning(self, "Invalid value", str(e))
            self.refresh()


# ---------- Connection page -------------------------------------------------
class ConnectionPage(QWidget):
    connected_changed = pyqtSignal(bool)
    log = pyqtSignal(str, str)  # (direction, message)

    POLL_RATES = [("250 ms", 250), ("500 ms", 500), ("1 sec", 1000),
                  ("2 sec", 2000), ("5 sec", 5000), ("10 sec", 10000)]

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.client = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Connection")
        title.setObjectName("PageTitle")
        sub = QLabel("Configure the protocol, set polling rate, then connect to your device.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(24, 24, 24, 24); cl.setSpacing(16)

        proto_row = QFormLayout(); proto_row.setSpacing(12)
        self.proto_combo = QComboBox(); self.proto_combo.addItems(["Modbus TCP"])
        self.proto_combo.currentTextChanged.connect(self._rebuild_fields)
        proto_row.addRow("Protocol", self.proto_combo)
        cl.addLayout(proto_row)

        self.fields_form = QFormLayout(); self.fields_form.setSpacing(12)
        self.field_widgets = {}
        cl.addLayout(self.fields_form)

        # Polling rate
        poll_form = QFormLayout(); poll_form.setSpacing(12)
        self.poll_combo = QComboBox()
        for label, _ in self.POLL_RATES:
            self.poll_combo.addItem(label)
        self.poll_combo.setCurrentIndex(2)  # default 1 sec
        self.poll_combo.currentIndexChanged.connect(self._on_poll_changed)
        poll_form.addRow("Polling Rate", self.poll_combo)
        cl.addLayout(poll_form)

        bottom = QHBoxLayout()
        self.status_dot = QLabel("●"); self.status_dot.setObjectName("StatusDot")
        self.status_dot.setStyleSheet("color:#9ca3af;")
        self.status_text = QLabel("Disconnected"); self.status_text.setObjectName("StatusText")
        bottom.addWidget(self.status_dot)
        bottom.addWidget(self.status_text)
        bottom.addStretch()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connect)
        bottom.addWidget(self.connect_btn)
        cl.addLayout(bottom)

        root.addWidget(card)
        root.addStretch()

        self._rebuild_fields(self.proto_combo.currentText())

    def poll_interval_ms(self) -> int:
        return self.POLL_RATES[self.poll_combo.currentIndex()][1]

    def _on_poll_changed(self, _idx):
        self.log.emit("INFO", f"Polling rate set to {self.poll_combo.currentText()}")
        # MainWindow listens via poll_combo signal? Easier: emit connected_changed with current state
        self.connected_changed.emit(self.store.connected)

    def _rebuild_fields(self, proto):
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self.field_widgets.clear()
        if proto == "Modbus TCP":
            ip = QLineEdit("127.0.0.1")
            port = QLineEdit("502")
            unit = QLineEdit("1")
            self.fields_form.addRow("IP Address", ip)
            self.fields_form.addRow("Port", port)
            self.fields_form.addRow("Unit ID", unit)
            self.field_widgets = {"ip": ip, "port": port, "unit": unit}

    def toggle_connect(self):
        if self.store.connected:
            self._disconnect()
            return

        ip = self.field_widgets["ip"].text().strip()
        try:
            port = int(self.field_widgets["port"].text().strip())
            unit = int(self.field_widgets["unit"].text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Port and Unit ID must be integers.")
            return

        self.log.emit("INFO", f"Connecting to {ip}:{port} (unit {unit})...")
        if HAS_PYMODBUS:
            try:
                self.client = ModbusTcpClient(ip, port=port)
                ok = self.client.connect()
                if not ok:
                    raise ConnectionError("Could not reach device.")
                self.store.unit_id = unit
            except Exception as e:
                QMessageBox.critical(self, "Connection failed", str(e))
                self.log.emit("ERR", f"Connection failed: {e}")
                self.client = None
                return
        else:
            self.client = "SIMULATED"
            self.log.emit("INFO", "pymodbus not installed — running in SIMULATED mode")

        self.store.connected = True
        self._set_status(True)
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setObjectName("Danger")
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self.log.emit("INFO", "Connected.")
        self.connected_changed.emit(True)

    def _disconnect(self):
        if HAS_PYMODBUS and self.client and self.client != "SIMULATED":
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.store.connected = False
        self._set_status(False)
        self.connect_btn.setText("Connect")
        self.connect_btn.setObjectName("")
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
        self.log.emit("INFO", "Disconnected.")
        self.connected_changed.emit(False)

    def _set_status(self, ok: bool):
        if ok:
            self.status_dot.setStyleSheet("color:#16a34a;")
            mode = "" if HAS_PYMODBUS else "  (simulated — install pymodbus for live data)"
            self.status_text.setText(f"Connected{mode}")
        else:
            self.status_dot.setStyleSheet("color:#9ca3af;")
            self.status_text.setText("Disconnected")

    def read_value(self, p: Parameter):
        if not self.store.connected:
            return None
        count = 2 if p.data_type == "u32" else 1

        if self.client == "SIMULATED" or not HAS_PYMODBUS:
            import random
            raw = random.randint(0, 1000)
            self.log.emit("TX", f"READ addr={p.address} count={count} unit={self.store.unit_id}")
            value = round(raw * p.scaling, 3)
            self.log.emit("RX", f"addr={p.address} raw={raw} value={value}{(' '+p.unit) if p.unit else ''}")
            return value

        try:
            self.log.emit("TX", f"READ addr={p.address} count={count} unit={self.store.unit_id}")
            rr = self.client.read_holding_registers(p.address, count=count)
            if rr.isError():
                self.log.emit("ERR", f"addr={p.address} -> {rr}")
                return None
            if count == 2:
                raw = (rr.registers[0] << 16) | rr.registers[1]
            else:
                raw = rr.registers[0]
            if p.data_type == "s16" and raw >= 32768:
                raw -= 65536
            value = round(raw * p.scaling, 3)
            self.log.emit("RX", f"addr={p.address} regs={rr.registers} value={value}{(' '+p.unit) if p.unit else ''}")
            return value
        except Exception as e:
            self.log.emit("ERR", f"addr={p.address} crash: {e}")
            return None


# ---------- Parameters page -------------------------------------------------
class ParametersPage(QWidget):
    COLS = ["", "S.No", "Parameter", "Address", "Value", "Unit"]

    def __init__(self, store, connection: "ConnectionPage"):
        super().__init__()
        self.store = store
        self.connection = connection
        self._build()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_values)
        self.timer.start(self.connection.poll_interval_ms())
        self.connection.connected_changed.connect(self._sync_timer)

    def _sync_timer(self, _connected):
        self.timer.setInterval(self.connection.poll_interval_ms())

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Parameters")
        title.setObjectName("PageTitle")
        sub = QLabel("Live values update once connected. Use the ☰ menu on each row to reorder.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        cl.addWidget(self.table)

        root.addWidget(card, 1)

    def refresh(self):
        self.table.setRowCount(len(self.store.parameters))
        for r, p in enumerate(self.store.parameters):
            # hamburger menu button
            btn = QToolButton()
            btn.setObjectName("RowMenu")
            btn.setText("☰")
            btn.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(btn)
            up = QAction("▲  Move Up", menu); up.triggered.connect(lambda _, i=r: self._move(i, -1))
            dn = QAction("▼  Move Down", menu); dn.triggered.connect(lambda _, i=r: self._move(i, 1))
            top = QAction("⤒  Move to Top", menu); top.triggered.connect(lambda _, i=r: self._move_to(i, 0))
            bot = QAction("⤓  Move to Bottom", menu); bot.triggered.connect(lambda _, i=r: self._move_to(i, len(self.store.parameters) - 1))
            rm = QAction("🗑  Remove", menu); rm.triggered.connect(lambda _, i=r: self._remove(i))
            menu.addAction(up); menu.addAction(dn); menu.addAction(top); menu.addAction(bot)
            menu.addSeparator(); menu.addAction(rm)
            btn.setMenu(menu)
            self.table.setCellWidget(r, 0, btn)

            val = "" if p.value is None else str(p.value)
            vals = [None, str(r + 1), p.name, str(p.address), val, p.unit]
            for c, v in enumerate(vals):
                if c == 0:
                    continue
                item = QTableWidgetItem(v)
                if c != 2:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)

    def _move(self, idx: int, delta: int):
        new = idx + delta
        if 0 <= new < len(self.store.parameters):
            ps = self.store.parameters
            ps[idx], ps[new] = ps[new], ps[idx]
            self.refresh()

    def _move_to(self, idx: int, target: int):
        ps = self.store.parameters
        if 0 <= idx < len(ps) and 0 <= target < len(ps):
            p = ps.pop(idx)
            ps.insert(target, p)
            self.refresh()

    def _remove(self, idx: int):
        if 0 <= idx < len(self.store.parameters):
            del self.store.parameters[idx]
            self.refresh()

    def poll_values(self):
        if self.store.connected:
            for p in self.store.parameters:
                p.value = self.connection.read_value(p)
        self.refresh()


# ---------- Debug console ---------------------------------------------------
class DebugConsolePage(QWidget):
    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Debug Console")
        title.setObjectName("PageTitle")
        sub = QLabel("Live TX / RX log of Modbus communication.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        bar = QHBoxLayout()
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Secondary")
        self.clear_btn.clicked.connect(lambda: self.console.clear())
        bar.addStretch(); bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        root.addWidget(self.console, 1)

    def append(self, direction: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = {"TX": "#60a5fa", "RX": "#34d399", "ERR": "#f87171", "INFO": "#fbbf24"}.get(direction, "#d1d5db")
        self.console.appendHtml(
            f'<span style="color:#6b7280;">[{ts}]</span> '
            f'<span style="color:{color};font-weight:600;">{direction:<4}</span> '
            f'<span style="color:#e5e7eb;">{msg}</span>'
        )


# ---------- Shared state ----------------------------------------------------
class Store:
    def __init__(self):
        self.parameters: List[Parameter] = []
        self.connected: bool = False
        self.unit_id: int = 1


# ---------- Main window -----------------------------------------------------
class MainWindow(QMainWindow):
    NAV_ITEMS = [
        ("🖧  Connection", "connection"),
        ("⚙  Mapping", "mapping"),
        ("📊  Parameters", "parameters"),
        ("🐞  Debug Console", "debug"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Modbus Mapping Studio")
        self.resize(1180, 720)
        self.store = Store()
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget(); sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        sl = QVBoxLayout(sidebar); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(0)

        # Transparent logo
        self.logo_label = QLabel()
        script_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(script_dir, "delta_logo.png")
        pm = make_transparent_pixmap(logo_path, max_w=130) if os.path.exists(logo_path) else QPixmap()
        if not pm.isNull():
            self.logo_label.setPixmap(pm)
        else:
            self.logo_label.setText("◆")
            self.logo_label.setStyleSheet("color:#ffffff; font-size:36px;")
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setStyleSheet(self.logo_label.styleSheet() + "background: transparent; padding: 22px 0 8px 0;")
        sl.addWidget(self.logo_label)

        brand = QLabel("Universal Modbus Monitor")
        brand.setObjectName("Brand"); brand.setAlignment(Qt.AlignCenter)
        brand.setWordWrap(True)
        sub = QLabel("Hardware Diagnostics")
        sub.setObjectName("BrandSub"); sub.setAlignment(Qt.AlignCenter)
        sl.addWidget(brand)
        sl.addWidget(sub)

        self.nav = QListWidget(); self.nav.setObjectName("NavList")
        for label, _ in self.NAV_ITEMS:
            QListWidgetItem(label, self.nav)
        sl.addWidget(self.nav, 1)

        footer = QLabel("v1.1")
        footer.setStyleSheet("color:#6b7280; padding: 16px 20px;")
        sl.addWidget(footer)

        layout.addWidget(sidebar)

        # Pages
        self.stack = QStackedWidget()
        self.connection_page = ConnectionPage(self.store)
        self.mapping_page = MappingPage(self.store)
        self.parameters_page = ParametersPage(self.store, self.connection_page)
        self.debug_page = DebugConsolePage()

        # Order matches NAV_ITEMS
        self.stack.addWidget(self.connection_page)
        self.stack.addWidget(self.mapping_page)
        self.stack.addWidget(self.parameters_page)
        self.stack.addWidget(self.debug_page)
        layout.addWidget(self.stack, 1)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)  # Connection is default

        # Wiring
        self.connection_page.log.connect(self.debug_page.append)
        self.connection_page.connected_changed.connect(self._on_connected)
        self.mapping_page.csv_imported.connect(self._after_csv_import)
        self.mapping_page.mapping_changed.connect(self.parameters_page.refresh)

    def _on_connected(self, connected: bool):
        self.parameters_page.refresh()
        # If connected and there are no parameters yet, nudge user to Mapping
        if connected and not self.store.parameters:
            QMessageBox.information(
                self, "Add a mapping",
                "Connected. Now import a CSV in the Mapping tab — values will appear in Parameters automatically.",
            )
            # jump to mapping tab
            self.nav.setCurrentRow(1)

    def _after_csv_import(self):
        # After importing CSV, jump to Parameters tab to see live values
        self.parameters_page.refresh()
        self.nav.setCurrentRow(2)


# ---------- Entry -----------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
