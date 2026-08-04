"""Hash + Vaka bilgileri paneli — Hash grup + Vaka grup + Rapor formatları.

Hash algoritmaları ve Vaka bilgileri YAN YANA iki group box (ekran genişse).
Format panel bu iki group box'ı ve altta rapor formatlarını içerir.
"""

from __future__ import annotations

from PyQt6.QtCore import QDateTime
from PyQt6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.hasher import SUPPORTED_ALGORITHMS
from logs.logger import get_logger

logger = get_logger("gui.format_panel")

REPORT_FORMATS = ["txt", "pdf", "json", "html", "csv", "xml"]


class HashGroup(QGroupBox):
    """'2. Hash algoritmaları' group box."""

    def __init__(self) -> None:
        super().__init__("2. Hash algoritmaları")
        self._checks: dict = {}
        vl = QVBoxLayout(self)
        vl.setContentsMargins(10, 14, 10, 10)
        vl.setSpacing(6)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for i, algo in enumerate(SUPPORTED_ALGORITHMS):
            cb = QCheckBox(algo.upper())
            if algo == "sha256":
                cb.setChecked(True)
            self._checks[algo] = cb
            grid.addWidget(cb, i // 2, i % 2)
        vl.addLayout(grid)
        self.verify_source_cb = QCheckBox("Kaynak diski de doğrula (yavaş)")
        self.verify_source_cb.setStyleSheet("font-size: 11px;")
        vl.addWidget(self.verify_source_cb)

    def selected(self) -> list:
        return [a for a, cb in self._checks.items() if cb.isChecked()] or ["sha256"]

    def verify_source(self) -> bool:
        return self.verify_source_cb.isChecked()


class CaseGroup(QGroupBox):
    """'3. Vaka bilgileri' group box."""

    def __init__(self) -> None:
        super().__init__("3. Vaka bilgileri")
        form = QFormLayout(self)
        form.setContentsMargins(10, 14, 10, 10)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(form.labelAlignment())

        self.case_edit = QLineEdit()
        self.case_edit.setPlaceholderText("CASE-2026-001")
        self.evidence_edit = QLineEdit()
        self.evidence_edit.setPlaceholderText("EVID-001")
        self.examiner_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Laboratuvar / Oda")
        self.incident_dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.incident_dt.setCalendarPopup(True)
        self.incident_dt.setDisplayFormat("dd.MM.yyyy HH:mm")

        form.addRow("Vaka no", self.case_edit)
        form.addRow("Delil no", self.evidence_edit)
        form.addRow("İnceleyen", self.examiner_edit)
        form.addRow("Konum", self.location_edit)
        form.addRow("Olay tarihi", self.incident_dt)

        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Notlar (opsiyonel)")
        self.notes_edit.setFixedHeight(46)
        form.addRow("Notlar", self.notes_edit)

    def case_number(self) -> str:
        return self.case_edit.text().strip()

    def evidence_number(self) -> str:
        return self.evidence_edit.text().strip()

    def examiner(self) -> str:
        return self.examiner_edit.text().strip()

    def location(self) -> str:
        return self.location_edit.text().strip()

    def incident_datetime(self) -> str:
        return self.incident_dt.dateTime().toString("yyyy-MM-dd HH:mm")

    def investigator_notes(self) -> str:
        return self.notes_edit.toPlainText().strip()


class OptionsGroup(QGroupBox):
    """Çıktı seçenekleri: imzala + resume + rapor formatları."""

    def __init__(self) -> None:
        super().__init__("4. Çıktı seçenekleri")
        self._report_checks: dict = {}
        vl = QVBoxLayout(self)
        vl.setContentsMargins(10, 14, 10, 10)
        vl.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(20)
        self.sign_cb = QCheckBox("RSA ile dijital imzala")
        self.sign_cb.setChecked(True)
        self.resume_cb = QCheckBox("Kaldığı yerden devam (resume)")
        self.resume_cb.setChecked(True)
        row1.addWidget(self.sign_cb)
        row1.addWidget(self.resume_cb)
        row1.addStretch(1)
        vl.addLayout(row1)

        # Rapor formatları
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(10)
        fmt_row.addWidget(QLabel("Rapor formatı:"))
        for fmt in REPORT_FORMATS:
            cb = QCheckBox(fmt.upper())
            if fmt in ("txt", "pdf"):
                cb.setChecked(True)
            self._report_checks[fmt] = cb
            fmt_row.addWidget(cb)
        fmt_row.addStretch(1)
        vl.addLayout(fmt_row)

    def sign_output(self) -> bool: return self.sign_cb.isChecked()
    def allow_resume(self) -> bool: return self.resume_cb.isChecked()
    def selected_report_formats(self) -> list:
        return [f for f, cb in self._report_checks.items() if cb.isChecked()] or ["txt"]


class FormatPanel(QWidget):
    """Yatay iki group box (Hash + Vaka) + altında OptionsGroup."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.hash_group = HashGroup()
        self.case_group = CaseGroup()
        row.addWidget(self.hash_group, 1)
        row.addWidget(self.case_group, 2)
        outer.addLayout(row)

        self.options_group = OptionsGroup()
        outer.addWidget(self.options_group)

    # Public getters (main_window çağırır)
    def selected_algorithms(self) -> list: return self.hash_group.selected()
    def selected_report_formats(self) -> list: return self.options_group.selected_report_formats()
    def case_number(self) -> str: return self.case_group.case_number()
    def evidence_number(self) -> str: return self.case_group.evidence_number()
    def examiner(self) -> str: return self.case_group.examiner()
    def location(self) -> str: return self.case_group.location()
    def incident_datetime(self) -> str: return self.case_group.incident_datetime()
    def investigator_notes(self) -> str: return self.case_group.investigator_notes()
    def sign_output(self) -> bool: return self.options_group.sign_output()
    def verify_source(self) -> bool: return self.hash_group.verify_source()
    def allow_resume(self) -> bool: return self.options_group.allow_resume()
