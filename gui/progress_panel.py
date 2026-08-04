"""İlerleme paneli — durum + progress bar + siyah zeminli mini log kutusu.

Kural (referans): log SADECE burada koyu zeminli (terminal referansı).
QGroupBox 'İlerleme' içinde tek bir bileşen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.widgets import make_danger, make_primary
from logs.logger import get_logger

logger = get_logger("gui.progress_panel")


class ProgressPanel(QGroupBox):
    """'İlerleme' group box: durum satırı + progress bar + siyah mini log."""

    # Legacy sinyaller (bazı yerler start_btn.clicked kullanıyor olabilir):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("İlerleme", parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 14, 10, 10)
        outer.setSpacing(6)

        # Durum satırı: yeşil nokta + metin
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._dot = QLabel("●")
        self._dot.setStyleSheet(
            f"color: {theme.COLOR_OK}; background: transparent; font-size: 14px;"
        )
        self.status_label = QLabel("Hazır — işlem başlatılmadı")
        self.status_label.setStyleSheet(
            f"color: {theme.COLOR_TEXT}; background: transparent; font-size: 11.5px;"
        )
        status_row.addWidget(self._dot)
        status_row.addWidget(self.status_label, 1)
        outer.addLayout(status_row)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        outer.addWidget(self.progress_bar)

        # Ek meta (bytes / percent)
        self.meta_label = QLabel("")
        self.meta_label.setStyleSheet(
            f"color: {theme.COLOR_TEXT_MUTED}; font-size: 10.5px; background: transparent;"
        )
        outer.addWidget(self.meta_label)

        # Siyah zeminli mini log
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(110)
        self.log_view.setPlaceholderText("")
        self.log_view.setStyleSheet(
            f"QPlainTextEdit {{ "
            f"background-color: {theme.COLOR_LOG_BG}; "
            f"color: {theme.COLOR_LOG_TEXT}; "
            f"border: 1px solid #333; "
            f"border-radius: 2px; "
            f"padding: 6px 8px; "
            f"font-family: {theme.FONT_STACK_MONO}; "
            f"font-size: 11px; }}"
        )
        outer.addWidget(self.log_view)

    # ------------------------------------------------------------------ API
    def set_status(self, message: str, ok: bool = True, warn: bool = False,
                   err: bool = False) -> None:
        self.status_label.setText(message)
        if err:
            self._dot.setStyleSheet(
                f"color: {theme.COLOR_DANGER}; background: transparent; font-size: 14px;"
            )
        elif warn:
            self._dot.setStyleSheet(
                f"color: #b7791f; background: transparent; font-size: 14px;"
            )
        elif ok:
            self._dot.setStyleSheet(
                f"color: {theme.COLOR_OK}; background: transparent; font-size: 14px;"
            )
        else:
            self._dot.setStyleSheet(
                f"color: #999; background: transparent; font-size: 14px;"
            )

    def set_progress(self, done: int, total: Optional[int]) -> None:
        if total and total > 0:
            pct = int(min(100, (done / total) * 100))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.meta_label.setText(
                f"{pct}%  ·  {self._fmt(done)} / {self._fmt(total)}"
            )
        else:
            self.progress_bar.setRange(0, 0)
            self.meta_label.setText(self._fmt(done))

    def reset_progress(self) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.meta_label.setText("")

    def append_log(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{ts}] {message}")

    def clear_log(self) -> None:
        self.log_view.clear()

    @staticmethod
    def _fmt(n: int) -> str:
        n = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
            n /= 1024
        return f"{n:.2f} PB"
