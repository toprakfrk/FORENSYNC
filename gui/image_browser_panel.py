"""İmaj Gezgini paneli — FTK Imager benzeri 3 panel yerleşim.

- Sol: Evidence Tree (kanıt ağacı: imaj → partition'lar → unallocated)
- Sağ üst: File List (seçili partition/klasördeki dosyalar)
- Sağ alt: Hex Viewer (offset | hex | ASCII)

pytsk3/pyewf kurulu değilse otomatik olarak imza (magic) taraması moduna
düşer ve kullanıcıyı gerekli paketleri kurmaya yönlendirir.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.image_browser import (
    BrowserFile,
    BrowserNode,
    ImageBrowser,
    format_hex_dump,
)
from gui import theme
from gui.widgets import make_primary
from logs.logger import get_logger

logger = get_logger("gui.image_browser_panel")

# Ağaçtaki düğüm rolü
NODE_ROLE = Qt.ItemDataRole.UserRole + 10


class _OpenWorker(QThread):
    finished_ok = pyqtSignal(list, str, bool, bool)   # nodes, backend, tsk_ok, ewf_ok
    failed = pyqtSignal(str)

    def __init__(self, browser: ImageBrowser, path: str) -> None:
        super().__init__()
        self._browser = browser
        self._path = path

    def run(self) -> None:  # noqa: D401
        try:
            nodes = self._browser.open(self._path)
            self.finished_ok.emit(
                nodes, self._browser.backend,
                self._browser.has_tsk(), self._browser.has_ewf(),
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class _FallbackScanWorker(QThread):
    """Arka planda imza taraması yapar (10 GB gibi büyük imajlarda UI donmasın)."""
    progress = pyqtSignal(int, int)   # pos, total
    finished_ok = pyqtSignal(list)     # List[BrowserFile]
    failed = pyqtSignal(str)

    def __init__(self, browser: ImageBrowser, max_bytes: int, step: int) -> None:
        super().__init__()
        self._browser = browser
        self._max_bytes = max_bytes
        self._step = step
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D401
        try:
            results = self._browser.scan_fallback(
                max_bytes=self._max_bytes,
                step=self._step,
                progress_callback=lambda p, t: self.progress.emit(p, t or 0),
                cancel_flag=lambda: self._cancel,
            )
            self.finished_ok.emit(results)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ImageBrowserPanel(QWidget):
    """İmaj gezgini görsel arayüzü."""

    log_message = pyqtSignal(str)
    status_message = pyqtSignal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._browser = ImageBrowser()
        self._current_file: BrowserFile | None = None
        self._open_worker: _OpenWorker | None = None
        self._scan_worker: _FallbackScanWorker | None = None
        self._has_fs = False   # açık imajda gerçek bir dosya sistemi (partition) bulundu mu
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # Üst şerit: dosya seçici
        src = QGroupBox("İmaj dosyası")
        gl = QHBoxLayout(src)
        gl.setContentsMargins(10, 14, 10, 10)
        gl.setSpacing(6)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(".dd / .raw / .001 / .E01")
        gl.addWidget(self.path_edit, 1)
        self.browse_btn = QPushButton("Gözat…")
        self.browse_btn.clicked.connect(self._browse)
        gl.addWidget(self.browse_btn)
        self.open_btn = QPushButton("Aç")
        make_primary(self.open_btn)
        self.open_btn.clicked.connect(self._on_open)
        gl.addWidget(self.open_btn)
        self.backend_label = QLabel("")
        self.backend_label.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px; padding-left: 8px;"
        )
        gl.addWidget(self.backend_label)
        outer.addWidget(src)

        # --- Yardımcı bilgi bandı (pytsk3 kurulu değilse görünür) ---
        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        self.notice.setOpenExternalLinks(False)
        self.notice.setStyleSheet(
            "QLabel { background-color: #fff3cd; color: #664d03; "
            "border: 1px solid #ffe69c; border-radius: 2px; "
            "padding: 8px 10px; font-size: 12px; }"
        )
        self.notice.setVisible(False)
        outer.addWidget(self.notice)

        # Tarama araç çubuğu (fallback modda etkin)
        scan_bar = QHBoxLayout()
        scan_bar.setSpacing(6)
        self.scan_btn = QPushButton("İmza taramasını başlat")
        self.scan_btn.setEnabled(False)
        self.scan_btn.clicked.connect(self._on_scan_click)
        scan_bar.addWidget(self.scan_btn)
        self.scan_cancel_btn = QPushButton("İptal")
        self.scan_cancel_btn.setEnabled(False)
        self.scan_cancel_btn.clicked.connect(self._on_scan_cancel)
        scan_bar.addWidget(self.scan_cancel_btn)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(True)
        self.scan_progress.setVisible(False)
        scan_bar.addWidget(self.scan_progress, 1)
        self.scan_status = QLabel("")
        self.scan_status.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11px;"
        )
        scan_bar.addWidget(self.scan_status)
        outer.addLayout(scan_bar)

        # Ana splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        # --- Sol: Evidence Tree
        left = QGroupBox("Evidence Tree")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 12, 6, 6)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree_click)
        self.tree.itemExpanded.connect(self._on_tree_expand)
        lv.addWidget(self.tree)
        splitter.addWidget(left)

        # --- Sağ: dikey splitter
        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.setChildrenCollapsible(False)
        right_split.setHandleWidth(1)

        # Sağ üst: File List
        files_grp = QGroupBox("File List")
        fv = QVBoxLayout(files_grp)
        fv.setContentsMargins(6, 12, 6, 6)
        self.files = QTreeWidget()
        self.files.setHeaderLabels(
            ["Ad", "Boyut", "Tür", "Erişim", "Oluşturma", "Değişim", "Uyarı"],
        )
        self.files.setAlternatingRowColors(True)
        self.files.setSortingEnabled(True)
        self.files.setRootIsDecorated(False)
        self.files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.files.header()
        header.setStretchLastSection(False)
        self.files.setColumnWidth(0, 240)
        self.files.setColumnWidth(1, 90)
        self.files.setColumnWidth(2, 110)
        self.files.setColumnWidth(3, 140)
        self.files.setColumnWidth(4, 140)
        self.files.setColumnWidth(5, 140)
        self.files.setColumnWidth(6, 120)
        self.files.itemClicked.connect(self._on_file_click)
        self.files.itemDoubleClicked.connect(self._on_file_double_click)
        fv.addWidget(self.files)
        right_split.addWidget(files_grp)

        # Sağ alt: Hex Viewer
        hex_grp = QGroupBox("Hex Viewer")
        hv = QVBoxLayout(hex_grp)
        hv.setContentsMargins(6, 12, 6, 6)
        self.hex_view = QPlainTextEdit()
        self.hex_view.setReadOnly(True)
        self.hex_view.setPlaceholderText(
            "Dosya listesinden bir dosya seçin; ilk 4 KB hex+ASCII gösterilir."
        )
        self.hex_view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {theme.COLOR_LOG_BG}; "
            f"color: #d0d0d0; border: 1px solid #333; padding: 6px 8px; "
            f"font-family: {theme.FONT_STACK_MONO}; font-size: 11px; }}"
        )
        self.hex_view.setMinimumHeight(160)
        hv.addWidget(self.hex_view)
        right_split.addWidget(hex_grp)
        right_split.setSizes([260, 200])

        splitter.addWidget(right_split)
        splitter.setSizes([260, 720])
        outer.addWidget(splitter, 1)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "İmaj dosyası", "",
            "İmaj Dosyaları (*.dd *.raw *.img *.001 *.E01 *.e01);;Tüm Dosyalar (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _on_open(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            return
        self.tree.clear()
        self.files.clear()
        self.hex_view.clear()
        self.backend_label.setText("Açılıyor…")
        self.notice.setVisible(False)
        self.scan_btn.setEnabled(False)
        self.open_btn.setEnabled(False)
        self.log_message.emit(f"İmaj açılıyor: {path}")
        self.status_message.emit("İmaj açılıyor…", True)
        self._open_worker = _OpenWorker(self._browser, path)
        self._open_worker.finished_ok.connect(self._on_opened)
        self._open_worker.failed.connect(self._on_open_fail)
        self._open_worker.start()

    def _on_open_fail(self, message: str) -> None:
        self._open_worker = None
        self.backend_label.setText("Hata")
        self.scan_btn.setEnabled(False)
        self.open_btn.setEnabled(True)
        self.notice.setTextFormat(Qt.TextFormat.RichText)
        self.notice.setText(f"<b>İmaj açılamadı:</b> {message}")
        self.notice.setVisible(True)
        self.status_message.emit(f"İmaj açma hatası: {message}", False)
        self.log_message.emit(f"İmaj açma HATASI: {message}")

    def _on_opened(
        self, nodes: list, backend: str, tsk_ok: bool, ewf_ok: bool,
    ) -> None:
        self.open_btn.setEnabled(True)
        self.backend_label.setText(f"Backend: {backend}")
        self.status_message.emit(f"Açıldı: {len(nodes)} düğüm ({backend})", True)
        self.log_message.emit(
            f"İmaj açıldı — backend={backend}, {len(nodes)} düğüm, "
            f"tsk={tsk_ok}, ewf={ewf_ok}"
        )
        # Gerçek bir dosya sistemi (partition/dir) bulunabildi mi?
        # RAM imajları (AVML/WinPMEM ham bellek dökümü) partition tablosu ve
        # dosya sistemi İÇERMEZ — bu normaldir. pytsk3 kurulu olsa bile (backend
        # "tsk" olsa bile) böyle imajlarda partition/dir düğümü oluşmaz; sadece
        # "Unpartitioned Space" düğümü kalır. Bu durumda da imza taraması
        # (carver) moduna izin vermemiz gerekir — yoksa kullanıcı hiçbir şey
        # göremez ve "klasörler açılmıyor" gibi görünür.
        self._has_fs = any(n.kind in ("partition", "dir") for n in nodes)
        # Bildirim bandı: fallback moddaysak veya ewf gerekliyken yoksa uyar.
        needs_ewf = self.path_edit.text().lower().endswith((".e01", ".ex01"))
        if not tsk_ok:
            py = sys.executable or "python"
            msg = (
                "<b>Fallback modda (imza taraması) — dosya sistemi ağacı YOK.</b> "
                "İmaj içindeki dosya/klasör yapısını (NTFS, ext4, FAT, HFS+ vb.) "
                "görüntülemek için Sleuth Kit Python bağlayıcısı gerekir:"
                "<pre style='margin:6px 0'>"
                f"{py} -m pip install pytsk3"
                + (" pyewf" if needs_ewf else "")
                + "</pre>"
                "<b>Linux:</b> önce <code>sudo apt install libtsk-dev"
                + (" libewf-dev" if needs_ewf else "") + "</code>&nbsp;·&nbsp;"
                "<b>macOS:</b> <code>brew install sleuthkit"
                + (" libewf" if needs_ewf else "") + "</code>&nbsp;·&nbsp;"
                "<b>Windows:</b> hazır wheel; pip yeterli."
                "<br>Kurulumdan sonra IMAJER'ı yeniden başlatın. "
                "<i>Şimdilik 'İmza taramasını başlat' ile ham (carver) tarama yapabilirsiniz.</i>"
            )
            self.notice.setTextFormat(Qt.TextFormat.RichText)
            self.notice.setText(msg)
            self.notice.setVisible(True)
        elif needs_ewf and not ewf_ok:
            py = sys.executable or "python"
            self.notice.setTextFormat(Qt.TextFormat.RichText)
            self.notice.setText(
                "<b>E01 formatı için <code>pyewf</code> kurulu değil.</b> "
                f"<code>{py} -m pip install pyewf</code>"
            )
            self.notice.setVisible(True)
        elif not self._has_fs:
            # pytsk3 kurulu ve çalışıyor ama bu imajda ayrıştırılabilir bir
            # dosya sistemi yok — tipik olarak bu bir RAM (bellek) imajıdır.
            self.notice.setTextFormat(Qt.TextFormat.RichText)
            self.notice.setText(
                "<b>Bu imajda bir dosya/klasör sistemi bulunamadı.</b> "
                "RAM imajları (AVML/WinPMEM ham bellek dökümü) partition "
                "tablosu veya dosya sistemi içermez — bu normaldir; "
                "klasör ağacında gezinemezsiniz. "
                "<i>Aşağıdaki 'İmza taramasını başlat' ile dosyaları "
                "(imza/carver) taraması ile bulabilirsiniz.</i>"
            )
            self.notice.setVisible(True)
        # Ağacı doldur — partition/klasör düğümlerine FTK tarzı "+" genişletme
        # oku için sahte (placeholder) bir çocuk eklenir; gerçek alt klasörler
        # kullanıcı düğümü genişletince (_on_tree_expand) yüklenir.
        self.tree.clear()
        root = None
        for n in nodes:
            if n.kind == "image":
                item = QTreeWidgetItem([n.name])
                item.setData(0, NODE_ROLE, n)
                item.setForeground(0, QBrush(QColor(theme.COLOR_TEXT)))
                self.tree.addTopLevelItem(item)
                root = item
                root.setExpanded(True)
            else:
                self._add_tree_node(root, n)

        # Dosya sistemi yoksa (fallback modda ya da RAM imajı gibi tsk'nin
        # ayrıştıramadığı imajlarda) tarama butonunu etkinleştir; kök düğümü
        # otomatik seç.
        if not self._has_fs:
            self.scan_btn.setEnabled(True)
            self.scan_status.setText(
                "Not: 'İmza taramasını başlat' ile carver moduna geçin — "
                "10 GB için ~1-3 dk sürer."
            )
            # Kök 'unpartitioned' düğümünü seçili yap.
            for i in range(self.tree.topLevelItemCount()):
                top = self.tree.topLevelItem(i)
                for j in range(top.childCount()):
                    child = top.child(j)
                    node = child.data(0, NODE_ROLE)
                    if isinstance(node, BrowserNode) and node.kind == "unpartitioned":
                        self.tree.setCurrentItem(child)
                        break

    def _add_tree_node(
        self, parent_item: QTreeWidgetItem | None, node: BrowserNode,
        has_children: bool | None = None,
    ) -> QTreeWidgetItem:
        """Ağaca bir düğüm ekler. Gerçekten alt klasörü varsa ok işareti
        (placeholder) konur; yoksa hiç konmaz."""
        item = QTreeWidgetItem([node.name])
        item.setData(0, NODE_ROLE, node)
        if node.kind in ("partition", "dir"):
            if has_children is None:
                has_children = self._browser.has_subdirs(node.partition_id, node.path or "/")
            if has_children:
                placeholder = QTreeWidgetItem(["…"])
                item.addChild(placeholder)
        if parent_item is not None:
            parent_item.addChild(item)
        else:
            self.tree.addTopLevelItem(item)
        return item

    def _on_tree_expand(self, item: QTreeWidgetItem) -> None:
        """Bir partition/klasör düğümü genişletildiğinde alt klasörleri
        (yalnızca klasörleri — dosyalar File List'te gösterilir) yükler."""
        node = item.data(0, NODE_ROLE)
        if not isinstance(node, BrowserNode) or node.kind not in ("partition", "dir"):
            return
        if item.childCount() != 1:
            return  # zaten dolduruldu (birden fazla çocuk var) ya da boş
        placeholder = item.child(0)
        if placeholder.data(0, NODE_ROLE) is not None:
            return  # placeholder değil, gerçek bir düğüm — zaten dolu
        item.removeChild(placeholder)
        try:
            entries = self._browser.list_dir(node.partition_id, node.path or "/")
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"Klasör listelenemedi: {exc}")
            return
        base = node.path.rstrip("/") if node.path and node.path != "/" else ""
        for f in entries:
            if not f.is_dir:
                continue
            child_path = f"{base}/{f.name}"
            child_node = BrowserNode(
                name=f.name, kind="dir", fs_type=node.fs_type,
                partition_id=node.partition_id, path=child_path,
                offset_bytes=node.offset_bytes, size_bytes=f.size_bytes,
            )
            has_children = self._browser.has_subdirs(node.partition_id, child_path)
            self._add_tree_node(item, child_node, has_children=has_children)

    def _on_tree_click(self, item: QTreeWidgetItem, _col: int) -> None:
        node = item.data(0, NODE_ROLE)
        if not isinstance(node, BrowserNode):
            return
        if node.kind in ("partition", "dir"):
            self._list_partition(node)
        elif node.kind in ("unpartitioned", "unallocated", "image"):
            # Dosya sistemi olmayan düğümler (fallback modu ya da RAM imajı
            # gibi tsk'nin ayrıştıramadığı imajlar) — tarama butonuyla açılır.
            self.files.clear()
            self.hex_view.clear()
            if not self._has_fs and node.kind != "image":
                self.scan_status.setText(
                    "Bu düğüm için 'İmza taramasını başlat' ile carver çalıştırın."
                )

    def _list_partition(self, node: BrowserNode) -> None:
        self.files.clear()
        try:
            entries = self._browser.list_dir(node.partition_id, node.path or "/")
        except Exception as exc:  # noqa: BLE001
            self.log_message.emit(f"Klasör listelenemedi: {exc}")
            return
        yellow = QBrush(QColor("#fff7d6"))
        red = QBrush(QColor(theme.COLOR_DANGER))
        for f in entries:
            size = f"{f.size_bytes:,}" if f.size_bytes else ("—" if not f.is_dir else "")
            typ = "<klasör>" if f.is_dir else (f.detected_type or "Regular File")
            warn = ""
            if f.bad_extension:
                warn = f"⚠ Bad ext: {f.detected_type}"
            elif f.footer_mismatch:
                warn = f"⚠ Kesik/tutarsız: {f.detected_type}"
            item = QTreeWidgetItem([
                f.name, size, typ,
                f.accessed[:19].replace("T", " ") if f.accessed else "",
                f.created[:19].replace("T", " ") if f.created else "",
                f.modified[:19].replace("T", " ") if f.modified else "",
                warn,
            ])
            item.setData(0, NODE_ROLE, f)
            if f.deleted:
                for col in range(7):
                    item.setForeground(col, red)
                if not warn:
                    item.setText(6, "⌫ Silinmiş")
            if f.bad_extension:
                for col in range(7):
                    item.setBackground(col, yellow)
                item.setToolTip(
                    0, f"Uzantı uyuşmazlığı!\nGerçek tür: {f.detected_type}\n"
                       f"Beklenen: {', '.join(f.detected_extensions) or 'yok'}",
                )
            elif f.footer_mismatch:
                for col in range(7):
                    item.setBackground(col, yellow)
                item.setToolTip(
                    0, f"Header türü '{f.detected_type}' ile eşleşen kuyruk "
                       f"(footer) imzası bulunamadı — dosya kesilmiş veya "
                       f"manipüle edilmiş olabilir.",
                )
            self.files.addTopLevelItem(item)

    # --- Fallback imza taraması ------------------------------------------
    def _on_scan_click(self) -> None:
        if self._scan_worker is not None:
            return
        # Full scan (max_bytes=0 = tamamı), 4 KiB step
        self.files.clear()
        self.hex_view.clear()
        self.scan_btn.setEnabled(False)
        self.scan_cancel_btn.setEnabled(True)
        self.scan_progress.setVisible(True)
        self.scan_progress.setValue(0)
        self.scan_status.setText("Tarama başladı…")
        self.log_message.emit("İmza taraması başladı (full scan, step=512 B, sektör hizalı)")
        self._scan_worker = _FallbackScanWorker(
            self._browser, max_bytes=0, step=512,
        )
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_ok.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_fail)
        self._scan_worker.start()

    def _on_scan_cancel(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.cancel()
            self.scan_status.setText("İptal ediliyor…")

    def _on_scan_progress(self, pos: int, total: int) -> None:
        if total > 0:
            pct = int(pos * 100 / total)
            self.scan_progress.setValue(min(pct, 100))
        gb = pos / (1024 ** 3)
        gb_total = total / (1024 ** 3) if total else 0
        self.scan_status.setText(f"Tarama: {gb:.2f} / {gb_total:.2f} GB")

    def _on_scan_done(self, entries: list) -> None:
        self.scan_worker_cleanup()
        self.scan_status.setText(f"Tarama tamam: {len(entries)} eşleşme")
        self.log_message.emit(f"İmza taraması bitti: {len(entries)} dosya")
        yellow = QBrush(QColor("#fff7d6"))
        for f in entries:
            size = "—"
            typ = f.detected_type or "?"
            warn = ""
            if f.bad_extension:
                warn = f"⚠ Bad ext: {f.detected_type}"
            item = QTreeWidgetItem([f.name, size, typ, "", "", "", warn])
            item.setData(0, NODE_ROLE, f)
            if f.bad_extension:
                for col in range(7):
                    item.setBackground(col, yellow)
            self.files.addTopLevelItem(item)

    def _on_scan_fail(self, message: str) -> None:
        self.scan_worker_cleanup()
        self.scan_status.setText(f"HATA: {message}")

    def scan_worker_cleanup(self) -> None:
        self._scan_worker = None
        self.scan_btn.setEnabled(True)
        self.scan_cancel_btn.setEnabled(False)
        self.scan_progress.setVisible(False)

    def _on_file_click(self, item: QTreeWidgetItem, _col: int) -> None:
        f = item.data(0, NODE_ROLE)
        if not isinstance(f, BrowserFile):
            return
        if f.is_dir:
            self.hex_view.setPlainText("")
            return
        self._current_file = f
        self._render_hex(f, 0, 4096)

    def _on_file_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        f = item.data(0, NODE_ROLE)
        if not isinstance(f, BrowserFile) or not f.is_dir:
            return
        cur = self.tree.currentItem()
        if cur is None:
            return
        node = cur.data(0, NODE_ROLE)
        if not isinstance(node, BrowserNode):
            return
        # Ağacı genişlet — henüz yüklenmediyse _on_tree_expand alt
        # klasörleri otomatik yükler; sonra çift tıklanan klasörü bulup seç.
        cur.setExpanded(True)
        for i in range(cur.childCount()):
            child = cur.child(i)
            child_node = child.data(0, NODE_ROLE)
            if isinstance(child_node, BrowserNode) and child_node.name == f.name:
                self.tree.setCurrentItem(child)
                self._list_partition(child_node)
                return

    def _render_hex(self, f: BrowserFile, offset: int, length: int) -> None:
        data = self._browser.read_bytes(f, offset, length)
        if not data:
            self.hex_view.setPlainText("(Dosya okunamadı veya boş.)")
            return
        text = format_hex_dump(data, base_offset=offset)
        header = (
            f"Dosya: {f.fs_path}\n"
            f"Boyut: {f.size_bytes:,} bayt   ·   "
            f"Gösterilen: ilk {len(data):,} bayt\n"
            + "-" * 78 + "\n"
        )
        self.hex_view.setPlainText(header + text)
