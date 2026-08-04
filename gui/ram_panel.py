"""RAM paneli — RAM imajı ayarları (group box)."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from logs.logger import get_logger

logger = get_logger("gui.ram_panel")


class RamPanel(QGroupBox):
    """RAM imajı group box."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("1. RAM imajı ayarları", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(10, 14, 10, 10)

        self.info_label = QLabel("RAM bilgisi bağlantıdan sonra görüntülenecek.")
        self.info_label.setStyleSheet("color: #555; font-size: 11.5px; background: transparent;")
        outer.addWidget(self.info_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        def _lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #555; font-size: 11px; background: transparent;")
            return lbl

        # Çıktı yolu
        grid.addWidget(_lbl("Çıktı yolu"), 0, 0, 1, 2)
        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("/mnt/evidence/case001_ram.lime")
        self.browse_btn = QPushButton("Gözat…")
        self.browse_btn.clicked.connect(self._browse)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(self.browse_btn, 0)
        out_w = QWidget()
        out_w.setLayout(out_row)
        grid.addWidget(out_w, 1, 0, 1, 2)

        # WinPMEM path
        grid.addWidget(_lbl("WinPMEM yolu (yalnızca Windows hedef)"), 2, 0, 1, 2)
        self.winpmem_edit = QLineEdit()
        self.winpmem_edit.setPlaceholderText(r"C:\tools\winpmem.exe")
        grid.addWidget(self.winpmem_edit, 3, 0, 1, 2)

        outer.addLayout(grid)

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "RAM imaj dosyası", "case001_ram.lime")
        if path:
            self.output_edit.setText(path)

    def set_ram_info(self, total_bytes: int, available_bytes: int) -> None:
        total_gb = total_bytes / (1024 ** 3)
        avail_gb = available_bytes / (1024 ** 3)
        self.info_label.setText(
            f"Toplam RAM: {total_gb:.2f} GB   ·   Kullanılabilir: {avail_gb:.2f} GB"
        )

    def output_path(self) -> str:
        return self.output_edit.text().strip()

    def winpmem_path(self) -> str:
        return self.winpmem_edit.text().strip()
