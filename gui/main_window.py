"""IMAJER — Ana pencere (klasik Windows Forms tarzı adli bilişim yazılımı).

Yerleşim (üstten alta):
    QMenuBar   — Dosya / Düzen / Görev / Görünüm / Yardım
    QToolBar   — Bağlan / Disk imajı / RAM imajı / İnceleme / Rapor (checkable)
    Merkez:
        Sol:  SourcesPanel (kanıt kaynakları ağacı + son işlemler)
        Sağ:  QStackedWidget (görev sayfaları)
              [Disk imajı, RAM imajı, İnceleme, Rapor, Hedefli tarama]
    QStatusBar — Sol: kısa durum · Sağ: kanıt dizini + gizlilik notu
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import APP_NAME, APP_VERSION
from core.acquisition_controller import AcquisitionController, AcquisitionParams
from core.error_handler import YTIError, log_exception
from core.ssh_connector import SSHCredentials
from gui import theme
from gui.analyzer_panel import AnalyzerPanel
from gui.connection_panel import ConnectionPanel
from gui.disk_panel import DiskPanel
from gui.format_panel import FormatPanel
from gui.progress_panel import ProgressPanel
from gui.ram_panel import RamPanel
from gui.report_panel import ReportPanel
from gui.sources_panel import SourcesPanel
from gui.targeted_panel import TargetedPanel
from gui.theme import APP_STYLESHEET
from gui.widgets import make_danger, make_primary, make_secondary
from logs.logger import get_logger

logger = get_logger("gui.main_window")


# ---------------------------------------------------------------------- Icon helper
def _make_icon(color: str, kind: str) -> QIcon:
    """Basit vektör ikonlar (ekstra dosya gerektirmesin diye QPainter ile çizilir)."""
    pm = QPixmap(20, 20)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(color)
    p.setPen(col)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = p.pen()
    pen.setWidth(2)
    p.setPen(pen)
    if kind == "connect":
        # Fiş / bağlantı
        p.drawLine(4, 10, 16, 10)
        p.drawRect(3, 6, 4, 8)
        p.drawRect(13, 6, 4, 8)
    elif kind == "disk":
        # Silindir (disk)
        p.drawEllipse(3, 3, 14, 4)
        p.drawLine(3, 5, 3, 15)
        p.drawLine(17, 5, 17, 15)
        p.drawEllipse(3, 13, 14, 4)
    elif kind == "ram":
        # Chip
        p.drawRect(4, 5, 12, 10)
        p.drawLine(2, 7, 4, 7)
        p.drawLine(2, 10, 4, 10)
        p.drawLine(2, 13, 4, 13)
        p.drawLine(16, 7, 18, 7)
        p.drawLine(16, 10, 18, 10)
        p.drawLine(16, 13, 18, 13)
    elif kind == "inspect":
        # Büyüteç
        p.drawEllipse(3, 3, 10, 10)
        p.drawLine(11, 11, 17, 17)
    elif kind == "report":
        # Kağıt
        p.drawLine(5, 3, 15, 3)
        p.drawLine(15, 3, 15, 17)
        p.drawLine(15, 17, 5, 17)
        p.drawLine(5, 17, 5, 3)
        p.drawLine(7, 7, 13, 7)
        p.drawLine(7, 10, 13, 10)
        p.drawLine(7, 13, 11, 13)
    elif kind == "triage":
        # Filtre
        p.drawLine(3, 4, 17, 4)
        p.drawLine(3, 4, 8, 10)
        p.drawLine(17, 4, 12, 10)
        p.drawLine(8, 10, 8, 16)
        p.drawLine(12, 10, 12, 14)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------- Worker
class AcquisitionWorker(QThread):
    """İmaj alma sürecini arka planda çalıştıran worker thread."""

    progress = pyqtSignal(int, object)
    status = pyqtSignal(str)
    finished_ok = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, controller: AcquisitionController, params: AcquisitionParams) -> None:
        super().__init__()
        self.controller = controller
        self.params = params

    def run(self) -> None:  # noqa: D401
        self.controller.progress_callback = lambda done, total: self.progress.emit(done, total)
        self.controller.status_callback = lambda msg: self.status.emit(msg)
        try:
            report = self.controller.run_full_acquisition(self.params)
            self.finished_ok.emit(report, self._collect_report_paths(report))
        except YTIError as exc:
            log_exception(exc, context="AcquisitionWorker.run")
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="AcquisitionWorker.run(unexpected)")
            self.failed.emit(f"Beklenmeyen hata: {exc}")

    @staticmethod
    def _collect_report_paths(report):
        paths = []
        for note in report.notes:
            if note.startswith("Rapor ("):
                try:
                    paths.append(note.split(": ", 1)[1])
                except IndexError:
                    pass
        return paths


# ---------------------------------------------------------------------- Ana pencere
_TASK_DISK = 0
_TASK_RAM = 1
_TASK_TRIAGE = 2
_TASK_INSPECT = 3
_TASK_REPORT = 4


class MainWindow(QMainWindow):
    """IMAJER ana pencere — klasik masaüstü yerleşim."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ForenSync Imager")
        self.resize(1180, 780)
        self.setMinimumSize(1024, 680)
        self.setStyleSheet(APP_STYLESHEET)

        self.controller = AcquisitionController()
        self.worker: Optional[AcquisitionWorker] = None
        self._paused = False
        self._current_task = _TASK_DISK

        self._build_menu()
        self._build_toolbar()
        self._build_center()
        self._build_statusbar()
        self._wire_signals()

    # ------------------------------------------------------------------ Menü
    def _build_menu(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("Dosya")
        act_new = QAction("Yeni oturum", self)
        act_new.triggered.connect(self._new_session)
        m_file.addAction(act_new)
        act_open_rep = QAction("Rapor dosyası aç…", self)
        act_open_rep.triggered.connect(self._open_report_file)
        m_file.addAction(act_open_rep)
        m_file.addSeparator()
        act_quit = QAction("Çıkış", self)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        m_edit = mb.addMenu("Düzen")
        act_reset = QAction("Formları sıfırla", self)
        act_reset.triggered.connect(self._reset_forms)
        m_edit.addAction(act_reset)

        self.m_task = mb.addMenu("Görev")
        # Bu menü toolbar aksiyonlarıyla doldurulacak (aynı QAction referansları)

        m_view = mb.addMenu("Görünüm")
        act_sources = QAction("Kanıt kaynaklarını göster/gizle", self, checkable=True)
        act_sources.setChecked(True)
        act_sources.toggled.connect(self._toggle_sources)
        m_view.addAction(act_sources)
        self._act_view_sources = act_sources

        m_help = mb.addMenu("Yardım")
        act_about = QAction("Hakkında", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

    # ------------------------------------------------------------------ Toolbar
    def _build_toolbar(self) -> None:
        tb = QToolBar("Ana araç çubuğu")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(tb)

        color = theme.COLOR_ACCENT

        self.act_connect = QAction(_make_icon(color, "connect"), "Bağlan", self)
        self.act_connect.triggered.connect(self._focus_connection)
        tb.addAction(self.act_connect)
        tb.addSeparator()

        group = QActionGroup(self)
        group.setExclusive(True)

        self.act_disk = QAction(_make_icon(color, "disk"), "Disk imajı", self)
        self.act_disk.setCheckable(True)
        self.act_disk.setChecked(True)
        self.act_disk.triggered.connect(lambda: self._switch_task(_TASK_DISK))
        group.addAction(self.act_disk)
        tb.addAction(self.act_disk)

        self.act_ram = QAction(_make_icon(color, "ram"), "RAM imajı", self)
        self.act_ram.setCheckable(True)
        self.act_ram.triggered.connect(lambda: self._switch_task(_TASK_RAM))
        group.addAction(self.act_ram)
        tb.addAction(self.act_ram)

        self.act_triage = QAction(_make_icon(color, "triage"), "Hedefli tarama", self)
        self.act_triage.setCheckable(True)
        self.act_triage.triggered.connect(lambda: self._switch_task(_TASK_TRIAGE))
        group.addAction(self.act_triage)
        tb.addAction(self.act_triage)

        self.act_inspect = QAction(_make_icon(color, "inspect"), "İnceleme", self)
        self.act_inspect.setCheckable(True)
        self.act_inspect.triggered.connect(lambda: self._switch_task(_TASK_INSPECT))
        group.addAction(self.act_inspect)
        tb.addAction(self.act_inspect)

        self.act_report = QAction(_make_icon(color, "report"), "Rapor", self)
        self.act_report.setCheckable(True)
        self.act_report.triggered.connect(lambda: self._switch_task(_TASK_REPORT))
        group.addAction(self.act_report)
        tb.addAction(self.act_report)

        for a in (self.act_disk, self.act_ram, self.act_triage,
                  self.act_inspect, self.act_report):
            self.m_task.addAction(a)

    # ------------------------------------------------------------------ Merkez
    def _build_center(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Üst: splitter (sol ağaç | sağ görev sayfası) ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        self.sources = SourcesPanel()
        splitter.addWidget(self.sources)

        # Progress panel ORTAK — main window seviyesinde önce oluşturuyoruz,
        # çünkü sayfa constructor'ları ona referans veriyor olabilir.
        self.progress_panel = ProgressPanel()

        self.stack = QStackedWidget()
        self.disk_page = self._build_disk_page()
        self.ram_page = self._build_ram_page()
        self.triage_page = self._build_triage_page()
        self.inspect_page = self._build_inspect_page()
        self.report_page = self._build_report_page()
        self.stack.addWidget(self.disk_page)       # 0
        self.stack.addWidget(self.ram_page)        # 1
        self.stack.addWidget(self.triage_page)     # 2
        self.stack.addWidget(self.inspect_page)    # 3
        self.stack.addWidget(self.report_page)     # 4

        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 950])
        outer.addWidget(splitter, 1)

        # ---- Alt: sabit ilerleme paneli (tüm görevler için ortak) ----
        prog_wrap = QWidget()
        prog_wrap.setStyleSheet(
            f"QWidget {{ background-color: {theme.COLOR_BG}; "
            f"border-top: 1px solid {theme.COLOR_BORDER_LIGHT}; }}"
        )
        pv = QVBoxLayout(prog_wrap)
        pv.setContentsMargins(10, 6, 10, 6)
        pv.setSpacing(0)
        pv.addWidget(self.progress_panel)
        outer.addWidget(prog_wrap, 0)

        self.setCentralWidget(central)

    # ---- Sayfa yapıları ---------------------------------------------------
    def _wrap_scroll(self, inner: QWidget) -> QWidget:
        """Sayfayı QScrollArea içine koy (küçük ekranda scroll olsun)."""
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(sc.Shape.NoFrame)
        sc.setWidget(inner)
        return sc

    def _build_disk_page(self) -> QWidget:
        # Sayfa: üst scroll edilebilir form + alt sabit aksiyon barı
        # (progress paneli tüm sayfalar için ortak, main window seviyesinde)
        page = QWidget()
        pv = QVBoxLayout(page)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        form_host = QWidget()
        v = QVBoxLayout(form_host)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        self.connection_panel = ConnectionPanel()
        v.addWidget(self.connection_panel)
        self.disk_panel = DiskPanel()
        v.addWidget(self.disk_panel)
        self.format_panel = FormatPanel()
        v.addWidget(self.format_panel)
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setWidget(form_host)
        pv.addWidget(scroll, 1)

        bottom = QWidget()
        bottom.setStyleSheet(
            f"QWidget {{ background-color: {theme.COLOR_BG}; "
            f"border-top: 1px solid {theme.COLOR_BORDER_LIGHT}; }}"
        )
        bv = QHBoxLayout(bottom)
        bv.setContentsMargins(10, 8, 10, 8)
        bv.setSpacing(6)
        bv.addStretch(1)
        self.cancel_btn = QPushButton("İptal")
        make_danger(self.cancel_btn)
        self.cancel_btn.setEnabled(False)
        self.reset_btn = QPushButton("Sıfırla")
        make_secondary(self.reset_btn)
        self.pause_btn = QPushButton("Duraklat")
        self.pause_btn.setEnabled(False)
        self.start_btn = QPushButton("İmaj almayı başlat")
        make_primary(self.start_btn)
        bv.addWidget(self.cancel_btn)
        bv.addWidget(self.reset_btn)
        bv.addWidget(self.pause_btn)
        bv.addWidget(self.start_btn)
        pv.addWidget(bottom, 0)
        return page

    def _build_ram_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        note = QLabel(
            "Bağlantı bilgileri ve vaka bilgileri 'Disk imajı' sekmesindeki alanlardan alınır."
        )
        note.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11.5px; padding: 4px 0;"
        )
        v.addWidget(note)

        self.ram_panel = RamPanel()
        v.addWidget(self.ram_panel)

        act_row = QHBoxLayout()
        act_row.addStretch(1)
        self.ram_cancel_btn = QPushButton("İptal")
        make_danger(self.ram_cancel_btn)
        self.ram_cancel_btn.setEnabled(False)
        self.ram_reset_btn = QPushButton("Sıfırla")
        self.ram_pause_btn = QPushButton("Duraklat")
        self.ram_pause_btn.setEnabled(False)
        self.ram_start_btn = QPushButton("RAM imajı al")
        make_primary(self.ram_start_btn)
        act_row.addWidget(self.ram_cancel_btn)
        act_row.addWidget(self.ram_reset_btn)
        act_row.addWidget(self.ram_pause_btn)
        act_row.addWidget(self.ram_start_btn)
        v.addLayout(act_row)

        v.addStretch(1)
        return self._wrap_scroll(w)

    def _build_triage_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        note = QLabel(
            "Bağlantı bilgileri 'Disk imajı' sekmesindeki alanlardan alınır. "
            "Bad extension tespiti için dosya imzası (magic) doğrulaması etkin bırakın."
        )
        note.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 11.5px; padding: 4px 0;"
        )
        v.addWidget(note)

        self.targeted_panel = TargetedPanel()
        v.addWidget(self.targeted_panel)

        act_row = QHBoxLayout()
        act_row.addStretch(1)
        self.triage_cancel_btn = QPushButton("İptal")
        make_danger(self.triage_cancel_btn)
        self.triage_cancel_btn.setEnabled(False)
        self.triage_start_btn = QPushButton("Taramayı başlat")
        make_primary(self.triage_start_btn)
        act_row.addWidget(self.triage_cancel_btn)
        act_row.addWidget(self.triage_start_btn)
        v.addLayout(act_row)

        v.addStretch(1)
        return self._wrap_scroll(w)

    def _build_inspect_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)
        self.analyzer_panel = AnalyzerPanel()
        v.addWidget(self.analyzer_panel, 1)
        return self._wrap_scroll(w)

    def _build_report_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)
        self.report_panel = ReportPanel()
        v.addWidget(self.report_panel, 1)
        return self._wrap_scroll(w)

    # ------------------------------------------------------------------ Status bar
    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(True)
        self.status_left = QLabel("Hazır")
        self.status_left.setStyleSheet(f"color: {theme.COLOR_TEXT}; padding: 0 8px;")
        sb.addWidget(self.status_left, 1)

        self.status_right = QLabel(
            "Kanıt dizini: —   ·   Parolalar log/rapora yazılmaz"
        )
        self.status_right.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; padding: 0 8px;"
        )
        sb.addPermanentWidget(self.status_right)

    # ------------------------------------------------------------------ Signals
    def _wire_signals(self) -> None:
        # Bağlantı
        self.connection_panel.connect_requested.connect(self._on_connect)

        # Sol ağaç -> disk seçimi
        self.sources.disk_selected.connect(self._on_disk_selected_from_tree)

        # Disk sayfası butonları
        self.start_btn.clicked.connect(self._on_start)
        self.pause_btn.clicked.connect(self._on_pause_toggle)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.reset_btn.clicked.connect(self._reset_forms)

        # RAM sayfası butonları
        self.ram_start_btn.clicked.connect(self._on_start)
        self.ram_pause_btn.clicked.connect(self._on_pause_toggle)
        self.ram_cancel_btn.clicked.connect(self._on_cancel)
        self.ram_reset_btn.clicked.connect(self._reset_forms)

        # Triage sayfası
        self.triage_start_btn.clicked.connect(self._on_start)
        self.triage_cancel_btn.clicked.connect(self._on_cancel)

        # Analyzer paneli log/status -> statusbar + progress
        self.analyzer_panel.log_message.connect(self.progress_panel.append_log)
        self.analyzer_panel.status_message.connect(
            lambda t, ok: self._set_status(t, ok=ok, err=not ok)
        )

    # ------------------------------------------------------------------ Slots
    def _switch_task(self, task_idx: int) -> None:
        self._current_task = task_idx
        self.stack.setCurrentIndex(task_idx)
        # Toolbar action check state'ini de senkronla (menüden geçişlerde).
        task_actions = {
            _TASK_DISK: self.act_disk, _TASK_RAM: self.act_ram,
            _TASK_TRIAGE: self.act_triage, _TASK_INSPECT: self.act_inspect,
            _TASK_REPORT: self.act_report,
        }
        for idx, act in task_actions.items():
            act.setChecked(idx == task_idx)
        names = {
            _TASK_DISK: "Disk imajı",
            _TASK_RAM: "RAM imajı",
            _TASK_TRIAGE: "Hedefli tarama",
            _TASK_INSPECT: "İnceleme",
            _TASK_REPORT: "Rapor",
        }
        self._set_status(f"Görev: {names.get(task_idx, '—')}", ok=True)

    def _focus_connection(self) -> None:
        # Bağlan aksiyonu tıklandığında disk sayfasına git ve host alanına odaklan.
        self.act_disk.setChecked(True)
        self._switch_task(_TASK_DISK)
        self.connection_panel.host_edit.setFocus()

    def _toggle_sources(self, visible: bool) -> None:
        self.sources.setVisible(visible)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"Hakkında — {APP_NAME}",
            f"<b>{APP_NAME}</b> — sürüm {APP_VERSION}<br>"
            "Adli bilişim disk/RAM imaj alma yazılımı<br><br>"
            "Uzak sunuculardan salt-okunur imaj alır, resume, kaynak-imaj hash "
            "doğrulama, hedefli tarama ve delil zinciri raporu üretir.<br><br>"
            "© 2026 ForenSync",
        )

    def _new_session(self) -> None:
        # Formları sıfırla, ağacı temizle.
        self._reset_forms()
        self.sources.clear_host()
        self._set_status("Yeni oturum", ok=True)

    def _open_report_file(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Rapor dosyası aç", "",
            "Rapor Dosyaları (*.txt *.pdf *.json *.html *.csv *.xml);;Tüm Dosyalar (*)",
        )
        if path:
            self.report_panel.show_report_from_file(path) if hasattr(
                self.report_panel, "show_report_from_file"
            ) else None
            # Basit: sadece açalım
            import subprocess, sys, os
            if os.path.exists(path):
                if sys.platform.startswith("win"):
                    os.startfile(path)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])

    def _reset_forms(self) -> None:
        self.connection_panel.host_edit.clear()
        self.connection_panel.user_edit.clear()
        self.connection_panel.pass_edit.clear()
        self.connection_panel.key_edit.clear()
        self.disk_panel.output_edit.clear()
        self.disk_panel.device_edit.clear()
        self.disk_panel._selected_device = ""
        self.ram_panel.output_edit.clear()
        self.progress_panel.reset_progress()
        self.progress_panel.clear_log()
        self.progress_panel.set_status("Hazır — işlem başlatılmadı", ok=True)
        self._set_status("Formlar sıfırlandı", ok=True)

    def _on_connect(self, creds: SSHCredentials) -> None:
        try:
            self._set_status("Bağlanılıyor…", ok=False)
            self.progress_panel.append_log(
                f"SSH bağlanılıyor: {creds.username}@{creds.host}:{creds.port}"
            )
            self.controller.connect(creds)
            self._set_status(f"Bağlı — {creds.username}@{creds.host}", ok=True)
            self.progress_panel.append_log("Bağlantı başarılı. Diskler alınıyor…")
            # Diskleri sol ağaca yükle
            disks = self.controller.list_disks()
            host_label = f"{creds.username}@{creds.host}"
            self.sources.set_host(host_label, disks)
            self.progress_panel.append_log(f"{len(disks)} disk listelendi.")
            # RAM bilgisi
            try:
                from core.ram_imager import RamImager
                ram = RamImager(self.controller.ssh, self.controller._os_type)
                info = ram.get_ram_info()
                self.ram_panel.set_ram_info(info.total_bytes, info.available_bytes)
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAM bilgisi alınamadı: %s", exc)
        except YTIError as exc:
            self._set_status("Bağlantı hatası", err=True)
            self._show_error("Bağlantı Hatası", str(exc))
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="MainWindow._on_connect")
            self._set_status("Bağlantı hatası", err=True)
            self._show_error("Bağlantı Hatası", f"Beklenmeyen hata: {exc}")

    def _on_disk_selected_from_tree(
        self, device_path: str, size_bytes: int, model: str
    ) -> None:
        self.disk_panel.set_selected_disk(device_path, size_bytes, model)
        self.progress_panel.append_log(f"Disk seçildi: {device_path}")

    # ---- Params oluşturma ------------------------------------------------
    def _build_params(self) -> Optional[AcquisitionParams]:
        creds = self.connection_panel.credentials()

        task = self._current_task
        if task == _TASK_DISK:
            # DiskPanel'de 'Uzantı Hedefli Tarama' işaretliyse iş targeted moda
            # dönüşür (disk imajı çekmez, uzak sistemi tarayıp seçili dosyaları
            # yerel klasöre kopyalar).
            if self.disk_panel.is_targeted_mode():
                target_root = self.disk_panel.target_root()
                if not target_root:
                    self._show_error(
                        "Eksik bilgi",
                        "Uzantı hedefli tarama için 'Uzak kök' zorunludur.",
                    )
                    return None
                out_dir = self.disk_panel.target_output_dir() or "/tmp/yti_triage"
                exts = self.disk_panel.target_extensions()
                if not exts:
                    self._show_error(
                        "Eksik bilgi",
                        "En az bir uzantı seçin.",
                    )
                    return None
                from core.targeted_imager import TargetedRule
                rule = TargetedRule(
                    name="disk-targeted", extensions=exts, use_signature_match=True,
                )
                image_type = "targeted"
                device = ""
                output = out_dir
                image_format = "raw"
                target_root_val = target_root
                target_rule = rule
                target_copy_dir = out_dir
                target_copy = True
                dd_bs = "4M"
                split_mb = 0
            else:
                output = self.disk_panel.output_path()
                device = self.disk_panel.selected_device()
                image_format = self.disk_panel.selected_format()
                image_type = "disk"
                if not device:
                    self._show_error("Eksik bilgi", "Lütfen soldaki ağaçtan bir disk seçin.")
                    return None
                if not output:
                    self._show_error("Eksik bilgi", "Lütfen çıktı dosya yolunu belirtin.")
                    return None
                target_root_val = ""
                target_rule = None
                target_copy_dir = ""
                target_copy = False
                dd_bs = self.disk_panel.dd_block_size()
                split_mb = self.disk_panel.split_size_mb()
        elif task == _TASK_RAM:
            output = self.ram_panel.output_path()
            device = ""
            image_format = "raw"
            image_type = "ram"
            if not output:
                self._show_error("Eksik bilgi", "Lütfen RAM çıktı dosya yolunu belirtin.")
                return None
            target_root_val = ""
            target_rule = None
            target_copy_dir = ""
            target_copy = False
            dd_bs = "4M"
            split_mb = 0
        elif task == _TASK_TRIAGE:
            output = self.targeted_panel.output_dir() or "/tmp/yti_triage"
            device = ""
            image_format = "raw"
            image_type = "targeted"
            target_root_val = self.targeted_panel.target_root()
            if not target_root_val:
                self._show_error("Eksik bilgi", "Uzak kök yolunu belirtin.")
                return None
            target_rule = self.targeted_panel.build_rule()
            target_copy_dir = self.targeted_panel.output_dir()
            target_copy = self.targeted_panel.copy_files()
            dd_bs = "4M"
            split_mb = 0
        else:
            return None

        return AcquisitionParams(
            credentials=creds,
            image_type=image_type,
            device_path=device,
            output_path=output,
            image_format=image_format,
            hash_algorithms=self.format_panel.selected_algorithms(),
            case_number=self.format_panel.case_number(),
            examiner=self.format_panel.examiner(),
            evidence_number=self.format_panel.evidence_number(),
            location=self.format_panel.location(),
            incident_datetime=self.format_panel.incident_datetime(),
            investigator_notes=self.format_panel.investigator_notes(),
            sign_output=self.format_panel.sign_output(),
            verify_source=self.format_panel.verify_source(),
            allow_resume=self.format_panel.allow_resume(),
            report_path=f"{output}.rapor.txt",
            report_formats=self.format_panel.selected_report_formats(),
            target_root=target_root_val,
            target_rule=target_rule,
            target_copy_dir=target_copy_dir,
            target_copy_files=target_copy,
            dd_block_size=dd_bs,
            split_size_mb=split_mb,
            winpmem_path=self.ram_panel.winpmem_path() or None,
        )

    def _on_start(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self._show_error("Zaten çalışıyor", "Bir iş zaten çalışıyor.")
            return
        params = self._build_params()
        if params is None:
            return
        self._paused = False
        self._set_running(True)
        self.progress_panel.clear_log()
        self.progress_panel.reset_progress()
        self.progress_panel.set_status(
            {"disk": "Disk imajı başlatılıyor…",
             "ram": "RAM imajı başlatılıyor…",
             "targeted": "Hedefli tarama başlatılıyor…"}[params.image_type],
            ok=True,
        )
        self.progress_panel.append_log("İşlem başlatıldı.")
        self.status_right.setText(
            f"Kanıt dizini: {params.output_path}   ·   Parolalar log/rapora yazılmaz"
        )
        self._set_status("İşleniyor…", ok=True)

        self.worker = AcquisitionWorker(self.controller, params)
        self.worker.progress.connect(self.progress_panel.set_progress)
        self.worker.status.connect(self._on_worker_status)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_worker_status(self, msg: str) -> None:
        self.progress_panel.set_status(msg, ok=True)
        self.progress_panel.append_log(msg)
        self._set_status(msg, ok=True)

    def _on_pause_toggle(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        if self._paused:
            self.controller.resume()
            self._set_pause_label("Duraklat")
            self.progress_panel.set_status("Devam ediyor…", ok=True)
            self.progress_panel.append_log("Devam edildi.")
            self._paused = False
        else:
            self.controller.pause()
            self._set_pause_label("Devam et")
            self.progress_panel.set_status("Duraklatıldı", warn=True)
            self.progress_panel.append_log("Duraklatıldı.")
            self._paused = True

    def _set_pause_label(self, text: str) -> None:
        for btn in (self.pause_btn, self.ram_pause_btn):
            btn.setText(text)

    def _set_running(self, running: bool) -> None:
        for start in (self.start_btn, self.ram_start_btn, self.triage_start_btn):
            start.setEnabled(not running)
        for pause in (self.pause_btn, self.ram_pause_btn):
            pause.setEnabled(running)
        for cancel in (self.cancel_btn, self.ram_cancel_btn, self.triage_cancel_btn):
            cancel.setEnabled(running)

    def _on_cancel(self) -> None:
        self.controller.cancel()
        self.progress_panel.set_status("İptal isteği gönderildi", warn=True)
        self.progress_panel.append_log("Kullanıcı tarafından iptal edildi.")
        self._set_status("İptal ediliyor…", warn=True)

    def _on_finished(self, report, report_paths) -> None:
        self._set_running(False)
        self.progress_panel.set_progress(1, 1)
        self.progress_panel.set_status("Tamamlandı", ok=True)
        self.progress_panel.append_log("İşlem başarıyla tamamlandı.")
        self._set_status("Tamamlandı", ok=True)
        self.report_panel.show_report(report, report_paths)
        # Son işlemler
        summary = (
            f"{report.case_number or '—'}  ·  "
            f"{report.device_path or report.image_type}  ·  tamamlandı"
        )
        self.sources.add_recent(summary)
        # Rapor sayfasına geç
        self.act_report.setChecked(True)
        self._switch_task(_TASK_REPORT)
        QMessageBox.information(
            self, "Tamamlandı", "İmaj alma işlemi başarıyla tamamlandı."
        )

    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self.progress_panel.set_status("İşlem başarısız", err=True)
        self.progress_panel.append_log(f"HATA: {message}")
        self._set_status("İşlem başarısız", err=True)
        self._show_error("İşlem hatası", message)

    def _set_status(self, text: str, ok: bool = True, warn: bool = False,
                    err: bool = False) -> None:
        color = theme.COLOR_TEXT
        if err:
            color = theme.COLOR_DANGER
        elif warn:
            color = "#b7791f"
        self.status_left.setText(text)
        self.status_left.setStyleSheet(f"color: {color}; padding: 0 8px;")

    def _show_error(self, title: str, message: str) -> None:
        logger.error("%s: %s", title, message)
        QMessageBox.critical(self, title, message)

    # ------------------------------------------------------------------ Close
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self.worker is not None and self.worker.isRunning():
                self.controller.cancel()
                self.worker.wait(3000)
            self.controller.close()
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="MainWindow.closeEvent")
        super().closeEvent(event)
