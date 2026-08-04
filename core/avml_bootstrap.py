"""AVML geçici kurulum (bootstrap) modülü.

Yalnızca RAM edinimi sırasında, uzak sistemde AVML PATH'te bulunamazsa
``RamImager`` tarafından çağrılır. AVML'nin resmi GitHub Releases
derlemesini geçici olarak ``/tmp/yti_avml`` yoluna indirir ve
çalıştırılabilir yapar.

Önemli:
- Bu kurulum KALICI DEĞİLDİR. RAM imajı tamamlandığında (başarılı ya da
  hatalı bitse de) ``RamImager._cleanup_remote_temp`` bu dosyayı SİLER.
- Bu modül yalnızca RAM edinim akışından çağrılır; disk imajlama akışı
  (``disk_imager.py`` / ``_acquire_disk``) bu modülü hiçbir zaman
  import etmez veya çağırmaz. Disk tarafında hedef sisteme yazma
  amaçlı hiçbir istisna yoktur.
- ``core/write_blocker.py`` içindeki ``_RAM_BOOTSTRAP_PATTERNS`` yalnızca
  bu modülün ürettiği tam komut string'leriyle eşleşir (sabit dosya
  yolu: /tmp/yti_avml). Başka hiçbir chmod/curl/wget komutuna izin
  verilmez.
"""

from __future__ import annotations

from core.error_handler import AcquisitionError, log_exception
from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("avml_bootstrap")

# WriteBlocker'daki _RAM_BOOTSTRAP_PATTERNS ile birebir eşleşmesi gereken
# sabit geçici yol. RamImager._REMOTE_AVML_TMP ile de aynı olmalıdır.
REMOTE_AVML_PATH = "/tmp/yti_avml"

_AVML_RELEASE_URL = "https://github.com/microsoft/avml/releases/latest/download/avml"


def bootstrap_avml(ssh: SSHConnector) -> str:
    """Uzak sisteme AVML'yi geçici olarak indirir ve çalıştırılabilir yapar.

    Yalnızca RAM edinim akışından, AVML PATH'te bulunamadığında çağrılır.
    Kalıcı bir kurulum YAPMAZ: dosya sabit olarak ``/tmp/yti_avml``
    altına iner; imaj tamamlandığında çağıran taraf (RamImager) bu
    dosyayı siler.

    Returns:
        Uzak sistemdeki geçici AVML yolu (``/tmp/yti_avml``).

    Raises:
        AcquisitionError: indirme aracı bulunamazsa, indirme başarısız
            olursa veya çalıştırılabilir yapılamazsa.
    """
    logger.info("AVML uzak sistemde bulunamadı; geçici kurulum başlıyor (%s).", REMOTE_AVML_PATH)

    try:
        out, _, code = ssh.exec_command("command -v curl")
        has_curl = code == 0 and out.strip() != ""

        if has_curl:
            dl_cmd = f"curl -fsSL {_AVML_RELEASE_URL} -o {REMOTE_AVML_PATH}"
        else:
            out, _, code = ssh.exec_command("command -v wget")
            has_wget = code == 0 and out.strip() != ""
            if not has_wget:
                raise AcquisitionError(
                    "Uzak sistemde AVML yok ve indirme için curl/wget de "
                    "bulunamadı. Lütfen AVML'yi ana bilgisayara elle kurun: "
                    "https://github.com/microsoft/avml/releases"
                )
            dl_cmd = f"wget -q {_AVML_RELEASE_URL} -O {REMOTE_AVML_PATH}"

        logger.info("AVML geçici indirme komutu çalıştırılıyor.")
        out, err, code = ssh.exec_command(dl_cmd, timeout=60)
        if code != 0:
            raise AcquisitionError(
                f"AVML geçici indirme başarısız (kod {code}): {err.strip()}"
            )

        out, err, code = ssh.exec_command(f"chmod +x {REMOTE_AVML_PATH}")
        if code != 0:
            raise AcquisitionError(
                f"AVML çalıştırılabilir yapılamadı (kod {code}): {err.strip()}"
            )

        # Doğrula: dosya gerçekten çalıştırılabilir mi? ("test -" zaten
        # WriteBlocker'ın genel izinli önekleri arasında.)
        _out, _err, code = ssh.exec_command(f"test -x {REMOTE_AVML_PATH}")
        if code != 0:
            raise AcquisitionError(
                "AVML geçici kurulum sonrası doğrulanamadı (dosya çalıştırılabilir değil)."
            )

        logger.info("AVML geçici olarak kuruldu: %s", REMOTE_AVML_PATH)
        return REMOTE_AVML_PATH
    except AcquisitionError:
        raise
    except Exception as exc:  # noqa: BLE001
        log_exception(exc, context="avml_bootstrap.bootstrap_avml")
        raise AcquisitionError(f"AVML geçici kurulumu başarısız: {exc}") from exc
