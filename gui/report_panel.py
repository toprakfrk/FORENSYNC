"""Rapor paneli — üretilen raporları listeler ve açmayı sağlar (group box)."""
from __future__ import annotations

import os
import subprocess
import sys

from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.reporter import ReportData
from logs.logger import get_logger

logger = get_logger("gui.report_panel")


class ReportPanel(QWidget):
    """Rapor özeti + üretilen dosya listesi (iki group box)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report_paths: list[str] = []
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        info = QGroupBox("Rapor özeti")
        info_l = QVBoxLayout(info)
        info_l.setContentsMargins(10, 14, 10, 10)

        self.summary = QTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMinimumHeight(160)
        info_l.addWidget(self.summary)

        outer.addWidget(info)

        files = QGroupBox("Üretilen rapor dosyaları")
        files_l = QVBoxLayout(files)
        files_l.setContentsMargins(10, 14, 10, 10)

        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(
            lambda item: self._open_path(item.data(256))
        )
        files_l.addWidget(self.file_list)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.open_btn = QPushButton("Seçili raporu aç")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_selected)
        btn_row.addWidget(self.open_btn)

        files_l.addLayout(btn_row)

        outer.addWidget(files, 1)

    def show_report(self, data: ReportData, report_paths) -> None:
        if isinstance(report_paths, str):
            self._report_paths = [report_paths] if report_paths else []
        else:
            self._report_paths = list(report_paths or [])

        lines = [
            f"Program:   {data.app_name}   ·   Sürüm: {data.app_version}",
            f"Vaka no:   {data.case_number}   ·   Delil no: {data.evidence_number}",
            f"İnceleyen: {data.examiner}   ·   Konum: {data.location}",
            f"Hedef:     {data.target_host}  ({data.os_type})",
            f"Cihaz:     {data.device_path}",
            f"İmaj tipi: {data.image_type}   ·   Format: {data.image_format}",
            f"Boyut:     {data.total_bytes:,} bayt",
            f"Başlangıç (UTC): {data.started_at}   ·   Bitiş (UTC): {data.finished_at}",
            f"Devam ile: {'Evet' if data.resumed else 'Hayır'}"
            + (f" (ofset {data.resumed_from_bytes:,})" if data.resumed else ""),
            f"Hash:      {'BAŞARILI' if data.hash_verified else 'N/A'} "
            f"({data.hash_verification_mode})"
            + (f"  ·  alınma tarihi: {data.hash_computed_at}" if data.hash_computed_at else ""),
        ]

        if data.hashes:
            lines.append("")
            lines.append("Yerel imaj hash'leri:")
            for algo, value in data.hashes.items():
                lines.append(f"  {algo}: {value}")

        if data.source_hashes:
            lines.append("Kaynak cihaz hash'leri:")
            for algo, value in data.source_hashes.items():
                lines.append(f"  {algo}: {value}")

        lines.append("")
        lines.append(
            f"NTP sapma: {data.ntp_offset_seconds:.3f} sn "
            f"({'güvenilir' if data.ntp_reliable else 'güvenilmez'})"
        )
        lines.append(f"İmza:      {data.signature_path or 'Yok'}")

        if data.targeted_files_count:
            lines.append(
                f"Hedefli tarama: {data.targeted_files_count} dosya, "
                f"{len(data.bad_extension_files)} uzantı-tür uyuşmazlığı"
            )

        for note in data.notes:
            lines.append(f"Not: {note}")

        self.summary.setPlainText("\n".join(lines))

        self.file_list.clear()
        for path in self._report_paths:
            item = QListWidgetItem(path)
            item.setData(256, path)
            self.file_list.addItem(item)

        self.open_btn.setEnabled(bool(self._report_paths))

    def _open_selected(self) -> None:
        item = self.file_list.currentItem()
        if item is None and self._report_paths:
            path = self._report_paths[0]
        elif item is not None:
            path = item.data(256)
        else:
            return
        self._open_path(path)

    def _open_path(self, path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:  # noqa: BLE001
            logger.error("Rapor açılamadı: %s", exc)