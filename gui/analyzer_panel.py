"""İmaj İnceleme paneli — üç sekmeli:

    1. Basit İnceleme    : mevcut liste + bad-extension işareti
    2. Uzantı Hedefli Yeni İmaj Al : kaynak imajdan seçili uzantılı
       dosyaları yeni bir klasöre çıkartır
    3. İmaj Gezgini      : FTK-Imager tarzı Evidence Tree + File List + Hex
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.image_analyzer import ImageAnalyzer, ImageAnalysisResult
from gui import theme
from gui.extension_picker import ExtensionPicker
from gui.image_browser_panel import ImageBrowserPanel
from gui.widgets import make_primary
from logs.logger import get_logger

logger = get_logger("gui.analyzer_panel")


class _AnalyzerWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image_path: str) -> None:
        super().__init__()
        self._image_path = image_path

    def run(self) -> None:  # noqa: D401
        try:
            result = ImageAnalyzer().analyze(self._image_path)
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _ExtractorWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, image_path: str, out_dir: str, exts: tuple) -> None:
        super().__init__()
        self._image_path = image_path
        self._out_dir = out_dir
        self._exts = exts

    def run(self) -> None:  # noqa: D401
        try:
            result = ImageAnalyzer().extract_by_extensions(
                self._image_path, self._out_dir, self._exts,
            )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _InspectTab(QWidget):
    """Basit inceleme sekmesi."""

    log_message = pyqtSignal(str)
    status_message = pyqtSignal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self._worker: _AnalyzerWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        src = QGroupBox("1. Yerel imaj dosyası")
        gl = QVBoxLayout(src)
        gl.setContentsMargins(10, 14, 10, 10)
        gl.setSpacing(6)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/tam/yol/imaj.dd  veya  .E01 / .aff")
        self.browse_btn = QPushButton("Gözat…")
        self.browse_btn.clicked.connect(self._browse)
        self.open_btn = QPushButton("Aç ve incele")
        make_primary(self.open_btn)
        self.open_btn.clicked.connect(self._on_open)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.browse_btn)
        row.addWidget(self.open_btn)
        gl.addLayout(row)
        self.summary_label = QLabel(
            "Bir imaj dosyası seçin; içeriği salt-okunur olarak listelenir."
        )
        self.summary_label.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        gl.addWidget(self.summary_label)
        outer.addWidget(src)

        tree_group = QGroupBox("2. İçerik")
        tl = QVBoxLayout(tree_group)
        tl.setContentsMargins(10, 14, 10, 10)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Yol / Konum", "Boyut", "Tespit edilen tür", "Uyarı"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.setColumnWidth(0, 380)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 200)
        self.tree.setMinimumHeight(280)
        tl.addWidget(self.tree)
        outer.addWidget(tree_group, 1)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "İncelenecek imaj dosyasını seçin", "",
            "İmaj Dosyaları (*.dd *.raw *.img *.001 *.E01 *.e01 *.aff);;Tüm Dosyalar (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _on_open(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            return
        self.log_message.emit(f"İmaj inceleme başladı: {path}")
        self.status_message.emit("İmaj inceleniyor…", True)
        self.tree.clear()
        self.summary_label.setText("İnceleniyor, lütfen bekleyin…")
        self.open_btn.setEnabled(False)
        self._worker = _AnalyzerWorker(path)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, result: ImageAnalysisResult) -> None:
        self.open_btn.setEnabled(True)
        self.summary_label.setText(
            f"Backend: {result.backend}  ·  Format: {result.image_format.upper()}  ·  "
            f"{len(result.files)} dosya  ·  "
            f"{len(result.bad_extension_files)} uzantı-tür uyuşmazlığı"
        )
        self.log_message.emit(
            f"İnceleme tamamlandı: {len(result.files)} dosya, "
            f"{len(result.bad_extension_files)} bad-extension."
        )
        self.status_message.emit(f"İnceleme tamam: {len(result.files)} dosya", True)
        yellow = QBrush(QColor("#fff7d6"))
        red = QBrush(QColor(theme.COLOR_DANGER))
        for f in result.files:
            size = f"{f.size_bytes:,}" if f.size_bytes else "—"
            warn = ""
            if f.bad_extension:
                warn = (f"⚠ Bad ext: {f.detected_type}, "
                        f"bekl. {', '.join(f.detected_extensions) or 'yok'}")
            item = QTreeWidgetItem([
                f.path, size,
                f.detected_type or ("<klasör>" if f.is_dir else "—"), warn,
            ])
            if f.bad_extension:
                for col in range(4):
                    item.setBackground(col, yellow)
                item.setForeground(3, red)
                item.setToolTip(
                    0, f"Uzantı uyuşmazlığı!\nGerçek tür: {f.detected_type}\n"
                       f"Beklenen uzantı(lar): {', '.join(f.detected_extensions) or 'yok'}",
                )
            self.tree.addTopLevelItem(item)

    def _on_failed(self, message: str) -> None:
        self.open_btn.setEnabled(True)
        self.summary_label.setText(f"HATA: {message}")
        self.log_message.emit(f"İnceleme hatası: {message}")
        self.status_message.emit("İnceleme başarısız", False)


class _ExtractTab(QWidget):
    """Uzantı hedefli yeni imaj alma sekmesi."""

    log_message = pyqtSignal(str)
    status_message = pyqtSignal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self._worker: _ExtractorWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        src = QGroupBox("1. Kaynak imaj + hedef klasör")
        gl = QVBoxLayout(src)
        gl.setContentsMargins(10, 14, 10, 10)
        gl.setSpacing(6)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Kaynak imaj:"))
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText(".dd / .raw / .001 / .E01")
        row1.addWidget(self.src_edit, 1)
        self.src_browse = QPushButton("Gözat…")
        self.src_browse.clicked.connect(self._browse_src)
        row1.addWidget(self.src_browse)
        gl.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Hedef klasör:"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("/mnt/evidence/case001_extracted")
        row2.addWidget(self.out_edit, 1)
        self.out_browse = QPushButton("Gözat…")
        self.out_browse.clicked.connect(self._browse_out)
        row2.addWidget(self.out_browse)
        gl.addLayout(row2)
        outer.addWidget(src)

        picker_group = QGroupBox("2. Çıkarılacak uzantıları seçin")
        pl = QVBoxLayout(picker_group)
        pl.setContentsMargins(10, 14, 10, 10)
        self.picker = ExtensionPicker()
        pl.addWidget(self.picker, 1)
        outer.addWidget(picker_group, 1)

        # Butonlar
        act_row = QHBoxLayout()
        act_row.addStretch(1)
        self.status_label = QLabel("Kaynak imajı, hedef klasörü ve uzantıları seçip başlatın.")
        self.status_label.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        act_row.addWidget(self.status_label, 1)
        self.start_btn = QPushButton("Yeni İmaj Al")
        make_primary(self.start_btn)
        self.start_btn.clicked.connect(self._on_start)
        act_row.addWidget(self.start_btn)
        outer.addLayout(act_row)

        # Sonuç kısa listesi (bad-extension vurgusu)
        self.result_tree = QTreeWidget()
        self.result_tree.setHeaderLabels(
            ["Dosya", "Boyut", "Tespit edilen tür", "Uyarı"],
        )
        self.result_tree.setColumnWidth(0, 400)
        self.result_tree.setColumnWidth(1, 90)
        self.result_tree.setColumnWidth(2, 200)
        self.result_tree.setMinimumHeight(180)
        outer.addWidget(self.result_tree, 1)

    def _browse_src(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Kaynak imaj dosyası", "",
            "İmaj Dosyaları (*.dd *.raw *.img *.001 *.E01 *.e01 *.aff);;Tüm Dosyalar (*)",
        )
        if path:
            self.src_edit.setText(path)

    def _browse_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Çıkış klasörü", "")
        if path:
            self.out_edit.setText(path)

    def _on_start(self) -> None:
        src = self.src_edit.text().strip()
        out = self.out_edit.text().strip()
        exts = self.picker.selected_extensions()
        if not src or not out or not exts:
            self.status_label.setText("Kaynak, hedef ve en az bir uzantı gerekli.")
            return
        self.status_label.setText("Çıkarılıyor…")
        self.start_btn.setEnabled(False)
        self.result_tree.clear()
        self.log_message.emit(f"Yeni imaj çıkarılıyor: {len(exts)} uzantı → {out}")
        self.status_message.emit("İmaj çıkarma başladı…", True)
        self._worker = _ExtractorWorker(src, out, exts)
        self._worker.finished_ok.connect(self._on_done)
        self._worker.failed.connect(self._on_fail)
        self._worker.start()

    def _on_done(self, result: ImageAnalysisResult) -> None:
        self.start_btn.setEnabled(True)
        self.status_label.setText(
            f"Tamam: {len(result.files)} dosya çıkarıldı, "
            f"{len(result.bad_extension_files)} bad-extension."
        )
        self.status_message.emit(
            f"Çıkarma tamam: {len(result.files)} dosya", True,
        )
        yellow = QBrush(QColor("#fff7d6"))
        red = QBrush(QColor(theme.COLOR_DANGER))
        for f in result.files:
            size = f"{f.size_bytes:,}" if f.size_bytes else "—"
            warn = ""
            if f.bad_extension:
                warn = (f"⚠ Bad ext: {f.detected_type}")
            item = QTreeWidgetItem([f.path, size, f.detected_type or "—", warn])
            if f.bad_extension:
                for col in range(4):
                    item.setBackground(col, yellow)
                item.setForeground(3, red)
                item.setToolTip(
                    0, f"Uzantı uyuşmazlığı!\nGerçek tür: {f.detected_type}\n"
                       f"Beklenen: {', '.join(f.detected_extensions) or 'yok'}",
                )
            self.result_tree.addTopLevelItem(item)

    def _on_fail(self, message: str) -> None:
        self.start_btn.setEnabled(True)
        self.status_label.setText(f"HATA: {message}")
        self.status_message.emit("Çıkarma başarısız", False)


class AnalyzerPanel(QWidget):
    """İmaj İnceleme görevi — 3 sekmeli konteyner."""

    log_message = pyqtSignal(str)
    status_message = pyqtSignal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        outer.addWidget(self.tabs, 1)

        self.inspect_tab = _InspectTab()
        self.extract_tab = _ExtractTab()
        self.browser_tab = ImageBrowserPanel()

        self.tabs.addTab(self.inspect_tab, "Basit İnceleme")
        self.tabs.addTab(self.extract_tab, "Dosya Uzantısı Hedefli Yeni İmaj Al")
        self.tabs.addTab(self.browser_tab, "İmaj Gezgini")

        # Sinyal köprüsü
        for t in (self.inspect_tab, self.extract_tab, self.browser_tab):
            if hasattr(t, "log_message"):
                t.log_message.connect(self.log_message.emit)
            if hasattr(t, "status_message"):
                t.status_message.connect(
                    lambda text, ok: self.status_message.emit(text, ok)
                )
