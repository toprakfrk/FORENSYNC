"""NTP zaman doğrulama modülü.

Adli bilişim raporunun zaman damgalarının güvenilir olması için sistem
saatini bir NTP sunucusuyla karşılaştırır ve sapmayı (offset) raporlar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

import ntplib

from core.error_handler import log_exception
from logs.logger import get_logger

logger = get_logger("ntp_verifier")

DEFAULT_NTP_SERVERS: List[str] = [
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
]


@dataclass
class NTPResult:
    """NTP doğrulama sonucu."""

    server: str
    ntp_time_utc: str
    local_time_utc: str
    offset_seconds: float
    reliable: bool


class NTPVerifier:
    """Yerel saati NTP sunucusuyla karşılaştırır."""

    def __init__(self, servers: List[str] | None = None, tolerance_seconds: float = 2.0) -> None:
        self.servers = servers or DEFAULT_NTP_SERVERS
        self.tolerance_seconds = tolerance_seconds
        self._client = ntplib.NTPClient()

    def verify(self) -> NTPResult:
        """İlk erişilebilen NTP sunucusuyla saat sapmasını doğrular."""
        last_error: Exception | None = None
        for server in self.servers:
            try:
                response = self._client.request(server, version=3, timeout=5)
                ntp_dt = datetime.fromtimestamp(response.tx_time, tz=timezone.utc)
                local_dt = datetime.now(timezone.utc)
                offset = float(response.offset)
                reliable = abs(offset) <= self.tolerance_seconds
                logger.info(
                    "NTP doğrulama (%s): offset=%.3fs güvenilir=%s", server, offset, reliable
                )
                return NTPResult(
                    server=server,
                    ntp_time_utc=ntp_dt.isoformat(),
                    local_time_utc=local_dt.isoformat(),
                    offset_seconds=offset,
                    reliable=reliable,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("NTP sunucusuna ulaşılamadı (%s): %s", server, exc)

        if last_error is not None:
            log_exception(last_error, context="NTPVerifier.verify")
        local_dt = datetime.now(timezone.utc)
        return NTPResult(
            server="N/A",
            ntp_time_utc="",
            local_time_utc=local_dt.isoformat(),
            offset_seconds=0.0,
            reliable=False,
        )
