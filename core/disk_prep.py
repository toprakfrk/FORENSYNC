"""Yerel hedef disk hazırlama modülü.

İmajın yazılacağı YEREL hedef alanını hazırlar (klasör oluşturma, boş alan
kontrolü). Uzak hedefe (delil kaynağına) asla dokunmaz. Uzak sistemde
yalnızca salt-okunur alan sorgusu yapar.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Optional

from core.error_handler import AcquisitionError, log_exception
from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("disk_prep")


@dataclass
class SpaceInfo:
    """Alan bilgisi (bayt)."""

    total: int
    used: int
    free: int


class DiskPrep:
    """Yerel imaj hedefini hazırlar ve alan yeterliliğini kontrol eder."""

    def __init__(self, ssh: Optional[SSHConnector] = None) -> None:
        self.ssh = ssh

    def ensure_local_dir(self, path: str) -> str:
        """İmaj çıktısı için yerel klasörü hazırlar."""
        directory = os.path.dirname(os.path.abspath(path))
        try:
            os.makedirs(directory, exist_ok=True)
            logger.info("Yerel hedef klasör hazır: %s", directory)
            return directory
        except OSError as exc:
            log_exception(exc, context="DiskPrep.ensure_local_dir")
            raise AcquisitionError(f"Yerel klasör oluşturulamadı: {exc}") from exc

    def local_free_space(self, path: str) -> SpaceInfo:
        """Yerel hedefteki boş alanı döndürür."""
        directory = os.path.dirname(os.path.abspath(path)) or "."
        usage = shutil.disk_usage(directory)
        info = SpaceInfo(total=usage.total, used=usage.used, free=usage.free)
        logger.info("Yerel boş alan: %d bayt", info.free)
        return info

    def check_space(self, output_path: str, required_bytes: int) -> bool:
        """İmaj için yeterli yerel alan olup olmadığını kontrol eder."""
        info = self.local_free_space(output_path)
        enough = info.free >= required_bytes
        if not enough:
            logger.error(
                "Yetersiz yerel alan: gerekli=%d, mevcut=%d", required_bytes, info.free
            )
        return enough
