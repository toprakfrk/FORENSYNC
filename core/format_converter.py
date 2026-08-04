"""Format donusturme modulu.

Ham (raw/dd) imaji adli bilisim standardi formatlara donusturur:
E01 (EWF, libewf/ewfacquire) ve AFF (afflib/affconvert). Sistem
bagimliliklari kurulu degilse anlamli bir hata firlatir.

v3 notu: Windows icin ewfacquire.exe artik proje icine bundled olarak
gelir (resources/win/ewfacquire.exe). Once bundled binary aranir,
bulunamazsa sistem PATH'inde aranir (Linux/macOS icin apt/brew ile
kurulan surum).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

from core.error_handler import AcquisitionError, log_exception
from logs.logger import get_logger

logger = get_logger("format_converter")


class ImageFormat(str, Enum):
    """Desteklenen imaj formatlari."""

    RAW = "raw"
    E01 = "e01"
    AFF = "aff"


@dataclass
class ConversionResult:
    """Format donusturme sonucu."""

    output_path: str
    fmt: ImageFormat
    completed: bool = False
    tool: str = ""
    stdout: str = ""
    stderr: str = ""


def _get_bundled_ewfacquire() -> Optional[str]:
    """Proje icine gomulu (bundled) ewfacquire.exe yolunu dondurur (yalnizca Windows).

    Gelistirme ortaminda: <proje_kok>/resources/win/ewfacquire.exe
    PyInstaller ile paketlenmis halde: sys._MEIPASS/resources/win/ewfacquire.exe
    """
    if platform.system() != "Windows":
        return None

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
    else:
        # Bu dosya core/format_converter.py -> proje kokune bir ust dizin
        base = Path(__file__).resolve().parent.parent

    candidate = base / "resources" / "win" / "ewfacquire.exe"
    if candidate.exists():
        return str(candidate)
    return None


def resolve_ewfacquire_path() -> Optional[str]:
    """ewfacquire binary yolunu cozer: once bundled, sonra sistem PATH."""
    bundled = _get_bundled_ewfacquire()
    if bundled:
        return bundled
    return shutil.which("ewfacquire")


class FormatConverter:
    """Ham imaji hedef formata donusturur."""

    # Subprocess icin maksimum bekleme suresi (saniye).
    # 0 = sinirsiz.
    DEFAULT_TIMEOUT = 0

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT) -> None:
        self.timeout_seconds = timeout_seconds if timeout_seconds > 0 else None

    def available_formats(self) -> List[ImageFormat]:
        """Sistemde kullanilabilir donusturme formatlarini dondurur."""
        formats = [ImageFormat.RAW]

        if resolve_ewfacquire_path():
            formats.append(ImageFormat.E01)

        if shutil.which("affconvert"):
            formats.append(ImageFormat.AFF)

        logger.info("Kullanilabilir formatlar: %s", [f.value for f in formats])
        return formats

    def convert(
        self,
        source_raw: str,
        target_format: ImageFormat,
        output_path: str,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
        case_number: str = "",
        examiner: str = "",
        evidence_number: str = "",
        notes: str = "",
    ) -> ConversionResult:
        """Ham imaji hedef formata donusturur."""
        if not os.path.exists(source_raw):
            raise AcquisitionError(f"Kaynak imaj bulunamadi: {source_raw}")

        try:
            if target_format == ImageFormat.RAW:
                result = ConversionResult(output_path=output_path, fmt=target_format, tool="copy")
                if source_raw != output_path:
                    shutil.copyfile(source_raw, output_path)
                result.completed = True
                return result

            if target_format == ImageFormat.E01:
                return self._convert_e01(
                    source_raw, output_path,
                    case_number=case_number, examiner=examiner,
                    evidence_number=evidence_number, notes=notes,
                )

            if target_format == ImageFormat.AFF:
                return self._convert_aff(source_raw, output_path)

            raise AcquisitionError(f"Bilinmeyen format: {target_format}")
        except AcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="FormatConverter.convert")
            raise AcquisitionError(f"Format donusturme basarisiz: {exc}") from exc

    # --- Ortak subprocess yurutme ------------------------------------------
    def _run(self, cmd: List[str], tool_name: str) -> tuple[int, str, str]:
        logger.info("[%s] calistiriliyor: %s", tool_name, " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise AcquisitionError(f"{tool_name} sistemde bulunamadi: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AcquisitionError(f"{tool_name} zaman asimina ugradi.") from exc
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )

    # --- E01 (libewf / ewfacquire) -----------------------------------------
    def _convert_e01(
        self,
        source_raw: str,
        output_path: str,
        case_number: str = "",
        examiner: str = "",
        evidence_number: str = "",
        notes: str = "",
    ) -> ConversionResult:
        ewfacquire_path = resolve_ewfacquire_path()
        if not ewfacquire_path:
            raise AcquisitionError(
                "E01 donusumu icin 'ewfacquire' (libewf) bulunamadi. "
                "Kurulum: Debian/Ubuntu 'apt install ewf-tools', macOS 'brew install libewf', "
                "Windows icin resources/win/ewfacquire.exe projeye gomulu olmali."
            )

        logger.info("ewfacquire kullaniliyor: %s", ewfacquire_path)

        # ewfacquire cikti yolundan .e01 uzantisini kaldirir (kendisi ekler).
        base = output_path
        if base.lower().endswith(".e01"):
            base = base[:-4]

        cmd = [
            ewfacquire_path,
            "-t", base,                       # target base
            "-f", "encase6",                  # E01 formati
            "-c", "best",                     # sikistirma
            "-b", "64",                       # bytes per sector chunk
            "-S", "1610612736",               # segment (1.5 GiB, bayt cinsinden duz sayi)
            "-u",                             # unattended
            "-C", case_number or "N/A",
            "-D", notes or "N/A",             # description
            "-E", evidence_number or "N/A",
            "-e", examiner or "N/A",
            "-M", "logical",                  # media type
            source_raw,
        ]

        code, out, err = self._run(cmd, "ewfacquire")
        result = ConversionResult(
            output_path=f"{base}.E01",
            fmt=ImageFormat.E01,
            tool="ewfacquire",
            stdout=out,
            stderr=err,
        )
        if code != 0:
            raise AcquisitionError(
                f"ewfacquire basarisiz (kod {code}): {err.strip() or out.strip()}"
            )
        result.completed = True
        logger.info("E01 donusumu tamamlandi: %s", result.output_path)
        return result

    # --- AFF (afflib / affconvert) -----------------------------------------
    def _convert_aff(self, source_raw: str, output_path: str) -> ConversionResult:
        if not shutil.which("affconvert"):
            raise AcquisitionError(
                "AFF donusumu icin 'affconvert' (afflib) sistemde bulunamadi. "
                "Kurulum: Debian/Ubuntu 'apt install afflib-tools'."
            )

        cmd = ["affconvert", "-o", output_path, source_raw]
        code, out, err = self._run(cmd, "affconvert")
        result = ConversionResult(
            output_path=output_path,
            fmt=ImageFormat.AFF,
            tool="affconvert",
            stdout=out,
            stderr=err,
        )
        if code != 0:
            raise AcquisitionError(
                f"affconvert basarisiz (kod {code}): {err.strip() or out.strip()}"
            )
        result.completed = True
        logger.info("AFF donusumu tamamlandi: %s", result.output_path)
        return result
