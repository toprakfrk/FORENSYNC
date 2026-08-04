"""Şifreleme tespit modülü.

Uzak diskteki şifreleme (LUKS / BitLocker) durumunu SALT-OKUNUR komutlarla
tespit eder. Hiçbir kilit açma / format işlemi yapmaz. Komutlar
WriteBlocker'dan geçer.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.os_detector import OSType
from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("crypto_handler")


@dataclass
class EncryptionStatus:
    """Şifreleme tespit sonucu."""

    encrypted: bool
    scheme: str = "none"  # luks | bitlocker | none
    detail: str = ""


class CryptoHandler:
    """Uzak diskte şifreleme olup olmadığını salt-okunur tespit eder."""

    def __init__(self, ssh: SSHConnector, os_type: OSType = OSType.LINUX) -> None:
        self.ssh = ssh
        self.os_type = os_type

    def detect(self, device_path: str) -> EncryptionStatus:
        """Verilen cihazda şifreleme durumunu tespit eder."""
        if self.os_type == OSType.WINDOWS:
            return self._detect_bitlocker(device_path)
        return self._detect_luks(device_path)

    def _detect_luks(self, device_path: str) -> EncryptionStatus:
        out, _, code = self.ssh.exec_command(f"sudo -n cryptsetup isLuks {device_path}")
        if code == 0:
            status_out, _, _ = self.ssh.exec_command(f"sudo -n cryptsetup status {device_path}")
            logger.info("LUKS şifreleme tespit edildi: %s", device_path)
            return EncryptionStatus(encrypted=True, scheme="luks", detail=status_out.strip())
        logger.info("LUKS tespit edilmedi: %s", device_path)
        return EncryptionStatus(encrypted=False, scheme="none")

    def _detect_bitlocker(self, device_path: str) -> EncryptionStatus:
        out, _, code = self.ssh.exec_command(f"manage-bde -status {device_path}")
        if code == 0 and "Protection On" in out:
            logger.info("BitLocker (Protection On) tespit edildi: %s", device_path)
            return EncryptionStatus(encrypted=True, scheme="bitlocker", detail=out.strip())
        logger.info("BitLocker tespit edilmedi/kapalı: %s", device_path)
        return EncryptionStatus(encrypted=False, scheme="none", detail=out.strip())
