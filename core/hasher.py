"""Hash hesaplama modülü.

İmaj dosyalarının bütünlüğünü doğrulamak için MD5/SHA1/SHA256/SHA512/
BLAKE2b/SHA3-256 hesaplar. Uzak (SSH) ve yerel dosyalar için hash
hesaplayabilir; iki hash'i karşılaştırır.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional

from core.error_handler import VerificationError, log_exception
from core.os_detector import OSType
from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("hasher")

SUPPORTED_ALGORITHMS: List[str] = [
    "md5", "sha1", "sha256", "sha512", "blake2b", "sha3_256",
]

_REMOTE_HASH_TOOLS_LINUX: Dict[str, str] = {
    "md5": "md5sum",
    "sha1": "sha1sum",
    "sha256": "sha256sum",
    "sha512": "sha512sum",
    "blake2b": "b2sum",
    "sha3_256": "sha3sum -a 256",
}

# Windows certutil algoritma isimleri.
_REMOTE_HASH_TOOLS_WIN: Dict[str, str] = {
    "md5": "MD5",
    "sha1": "SHA1",
    "sha256": "SHA256",
    "sha512": "SHA512",
}


class Hasher:
    """Yerel ve uzak dosya hash'lerini hesaplar ve karşılaştırır."""

    def __init__(
        self,
        ssh: Optional[SSHConnector] = None,
        os_type: OSType = OSType.LINUX,
    ) -> None:
        self.ssh = ssh
        self.os_type = os_type

    def hash_local_file(
        self,
        path: str,
        algorithm: str = "sha256",
        chunk_size: int = 4 * 1024 * 1024,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Yerel bir dosyanın hash'ini hesaplar."""
        algorithm = algorithm.lower()
        if algorithm not in SUPPORTED_ALGORITHMS:
            raise VerificationError(f"Desteklenmeyen algoritma: {algorithm}")

        digest = hashlib.new(algorithm)
        read_bytes = 0
        try:
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    read_bytes += len(chunk)
                    if progress_callback is not None:
                        progress_callback(read_bytes)
            result = digest.hexdigest()
            logger.info("Yerel hash (%s) %s = %s", algorithm, path, result)
            return result
        except OSError as exc:
            log_exception(exc, context="Hasher.hash_local_file")
            raise VerificationError(f"Yerel dosya hash'lenemedi: {exc}") from exc

    def hash_remote_file(self, remote_path: str, algorithm: str = "sha256") -> str:
        """Uzak (SSH) dosyanın hash'ini hedefte hesaplatır."""
        algorithm = algorithm.lower()
        if algorithm not in SUPPORTED_ALGORITHMS:
            raise VerificationError(f"Desteklenmeyen algoritma: {algorithm}")
        if self.ssh is None:
            raise VerificationError("Uzak hash için SSH bağlantısı gerekli.")

        if self.os_type == OSType.WINDOWS:
            algo_upper = _REMOTE_HASH_TOOLS_WIN.get(algorithm)
            if algo_upper is None:
                raise VerificationError(
                    f"Windows hedeflerinde {algorithm} desteklenmiyor (certutil)."
                )
            cmd = f'certutil -hashfile "{remote_path}" {algo_upper}'
            out, err, code = self.ssh.exec_command(cmd)
            if code != 0 or not out.strip():
                raise VerificationError(f"Uzak (Windows) hash hesaplanamadı: {err.strip()}")
            # certutil çıktısı:
            #   MD5 hash of file X:
            #   abcdef1234...
            #   CertUtil: -hashfile command completed successfully.
            for line in out.splitlines():
                line_l = line.strip().lower()
                if not line_l or ":" in line_l or "certutil" in line_l:
                    continue
                if all(c in "0123456789abcdef" for c in line.strip().replace(" ", "").lower()):
                    remote_hash = line.strip().replace(" ", "")
                    logger.info(
                        "Uzak hash (%s) %s = %s", algorithm, remote_path, remote_hash
                    )
                    return remote_hash
            raise VerificationError("Uzak (Windows) hash çıktısı çözümlenemedi.")

        # Linux/POSIX
        tool = _REMOTE_HASH_TOOLS_LINUX.get(algorithm)
        if tool is None:
            raise VerificationError(f"Linux hedeflerinde {algorithm} desteklenmiyor.")
        out, err, code = self.ssh.exec_command(f"{tool} {remote_path}")
        if code != 0 or not out.strip():
            raise VerificationError(f"Uzak hash hesaplanamadı: {err.strip()}")
        remote_hash = out.strip().split()[0]
        logger.info("Uzak hash (%s) %s = %s", algorithm, remote_path, remote_hash)
        return remote_hash

    def hash_remote_device(
        self,
        device_path: str,
        algorithm: str = "sha256",
    ) -> str:
        """Uzak bir blok cihazının tamamının hash'ini SSH üzerinden hesaplatır.

        dd if=DEVICE | shaXsum şeklinde stream'ler; büyük diskler için uzun
        sürebileceğinden kullanıcıya opsiyonel bırakılmalıdır.
        """
        algorithm = algorithm.lower()
        if algorithm not in SUPPORTED_ALGORITHMS:
            raise VerificationError(f"Desteklenmeyen algoritma: {algorithm}")
        if self.ssh is None:
            raise VerificationError("Uzak hash için SSH bağlantısı gerekli.")
        if self.os_type == OSType.WINDOWS:
            raise VerificationError(
                "Uzak Windows cihazlarının canlı hash'i şu an desteklenmiyor."
            )

        tool = _REMOTE_HASH_TOOLS_LINUX.get(algorithm)
        if tool is None:
            raise VerificationError(f"Cihaz hash'i için {algorithm} desteklenmiyor.")

        # dd blok cihazı okuyup pipe eder; whitelist "dd if=" ile başlıyor.
        cmd = f"sudo -n dd if={device_path} bs=4M status=none | {tool}"
        out, err, code = self.ssh.exec_command(cmd, timeout=None)
        if code != 0 or not out.strip():
            raise VerificationError(f"Cihaz hash'i hesaplanamadı: {err.strip()}")
        remote_hash = out.strip().split()[0]
        logger.info("Cihaz hash (%s) %s = %s", algorithm, device_path, remote_hash)
        return remote_hash

    @staticmethod
    def compare(hash_a: str, hash_b: str) -> bool:
        """İki hash'i büyük/küçük harf duyarsız karşılaştırır."""
        equal = hash_a.strip().lower() == hash_b.strip().lower()
        if equal:
            logger.info("Hash karşılaştırması EŞLEŞTİ.")
        else:
            logger.error("Hash karşılaştırması UYUŞMADI: %s != %s", hash_a, hash_b)
        return equal
