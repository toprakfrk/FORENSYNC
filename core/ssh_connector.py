"""SSH bağlantı yöneticisi (paramiko tabanlı).

Hedefe gönderilen her komut, çalıştırılmadan önce paylaşılan
``WriteBlocker`` nesnesi ile doğrulanır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import paramiko

from core.error_handler import ConnectionError_, log_exception
from core.write_blocker import WriteBlocker
from logs.logger import get_logger

logger = get_logger("ssh_connector")


@dataclass
class SSHCredentials:
    """SSH bağlantı bilgileri."""

    host: str
    port: int = 22
    username: str = "root"
    password: Optional[str] = None
    key_path: Optional[str] = None
    timeout: int = 30


class SSHConnector:
    """Uzak sunucuya SSH bağlantısı kurar ve salt-okunur komut çalıştırır."""

    def __init__(self, write_blocker: WriteBlocker) -> None:
        self._client: Optional[paramiko.SSHClient] = None
        self._creds: Optional[SSHCredentials] = None
        self.write_blocker = write_blocker

    @property
    def is_connected(self) -> bool:
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return bool(transport and transport.is_active())

    def connect(self, creds: SSHCredentials) -> None:
        """Bağlantıyı kurar.

        Raises:
            ConnectionError_: Bağlantı kurulamazsa.
        """
        self._creds = creds
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            logger.info("SSH bağlanılıyor: %s@%s:%d", creds.username, creds.host, creds.port)
            client.connect(
                hostname=creds.host,
                port=creds.port,
                username=creds.username,
                password=creds.password,
                key_filename=creds.key_path,
                timeout=creds.timeout,
                allow_agent=False,
                look_for_keys=bool(creds.key_path),
            )
            self._client = client
            # Keepalive: NAT/firewall arkasındaki bağlantılarda, uzak
            # tarafta biraz uzun süren bir komut çalışırken (örn. Windows
            # WMIC/PowerShell sorguları) SSH kanalında görünür veri akışı
            # olmaz — bazı ağ cihazları bu durumu "boşta bağlantı" sanıp
            # kapatır (WinError 10054 / "connection reset"). Düzenli
            # keepalive paketleri bunu önler.
            transport = client.get_transport()
            if transport is not None:
                transport.set_keepalive(15)
                # Disk/RAM imajı gibi uzun akışlarda paramiko belirli
                # aralıklarla SSH anahtarını yeniler (varsayılan: 1 GB veya
                # 3600 saniye). Bu yenileme sırasında veri akışı duruyor ve
                # karşı taraf cevap vermekte gecikince "Key-exchange timed out"
                # hatası alınıyor. Aktarım süresince yenilemenin tetiklenmemesi
                # için eşikleri pratikte ulaşılamaz değerlere çekiyoruz.
                transport.packetizer.REKEY_BYTES = pow(2, 40)  # 1 TB
                transport.packetizer.REKEY_TIME = pow(2, 32)   # ~136 yıl
            logger.info("SSH bağlantısı başarılı: %s", creds.host)
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="SSHConnector.connect")
            raise ConnectionError_(f"SSH bağlantısı kurulamadı: {exc}") from exc

    def _reconnect(self) -> bool:
        """Mevcut kimlik bilgileriyle bağlantıyı sessizce yeniden kurmayı
        dener (yalnızca salt-okunur komut tekrarı için kullanılır — akış/
        stream okumaları bunu kullanmaz, orada resume mantığı geçerlidir).
        """
        if self._creds is None:
            return False
        try:
            logger.warning(
                "SSH bağlantısı koptu, yeniden bağlanılıyor: %s", self._creds.host
            )
            self.connect(self._creds)
            return True
        except ConnectionError_ as exc:
            logger.error("Yeniden bağlanma başarısız: %s", exc)
            return False

    def exec_command(
        self, command: str, timeout: Optional[int] = None, _retry: bool = True,
    ) -> Tuple[str, str, int]:
        """Salt-okunur komut çalıştırır (WriteBlocker doğrulamasından sonra).
        Bağlantı, komut sırasında ağ tarafından koparılırsa (örn. WinError
        10054 / "connection reset"), bir kez yeniden bağlanılıp komut
        otomatik olarak tekrar denenir.

        Returns:
            (stdout, stderr, exit_status)
        """
        if not self.is_connected or self._client is None:
            if _retry and self._reconnect():
                return self.exec_command(command, timeout=timeout, _retry=False)
            raise ConnectionError_("SSH bağlantısı aktif değil.")

        # Write Blocker zorunlu doğrulama.
        safe_command = self.write_blocker.verify_command(command)

        logger.debug("Komut çalıştırılıyor: %s", safe_command)
        try:
            stdin, stdout, stderr = self._client.exec_command(safe_command, timeout=timeout)
            stdin.close()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            code = stdout.channel.recv_exit_status()
            if code != 0:
                logger.warning("Komut sıfırdan farklı çıkış kodu (%d): %s", code, safe_command)
            return out, err, code
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="SSHConnector.exec_command")
            if _retry and self._reconnect():
                logger.info("Yeniden bağlanıldı, komut tekrar deneniyor: %s", safe_command)
                return self.exec_command(command, timeout=timeout, _retry=False)
            raise ConnectionError_(f"Komut çalıştırılamadı: {exc}") from exc

    def open_read_stream(self, remote_command: str):
        """İmaj verisini stream olarak okumak için stdout channel döndürür.

        WriteBlocker doğrulamasından geçirilir. Büyük veriyi belleğe
        yüklemeden akış halinde okumak için kullanılır.
        """
        if not self.is_connected or self._client is None:
            raise ConnectionError_("SSH bağlantısı aktif değil.")
        safe_command = self.write_blocker.verify_command(remote_command)
        logger.debug("Akış komutu açılıyor: %s", safe_command)
        stdin, stdout, stderr = self._client.exec_command(safe_command)
        stdin.close()
        return stdout, stderr

    def close(self) -> None:
        """Bağlantıyı güvenli şekilde kapatır."""
        if self._client is not None:
            try:
                self._client.close()
                logger.info("SSH bağlantısı kapatıldı.")
            except Exception as exc:  # noqa: BLE001
                log_exception(exc, context="SSHConnector.close")
            finally:
                self._client = None