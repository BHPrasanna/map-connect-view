"""
Modbus Mapping GUI
------------------
PyQt5 desktop app:
  * Left navigation (Connection / Mapping / Parameters / Debug Console)
  * Connection is the default landing page
  * CSV import for parameter mapping (with S.No column, editable cells)
  * Live parameter values once connected, drag-reorder rows
  * Debug console showing raw TX/RX Modbus frames (hex)

Run:
    pip install PyQt5 pymodbus pyserial
    python app.py

CSV columns (case-insensitive, S.No optional — auto-numbered if missing):
    s.no, address, parameter, data_type, scaling, unit
"""

import csv
import os
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap, QImage, QColor, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
    QPushButton, QLabel, QStackedWidget, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QLineEdit, QDialog, QDialogButtonBox, QFrame,
    QSizePolicy, QAbstractItemView, QPlainTextEdit, QToolButton,
    QStyledItemDelegate,
)

# ---------- Optional Modbus backend -----------------------------------------
try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
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
    value: Optional[object] = None

    @property
    def is_status(self) -> bool:
        u = (self.unit or "").strip()
        return u == "" or u == "--"


# ---------- Stylesheets -----------------------------------------------------
LIGHT_STYLE = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #1f2937; }
QMainWindow { background: #f6f7fb; }
QStackedWidget, QStackedWidget > QWidget { background: #f6f7fb; }

#Sidebar { background: #ffffff; border-right: 1px solid #e5e7eb; }
#Sidebar QWidget { background: transparent; }
#Sidebar QLabel { background: transparent; color: #1f2937; }
#Sidebar QLabel#Brand { color: #0f172a; font-size: 14px; font-weight: 800; padding: 6px 12px 2px 12px; }
#Sidebar QLabel#BrandSub { color: #6b7280; font-size: 11px; padding: 0 12px 16px 12px; font-weight: 600; }
#Sidebar QLabel#LogoLabel { background: transparent; padding: 22px 0 8px 0; }
#Sidebar QLabel#Footer { color: #9ca3af; padding: 14px 20px; background: transparent; }

QListWidget#NavList { background: transparent; border: none; outline: 0; padding: 8px; }
QListWidget#NavList::item {
    color: #1f2937; padding: 12px 16px; margin: 2px 6px;
    border-radius: 8px; font-weight: 800; background: transparent;
}
QListWidget#NavList::item:hover { background: #eef2ff; color: #1e3a8a; }
QListWidget#NavList::item:selected { background: #2563eb; color: #ffffff; }

#PageTitle { font-size: 22px; font-weight: 700; color: #0f172a; background: transparent; }
#PageSubtitle { color: #6b7280; font-size: 13px; background: transparent; }

QFrame#Card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; }
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
QPushButton#Secondary { background: #ffffff; color: #1f2937; border: 1px solid #d1d5db; }
QPushButton#Secondary:hover { background: #f3f4f6; }
QPushButton#Danger { background: #dc2626; }
QPushButton#Danger:hover { background: #b91c1c; }
QToolButton#ThemeToggle {
    background: transparent; border: 1px solid #e5e7eb; border-radius: 8px;
    padding: 6px; color: #1f2937; font-size: 14px;
}
QToolButton#ThemeToggle:hover { background: #f3f4f6; }
QToolButton#IconBtn {
    background: transparent; border: none; font-size: 15px; padding: 2px;
}
QToolButton#IconBtn:hover { background: #fee2e2; border-radius: 6px; }

QLineEdit, QComboBox {
    background: #ffffff; border: 1px solid #d1d5db; border-radius: 8px;
    padding: 8px 10px; min-height: 20px; color: #0f172a;
    selection-background-color: #2563eb;
}
QComboBox::drop-down { border: none; width: 22px; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }

QTableWidget {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px;
    gridline-color: #f1f5f9; selection-background-color: #dbeafe; selection-color: #1e3a8a;
}
QHeaderView::section {
    background: #f9fafb; color: #374151; padding: 8px; border: none;
    border-bottom: 1px solid #e5e7eb; font-weight: 700;
}
QTableWidget::item { padding: 2px 6px; }

QPlainTextEdit#Console {
    background: #ffffff; color: #1f2937; border: 1px solid #e5e7eb;
    border-radius: 10px; padding: 12px;
    font-family: 'Consolas', 'Menlo', monospace; font-size: 12px;
}

QLabel#DragHandle { background: transparent; color: #9ca3af; font-size: 16px; font-weight: 700; padding: 0 8px; }
QLabel#DragHandle:hover { color: #2563eb; }
"""

DARK_STYLE = LIGHT_STYLE.replace("#ffffff", "#111827").replace("#f6f7fb", "#0f172a")  # simple fallback


# ---------- Utilities -------------------------------------------------------
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def make_transparent_pixmap(path: str, max_w: int = 140, tol: int = 18) -> QPixmap:
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


# ---------- Modbus frame builders (for raw display) ------------------------
def _crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _lrc(data: bytes) -> int:
    return ((-sum(data)) & 0xFF)


def build_read_frame(mode: str, unit: int, address: int, count: int, tid: int = 1) -> bytes:
    """Build the raw wire frame for a Read Holding Registers (FC=3) request."""
    fc = 0x03
    if mode == "TCP":
        # MBAP + PDU
        pdu = struct.pack(">BHH", fc, address, count)
        mbap = struct.pack(">HHHB", tid & 0xFFFF, 0, len(pdu) + 1, unit & 0xFF)
        return mbap + pdu
    elif mode == "RTU":
        core = struct.pack(">BBHH", unit & 0xFF, fc, address, count)
        crc = _crc16(core)
        return core + struct.pack("<H", crc)
    elif mode == "ASCII":
        core = struct.pack(">BBHH", unit & 0xFF, fc, address, count)
        lrc = _lrc(core)
        body = (core + bytes([lrc])).hex().upper().encode()
        return b":" + body + b"\r\n"
    return b""


def build_read_response(mode: str, unit: int, registers: List[int], tid: int = 1) -> bytes:
    fc = 0x03
    reg_bytes = b"".join(struct.pack(">H", r & 0xFFFF) for r in registers)
    pdu = struct.pack(">BB", fc, len(reg_bytes)) + reg_bytes
    if mode == "TCP":
        mbap = struct.pack(">HHHB", tid & 0xFFFF, 0, len(pdu) + 1, unit & 0xFF)
        return mbap + pdu
    elif mode == "RTU":
        core = struct.pack(">B", unit & 0xFF) + pdu
        return core + struct.pack("<H", _crc16(core))
    elif mode == "ASCII":
        core = struct.pack(">B", unit & 0xFF) + pdu
        lrc = _lrc(core)
        return b":" + (core + bytes([lrc])).hex().upper().encode() + b"\r\n"
    return b""


def hexify(b: bytes) -> str:
    if not b:
        return ""
    # ASCII frames are human-readable
    if b.startswith(b":"):
        try:
            return b.decode("ascii").rstrip("\r\n")
        except Exception:
            pass
    return " ".join(f"{x:02X}" for x in b)


# ---------- Data-type dropdown delegate (double-click reveals combo) -------
class DataTypeDelegate(QStyledItemDelegate):
    OPTIONS = ["u16", "u32", "s16"]

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(self.OPTIONS)
        return cb

    def setEditorData(self, editor, index):
        val = (index.data() or "u16").lower()
        i = editor.findText(val)
        editor.setCurrentIndex(i if i >= 0 else 0)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.EditRole)


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

        form = QFormLayout(); form.setSpacing(10)
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

    COLS = ["S.No", "Parameter", "Address", "Data Type", "Scaling", "Unit", ""]
    COL_DELETE = 6

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._suspend = False
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Parameter Mapping"); title.setObjectName("PageTitle")
        sub = QLabel("Import a CSV file or add parameters manually. Double-click any cell to edit.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title); root.addWidget(sub)

        bar = QHBoxLayout(); bar.setSpacing(10)
        self.import_btn = QPushButton("Import CSV"); self.import_btn.clicked.connect(self.import_csv)
        self.add_btn = QPushButton("+ Add Parameter"); self.add_btn.setObjectName("Secondary")
        self.add_btn.clicked.connect(self.add_parameter)
        self.clear_btn = QPushButton("Clear"); self.clear_btn.setObjectName("Secondary")
        self.clear_btn.clicked.connect(self.clear_all)
        bar.addWidget(self.import_btn); bar.addWidget(self.add_btn); bar.addStretch(); bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_DELETE, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        # Dropdown delegate for the Data Type column — only appears on double-click
        self.table.setItemDelegateForColumn(3, DataTypeDelegate(self.table))
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
                            v = row[fmap[n]]
                            return "" if v is None else str(v)
                    return ""

                for row in reader:
                    name = col(row, "parameter", "parameter name", "name").strip()
                    if not name:
                        continue
                    dt_raw = col(row, "data_type", "type", "datatype").strip().lower()
                    if dt_raw not in ("u16", "u32", "s16"):
                        dt_raw = "u16"
                    try:
                        scaling = float(col(row, "scaling", "scaling factor") or 1)
                    except ValueError:
                        scaling = 1.0
                    params.append(Parameter(
                        address=int(float(col(row, "address"))),
                        name=name,
                        data_type=dt_raw,
                        scaling=scaling,
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

    def delete_row(self, row: int):
        if not (0 <= row < len(self.store.parameters)):
            return
        p = self.store.parameters[row]
        if QMessageBox.question(self, "Delete", f"Delete parameter '{p.name}'?") != QMessageBox.Yes:
            return
        del self.store.parameters[row]
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
            # Delete button widget
            btn = QToolButton()
            btn.setObjectName("IconBtn")
            btn.setText("🗑")
            btn.setToolTip("Delete row")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, row=r: self.delete_row(row))
            self.table.setCellWidget(r, self.COL_DELETE, btn)
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

    PROTOCOLS = ["Modbus TCP", "Modbus RTU", "Modbus ASCII"]

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.client = None
        self._tid = 0
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Connection"); title.setObjectName("PageTitle")
        sub = QLabel("Configure the protocol, set polling rate, then connect to your device.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title); root.addWidget(sub)

        center_row = QHBoxLayout(); center_row.addStretch()
        card = QFrame(); card.setObjectName("Card")
        card.setMaximumWidth(720); card.setMinimumWidth(560)
        cl = QVBoxLayout(card); cl.setContentsMargins(32, 28, 32, 28); cl.setSpacing(14)
        center_row.addWidget(card, 1); center_row.addStretch()

        def bold(text):
            lbl = QLabel(text); lbl.setObjectName("FieldLabel")
            lbl.setMinimumWidth(120); lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return lbl

        self.form = QFormLayout()
        self.form.setSpacing(14)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFormAlignment(Qt.AlignTop)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.form.setHorizontalSpacing(20)

        self.proto_combo = QComboBox(); self.proto_combo.addItems(self.PROTOCOLS)
        self.proto_combo.currentTextChanged.connect(self._rebuild_fields)
        self.proto_combo.setMinimumWidth(360)
        self.proto_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.form.addRow(bold("Protocol"), self.proto_combo)

        self.field_widgets = {}
        self._dynamic_label = bold

        self._poll_index = 2  # remembered across rebuilds
        self.poll_combo = None

        cl.addLayout(self.form)


        bottom = QHBoxLayout()
        self.status_dot = QLabel("●"); self.status_dot.setObjectName("StatusDot")
        self.status_dot.setStyleSheet("color:#9ca3af; background: transparent;")
        self.status_text = QLabel("Disconnected"); self.status_text.setObjectName("StatusText")
        bottom.addWidget(self.status_dot); bottom.addWidget(self.status_text); bottom.addStretch()
        self.connect_btn = QPushButton("Connect"); self.connect_btn.setMinimumWidth(140)
        self.connect_btn.clicked.connect(self.toggle_connect)
        bottom.addWidget(self.connect_btn)
        cl.addLayout(bottom)

        root.addLayout(center_row); root.addStretch()

        self._rebuild_fields(self.proto_combo.currentText())

    def poll_interval_ms(self) -> int:
        return self.POLL_RATES[self.poll_combo.currentIndex()][1]

    def current_mode(self) -> str:
        p = self.proto_combo.currentText()
        if "TCP" in p:
            return "TCP"
        if "RTU" in p:
            return "RTU"
        return "ASCII"

    def _on_poll_changed(self, _idx):
        self.log.emit("INFO", f"Polling rate set to {self.poll_combo.currentText()}")
        self.connected_changed.emit(self.store.connected)

    def _mkline(self, text=""):
        w = QLineEdit(text)
        w.setMinimumWidth(360)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return w

    def _mkcombo(self, items, default_index=0):
        w = QComboBox(); w.addItems(items); w.setCurrentIndex(default_index)
        w.setMinimumWidth(360)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return w

    def _rebuild_fields(self, proto):
        # Clear all rows after Protocol
        while self.form.rowCount() > 1:
            self.form.removeRow(1)
        self.field_widgets.clear()
        bold = self._dynamic_label

        if proto == "Modbus TCP":
            self.field_widgets["ip"] = self._mkline("127.0.0.1")
            self.field_widgets["port"] = self._mkline("502")
            self.field_widgets["unit"] = self._mkline("1")
            self.form.addRow(bold("IP Address"), self.field_widgets["ip"])
            self.form.addRow(bold("Port"), self.field_widgets["port"])
            self.form.addRow(bold("Unit ID"), self.field_widgets["unit"])
        else:
            # RTU / ASCII — serial parameters
            self.field_widgets["port"] = self._mkline("COM1" if sys.platform.startswith("win") else "/dev/ttyUSB0")
            self.field_widgets["baud"] = self._mkcombo(
                ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"], default_index=3)
            self.field_widgets["parity"] = self._mkcombo(["None", "Even", "Odd"], default_index=0)
            self.field_widgets["databits"] = self._mkcombo(["7", "8"], default_index=1)
            self.field_widgets["stopbits"] = self._mkcombo(["1", "2"], default_index=0)
            self.field_widgets["unit"] = self._mkline("1")
            self.form.addRow(bold("Serial Port"), self.field_widgets["port"])
            self.form.addRow(bold("Baud Rate"), self.field_widgets["baud"])
            self.form.addRow(bold("Parity"), self.field_widgets["parity"])
            self.form.addRow(bold("Data Bits"), self.field_widgets["databits"])
            self.form.addRow(bold("Stop Bits"), self.field_widgets["stopbits"])
            self.form.addRow(bold("Device ID"), self.field_widgets["unit"])

        self.form.addRow(bold("Polling Rate"), self.poll_combo)

    def toggle_connect(self):
        if self.store.connected:
            self._disconnect()
            return
        mode = self.current_mode()
        try:
            unit = int(self.field_widgets["unit"].text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Unit / Device ID must be an integer.")
            return

        if mode == "TCP":
            ip = self.field_widgets["ip"].text().strip()
            try:
                port = int(self.field_widgets["port"].text().strip())
            except ValueError:
                QMessageBox.warning(self, "Invalid", "Port must be an integer.")
                return
            self.log.emit("INFO", f"Connecting Modbus TCP {ip}:{port} (unit {unit})...")
            if HAS_PYMODBUS:
                try:
                    self.client = ModbusTcpClient(ip, port=port)
                    if not self.client.connect():
                        raise ConnectionError("Could not reach device.")
                except Exception as e:
                    QMessageBox.critical(self, "Connection failed", str(e))
                    self.log.emit("ERR", f"Connection failed: {e}")
                    self.client = None
                    return
            else:
                self.client = "SIMULATED"
        else:
            serial_port = self.field_widgets["port"].text().strip()
            baud = int(self.field_widgets["baud"].currentText())
            parity = {"None": "N", "Even": "E", "Odd": "O"}[self.field_widgets["parity"].currentText()]
            databits = int(self.field_widgets["databits"].currentText())
            stopbits = int(self.field_widgets["stopbits"].currentText())
            framer = "rtu" if mode == "RTU" else "ascii"
            self.log.emit("INFO",
                f"Connecting Modbus {mode} {serial_port} {baud} {databits}{parity}{stopbits} (unit {unit})...")
            if HAS_PYMODBUS:
                try:
                    # pymodbus 3.x accepts framer as string "rtu"/"ascii"
                    self.client = ModbusSerialClient(
                        port=serial_port, baudrate=baud, parity=parity,
                        bytesize=databits, stopbits=stopbits, timeout=1, framer=framer)
                    if not self.client.connect():
                        raise ConnectionError(f"Could not open serial port {serial_port}.")
                except Exception as e:
                    QMessageBox.critical(self, "Connection failed", str(e))
                    self.log.emit("ERR", f"Connection failed: {e}")
                    self.client = None
                    return
            else:
                self.client = "SIMULATED"

        self.store.unit_id = unit
        self.store.connected = True
        self._set_status(True)
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setObjectName("Danger")
        self.connect_btn.style().unpolish(self.connect_btn); self.connect_btn.style().polish(self.connect_btn)
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
        self.connect_btn.style().unpolish(self.connect_btn); self.connect_btn.style().polish(self.connect_btn)
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

    def _next_tid(self):
        self._tid = (self._tid + 1) & 0xFFFF
        return self._tid or 1

    def read_value(self, p: Parameter):
        if not self.store.connected:
            return None
        count = 2 if p.data_type == "u32" else 1
        mode = self.current_mode()
        unit = self.store.unit_id
        tid = self._next_tid()

        # Emit RAW TX frame
        tx = build_read_frame(mode, unit, p.address, count, tid)
        self.log.emit("TX", hexify(tx))

        if self.client == "SIMULATED" or not HAS_PYMODBUS:
            import random
            if count == 2:
                raw = random.randint(0, 1_000_000)
                regs = [(raw >> 16) & 0xFFFF, raw & 0xFFFF]
            else:
                raw = random.randint(0, 1000)
                regs = [raw & 0xFFFF]
            rx = build_read_response(mode, unit, regs, tid)
            self.log.emit("RX", hexify(rx))
        else:
            try:
                rr = self.client.read_holding_registers(p.address, count=count, slave=unit)
                if rr.isError():
                    self.log.emit("ERR", f"addr={p.address} -> {rr}")
                    return None
                regs = list(rr.registers)
                rx = build_read_response(mode, unit, regs, tid)
                self.log.emit("RX", hexify(rx))
                if count == 2:
                    raw = (regs[0] << 16) | regs[1]
                else:
                    raw = regs[0]
            except Exception as e:
                self.log.emit("ERR", f"addr={p.address} crash: {e}")
                return None

        if self.client == "SIMULATED" or not HAS_PYMODBUS:
            if count == 2:
                raw = (regs[0] << 16) | regs[1]
            else:
                raw = regs[0]

        if p.data_type == "s16" and raw >= 32768:
            raw -= 65536

        if p.is_status:
            return "YES" if raw != 0 else "NO"
        return round(raw * p.scaling, 3)


# ---------- Parameters page -------------------------------------------------
class ReorderTable(QTableWidget):
    row_moved = pyqtSignal(int, int)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dropEvent(self, event):
        if event.source() is not self:
            return
        src = self.currentRow()
        drop_row = self.indexAt(event.pos()).row()
        if drop_row == -1:
            drop_row = self.rowCount() - 1
        if src == -1 or src == drop_row:
            event.ignore()
            return
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.row_moved.emit(src, drop_row)


class ParametersPage(QWidget):
    COLS = ["S.No", "Parameter", "Address", "Value", "Unit", ""]

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
        root.setContentsMargins(32, 28, 32, 28); root.setSpacing(18)

        title = QLabel("Parameters"); title.setObjectName("PageTitle")
        sub = QLabel("Live values update once connected. Drag the ⋮⋮ handle on any row to reorder.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title); root.addWidget(sub)

        card = QFrame(); card.setObjectName("Card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 16, 16, 16)

        self.table = ReorderTable(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Stretch)
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(len(self.COLS) - 1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.row_moved.connect(self._on_row_moved)
        cl.addWidget(self.table)

        root.addWidget(card, 1)

    def refresh(self):
        self.table.setRowCount(len(self.store.parameters))
        for r, p in enumerate(self.store.parameters):
            val = "" if p.value is None else str(p.value)
            unit_display = "" if p.is_status else p.unit
            vals = [str(r + 1), p.name, str(p.address), val, unit_display]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c != 1:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)
            handle = QLabel("⋮⋮"); handle.setObjectName("DragHandle")
            handle.setAlignment(Qt.AlignCenter); handle.setToolTip("Drag to reorder")
            handle.setCursor(Qt.OpenHandCursor)
            self.table.setCellWidget(r, len(self.COLS) - 1, handle)

    def _on_row_moved(self, src: int, dst: int):
        ps = self.store.parameters
        if not (0 <= src < len(ps)):
            return
        dst = max(0, min(dst, len(ps) - 1))
        p = ps.pop(src); ps.insert(dst, p)
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
        root.setContentsMargins(32, 28, 32, 28); root.setSpacing(18)

        title = QLabel("Debug Console"); title.setObjectName("PageTitle")
        sub = QLabel("Raw Modbus frames (TX / RX) — hex bytes for TCP/RTU, ASCII text for Modbus ASCII.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title); root.addWidget(sub)

        bar = QHBoxLayout()
        self.clear_btn = QPushButton("Clear"); self.clear_btn.setObjectName("Secondary")
        self.clear_btn.clicked.connect(lambda: self.console.clear())
        bar.addStretch(); bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        root.addWidget(self.console, 1)

    def append(self, direction: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.console.appendPlainText(f"[{ts}] {direction:<4} {msg}")


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
        self.setWindowTitle("Universal Modbus Monitor")
        self.icon_path = resource_path("delta_icon.png")
        self.setWindowIcon(QIcon(self.icon_path))
        self.resize(1180, 720)
        self.store = Store()
        self._build()

    def _build(self):
        central = QWidget(); self.setCentralWidget(central)
        layout = QHBoxLayout(central); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)

        sidebar = QWidget(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(240)
        sl = QVBoxLayout(sidebar); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(0)

        self.logo_label = QLabel()
        logo_path = resource_path("delta_logo-removebg-preview.png")
        pm = make_transparent_pixmap(logo_path, max_w=130) if os.path.exists(logo_path) else QPixmap()
        if not pm.isNull():
            self.logo_label.setPixmap(pm)
        else:
            self.logo_label.setText("◆")
            self.logo_label.setStyleSheet("color:#2563eb; font-size:36px; background: transparent;")
        self.logo_label.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.logo_label)

        brand = QLabel("Universal Modbus Monitor")
        brand.setObjectName("Brand"); brand.setAlignment(Qt.AlignCenter); brand.setWordWrap(True)
        sub = QLabel("Hardware Diagnostics"); sub.setObjectName("BrandSub"); sub.setAlignment(Qt.AlignCenter)
        sl.addWidget(brand); sl.addWidget(sub)

        self.nav = QListWidget(); self.nav.setObjectName("NavList")
        for label, _ in self.NAV_ITEMS:
            QListWidgetItem(label, self.nav)
        sl.addWidget(self.nav, 1)

        footer_row = QHBoxLayout(); footer_row.setContentsMargins(16, 8, 16, 12)
        footer = QLabel("v1.3"); footer.setObjectName("Footer"); footer.setContentsMargins(0, 0, 0, 0)
        self.theme_btn = QToolButton(); self.theme_btn.setObjectName("ThemeToggle")
        self.theme_btn.setText("🌙"); self.theme_btn.setToolTip("Switch to dark theme")
        self.theme_btn.clicked.connect(self._toggle_theme)
        footer_row.addWidget(footer); footer_row.addStretch(); footer_row.addWidget(self.theme_btn)
        sl.addLayout(footer_row)

        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.connection_page = ConnectionPage(self.store)
        self.mapping_page = MappingPage(self.store)
        self.parameters_page = ParametersPage(self.store, self.connection_page)
        self.debug_page = DebugConsolePage()

        self.stack.addWidget(self.connection_page)
        self.stack.addWidget(self.mapping_page)
        self.stack.addWidget(self.parameters_page)
        self.stack.addWidget(self.debug_page)
        layout.addWidget(self.stack, 1)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.connection_page.log.connect(self.debug_page.append)
        self.connection_page.connected_changed.connect(self._on_connected)
        self.mapping_page.csv_imported.connect(self._after_csv_import)
        self.mapping_page.mapping_changed.connect(self.parameters_page.refresh)

    def _on_connected(self, connected: bool):
        self.parameters_page.refresh()
        if connected and not self.store.parameters:
            QMessageBox.information(
                self, "Add a mapping",
                "Connected. Now import a CSV in the Mapping tab — values will appear in Parameters automatically.",
            )
            self.nav.setCurrentRow(1)

    def _after_csv_import(self):
        self.parameters_page.refresh()
        self.nav.setCurrentRow(2)

    def _toggle_theme(self):
        app = QApplication.instance()
        if getattr(app, "_theme", "light") == "light":
            app.setStyleSheet(DARK_STYLE); app._theme = "dark"
            self.theme_btn.setText("☀"); self.theme_btn.setToolTip("Switch to light theme")
        else:
            app.setStyleSheet(LIGHT_STYLE); app._theme = "light"
            self.theme_btn.setText("🌙"); self.theme_btn.setToolTip("Switch to dark theme")


def main():
    app = QApplication(sys.argv)
    app._theme = "light"
    app.setStyleSheet(LIGHT_STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
