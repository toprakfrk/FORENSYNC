"""Kategorili uzantı seçici widget'ı.

Adli bilişimde sık kullanılan dosya türlerini kategoriye göre listeleyen,
her uzantının yanında checkbox bulunan yeniden kullanılabilir bir panel.

Kullanım:
    picker = ExtensionPicker()
    exts = picker.selected_extensions()   # Tuple[str, ...]
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.file_categories import CATEGORIES, ExtensionCategory
from gui import theme


class _CategoryBlock(QGroupBox):
    """Tek bir kategori için mini group box: başlık + uzantı checkbox'ları."""

    changed = pyqtSignal()

    def __init__(self, cat: ExtensionCategory) -> None:
        super().__init__(cat.name)
        self.setStyleSheet(
            f"QGroupBox {{ font-size: 11px; color: {theme.COLOR_TEXT_MUTED}; "
            f"border: 1px solid {theme.COLOR_BORDER}; margin-top: 8px; "
            f"padding: 8px 6px 6px 6px; background-color: {theme.COLOR_CARD}; }}"
            "QGroupBox::title { padding: 0 4px; left: 6px; }"
        )
        self._checks: List[QCheckBox] = []
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 12, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        # 3 sütuna yerleştir
        cols = 3
        for i, ext in enumerate(cat.extensions):
            cb = QCheckBox(ext)
            cb.setStyleSheet(
                "QCheckBox { font-size: 11px; padding: 1px 2px; background: transparent; }"
                "QCheckBox::indicator { width: 12px; height: 12px; }"
            )
            cb.stateChanged.connect(self.changed.emit)
            self._checks.append(cb)
            grid.addWidget(cb, i // cols, i % cols)

    def selected(self) -> List[str]:
        return [cb.text() for cb in self._checks if cb.isChecked()]

    def set_all(self, checked: bool) -> None:
        for cb in self._checks:
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self.changed.emit()

    def set_selected(self, exts: Tuple[str, ...]) -> None:
        lowered = tuple(e.lower() for e in exts)
        for cb in self._checks:
            cb.blockSignals(True)
            cb.setChecked(cb.text().lower() in lowered)
            cb.blockSignals(False)


class ExtensionPicker(QWidget):
    """Yeniden kullanılabilir kategorili uzantı seçici."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._blocks: Dict[str, _CategoryBlock] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Üst araç şeridi: Tümünü Seç / Temizle + özet
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.summary_label = QLabel("Uzantı seçilmedi")
        self.summary_label.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        self.select_all_btn = QPushButton("Tümünü Seç")
        self.select_all_btn.setMaximumWidth(100)
        self.clear_btn = QPushButton("Temizle")
        self.clear_btn.setMaximumWidth(80)
        self.presets_btn = QPushButton("Yaygın (Belge+Görsel)")
        self.presets_btn.setMaximumWidth(180)
        top.addWidget(self.summary_label, 1)
        top.addWidget(self.presets_btn)
        top.addWidget(self.select_all_btn)
        top.addWidget(self.clear_btn)
        outer.addLayout(top)

        # Scroll içinde kategoriler grid'i
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        # 2 kolonlu düzen
        for idx, cat in enumerate(CATEGORIES):
            block = _CategoryBlock(cat)
            block.changed.connect(self._on_changed)
            self._blocks[cat.name] = block
            grid.addWidget(block, idx // 2, idx % 2)
        scroll.setWidget(host)
        scroll.setMinimumHeight(280)
        outer.addWidget(scroll, 1)

        self.select_all_btn.clicked.connect(self._select_all)
        self.clear_btn.clicked.connect(self._clear_all)
        self.presets_btn.clicked.connect(self._apply_preset)

    def _on_changed(self) -> None:
        exts = self.selected_extensions()
        if not exts:
            self.summary_label.setText("Uzantı seçilmedi")
        else:
            self.summary_label.setText(
                f"{len(exts)} uzantı seçildi: {', '.join(exts[:8])}"
                + (" …" if len(exts) > 8 else "")
            )
        self.changed.emit()

    def _select_all(self) -> None:
        for b in self._blocks.values():
            b.set_all(True)

    def _clear_all(self) -> None:
        for b in self._blocks.values():
            b.set_all(False)

    def _apply_preset(self) -> None:
        """Yaygın: Belgeler + Görseller kategorilerini işaretle."""
        self._clear_all()
        preset = ("Belgeler", "Görseller")
        for name in preset:
            b = self._blocks.get(name)
            if b:
                b.set_all(True)

    # --- Public API ---------------------------------------------------------
    def selected_extensions(self) -> Tuple[str, ...]:
        out: List[str] = []
        seen: set = set()
        for b in self._blocks.values():
            for e in b.selected():
                if e not in seen:
                    seen.add(e)
                    out.append(e)
        return tuple(out)

    def set_selected(self, exts: Tuple[str, ...]) -> None:
        for b in self._blocks.values():
            b.set_selected(exts)
        self._on_changed()
