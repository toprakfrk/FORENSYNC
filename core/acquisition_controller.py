"""Edinim (acquisition) kontrolcüsü — tüm süreci tek yerden yönetir.

Bağlantı, OS tespiti, şifreleme tespiti, write blocker, imaj alma (disk/ram),
hash doğrulama (yerel + kaynak-vs-imaj), NTP doğrulama, dijital imzalama,
hedefli tarama (targeted) ve raporlama adımlarını koordine eder.

Bu sınıf framework'ten bağımsızdır; ilerleme ve durum için callback kullanır.
GUI tarafı bu kontrolcüyü bir QThread içinde çalıştırır.

Paralel/çoklu iş desteği: her ``AcquisitionController`` örneği KENDİ
``SSHConnector`` + ``WriteBlocker``'ını yönetir; farklı sunuculara veya
aynı sunucudaki farklı disklere birden çok controller örneği paralel
çalıştırılabilir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from core import APP_NAME, APP_VERSION
from core.crypto_handler import CryptoHandler
from core.digital_signer import DigitalSigner
from core.disk_imager import DiskImager
from core.disk_prep import DiskPrep
from core.error_handler import AcquisitionError, log_exception
from core.format_converter import FormatConverter, ImageFormat
from core.hasher import Hasher
from core.hpa_handler import HPAHandler
from core.ntp_verifier import NTPVerifier
from core.os_detector import OSDetector, OSType
from core.ram_imager import RamImager
from core.reporter import Reporter, ReportData
from core.ssh_connector import SSHConnector, SSHCredentials
from core.targeted_imager import TargetedImager, TargetedRule
from core.write_blocker import WriteBlocker
from logs.logger import get_logger, get_session_id

logger = get_logger("acquisition_controller")

ProgressCallback = Callable[[int, Optional[int]], None]
StatusCallback = Callable[[str], None]


@dataclass
class AcquisitionParams:
    """Standart edinim parametreleri (params dict yerine tipli yapı)."""

    credentials: SSHCredentials
    image_type: str = "disk"  # disk | ram | targeted
    device_path: str = ""
    output_path: str = ""
    image_format: str = "raw"
    hash_algorithms: List[str] = field(default_factory=lambda: ["sha256"])

    # Chain of custody
    case_number: str = ""
    examiner: str = ""
    evidence_number: str = ""
    location: str = ""
    incident_datetime: str = ""
    investigator_notes: str = ""

    # İmzalama
    sign_output: bool = True
    private_key_path: Optional[str] = None
    public_key_path: Optional[str] = None

    # Doğrulama seçenekleri
    verify_source: bool = False  # kaynak cihaz üzerinde de hash hesaplayıp karşılaştır
    allow_resume: bool = True

    # Rapor
    report_path: str = ""            # geriye uyumluluk: tek .txt yolu
    report_formats: List[str] = field(default_factory=lambda: ["txt"])
    # base_path (.txt uzantısız), multi format için

    # Targeted
    target_root: str = ""
    target_rule: Optional[TargetedRule] = None
    target_copy_dir: str = ""
    target_copy_files: bool = False

    # Disk edinim ayarları (chunk / split)
    dd_block_size: str = "4M"      # dd bs= değeri
    split_size_mb: int = 0          # 0: bölme yok; N MB: NxNMB parçalar

    # Windows RAM için (WinPMEM yolu)
    winpmem_path: Optional[str] = None


class AcquisitionController:
    """Tüm imaj alma sürecini koordine eden yüksek seviye kontrolcü."""

    def __init__(self) -> None:
        # SSH komutu gönderen TÜM bileşenler AYNI WriteBlocker'ı paylaşır.
        self.write_blocker = WriteBlocker()
        self.ssh = SSHConnector(self.write_blocker)
        self.hasher = Hasher(self.ssh)
        self.disk_prep = DiskPrep(self.ssh)
        self.format_converter = FormatConverter()
        self.reporter = Reporter()
        self.ntp = NTPVerifier()

        self._os_type: OSType = OSType.UNKNOWN
        self._disk_imager: Optional[DiskImager] = None
        self._ram_imager: Optional[RamImager] = None
        self._targeted_imager: Optional[TargetedImager] = None
        self.hpa_present = False

        self.progress_callback: Optional[ProgressCallback] = None
        self.status_callback: Optional[StatusCallback] = None

    # --- Yardımcılar --------------------------------------------------------
    def _status(self, message: str) -> None:
        logger.info("DURUM: %s", message)
        if self.status_callback is not None:
            self.status_callback(message)

    def _wrap_progress(self) -> ProgressCallback:
        def _cb(done: int, total: Optional[int]) -> None:
            if self.progress_callback is not None:
                self.progress_callback(done, total)
        return _cb

    # --- Facade adımları ----------------------------------------------------
    def connect(self, credentials: SSHCredentials) -> None:
        self._status("Bağlanılıyor...")
        self.ssh.connect(credentials)
        detector = OSDetector(self.ssh)
        self._os_type = detector.detect()
        self.hasher.os_type = self._os_type
        self._status(f"Bağlantı kuruldu. OS: {self._os_type.value}")

    def list_disks(self):
        imager = DiskImager(self.ssh)
        return imager.list_disks()

    def cancel(self) -> None:
        if self._disk_imager is not None:
            self._disk_imager.cancel()
        if self._ram_imager is not None:
            self._ram_imager.cancel()
        if self._targeted_imager is not None:
            self._targeted_imager.cancel()

    def pause(self) -> None:
        if self._disk_imager is not None:
            self._disk_imager.pause()
        if self._ram_imager is not None:
            self._ram_imager.pause()

    def resume(self) -> None:
        if self._disk_imager is not None:
            self._disk_imager.resume()
        if self._ram_imager is not None:
            self._ram_imager.resume()

    # --- Ana akış -----------------------------------------------------------
    def run_full_acquisition(self, params: AcquisitionParams) -> ReportData:
        started_at = datetime.now(timezone.utc).isoformat()
        report = ReportData(
            app_name=APP_NAME,
            app_version=APP_VERSION,
            case_number=params.case_number,
            examiner=params.examiner,
            evidence_number=params.evidence_number,
            location=params.location,
            incident_datetime=params.incident_datetime,
            investigator_notes=params.investigator_notes,
            target_host=params.credentials.host,
            device_path=params.device_path,
            image_type=params.image_type,
            image_format=params.image_format,
            output_path=params.output_path,
            started_at=started_at,
            session_id=get_session_id(),
        )
        progress = self._wrap_progress()

        try:
            if not self.ssh.is_connected:
                self.connect(params.credentials)
            report.os_type = self._os_type.value

            # NTP zaman doğrulama.
            self._status("NTP zaman doğrulaması yapılıyor...")
            ntp_result = self.ntp.verify()
            report.ntp_server = ntp_result.server
            report.ntp_offset_seconds = ntp_result.offset_seconds
            report.ntp_reliable = ntp_result.reliable

            # Şifreleme + HPA tespiti (disk için).
            if params.image_type == "disk" and params.device_path:
                self._status("Şifreleme durumu kontrol ediliyor...")
                crypto = CryptoHandler(self.ssh, self._os_type)
                enc = crypto.detect(params.device_path)
                report.encryption_scheme = enc.scheme
                if enc.encrypted:
                    report.notes.append(f"Disk şifreli tespit edildi: {enc.scheme}")

                self._status("HPA/DCO durumu kontrol ediliyor...")
                hpa = HPAHandler(self.ssh)
                hpa_status = hpa.detect(params.device_path)
                report.hpa_present = hpa_status.hpa_present
                report.dco_present = hpa_status.dco_present
                if hpa_status.hpa_present:
                    report.notes.append(
                        "HPA tespit edildi — gizli alan mevcut. "
                        "İmaj yalnızca görünür sektörleri kapsar."
                    )
                if hpa_status.dco_present:
                    report.notes.append("DCO tespit edildi.")

            # İmaj alma.
            if params.image_type == "ram":
                report = self._acquire_ram(params, report, progress)
            elif params.image_type == "targeted":
                report = self._acquire_targeted(params, report, progress)
            else:
                report = self._acquire_disk(params, report, progress)

            # Hash doğrulama (targeted için imaj tek dosya değil, atlanır;
            # RAM için ram_imager kendi 8 MiB parça bazlı SHA-256'sını hesaplar;
            # split disk modunda her parça _acquire_split içinde zaten hash'lendi).
            _is_split = (
                params.image_type == "disk"
                and params.split_size_mb
                and params.split_size_mb > 0
            )
            if params.image_type not in ("targeted", "ram") and not _is_split:
                self._status("Bütünlük (hash) doğrulaması yapılıyor...")
                self._verify_hashes(params, report)

            # Format dönüştürme.
            if (
                params.image_type == "disk"
                and params.image_format
                and params.image_format.lower() != "raw"
            ):
                self._status(
                    f"{params.image_format.upper()} formatına dönüştürülüyor..."
                )
                self._convert_format(params, report)

            # Dijital imzalama.
            if params.sign_output and params.image_type != "targeted":
                self._status("Çıktı dijital olarak imzalanıyor...")
                self._sign_output(params, report)

            # Rapor üretimi.
            report.finished_at = datetime.now(timezone.utc).isoformat()
            self._generate_reports(params, report)

            self._status("İşlem başarıyla tamamlandı.")
            logger.info(
                "Edinim tamamlandı. WriteBlocker onay=%d engel=%d",
                self.write_blocker.verified_count,
                self.write_blocker.blocked_count,
            )
            return report
        except AcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="AcquisitionController.run_full_acquisition")
            raise AcquisitionError(f"Edinim başarısız: {exc}") from exc

    # --- Alt adımlar --------------------------------------------------------
    def _acquire_disk(self, params, report, progress) -> ReportData:
        self._status("Disk imajı alınıyor...")
        self._disk_imager = DiskImager(self.ssh)

        disks = {d.path: d for d in self._disk_imager.list_disks()}
        total = disks[params.device_path].size_bytes if params.device_path in disks else None

        if total and not self.disk_prep.check_space(params.output_path, total):
            raise AcquisitionError("İmaj için yeterli yerel disk alanı yok.")

        result = self._disk_imager.acquire(
            device_path=params.device_path,
            output_path=params.output_path,
            block_size=params.dd_block_size or "4M",
            total_bytes=total,
            progress_callback=progress,
            allow_resume=params.allow_resume,
            split_size_mb=params.split_size_mb or 0,
        )
        report.output_path = (
            f"{params.output_path}.001"
            if params.split_size_mb and params.split_size_mb > 0
            else params.output_path
        )
        report.total_bytes = result.total_bytes
        report.resumed = result.resumed
        report.resumed_from_bytes = result.resumed_from_bytes
        if params.split_size_mb and params.split_size_mb > 0:
            report.notes.append(
                f"Split imaj: {params.split_size_mb} MB parçalar halinde "
                f"({params.output_path}.NNN)."
            )
            # Split hash'leri result'tan rapora taşı; _verify_hashes bu
            # modda çağrılmaz (tek dosya yerine .001/.002... parçaları var).
            if result.hashes:
                report.hashes = result.hashes
                report.hash_verified = True
                report.hash_verification_mode = "split-parts-sha256"
                report.hash_computed_at = __import__(
                    "datetime"
                ).datetime.now(__import__("datetime").timezone.utc).isoformat()
                report.notes.append(
                    f"Split parça hash'leri (SHA-256): {len(result.hashes)} parça doğrulandı."
                )
        return report

    def _acquire_ram(self, params, report, progress) -> ReportData:
        self._status("RAM imajı alınıyor (8 MiB parçalar, SHA-256 doğrulama)...")
        self._ram_imager = RamImager(
            self.ssh, self._os_type, winpmem_path=params.winpmem_path
        )
        result = self._ram_imager.acquire(
            output_path=params.output_path,
            progress_callback=progress,
        )
        report.total_bytes = result.total_bytes
        # RAM sonucunu rapora yansıt.
        report.output_path = result.output_path  # gerçek memory-attempt-NNN.001 yolu
        report.notes.append(
            f"RAM aracı: {result.tool}, attempt #{result.attempt_number}, "
            f"{result.chunk_count} × 8 MiB parça"
        )
        if result.stream_sha256:
            report.hashes = {"SHA256 (stream)": result.stream_sha256,
                             "SHA256 (file)": result.file_sha256}
            report.hash_verified = result.verified_continuous
            report.hash_verification_mode = (
                "verified_continuous" if result.verified_continuous
                else "hash-mismatch"
            )
            report.hash_computed_at = datetime.now(timezone.utc).isoformat()
        return report

    def _acquire_targeted(self, params, report, progress) -> ReportData:
        self._status("Hedefli tarama yapılıyor (Custom Content)...")
        if not params.target_root or params.target_rule is None:
            raise AcquisitionError("Targeted mod için target_root ve target_rule gerekli.")
        self._targeted_imager = TargetedImager(self.ssh, self._os_type)
        result = self._targeted_imager.scan(
            remote_root=params.target_root,
            rule=params.target_rule,
            output_dir=params.target_copy_dir,
            copy_files=params.target_copy_files,
            progress_callback=progress,
        )
        report.targeted_files_count = len(result.hits)
        report.bad_extension_files = [h.remote_path for h in result.hits if h.bad_extension]
        report.total_bytes = result.total_bytes_copied
        report.notes.append(
            f"Hedefli tarama: {len(result.hits)} dosya, "
            f"{result.bad_extension_count} uzantı-tür uyuşmazlığı."
        )
        return report

    def _verify_hashes(self, params, report) -> None:
        """Yerel imaj hash'ini hesapla; ``verify_source`` açıksa kaynak
        cihaz üzerinde de aynı algoritmalarla hash hesaplayıp karşılaştır.
        """
        hashes: Dict[str, str] = {}
        source_hashes: Dict[str, str] = {}
        for algo in params.hash_algorithms:
            try:
                local_hash = self.hasher.hash_local_file(report.output_path or params.output_path, algo)
                hashes[algo.upper()] = local_hash
            except Exception as exc:  # noqa: BLE001
                logger.warning("Yerel hash (%s) hesaplanamadı: %s", algo, exc)
        report.hashes = hashes
        report.hash_computed_at = datetime.now(timezone.utc).isoformat()

        if params.verify_source and params.image_type == "disk" and params.device_path:
            self._status("Kaynak cihaz hash'i hesaplanıyor (uzun sürebilir)...")
            all_match = True
            for algo in params.hash_algorithms:
                try:
                    remote_hash = self.hasher.hash_remote_device(params.device_path, algo)
                    source_hashes[algo.upper()] = remote_hash
                    if algo.upper() in hashes:
                        if not Hasher.compare(remote_hash, hashes[algo.upper()]):
                            all_match = False
                            report.notes.append(
                                f"UYARI: {algo.upper()} kaynak ile imaj uyuşmuyor!"
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Kaynak hash (%s) hesaplanamadı: %s", algo, exc)
                    all_match = False
            report.source_hashes = source_hashes
            report.hash_verified = bool(hashes) and bool(source_hashes) and all_match
            report.hash_verification_mode = "source-vs-image"
        else:
            report.hash_verified = bool(hashes)
            report.hash_verification_mode = "local-only"

    def _convert_format(self, params, report) -> None:
        fmt = ImageFormat(params.image_format.lower())
        actual_path = report.output_path or params.output_path
        # Format dönüşümünde çıktı yolu: aynı base + yeni uzantı.
        base = actual_path.rsplit(".", 1)[0] if "." in actual_path else actual_path
        converted = f"{base}.{fmt.value}"
        self.format_converter.convert(
            actual_path, fmt, converted,
            case_number=params.case_number,
            examiner=params.examiner,
            evidence_number=params.evidence_number,
            notes=params.investigator_notes,
        )
        report.notes.append(f"{fmt.value.upper()} formatına dönüştürüldü: {converted}")

    def _sign_output(self, params, report) -> None:
        # NOT: params.output_path kullanıcının İSTEDİĞİ yoldur; ama RAM
        # edinimi dosyayı her zaman "stem-attempt-NNN.001" olarak yazar
        # (bkz. RamImager._next_attempt_path / _acquire_ram: satır 301'de
        # report.output_path = result.output_path ile GERÇEK yol senkron
        # tutulur). Disk akışında ikisi zaten aynıdır. Bu yüzden burada
        # her zaman report.output_path kullanılmalı — yoksa RAM imajları
        # için "dosya bulunamadı" hatası alınır (imaj var ama farklı
        # isimde).
        actual_path = report.output_path or params.output_path
        signer = DigitalSigner(params.private_key_path, params.public_key_path)
        if not params.private_key_path:
            priv = f"{actual_path}.key"
            pub = f"{actual_path}.pub"
            signer.generate_keypair(priv, pub)
            report.notes.append("Anahtar çifti otomatik üretildi.")
        sig = signer.sign_file(actual_path)
        report.signature_path = sig

    def _generate_reports(self, params, report) -> None:
        """Rapor üretimi — hem tekil (report_path) hem çoklu (report_formats)."""
        self._status("Rapor üretiliyor...")
        generated_paths: List[str] = []
        # Geriye uyumluluk: report_path .txt olarak varsa üret.
        if params.report_path:
            try:
                p = self.reporter.generate_txt(report, params.report_path)
                generated_paths.append(p)
            except Exception as exc:  # noqa: BLE001
                report.notes.append(f"TXT rapor üretilemedi: {exc}")

        # Çoklu format.
        if params.report_formats:
            base = params.report_path.rsplit(".", 1)[0] if params.report_path else \
                   params.output_path
            outputs = self.reporter.generate_multi(report, base, params.report_formats)
            for fmt, path in outputs.items():
                report.notes.append(f"Rapor ({fmt.upper()}): {path}")
                generated_paths.append(path)

        # Rapor bütünlük manifestosu: her üretilen rapor dosyasının SHA-256
        # hash'i hesaplanıp AYRI bir dosyaya yazılır. Böylece raporun
        # kendisi sonradan değiştirilirse, bu manifestoyla karşılaştırılınca
        # tutarsızlık ortaya çıkar — doğrulamak isteyen ilgili rapor
        # dosyasının hash'ini kendisi hesaplayıp manifestoyla karşılaştırır.
        if generated_paths:
            self._write_report_hash_manifest(params, report, generated_paths)

    def _write_report_hash_manifest(
        self, params, report, report_paths: List[str],
    ) -> None:
        manifest_lines = [
            "IMAJER — Rapor Bütünlük Manifestosu (SHA-256)",
            f"Oturum ID: {report.session_id}",
            f"Üretim tarihi (UTC): {datetime.now(timezone.utc).isoformat()}",
            "-" * 60,
        ]
        found_any = False
        for path in report_paths:
            try:
                digest = self.hasher.hash_local_file(path, "sha256")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Rapor hash'i hesaplanamadı (%s): %s", path, exc)
                continue
            found_any = True
            manifest_lines.append(f"{os.path.basename(path)}  SHA256={digest}")
        if not found_any:
            return
        base = params.report_path.rsplit(".", 1)[0] if params.report_path else \
               params.output_path
        manifest_path = f"{base}_rapor_hashleri.txt"
        try:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(manifest_lines) + "\n")
            report.notes.append(f"Rapor bütünlük manifestosu: {manifest_path}")
            logger.info("Rapor hash manifestosu üretildi: %s", manifest_path)
        except OSError as exc:
            logger.warning("Rapor hash manifestosu yazılamadı: %s", exc)

    def close(self) -> None:
        self.ssh.close()