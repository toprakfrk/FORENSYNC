"""Adli bilişim raporu üretici (TXT / PDF / JSON / HTML / CSV / XML).

TXT temel akış olarak korunur. PDF üretimi ``reportlab`` mevcutsa
etkinleşir, aksi halde kullanıcı için anlamlı bir hata döner. JSON/HTML/
CSV/XML standart kütüphanelerle üretilir (ek bağımlılık yok).

Aynı ``ReportData`` nesnesinden birden çok formatta rapor üretilebilir.
"""

from __future__ import annotations

import csv
import html as html_module
import io
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.error_handler import log_exception
from logs.logger import get_logger

logger = get_logger("reporter")


@dataclass
class ReportData:
    """Rapor için toplanan tüm veriler."""

    # Program ve sürümü (chain-of-custody için: hangi araçla, hangi
    # sürümle alındığı raporda görünmesi gerekir)
    app_name: str = ""
    app_version: str = ""

    case_number: str = ""
    examiner: str = ""
    # Ek metadata (chain of custody) alanları
    evidence_number: str = ""
    location: str = ""
    incident_datetime: str = ""
    investigator_notes: str = ""

    target_host: str = ""
    os_type: str = ""
    device_path: str = ""
    image_type: str = ""  # disk | ram
    image_format: str = ""
    output_path: str = ""
    total_bytes: int = 0
    hashes: Dict[str, str] = field(default_factory=dict)
    source_hashes: Dict[str, str] = field(default_factory=dict)  # kaynak vs hedef karşılaştırma
    hash_verified: bool = False
    hash_verification_mode: str = "local-only"  # "local-only" | "source-vs-image" | "n/a"
    hash_computed_at: str = ""  # hash'lerin hesaplandığı an (UTC, ISO 8601)

    ntp_offset_seconds: float = 0.0
    ntp_reliable: bool = False
    ntp_server: str = ""
    signature_path: str = ""
    encryption_scheme: str = "none"
    hpa_present: bool = False
    dco_present: bool = False

    resumed: bool = False
    resumed_from_bytes: int = 0

    started_at: str = ""
    finished_at: str = ""
    session_id: str = ""

    # Targeted / bad-extension bulguları
    targeted_files_count: int = 0
    bad_extension_files: List[str] = field(default_factory=list)

    notes: List[str] = field(default_factory=list)


class Reporter:
    """Delil raporunu birden çok formatta üretir."""

    _WIDTH = 72

    # ------------------------------------------------------------------ TXT
    def generate_txt(self, data: ReportData, output_path: str) -> str:
        try:
            lines: List[str] = []
            lines.append("=" * self._WIDTH)
            lines.append("FORENSYNC IMAGER".center(self._WIDTH))
            lines.append("Adli Bilişim İmaj Alma Raporu".center(self._WIDTH))
            lines.append("=" * self._WIDTH)
            lines.append("")

            lines.extend(self._section("1. Vaka Bilgileri", [
                ("Program", data.app_name or "-"),
                ("Sürüm", data.app_version or "-"),
                ("Vaka No", data.case_number),
                ("Delil No", data.evidence_number),
                ("İnceleyen", data.examiner),
                ("Konum", data.location),
                ("Olay Tarihi/Saati", data.incident_datetime),
                ("Oturum ID", data.session_id),
                ("Başlangıç (UTC)", data.started_at),
                ("Bitiş (UTC)", data.finished_at),
                ("Rapor Tarihi (UTC)", datetime.now(timezone.utc).isoformat()),
            ]))

            lines.extend(self._section("2. Hedef Sistem", [
                ("Hedef Host", data.target_host),
                ("İşletim Sistemi", data.os_type),
                ("Cihaz", data.device_path),
                ("İmaj Tipi", data.image_type),
                ("Format", data.image_format),
                ("Şifreleme", data.encryption_scheme),
                ("HPA Mevcut", "Evet" if data.hpa_present else "Hayır"),
                ("DCO Mevcut", "Evet" if data.dco_present else "Hayır"),
            ]))

            imaj_rows = [
                ("Çıktı Dosyası", data.output_path),
                ("Toplam Boyut (bayt)", f"{data.total_bytes:,}"),
                ("Hash Doğrulama", "BAŞARILI" if data.hash_verified else "BAŞARISIZ/N/A"),
                ("Doğrulama Modu", data.hash_verification_mode),
                ("Hash Alınma Tarihi (UTC)", data.hash_computed_at or "-"),
                ("Devam ile Alındı", "Evet" if data.resumed else "Hayır"),
            ]
            if data.resumed:
                imaj_rows.append(
                    ("Devam Ofseti (bayt)", f"{data.resumed_from_bytes:,}")
                )
            lines.extend(self._section("3. İmaj ve Bütünlük", imaj_rows))
            if data.hashes:
                lines.append("  Yerel imaj hash'leri:")
                for algo, value in data.hashes.items():
                    lines.append(f"    {algo}: {value}")
            if data.source_hashes:
                lines.append("  Kaynak cihaz hash'leri:")
                for algo, value in data.source_hashes.items():
                    lines.append(f"    {algo}: {value}")
            lines.append("")

            lines.extend(self._section("4. Zaman Doğrulama (NTP)", [
                ("NTP Sunucu", data.ntp_server),
                ("Sapma (sn)", f"{data.ntp_offset_seconds:.3f}"),
                ("Güvenilir", "Evet" if data.ntp_reliable else "Hayır"),
            ]))

            lines.extend(self._section("5. Dijital İmza", [
                ("İmza Dosyası", data.signature_path or "Yok"),
            ]))

            if data.targeted_files_count or data.bad_extension_files:
                lines.append("6. Hedefli Tarama Bulguları")
                lines.append("-" * self._WIDTH)
                lines.append(f"  Toplam hedefli dosya: {data.targeted_files_count}")
                if data.bad_extension_files:
                    lines.append("  Uzantı-tür uyuşmazlığı olanlar:")
                    for f in data.bad_extension_files[:200]:
                        lines.append(f"    - {f}")
                    if len(data.bad_extension_files) > 200:
                        lines.append(
                            f"    ... ve {len(data.bad_extension_files) - 200} daha"
                        )
                lines.append("")

            if data.investigator_notes:
                lines.append("7. İnceleyici Notları")
                lines.append("-" * self._WIDTH)
                for ln in data.investigator_notes.splitlines():
                    lines.append(f"  {ln}")
                lines.append("")

            if data.notes:
                lines.append("8. Sistem Notları")
                lines.append("-" * self._WIDTH)
                for note in data.notes:
                    lines.append(f"  - {note}")
                lines.append("")

            with open(output_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            logger.info("Metin rapor üretildi: %s", output_path)
            return output_path
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="Reporter.generate_txt")
            raise

    # ------------------------------------------------------------------ JSON
    def generate_json(self, data: ReportData, output_path: str) -> str:
        payload = asdict(data)
        payload["report_generated_at"] = datetime.now(timezone.utc).isoformat()
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        logger.info("JSON rapor üretildi: %s", output_path)
        return output_path

    # ------------------------------------------------------------------ CSV
    def generate_csv(self, data: ReportData, output_path: str) -> str:
        # Anahtar / değer düzleştirilmiş CSV.
        rows = [("field", "value")]
        flat = self._flatten_dict(asdict(data))
        for k, v in flat.items():
            rows.append((k, str(v)))
        with open(output_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerows(rows)
        logger.info("CSV rapor üretildi: %s", output_path)
        return output_path

    # ------------------------------------------------------------------ XML
    def generate_xml(self, data: ReportData, output_path: str) -> str:
        root = ET.Element("YTIReport")
        root.set("generated_at", datetime.now(timezone.utc).isoformat())
        self._to_xml(root, asdict(data))
        tree = ET.ElementTree(root)
        try:
            ET.indent(tree, space="  ")
        except AttributeError:
            pass
        tree.write(output_path, encoding="utf-8", xml_declaration=True)
        logger.info("XML rapor üretildi: %s", output_path)
        return output_path

    # ------------------------------------------------------------------ HTML
    def generate_html(self, data: ReportData, output_path: str) -> str:
        buf = io.StringIO()
        esc = html_module.escape
        buf.write("<!doctype html><html lang='tr'><head><meta charset='utf-8'>")
        buf.write("<title>YTI Delil Raporu</title>")
        buf.write(
            "<style>body{font-family:Segoe UI,Inter,Arial,sans-serif;"
            "background:#F0F2F5;color:#1a2b3c;padding:24px}"
            "h1{color:#0A3A6C;border-bottom:2px solid #0A3A6C;padding-bottom:6px}"
            "h2{color:#0A3A6C;margin-top:24px}"
            "table{border-collapse:collapse;background:#fff;width:100%;"
            "box-shadow:0 1px 2px rgba(0,0,0,.06)}"
            "td,th{padding:8px 12px;border-bottom:1px solid #E5E7EB;"
            "vertical-align:top;text-align:left}"
            "th{background:#0A3A6C;color:#fff;font-weight:600}"
            ".hash{font-family:'JetBrains Mono',Menlo,Consolas,monospace;font-size:12px}"
            ".ok{color:#2E8B57;font-weight:600}"
            ".fail{color:#B00020;font-weight:600}"
            "</style></head><body>"
        )
        buf.write("<h1>ForenSync Imager — Delil Raporu</h1>")

        def _table(title: str, rows: List[tuple]) -> None:
            buf.write(f"<h2>{esc(title)}</h2><table><tbody>")
            for k, v in rows:
                buf.write(f"<tr><th style='width:220px'>{esc(str(k))}</th>")
                buf.write(f"<td>{esc(str(v))}</td></tr>")
            buf.write("</tbody></table>")

        _table("1. Vaka Bilgileri", [
            ("Program", data.app_name or "-"),
            ("Sürüm", data.app_version or "-"),
            ("Vaka No", data.case_number),
            ("Delil No", data.evidence_number),
            ("İnceleyen", data.examiner),
            ("Konum", data.location),
            ("Olay Tarihi/Saati", data.incident_datetime),
            ("Oturum ID", data.session_id),
            ("Başlangıç (UTC)", data.started_at),
            ("Bitiş (UTC)", data.finished_at),
        ])
        _table("2. Hedef Sistem", [
            ("Hedef Host", data.target_host),
            ("İşletim Sistemi", data.os_type),
            ("Cihaz", data.device_path),
            ("İmaj Tipi", data.image_type),
            ("Format", data.image_format),
            ("Şifreleme", data.encryption_scheme),
            ("HPA Mevcut", "Evet" if data.hpa_present else "Hayır"),
            ("DCO Mevcut", "Evet" if data.dco_present else "Hayır"),
        ])
        _table("3. İmaj ve Bütünlük", [
            ("Çıktı Dosyası", data.output_path),
            ("Toplam Boyut (bayt)", f"{data.total_bytes:,}"),
            ("Hash Doğrulama",
             '<span class="ok">BAŞARILI</span>' if data.hash_verified else
             '<span class="fail">BAŞARISIZ / N/A</span>'),
            ("Doğrulama Modu", data.hash_verification_mode),
            ("Hash Alınma Tarihi (UTC)", data.hash_computed_at or "-"),
            ("Devam ile Alındı", "Evet" if data.resumed else "Hayır"),
        ])
        if data.hashes:
            buf.write("<h2>Yerel imaj hash değerleri</h2><table><tbody>")
            for algo, value in data.hashes.items():
                buf.write(f"<tr><th>{esc(algo)}</th><td class='hash'>{esc(value)}</td></tr>")
            buf.write("</tbody></table>")
        if data.source_hashes:
            buf.write("<h2>Kaynak cihaz hash değerleri</h2><table><tbody>")
            for algo, value in data.source_hashes.items():
                buf.write(f"<tr><th>{esc(algo)}</th><td class='hash'>{esc(value)}</td></tr>")
            buf.write("</tbody></table>")
        _table("4. Zaman Doğrulama (NTP)", [
            ("NTP Sunucu", data.ntp_server),
            ("Sapma (sn)", f"{data.ntp_offset_seconds:.3f}"),
            ("Güvenilir", "Evet" if data.ntp_reliable else "Hayır"),
        ])
        _table("5. Dijital İmza", [("İmza Dosyası", data.signature_path or "Yok")])
        if data.investigator_notes:
            buf.write("<h2>İnceleyici Notları</h2>")
            buf.write(
                f"<div style='background:#fff;padding:12px;white-space:pre-wrap'>"
                f"{esc(data.investigator_notes)}</div>"
            )
        if data.notes:
            buf.write("<h2>Sistem Notları</h2><ul>")
            for note in data.notes:
                buf.write(f"<li>{esc(note)}</li>")
            buf.write("</ul>")
        buf.write("</body></html>")

        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(buf.getvalue())
        logger.info("HTML rapor üretildi: %s", output_path)
        return output_path

    # ------------------------------------------------------------------ PDF
    def generate_pdf(self, data: ReportData, output_path: str) -> str:
        """Reportlab kullanarak PDF raporu üretir."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:
            raise ImportError(
                "PDF üretimi için 'reportlab' gerekli. Kurulum: pip install reportlab"
            ) from exc

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "TitleYti", parent=styles["Title"],
            textColor=colors.HexColor("#0A3A6C"), spaceAfter=8,
        )
        h2 = ParagraphStyle(
            "H2Yti", parent=styles["Heading2"],
            textColor=colors.HexColor("#0A3A6C"),
        )
        mono = ParagraphStyle(
            "Mono", parent=styles["Code"], fontName="Courier", fontSize=8, leading=10,
        )
        doc = SimpleDocTemplate(
            output_path, pagesize=A4,
            leftMargin=18 * mm, rightMargin=18 * mm,
            topMargin=18 * mm, bottomMargin=18 * mm,
            title=f"IMAJER Delil Raporu - {data.case_number}",
        )
        story = []
        story.append(Paragraph("ForenSync <b>IMAJER</b>", title_style))
        story.append(Paragraph("Adli Bilişim İmaj Alma Raporu", styles["Heading3"]))
        story.append(Spacer(1, 6))

        def _table(rows):
            t = Table(rows, colWidths=[55 * mm, 115 * mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#0A3A6C")),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
                ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#F7FAFC")),
            ]))
            return t

        story.append(Paragraph("1. Vaka Bilgileri", h2))
        story.append(_table([
            ["Program", data.app_name or "-"],
            ["Sürüm", data.app_version or "-"],
            ["Vaka No", data.case_number or "-"],
            ["Delil No", data.evidence_number or "-"],
            ["İnceleyen", data.examiner or "-"],
            ["Konum", data.location or "-"],
            ["Olay Tarihi/Saati", data.incident_datetime or "-"],
            ["Oturum ID", data.session_id or "-"],
            ["Başlangıç (UTC)", data.started_at or "-"],
            ["Bitiş (UTC)", data.finished_at or "-"],
        ]))
        story.append(Spacer(1, 8))

        story.append(Paragraph("2. Hedef Sistem", h2))
        story.append(_table([
            ["Hedef Host", data.target_host or "-"],
            ["İşletim Sistemi", data.os_type or "-"],
            ["Cihaz", data.device_path or "-"],
            ["İmaj Tipi", data.image_type],
            ["Format", data.image_format],
            ["Şifreleme", data.encryption_scheme],
            ["HPA Mevcut", "Evet" if data.hpa_present else "Hayır"],
            ["DCO Mevcut", "Evet" if data.dco_present else "Hayır"],
        ]))
        story.append(Spacer(1, 8))

        story.append(Paragraph("3. İmaj ve Bütünlük", h2))
        integ_rows = [
            ["Çıktı Dosyası", data.output_path or "-"],
            ["Toplam Boyut (bayt)", f"{data.total_bytes:,}"],
            ["Hash Doğrulama", "BAŞARILI" if data.hash_verified else "BAŞARISIZ / N/A"],
            ["Doğrulama Modu", data.hash_verification_mode],
            ["Hash Alınma Tarihi (UTC)", data.hash_computed_at or "-"],
            ["Devam ile Alındı", "Evet" if data.resumed else "Hayır"],
        ]
        story.append(_table(integ_rows))
        if data.hashes:
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>Yerel imaj hash'leri</b>", styles["BodyText"]))
            for algo, value in data.hashes.items():
                story.append(Paragraph(f"<b>{algo}</b>: {value}", mono))
        if data.source_hashes:
            story.append(Spacer(1, 4))
            story.append(Paragraph("<b>Kaynak cihaz hash'leri</b>", styles["BodyText"]))
            for algo, value in data.source_hashes.items():
                story.append(Paragraph(f"<b>{algo}</b>: {value}", mono))
        story.append(Spacer(1, 8))

        story.append(Paragraph("4. Zaman Doğrulama (NTP)", h2))
        story.append(_table([
            ["NTP Sunucu", data.ntp_server or "-"],
            ["Sapma (sn)", f"{data.ntp_offset_seconds:.3f}"],
            ["Güvenilir", "Evet" if data.ntp_reliable else "Hayır"],
        ]))
        story.append(Spacer(1, 8))

        story.append(Paragraph("5. Dijital İmza", h2))
        story.append(_table([
            ["İmza Dosyası", data.signature_path or "Yok"],
        ]))

        if data.investigator_notes:
            story.append(Spacer(1, 8))
            story.append(Paragraph("6. İnceleyici Notları", h2))
            story.append(Paragraph(
                html_module.escape(data.investigator_notes).replace("\n", "<br/>"),
                styles["BodyText"],
            ))
        if data.notes:
            story.append(Spacer(1, 8))
            story.append(Paragraph("7. Sistem Notları", h2))
            for note in data.notes:
                story.append(Paragraph(f"• {html_module.escape(note)}", styles["BodyText"]))

        doc.build(story)
        logger.info("PDF rapor üretildi: %s", output_path)
        return output_path

    # ------------------------------------------------------------------ Multi
    def generate_multi(
        self,
        data: ReportData,
        base_path: str,
        formats: List[str],
    ) -> Dict[str, str]:
        """Birden çok formatta rapor üretir. ``base_path`` uzantısız olmalı.

        Returns:
            {"format": "path"} eşlemesi.
        """
        outputs: Dict[str, str] = {}
        errors: List[str] = []
        for fmt in formats:
            fmt = fmt.lower().strip()
            try:
                if fmt == "txt":
                    outputs["txt"] = self.generate_txt(data, base_path + ".txt")
                elif fmt == "pdf":
                    outputs["pdf"] = self.generate_pdf(data, base_path + ".pdf")
                elif fmt == "json":
                    outputs["json"] = self.generate_json(data, base_path + ".json")
                elif fmt == "html":
                    outputs["html"] = self.generate_html(data, base_path + ".html")
                elif fmt == "csv":
                    outputs["csv"] = self.generate_csv(data, base_path + ".csv")
                elif fmt == "xml":
                    outputs["xml"] = self.generate_xml(data, base_path + ".xml")
                else:
                    errors.append(f"Bilinmeyen format: {fmt}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fmt}: {exc}")
                logger.error("Rapor üretilemedi (%s): %s", fmt, exc)
        if errors:
            data.notes.append("Rapor üretim uyarıları: " + "; ".join(errors))
        return outputs

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _section(title: str, rows: List) -> List[str]:
        out = [title, "-" * Reporter._WIDTH]
        label_width = max((len(str(k)) for k, _ in rows), default=0) + 2
        for key, value in rows:
            out.append(f"{str(key) + ':':<{label_width}} {value}")
        out.append("")
        return out

    def _flatten_dict(self, d: dict, parent: str = "") -> Dict[str, str]:
        flat: Dict[str, str] = {}
        for k, v in d.items():
            key = f"{parent}.{k}" if parent else k
            if isinstance(v, dict):
                flat.update(self._flatten_dict(v, key))
            elif isinstance(v, (list, tuple)):
                flat[key] = "; ".join(str(x) for x in v)
            else:
                flat[key] = "" if v is None else str(v)
        return flat

    def _to_xml(self, parent: ET.Element, data) -> None:
        if isinstance(data, dict):
            for k, v in data.items():
                child = ET.SubElement(parent, str(k))
                self._to_xml(child, v)
        elif isinstance(data, (list, tuple)):
            for item in data:
                child = ET.SubElement(parent, "item")
                self._to_xml(child, item)
        else:
            parent.text = "" if data is None else str(data)
