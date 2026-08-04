"""Disk paneli — Kaynak disk seçici + format + çıktı yolu + chunk/split ayarları.

Yeni eklenenler (v2):
- dd bs (uzak okuma bloğu) seçimi: 1M / 4M / 8M / 16M / 32M
- Split (parçalı imaj) boyutu (MB) — 0: parçalanmaz; N>0: base.001, .002…
- 'Uzantı Hedefli Tarama' checkbox — işaretlenirse iş 'targeted' moda
  geçer ve uzantı seçiciden gelen liste uygulanır.
"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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

from gui.extension_picker import ExtensionPicker
from logs.logger import get_logger

logger = get_logger("gui.disk_panel")


class DiskPanel(QGroupBox):
    """Disk seçimi + çıktı + chunk/split + hedefli tarama."""

    refresh_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("1. Disk seçimi ve çıktı", parent)
        self._selected_device: str = ""
        self._selected_size: int = 0
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(8)
        outer.setContentsMargins(10, 14, 10, 10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        def _lbl(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #555; font-size: 11px; background: transparent;")
            return lbl

        # Kaynak disk (sol ağaçtan otomatik doldurulur; salt-okunur)
        grid.addWidget(_lbl("Kaynak disk"), 0, 0)
        self.device_edit = QLineEdit()
        self.device_edit.setPlaceholderText("Soldaki ağaçtan bir disk seçin")
        self.device_edit.setReadOnly(True)
        grid.addWidget(self.device_edit, 1, 0)

        # Format
        grid.addWidget(_lbl("Format"), 0, 1)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["raw", "e01", "aff"])
        self.format_combo.setMaximumWidth(180)
        grid.addWidget(self.format_combo, 1, 1)

        # Çıktı yolu + Gözat
        grid.addWidget(_lbl("Çıktı yolu"), 2, 0, 1, 2)
        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("/mnt/evidence/case001.dd")
        self.browse_btn = QPushButton("Gözat…")
        self.browse_btn.clicked.connect(self._browse)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(self.browse_btn, 0)
        out_w = QWidget()
        out_w.setLayout(out_row)
        grid.addWidget(out_w, 3, 0, 1, 2)

        # Chunk / Split satırı
        chunk_row = QHBoxLayout()
        chunk_row.setSpacing(10)
        chunk_row.addWidget(_lbl("Uzak okuma bloğu (dd bs)"))
        self.bs_combo = QComboBox()
        self.bs_combo.addItems(["1M", "4M", "8M", "16M", "32M"])
        self.bs_combo.setCurrentText("4M")
        self.bs_combo.setMaximumWidth(80)
        chunk_row.addWidget(self.bs_combo)
        chunk_row.addSpacing(20)
        chunk_row.addWidget(_lbl("Parça boyutu (MB)"))
        self.split_spin = QSpinBox()
        self.split_spin.setRange(0, 10240)
        self.split_spin.setSingleStep(64)
        self.split_spin.setValue(0)
        self.split_spin.setSpecialValueText("Bölme yok")
        self.split_spin.setSuffix(" MB")
        self.split_spin.setMaximumWidth(140)
        self.split_spin.setToolTip(
            "0: tek dosya. Örn 1024: 1 GB'lık .001, .002, … parçalar."
        )
        chunk_row.addWidget(self.split_spin)
        chunk_row.addStretch(1)
        grid.addLayout(chunk_row, 4, 0, 1, 2)

        outer.addLayout(grid)

        # --- Hedefli tarama (opsiyonel) ------------------------------------
        self.targeted_cb = QCheckBox(
            "Uzantı Hedefli Tarama — tüm diski değil, seçili uzantılara "
            "uyan dosyaları çek"
        )
        self.targeted_cb.setStyleSheet("padding-top: 6px;")
        self.targeted_cb.toggled.connect(self._toggle_targeted)
        outer.addWidget(self.targeted_cb)

        self.targeted_container = QGroupBox("Uzantı seçimi")
        tc = QVBoxLayout(self.targeted_container)
        tc.setContentsMargins(10, 14, 10, 10)
        tc.setSpacing(6)
        # Uzak kök yolu
        root_row = QHBoxLayout()
        root_row.setSpacing(6)
        root_row.addWidget(QLabel("Uzak kök:"))
        self.target_root_edit = QLineEdit()
        self.target_root_edit.setPlaceholderText("/home veya C:\\Users")
        root_row.addWidget(self.target_root_edit, 1)
        root_row.addWidget(QLabel("Yerel çıktı klasörü:"))
        self.target_out_edit = QLineEdit()
        self.target_out_edit.setPlaceholderText("/mnt/evidence/triage")
        root_row.addWidget(self.target_out_edit, 1)
        self.target_out_btn = QPushButton("Gözat…")
        self.target_out_btn.clicked.connect(self._browse_target_out)
        root_row.addWidget(self.target_out_btn)
        tc.addLayout(root_row)

        self.ext_picker = ExtensionPicker()
        tc.addWidget(self.ext_picker, 1)

        self.targeted_container.setVisible(False)
        outer.addWidget(self.targeted_container)

        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)

    def _browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "İmaj çıktı dosyası", "case001.dd")
        if path:
            self.output_edit.setText(path)

    def _browse_target_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Hedefli tarama çıktı klasörü", "")
        if path:
            self.target_out_edit.setText(path)

    def _toggle_targeted(self, on: bool) -> None:
        self.targeted_container.setVisible(on)

    # ---- Ağaçtan çağrılır ----
    def set_selected_disk(self, device_path: str, size_bytes: int = 0,
                          model: str = "") -> None:
        self._selected_device = device_path
        self._selected_size = size_bytes
        label = device_path
        if size_bytes:
            gb = size_bytes / (1024 ** 3)
            label += f"  ·  {gb:.1f} GB"
        if model:
            label += f"  ·  {model}"
        self.device_edit.setText(label)

    # --- Getters ---
    def selected_device(self) -> str: return self._selected_device
    def selected_size_bytes(self) -> int: return self._selected_size
    def selected_format(self) -> str: return self.format_combo.currentText()
    def output_path(self) -> str: return self.output_edit.text().strip()
    def dd_block_size(self) -> str: return self.bs_combo.currentText()
    def split_size_mb(self) -> int: return int(self.split_spin.value())

    def is_targeted_mode(self) -> bool: return self.targeted_cb.isChecked()
    def target_root(self) -> str: return self.target_root_edit.text().strip()
    def target_output_dir(self) -> str: return self.target_out_edit.text().strip()
    def target_extensions(self) -> tuple: return self.ext_picker.selected_extensions()

    def set_disks(self, disks) -> None:
        # Legacy: disk listesi ağaca taşındı.
        pass
