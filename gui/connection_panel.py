"""Bağlantı paneli — Host/Port/Kullanıcı/Parola/Anahtar + 'Bağlan' butonu.

QGroupBox 'Hedef bağlantı' içindeki tek panel. Sağa yaslı 'Bağlan' butonu.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.ssh_connector import SSHCredentials
from gui.widgets import make_primary
from logs.logger import get_logger

logger = get_logger("gui.connection_panel")


class ConnectionPanel(QGroupBox):
    """Hedef bağlantı group box."""

    connect_requested = pyqtSignal(object)  # SSHCredentials

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Hedef bağlantı", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(10, 14, 10, 10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)

        def _label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #555; font-size: 11px; background: transparent;")
            return lbl

        # Host
        grid.addWidget(_label("Host"), 0, 0)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.10")
        grid.addWidget(self.host_edit, 1, 0)

        # Port
        grid.addWidget(_label("Port"), 0, 1)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self.port_spin.setMaximumWidth(90)
        grid.addWidget(self.port_spin, 1, 1)

        # Kullanıcı
        grid.addWidget(_label("Kullanıcı"), 2, 0)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("root")
        grid.addWidget(self.user_edit, 3, 0)

        # Parola
        grid.addWidget(_label("Parola"), 2, 1)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_edit.setPlaceholderText("Kaydedilmez")
        grid.addWidget(self.pass_edit, 3, 1)

        # Anahtar + Gözat
        grid.addWidget(_label("Özel anahtar (opsiyonel)"), 4, 0, 1, 2)
        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        key_row.setContentsMargins(0, 0, 0, 0)
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("id_rsa / *.pem yolu")
        self.key_browse_btn = QPushButton("Gözat…")
        self.key_browse_btn.clicked.connect(self._browse_key)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.key_browse_btn, 0)
        key_wrapper = QWidget()
        key_wrapper.setLayout(key_row)
        grid.addWidget(key_wrapper, 5, 0, 1, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        # Sağa yaslı Bağlan butonu
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.addStretch(1)
        self.connect_btn = QPushButton("Bağlan")
        make_primary(self.connect_btn)
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.clicked.connect(self._on_connect)
        btn_row.addWidget(self.connect_btn)
        outer.addLayout(btn_row)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "SSH özel anahtar dosyası",
            "",
            "Anahtar Dosyaları (*.pem *.key id_*);;Tüm Dosyalar (*)",
        )
        if path:
            self.key_edit.setText(path)

    def _on_connect(self) -> None:
        creds = self.credentials()
        logger.info("Bağlantı isteği: %s@%s", creds.username, creds.host)
        self.connect_requested.emit(creds)

    def credentials(self) -> SSHCredentials:
        return SSHCredentials(
            host=self.host_edit.text().strip(),
            port=self.port_spin.value(),
            username=self.user_edit.text().strip() or "root",
            password=self.pass_edit.text() or None,
            key_path=self.key_edit.text().strip() or None,
        )

    # Legacy erişim (main_window)
    @property
    def creds(self) -> SSHCredentials:
        return self.credentials()
