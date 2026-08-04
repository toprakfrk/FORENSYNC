"""Sol dock — 'Kanıt kaynakları' ağacı + 'Son işlemler' listesi.

Referans: soldaki dar panel. Bağlı sunucu(lar) → altında diskler ağaç
yapısında; ayrı bölümde son tamamlanmış imajlar. Bir disk seçildiğinde
sinyal yayar.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui import theme


# Roles
ROLE_DEVICE_PATH = Qt.ItemDataRole.UserRole + 1
ROLE_SIZE_BYTES = Qt.ItemDataRole.UserRole + 2
ROLE_MODEL      = Qt.ItemDataRole.UserRole + 3


class SourcesPanel(QWidget):
    """Kanıt kaynakları + Son işlemler."""

    disk_selected = pyqtSignal(str, int, str)  # (device_path, size_bytes, model)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        title = QLabel("Kanıt kaynakları")
        title.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px; "
            f"font-weight: 600; padding: 2px 2px; background: transparent;"
        )
        outer.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_click)
        outer.addWidget(self.tree, 1)

        rec_title = QLabel("Son işlemler")
        rec_title.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px; "
            f"font-weight: 600; padding: 6px 2px 2px 2px; background: transparent;"
        )
        outer.addWidget(rec_title)

        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(140)
        outer.addWidget(self.recent_list)

    # ---- Ağaç güncelleme ----
    def set_host(self, host: str, disks: list) -> None:
        """Bağlı host'u ve altındaki diskleri yenile.

        Args:
            host: 'user@192.168.1.10' benzeri etiket
            disks: DiskInfo listesi (path, size_bytes, model)
        """
        self.tree.clear()
        if not host:
            return
        host_item = QTreeWidgetItem([host])
        host_item.setForeground(0, self.palette().text())
        # host, seçilemez
        host_item.setFlags(host_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        for d in disks:
            gb = d.size_bytes / (1024 ** 3) if d.size_bytes else 0.0
            label = f"{d.path} — {gb:.1f} GB"
            if getattr(d, "model", ""):
                label += f" · {d.model}"
            child = QTreeWidgetItem([label])
            child.setData(0, ROLE_DEVICE_PATH, d.path)
            child.setData(0, ROLE_SIZE_BYTES, d.size_bytes)
            child.setData(0, ROLE_MODEL, getattr(d, "model", ""))
            host_item.addChild(child)
        self.tree.addTopLevelItem(host_item)
        host_item.setExpanded(True)

    def clear_host(self) -> None:
        self.tree.clear()

    def add_recent(self, label: str) -> None:
        """'Son işlemler'e bir satır ekle."""
        item = QListWidgetItem(label)
        item.setToolTip(label)
        self.recent_list.insertItem(0, item)
        # Maks 20 satır tut
        while self.recent_list.count() > 20:
            self.recent_list.takeItem(self.recent_list.count() - 1)

    # ---- Slot ----
    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        dev = item.data(0, ROLE_DEVICE_PATH)
        if not dev:
            return
        size = item.data(0, ROLE_SIZE_BYTES) or 0
        model = item.data(0, ROLE_MODEL) or ""
        self.disk_selected.emit(dev, int(size), model)
