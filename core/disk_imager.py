"""Disk imajlama modülü.

Uzak sistemdeki bir bloğu (disk/partition) hedefe SIFIR YAZMA prensibiyle,
salt-okunur ``dd``/``dc3dd`` akışı üzerinden okuyup yerel hedefe yazar.
Tüm SSH komutları WriteBlocker'dan geçer.

v2 notu (resume desteği):
İmaj alırken ``{output_path}.yti_resume.json`` durum dosyası yazılır.
Aynı ``output_path`` ile tekrar çağrıldığında ve kısmi yerel dosya mevcutsa,
uzak ``dd`` komutuna ``skip_bytes`` iflag'i eklenerek kaldığı yerden
devam edilir. Tamamlanınca durum dosyası silinir.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from core.error_handler import AcquisitionError, log_exception
from core.ssh_connector import SSHConnector
from logs.logger import get_logger, get_session_id

logger = get_logger("disk_imager")

ProgressCallback = Callable[[int, Optional[int]], None]

_RESUME_EXT = ".yti_resume.json"


@dataclass
class DiskInfo:
    """Uzak sistemdeki bir disk/blok cihazının bilgisi."""

    name: str
    path: str
    size_bytes: int
    model: str = ""
    is_hpa_present: bool = False


@dataclass
class DiskImageResult:
    """Disk imajlama sonucu."""

    output_path: str
    total_bytes: int
    completed: bool = False
    resumed: bool = False
    resumed_from_bytes: int = 0
    algorithms: List[str] = field(default_factory=list)
    hashes: dict = field(default_factory=dict)


def _resume_path(output_path: str) -> str:
    return f"{output_path}{_RESUME_EXT}"


class DiskImager:
    """Uzak diskten yerel hedefe sıfır-yazma prensibiyle imaj alır."""

    def __init__(self, ssh: SSHConnector) -> None:
        self.ssh = ssh
        self._running = False
        self._paused = False
        self._cancelled = False
        self.hpa_present = False

    # --- Kontrol bayrakları -------------------------------------------------
    def pause(self) -> None:
        self._paused = True
        logger.info("DiskImager duraklatıldı.")

    def resume(self) -> None:
        self._paused = False
        logger.info("DiskImager devam ediyor.")

    def cancel(self) -> None:
        self._cancelled = True
        logger.warning("DiskImager iptal istendi.")

    # --- Keşif --------------------------------------------------------------
    def list_disks(self) -> List[DiskInfo]:
        """Uzak sistemdeki blok cihazlarını listeler (salt-okunur)."""
        disks: List[DiskInfo] = []
        out, _, code = self.ssh.exec_command(
            "lsblk -b -d -n -o NAME,SIZE,TYPE,MODEL"
        )
        if code != 0:
            logger.warning("lsblk başarısız, disk listesi boş dönebilir.")
            return disks

        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 3:
                continue
            name = parts[0]
            try:
                size = int(parts[1])
            except ValueError:
                continue
            dtype = parts[2].strip()
            if dtype not in ("disk", "loop"):
                continue
            model = parts[3].strip() if len(parts) >= 4 else ""
            disks.append(DiskInfo(name=name, path=f"/dev/{name}", size_bytes=size, model=model))
        logger.info("%d disk bulundu.", len(disks))
        return disks

    def detect_hpa(self, device_path: str) -> bool:
        """HPA (Host Protected Area) varlığını tespit eder."""
        out, _, code = self.ssh.exec_command(f"sudo -n hdparm -N {device_path}")
        present = False
        if code == 0 and "HPA is enabled" in out:
            present = True
        self.hpa_present = present
        logger.info("HPA durumu (%s): %s", device_path, present)
        return present

    # --- Resume yardımcıları ------------------------------------------------
    @staticmethod
    def _read_resume_state(output_path: str) -> Optional[dict]:
        rp = _resume_path(output_path)
        if not os.path.exists(rp):
            return None
        try:
            with open(rp, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Resume state okunamadı: %s", exc)
            return None

    @staticmethod
    def _write_resume_state(output_path: str, state: dict) -> None:
        rp = _resume_path(output_path)
        try:
            with open(rp, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
        except OSError as exc:
            logger.debug("Resume state yazılamadı: %s", exc)

    @staticmethod
    def _remove_resume_state(output_path: str) -> None:
        rp = _resume_path(output_path)
        try:
            if os.path.exists(rp):
                os.remove(rp)
        except OSError:
            pass

    def _plan_resume(
        self, device_path: str, output_path: str
    ) -> tuple[int, bool]:
        """Resume için başlangıç ofsetini belirler.

        Returns:
            (start_bytes, resumed)
        """
        state = self._read_resume_state(output_path)
        if state is None:
            return 0, False
        if state.get("device_path") != device_path:
            logger.warning(
                "Resume state farklı cihaza ait (%s != %s). Baştan alınacak.",
                state.get("device_path"), device_path,
            )
            self._remove_resume_state(output_path)
            return 0, False
        if not os.path.exists(output_path):
            self._remove_resume_state(output_path)
            return 0, False
        try:
            actual = os.path.getsize(output_path)
        except OSError:
            return 0, False
        # Küçük olan değeri esas al (state ile disk boyutu tutarsızlığına karşı)
        start = min(int(state.get("written_bytes", 0)), actual)
        # 1 MB blok hizasına indir (chunk == 1 MB)
        start = (start // (1024 * 1024)) * (1024 * 1024)
        if start <= 0:
            return 0, False
        logger.info("Resume: kaldığı yerden devam edilecek offset=%d", start)
        return start, True

    # --- İmaj alma ----------------------------------------------------------
    def acquire(
        self,
        device_path: str,
        output_path: str,
        block_size: str = "4M",
        total_bytes: Optional[int] = None,
        progress_callback: Optional[ProgressCallback] = None,
        allow_resume: bool = True,
        split_size_mb: int = 0,
    ) -> DiskImageResult:
        """Uzak diskten yerel dosyaya salt-okunur imaj alır.

        Args:
            block_size: dd ``bs=`` değeri (ör. "1M", "4M", "8M"). Uzak
                sunucudan çekilen dd bloğunu belirler.
            split_size_mb: 0'dan büyükse çıktı, verilen MB boyutunda
                ``output_path`` + ``.001``, ``.002`` gibi parçalara bölünür
                (adli standart split raw / EWF benzeri).
            allow_resume: True ise, kısmi imaj varsa kaldığı yerden devam eder
                (yalnızca split_size_mb == 0 iken; split modunda resume yok).

        Raises:
            AcquisitionError: İmaj alınamazsa.
        """
        self._running = True
        self._paused = False
        self._cancelled = False
        result = DiskImageResult(output_path=output_path, total_bytes=total_bytes or 0)

        # Split modunda resume yok — canlı disk okurken chunk uyumu kritik.
        if split_size_mb and split_size_mb > 0:
            return self._acquire_split(
                device_path=device_path,
                base_output_path=output_path,
                block_size=block_size,
                total_bytes=total_bytes,
                progress_callback=progress_callback,
                split_size_bytes=split_size_mb * 1024 * 1024,
            )

        # Resume planı.
        start_bytes = 0
        resumed = False
        if allow_resume:
            start_bytes, resumed = self._plan_resume(device_path, output_path)
        if resumed:
            # dd'yi skip_bytes ile kaldığı yerden başlat.
            # bs=4M sabit bloklu ama iflag=skip_bytes ile byte cinsinden skip
            remote_cmd = (
                f"sudo -n dd if={device_path} bs={block_size} "
                f"iflag=skip_bytes skip={start_bytes} status=none"
            )
            file_mode = "ab"  # append
            # Yerel dosyayı hizala.
            try:
                with open(output_path, "rb+") as fh:
                    fh.truncate(start_bytes)
            except OSError as exc:
                logger.warning("Resume için dosya truncate edilemedi: %s", exc)
                start_bytes = 0
                resumed = False
                remote_cmd = f"sudo -n dd if={device_path} bs={block_size} status=none"
                file_mode = "wb"
        else:
            remote_cmd = f"sudo -n dd if={device_path} bs={block_size} status=none"
            file_mode = "wb"

        logger.info(
            "Disk imajı %s: %s -> %s (offset=%d)",
            "DEVAM" if resumed else "BAŞLIYOR",
            device_path, output_path, start_bytes,
        )

        written = start_bytes
        result.resumed = resumed
        result.resumed_from_bytes = start_bytes if resumed else 0

        stdout = None
        _stderr = None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            # İlk resume state yaz.
            initial_state = {
                "device_path": device_path,
                "block_size": block_size,
                "written_bytes": start_bytes,
                "session_id": get_session_id(),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_resume_state(output_path, initial_state)

            stdout, _stderr = self.ssh.open_read_stream(remote_cmd)
            channel = stdout.channel
            _PROGRESS_MIN_INTERVAL = 0.2  # saniye
            _PROGRESS_MIN_BYTES = 8 * 1024 * 1024  # 8 MB
            _RESUME_WRITE_INTERVAL = 4.0  # saniye
            last_emit_time = time.monotonic()
            last_emit_bytes = written
            last_resume_write = time.monotonic()

            with open(output_path, file_mode) as out_file:
                while True:
                    if self._cancelled:
                        raise AcquisitionError("İmaj alma kullanıcı tarafından iptal edildi.")
                    while self._paused and not self._cancelled:
                        time.sleep(0.5)
                    chunk = stdout.read(1024 * 1024)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    written += len(chunk)
                    now = time.monotonic()
                    if progress_callback is not None:
                        if (
                            written - last_emit_bytes >= _PROGRESS_MIN_BYTES
                            or now - last_emit_time >= _PROGRESS_MIN_INTERVAL
                        ):
                            progress_callback(written, total_bytes)
                            last_emit_time = now
                            last_emit_bytes = written
                    # Periyodik resume state güncelle.
                    if now - last_resume_write >= _RESUME_WRITE_INTERVAL:
                        initial_state["written_bytes"] = written
                        self._write_resume_state(output_path, initial_state)
                        last_resume_write = now

                if progress_callback is not None:
                    progress_callback(written, total_bytes)

            exit_status = channel.recv_exit_status()
            if exit_status != 0:
                err_output = _stderr.read().decode("utf-8", errors="replace") if _stderr else ""
                raise AcquisitionError(
                    f"Uzak dd komutu başarısız (kod {exit_status}): {err_output.strip()}"
                )

            result.total_bytes = written
            result.completed = True
            # Başarı: resume state'i temizle.
            self._remove_resume_state(output_path)
            logger.info(
                "Disk imajı tamamlandı: %d bayt yazıldı%s.",
                written, " (resume)" if resumed else "",
            )
            return result
        except AcquisitionError:
            # İptal / kritik hata: state korunur (bir sonraki denemede resume için).
            raise
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="DiskImager.acquire")
            raise AcquisitionError(f"Disk imajı alınamadı: {exc}") from exc
        finally:
            self._running = False
            if stdout is not None:
                try:
                    stdout.channel.close()
                except Exception:  # noqa: BLE001
                    pass

    # --- Split (parçalı) imaj alma -----------------------------------------
    def _acquire_split(
        self,
        device_path: str,
        base_output_path: str,
        block_size: str,
        total_bytes: Optional[int],
        progress_callback: Optional[ProgressCallback],
        split_size_bytes: int,
    ) -> "DiskImageResult":
        """Parçalı imaj (adli split raw): base.001, base.002, ...

        Split modunda resume yoktur (canlı disk üzerinde parça
        hizasını korumak riskli); baştan başlar. Her parça hedef boyut
        dolduğunda kapatılıp sonraki açılır.
        """
        # Eski dosyaları temizle (aynı base + .NNN).
        base_dir = os.path.dirname(os.path.abspath(base_output_path)) or "."
        try:
            os.makedirs(base_dir, exist_ok=True)
        except OSError:
            pass

        remote_cmd = f"sudo -n dd if={device_path} bs={block_size} status=none"
        logger.info(
            "Disk imajı (SPLIT %d MB) başlıyor: %s -> %s.NNN",
            split_size_bytes // (1024 * 1024), device_path, base_output_path,
        )

        written_total = 0
        stdout = None
        _stderr = None
        result = DiskImageResult(
            output_path=base_output_path, total_bytes=total_bytes or 0,
        )
        try:
            stdout, _stderr = self.ssh.open_read_stream(remote_cmd)
            channel = stdout.channel
            _INTERVAL = 0.2
            last_emit = time.monotonic()
            part_idx = 1
            written_in_part = 0
            out_file = open(f"{base_output_path}.{part_idx:03d}", "wb")
            try:
                while True:
                    if self._cancelled:
                        raise AcquisitionError(
                            "İmaj alma kullanıcı tarafından iptal edildi."
                        )
                    while self._paused and not self._cancelled:
                        time.sleep(0.5)
                    # 1 MiB read birimi
                    chunk = stdout.read(1024 * 1024)
                    if not chunk:
                        break
                    # Parçayı split boyutuna sığdıracak şekilde böl.
                    remaining_in_part = split_size_bytes - written_in_part
                    if len(chunk) > remaining_in_part:
                        head = chunk[:remaining_in_part]
                        tail = chunk[remaining_in_part:]
                        out_file.write(head)
                        written_in_part += len(head)
                        written_total += len(head)
                        out_file.close()
                        part_idx += 1
                        out_file = open(
                            f"{base_output_path}.{part_idx:03d}", "wb"
                        )
                        out_file.write(tail)
                        written_in_part = len(tail)
                        written_total += len(tail)
                    else:
                        out_file.write(chunk)
                        written_in_part += len(chunk)
                        written_total += len(chunk)
                        if written_in_part >= split_size_bytes:
                            out_file.close()
                            part_idx += 1
                            out_file = open(
                                f"{base_output_path}.{part_idx:03d}", "wb"
                            )
                            written_in_part = 0
                    now = time.monotonic()
                    if progress_callback is not None and now - last_emit >= _INTERVAL:
                        progress_callback(written_total, total_bytes)
                        last_emit = now
                if progress_callback is not None:
                    progress_callback(written_total, total_bytes)
            finally:
                try:
                    out_file.close()
                except Exception:  # noqa: BLE001
                    pass

            exit_status = channel.recv_exit_status()
            if exit_status != 0:
                err_output = _stderr.read().decode("utf-8", errors="replace") if _stderr else ""
                raise AcquisitionError(
                    f"Uzak dd komutu başarısız (kod {exit_status}): {err_output.strip()}"
                )
            result.total_bytes = written_total
            result.completed = True

            # Her parçanın SHA-256 hash'ini hesapla.
            # Akış sırasında değil, yazma bittikten sonra hesaplanır —
            # böylece diske gerçekten yazılan veri doğrulanmış olur.
            import hashlib as _hashlib
            part_hashes: dict = {}
            for i in range(1, part_idx + 1):
                part_path = f"{base_output_path}.{i:03d}"
                if not os.path.exists(part_path):
                    break
                try:
                    h = _hashlib.sha256()
                    with open(part_path, "rb") as pf:
                        while True:
                            d = pf.read(4 * 1024 * 1024)
                            if not d:
                                break
                            h.update(d)
                    digest = h.hexdigest()
                    part_hashes[os.path.basename(part_path)] = digest
                    logger.info(
                        "Split parça hash (SHA-256) %s = %s",
                        os.path.basename(part_path), digest,
                    )
                except OSError as exc:
                    logger.warning(
                        "Split parça hash hesaplanamadı (%s): %s", part_path, exc
                    )
            result.hashes = part_hashes
            result.algorithms = ["sha256"]

            logger.info(
                "Disk imajı (SPLIT) tamamlandı: %d parça, %d bayt, %d parça hash'lendi.",
                part_idx, written_total, len(part_hashes),
            )
            return result
        except AcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="DiskImager._acquire_split")
            raise AcquisitionError(f"Split imaj alınamadı: {exc}") from exc
        finally:
            self._running = False
            if stdout is not None:
                try:
                    stdout.channel.close()
                except Exception:  # noqa: BLE001
                    pass
