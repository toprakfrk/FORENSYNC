"""HPA / DCO (Host Protected Area / Device Configuration Overlay) handler.

Adli bilişim standardı: HPA gizli alanı gerçekten imajlamak için önce
kaldırılıp diskin tamamı görünür yapılmalı, imaj alındıktan SONRA orijinal
HPA konfigürasyonu geri yüklenmelidir. Aksi halde delil zinciri
kırılır ("kaynak diskin durumu değiştirildi").

Bu modül HPA'yı SALT-OKUNUR olarak TESPİT eder. Kaldırma/geri yükleme
işlemleri yazma içerdiği için WriteBlocker whitelist'i tarafından
ENGELLENİR — bu tasarım gereğidir. HPA kaldırma özelliği kullanılacaksa,
uzak sistemde manuel olarak yapılmalı veya WriteBlocker'ın kısıtlı bir
istisna moduna sokulması gerekir (bu proje kapsamında dahil değildir).

Bu modül ``try/finally`` deseninin şablonunu ve tespit/raporlama akışını
sağlar; ileride yazma-izin verilmiş bir modda kaldırma eklenmek istenirse
buradan genişletilebilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("hpa_handler")


@dataclass
class HPAStatus:
    """HPA durumu."""

    device_path: str
    hpa_present: bool = False
    dco_present: bool = False
    native_max_sectors: Optional[int] = None
    current_max_sectors: Optional[int] = None
    raw_output: str = ""


class HPAHandler:
    """HPA/DCO tespit sınıfı (salt-okunur).

    Kaldırma özelliği bu sürümde DEVRE DIŞI — WriteBlocker mimarisi yazma
    içeren komutları engeller. Ancak sınıf ``ensure_restored()`` gibi
    ``try/finally`` yapısını dışa dönük olarak sağlar; ileride etkinleştirmek
    isteyenler için kanca noktaları hazırdır.
    """

    def __init__(self, ssh: SSHConnector) -> None:
        self.ssh = ssh
        self._removed_before_acquisition = False
        self._original_max_sectors: Optional[int] = None

    def detect(self, device_path: str) -> HPAStatus:
        """hdparm -N ile HPA + hdparm --dco-identify ile DCO durumunu tespit."""
        status = HPAStatus(device_path=device_path)
        out_n, _, code_n = self.ssh.exec_command(f"sudo -n hdparm -N {device_path}")
        status.raw_output += out_n
        if code_n == 0 and out_n:
            for line in out_n.splitlines():
                line_s = line.strip()
                if line_s.startswith("max sectors"):
                    # örn: "max sectors   = 3907029168/3907029168, HPA is disabled"
                    parts = line_s.split("=", 1)[1].strip()
                    if "," in parts:
                        nums, hpa_note = [p.strip() for p in parts.split(",", 1)]
                        status.hpa_present = "HPA is enabled" in hpa_note
                    else:
                        nums = parts
                    if "/" in nums:
                        cur_s, native_s = [n.strip() for n in nums.split("/", 1)]
                        try:
                            status.current_max_sectors = int(cur_s)
                            status.native_max_sectors = int(native_s)
                        except ValueError:
                            pass
        out_d, _, code_d = self.ssh.exec_command(f"sudo -n hdparm --dco-identify {device_path}")
        status.raw_output += "\n" + out_d
        if code_d == 0 and "DCO Revision" in out_d:
            status.dco_present = True
        logger.info(
            "HPA=%s DCO=%s cur=%s native=%s",
            status.hpa_present, status.dco_present,
            status.current_max_sectors, status.native_max_sectors,
        )
        return status

    # ------------------------------------------------------------------
    # Aşağıdaki context-manager tarzı kullanım (try/finally garantisi)
    # ------------------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Bir gün HPA kaldırma etkinleşirse burada geri yükleme yapılacak.
        # Şimdilik logdan öte bir aksiyon yok — write engellenmiş durumda.
        if self._removed_before_acquisition:
            logger.warning(
                "HPA geri yükleme YAPILAMADI (WriteBlocker aktif). "
                "Manuel geri yükleme gerekli olabilir."
            )
        return False  # exception'ı bastırma
