"""Custom Content / Targeted paneli — kategorili uzantı seçici ile."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
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

from core.targeted_imager import TargetedRule
from gui.extension_picker import ExtensionPicker
from logs.logger import get_logger

logger = get_logger("gui.targeted_panel")


class TargetedPanel(QGroupBox):
    """Custom content / targeted imaging group box."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("1. Hedefli tarama kuralı", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(8)

        # Kaynak / hedef satırı
        top = QGridLayout()
        top.setHorizontalSpacing(10)
        top.setVerticalSpacing(6)
        top.addWidget(QLabel("Uzak kök"), 0, 0)
        self.root_edit = QLineEdit()
        self.root_edit.setPlaceholderText("/home veya C:\\Users")
        top.addWidget(self.root_edit, 0, 1, 1, 3)

        top.addWidget(QLabel("Yerel çıktı"), 1, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("/mnt/evidence/triage_case001")
        top.addWidget(self.out_edit, 1, 1, 1, 2)
        self.browse_btn = QPushButton("Gözat…")
        self.browse_btn.clicked.connect(self._browse)
        top.addWidget(self.browse_btn, 1, 3)
        top.setColumnStretch(1, 1)
        top.setColumnStretch(2, 1)
        outer.addLayout(top)

        self.signature_cb = QCheckBox(
            "Dosya imzası (magic number) ile doğrula ve bad-extension tespit et"
        )
        self.signature_cb.setChecked(True)
        outer.addWidget(self.signature_cb)

        self.copy_cb = QCheckBox("Eşleşenleri yerel klasöre kopyala")
        self.copy_cb.setChecked(True)
        outer.addWidget(self.copy_cb)

        picker_grp = QGroupBox("Uzantı seçimi (kategorili)")
        pl = QVBoxLayout(picker_grp)
        pl.setContentsMargins(10, 14, 10, 10)
        self.picker = ExtensionPicker()
        # Varsayılan preset
        self.picker._apply_preset()  # noqa: SLF001
        pl.addWidget(self.picker, 1)
        outer.addWidget(picker_grp, 1)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Yerel kopya hedef klasörü", "")
        if path:
            self.out_edit.setText(path)

    def target_root(self) -> str: return self.root_edit.text().strip()
    def output_dir(self) -> str: return self.out_edit.text().strip()
    def copy_files(self) -> bool: return self.copy_cb.isChecked()

    def build_rule(self) -> TargetedRule:
        exts = self.picker.selected_extensions()
        return TargetedRule(
            name="custom", extensions=exts,
            use_signature_match=self.signature_cb.isChecked(),
        )
