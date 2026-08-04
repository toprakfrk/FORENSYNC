"""Dijital imzalama modülü.

İmaj ve rapor dosyalarının bütünlüğünü ve kaynağını kanıtlamak için
RSA özel anahtarı ile dijital imza üretir ve doğrular. Anahtar çifti
yoksa üretebilir. Özel anahtar ASLA repoya eklenmemelidir (.gitignore).
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils as asym_utils

from core.error_handler import ConfigurationError, log_exception
from logs.logger import get_logger

logger = get_logger("digital_signer")


class DigitalSigner:
    """RSA tabanlı dosya imzalama / doğrulama."""

    def __init__(self, private_key_path: Optional[str] = None,
                 public_key_path: Optional[str] = None) -> None:
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path

    def generate_keypair(self, private_key_path: str, public_key_path: str,
                         key_size: int = 4096) -> Tuple[str, str]:
        """Yeni bir RSA anahtar çifti üretir ve diske yazar."""
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        priv_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        os.makedirs(os.path.dirname(os.path.abspath(private_key_path)), exist_ok=True)
        with open(private_key_path, "wb") as fh:
            fh.write(priv_bytes)
        with open(public_key_path, "wb") as fh:
            fh.write(pub_bytes)
        self.private_key_path = private_key_path
        self.public_key_path = public_key_path
        logger.info("RSA anahtar çifti üretildi (%d bit).", key_size)
        return private_key_path, public_key_path

    def sign_file(self, file_path: str, signature_path: Optional[str] = None) -> str:
        """Dosyayı imzalar ve imza dosyasının yolunu döndürür."""
        if not self.private_key_path:
            raise ConfigurationError(
                "İmzalama için private_key_path gerekli (None). Önce generate_keypair çağırın."
            )
        try:
            with open(self.private_key_path, "rb") as fh:
                private_key = serialization.load_pem_private_key(fh.read(), password=None)

            digest = hashes.Hash(hashes.SHA256())
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                    digest.update(chunk)
            file_hash = digest.finalize()

            signature = private_key.sign(  # type: ignore[union-attr]
                file_hash,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.MAX_LENGTH),
                asym_utils.Prehashed(hashes.SHA256()),
            )
            signature_path = signature_path or f"{file_path}.sig"
            with open(signature_path, "wb") as fh:
                fh.write(signature)
            logger.info("Dosya imzalandı: %s -> %s", file_path, signature_path)
            return signature_path
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="DigitalSigner.sign_file")
            raise ConfigurationError(f"İmzalama başarısız: {exc}") from exc

    def verify_file(self, file_path: str, signature_path: str,
                    public_key_path: Optional[str] = None) -> bool:
        """İmzayı verilen açık anahtarla doğrular."""
        public_key_path = public_key_path or self.public_key_path
        if not public_key_path:
            raise ConfigurationError("Doğrulama için public_key_path gerekli.")
        try:
            with open(public_key_path, "rb") as fh:
                public_key = serialization.load_pem_public_key(fh.read())
            with open(signature_path, "rb") as fh:
                signature = fh.read()

            digest = hashes.Hash(hashes.SHA256())
            with open(file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                    digest.update(chunk)
            file_hash = digest.finalize()

            public_key.verify(  # type: ignore[union-attr]
                signature,
                file_hash,
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                            salt_length=padding.PSS.MAX_LENGTH),
                asym_utils.Prehashed(hashes.SHA256()),
            )
            logger.info("İmza doğrulandı: %s", file_path)
            return True
        except InvalidSignature:
            logger.error("İmza GEÇERSİZ: %s", file_path)
            return False
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="DigitalSigner.verify_file")
            return False
