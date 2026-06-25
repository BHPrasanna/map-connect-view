"""
Modbus Mapping GUI
------------------
A clean PyQt5 desktop application with:
  * Left navigation (Mapping / Connection / Parameters)
  * CSV import for parameter mapping
  * Modbus TCP connection settings
  * Live parameter values once connected

Run:
    pip install PyQt5 pymodbus
    python app.py

The CSV is expected to have these columns (case-insensitive):
    address, parameter, data_type, scaling, unit
"""

import csv
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtWidgets import (
    QApplication, QWidget, QMainWindow, QHBoxLayout, QVBoxLayout, QFormLayout,
    QPushButton, QLabel, QStackedWidget, QListWidget, QListWidgetItem,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QLineEdit, QDialog, QDialogButtonBox, QFrame, QSpacerItem,
    QSizePolicy, QAbstractItemView,
)

# ---------- Optional Modbus backend -----------------------------------------
try:
    from pymodbus.client import ModbusTcpClient  # pymodbus >= 3
    HAS_PYMODBUS = True
except Exception:
    HAS_PYMODBUS = False


# ---------- Data model ------------------------------------------------------
@dataclass
class Parameter:
    address: int
    name: str
    data_type: str  # "u16" or "u32"
    scaling: float
    unit: str
    value: Optional[float] = None


# ---------- Stylesheet ------------------------------------------------------
STYLE = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #1f2937; }
QMainWindow, QWidget { background: #f6f7fb; }

#Sidebar {
    background: #111827;
    border: none;
}
#Sidebar QLabel#Brand {
    color: #ffffff;
    font-size: 18px;
    font-weight: 700;
    padding: 24px 20px 12px 20px;
}
#Sidebar QLabel#BrandSub {
    color: #9ca3af;
    font-size: 11px;
    padding: 0 20px 20px 20px;
}
QListWidget#NavList {
    background: transparent;
    border: none;
    outline: 0;
    padding: 8px;
}
QListWidget#NavList::item {
    color: #d1d5db;
    padding: 12px 16px;
    margin: 2px 6px;
    border-radius: 8px;
}
QListWidget#NavList::item:hover { background: #1f2937; color: #ffffff; }
QListWidget#NavList::item:selected { background: #2563eb; color: #ffffff; }

#PageTitle { font-size: 22px; font-weight: 700; color: #0f172a; }
#PageSubtitle { color: #6b7280; font-size: 13px; }

QFrame#Card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QPushButton {
    background: #2563eb;
    color: white;
    border: none;
    padding: 9px 18px;
    border-radius: 8px;
    font-weight: 600;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton:disabled { background: #9ca3af; }

QPushButton#Secondary {
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #d1d5db;
}
QPushButton#Secondary:hover { background: #f3f4f6; }

QPushButton#Danger { background: #dc2626; }
QPushButton#Danger:hover { background: #b91c1c; }

QLineEdit, QComboBox {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #2563eb; }

QTableWidget {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    gridline-color: #f1f5f9;
    selection-background-color: #dbeafe;
    selection-color: #1e3a8a;
}
QHeaderView::section {
    background: #f9fafb;
    color: #374151;
    padding: 10px;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    font-weight: 600;
}
QTableWidget::item { padding: 8px; }

QLabel#StatusDot { font-size: 18px; }
QLabel#StatusText { color: #6b7280; }
"""


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
        form.setLabelAlignment(Qt.AlignLeft)

        self.name_edit = QLineEdit()
        self.address_edit = QLineEdit()
        self.address_edit.setPlaceholderText("e.g. 40001")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["u16", "u32"])
        self.scaling_edit = QLineEdit()
        self.scaling_edit.setPlaceholderText("e.g. 0.1")
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("e.g. V, A, kWh")

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

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Parameter Mapping")
        title.setObjectName("PageTitle")
        sub = QLabel("Import a CSV file or add parameters manually to define the mapping.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        # Toolbar
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.import_btn = QPushButton("  Import CSV")
        self.import_btn.clicked.connect(self.import_csv)
        self.add_btn = QPushButton("  + Add Parameter")
        self.add_btn.setObjectName("Secondary")
        self.add_btn.clicked.connect(self.add_parameter)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Secondary")
        self.clear_btn.clicked.connect(self.clear_all)
        bar.addWidget(self.import_btn)
        bar.addWidget(self.add_btn)
        bar.addStretch()
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        # Table card
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Parameter", "Address", "Data Type", "Scaling", "Unit"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
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
                # normalise keys
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
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    def add_parameter(self):
        dlg = AddParameterDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            self.store.parameters.append(dlg.parameter())
            self.refresh()

    def clear_all(self):
        if not self.store.parameters:
            return
        if QMessageBox.question(self, "Clear", "Remove all parameters?") == QMessageBox.Yes:
            self.store.parameters.clear()
            self.refresh()

    def refresh(self):
        self.table.setRowCount(len(self.store.parameters))
        for r, p in enumerate(self.store.parameters):
            for c, v in enumerate([p.name, str(p.address), p.data_type, str(p.scaling), p.unit]):
                item = QTableWidgetItem(v)
                if c != 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)


# ---------- Connection page -------------------------------------------------
class ConnectionPage(QWidget):
    connected_changed = pyqtSignal(bool)

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
        sub = QLabel("Configure the protocol and connect to your device.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(16)

        proto_row = QFormLayout()
        proto_row.setSpacing(12)
        self.proto_combo = QComboBox()
        self.proto_combo.addItems(["Modbus TCP"])
        self.proto_combo.currentTextChanged.connect(self._rebuild_fields)
        proto_row.addRow("Protocol", self.proto_combo)
        cl.addLayout(proto_row)

        self.fields_form = QFormLayout()
        self.fields_form.setSpacing(12)
        self.field_widgets = {}
        cl.addLayout(self.fields_form)

        # Status + connect
        bottom = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("StatusDot")
        self.status_dot.setStyleSheet("color:#9ca3af;")
        self.status_text = QLabel("Disconnected")
        self.status_text.setObjectName("StatusText")
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

    def _rebuild_fields(self, proto):
        # clear
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
        if not self.store.parameters:
            QMessageBox.warning(
                self, "No mapping",
                "Please import a CSV (or add parameters) on the Mapping tab before connecting.",
            )
            return

        ip = self.field_widgets["ip"].text().strip()
        try:
            port = int(self.field_widgets["port"].text().strip())
            unit = int(self.field_widgets["unit"].text().strip())
        except ValueError:
            QMessageBox.warning(self, "Invalid", "Port and Unit ID must be integers.")
            return

        if HAS_PYMODBUS:
            try:
                self.client = ModbusTcpClient(ip, port=port)
                ok = self.client.connect()
                if not ok:
                    raise ConnectionError("Could not reach device.")
                self.store.unit_id = unit
            except Exception as e:
                QMessageBox.critical(self, "Connection failed", str(e))
                self.client = None
                return
        else:
            # Simulation mode — no pymodbus installed
            self.client = "SIMULATED"

        self.store.connected = True
        self._set_status(True)
        self.connect_btn.setText("Disconnect")
        self.connect_btn.setObjectName("Danger")
        self.connect_btn.setStyleSheet("")  # repolish
        self.connect_btn.style().unpolish(self.connect_btn)
        self.connect_btn.style().polish(self.connect_btn)
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
        """Read a single parameter from the device (or simulate)."""
        if not self.store.connected:
            return None
        if self.client == "SIMULATED" or not HAS_PYMODBUS:
            import random
            raw = random.randint(0, 1000)
            return round(raw * p.scaling, 3)
        try:
            count = 2 if p.data_type == "u32" else 1
            rr = self.client.read_holding_registers(p.address, count, unit=self.store.unit_id)
            if rr.isError():
                return None
            if count == 2:
                raw = (rr.registers[0] << 16) | rr.registers[1]
            else:
                raw = rr.registers[0]
            return round(raw * p.scaling, 3)
        except Exception:
            return None


# ---------- Parameters page -------------------------------------------------
class ParametersPage(QWidget):
    def __init__(self, store, connection: ConnectionPage):
        super().__init__()
        self.store = store
        self.connection = connection
        self._build()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_values)
        self.timer.start(1000)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        title = QLabel("Parameters")
        title.setObjectName("PageTitle")
        sub = QLabel("Live values are updated once the device is connected.")
        sub.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(sub)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Parameter", "Address", "Value", "Unit"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        cl.addWidget(self.table)

        root.addWidget(card, 1)

    def refresh(self):
        self.table.setRowCount(len(self.store.parameters))
        for r, p in enumerate(self.store.parameters):
            val = "" if p.value is None else str(p.value)
            for c, v in enumerate([p.name, str(p.address), val, p.unit]):
                item = QTableWidgetItem(v)
                if c != 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, c, item)

    def poll_values(self):
        if self.store.connected:
            for p in self.store.parameters:
                p.value = self.connection.read_value(p)
        self.refresh()


# ---------- Shared state ----------------------------------------------------
class Store:
    def __init__(self):
        self.parameters: List[Parameter] = []
        self.connected: bool = False
        self.unit_id: int = 1


# ---------- Main window -----------------------------------------------------
class MainWindow(QMainWindow):
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        brand = QLabel("◆ Modbus Studio")
        brand.setObjectName("Brand")
        sub = QLabel("Mapping & monitoring")
        sub.setObjectName("BrandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        for name in ["Mapping", "Connection", "Parameters"]:
            item = QListWidgetItem(name)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            self.nav.addItem(item)
        sl.addWidget(self.nav, 1)

        footer = QLabel("v1.0")
        footer.setStyleSheet("color:#6b7280; padding: 16px 20px;")
        sl.addWidget(footer)

        layout.addWidget(sidebar)

        # Pages
        self.stack = QStackedWidget()
        self.mapping_page = MappingPage(self.store)
        self.connection_page = ConnectionPage(self.store)
        self.parameters_page = ParametersPage(self.store, self.connection_page)
        self.stack.addWidget(self.mapping_page)
        self.stack.addWidget(self.connection_page)
        self.stack.addWidget(self.parameters_page)
        layout.addWidget(self.stack, 1)

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        # Wiring
        self.mapping_page.csv_imported.connect(self._after_csv_import)
        self.mapping_page.csv_imported.connect(self.parameters_page.refresh)
        self.connection_page.connected_changed.connect(lambda _: self.parameters_page.refresh())

    def _after_csv_import(self):
        # Redirect to Connection tab after successful import
        self.nav.setCurrentRow(1)


# ---------- Entry -----------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
