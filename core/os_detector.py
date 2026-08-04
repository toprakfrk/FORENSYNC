"""Ortak işletim sistemi tespit modülü.

Uzak sistemin Linux mı Windows mı olduğunu SSH üzerinden tespit eder.
SSH komutu gönderdiği için paylaşılan WriteBlocker kapsamındadır.
"""

from __future__ import annotations

from enum import Enum

from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("os_detector")


class OSType(str, Enum):
    """Desteklenen işletim sistemi tipleri."""

    LINUX = "linux"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


class OSDetector:
    """SSH bağlantısı üzerinden hedef OS tespiti yapar."""

    def __init__(self, ssh: SSHConnector) -> None:
        self.ssh = ssh

    def detect(self) -> OSType:
        """Hedef işletim sistemini tespit eder."""
        # Önce POSIX uname denemesi.
        out, _, code = self.ssh.exec_command("uname -s")
        if code == 0 and out.strip():
            value = out.strip().lower()
            if "linux" in value:
                logger.info("OS tespit edildi: Linux (%s)", value)
                return OSType.LINUX
            if "darwin" in value or "bsd" in value:
                logger.info("OS tespit edildi: POSIX (%s) -> Linux akışı", value)
                return OSType.LINUX

        # Windows denemesi (PowerShell).
        out, _, code = self.ssh.exec_command(
            'powershell -NoProfile -Command "(Get-CimInstance Win32_OperatingSystem).Caption"'
        )
        if code == 0 and out.strip():
            logger.info("OS tespit edildi: Windows (%s)", out.strip())
            return OSType.WINDOWS

        # systeminfo yedeği.
        out, _, code = self.ssh.exec_command("systeminfo")
        if code == 0 and "Windows" in out:
            logger.info("OS tespit edildi: Windows (systeminfo)")
            return OSType.WINDOWS

        logger.warning("OS tespit edilemedi.")
        return OSType.UNKNOWN
