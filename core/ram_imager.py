"""RAM imajlama modülü — 8 MiB parçalı, SHA-256 doğrulamalı, resume YOK.

Endüstri standardı "minimal müdahale" prensibiyle uzak sistemin uçucu
belleğini (RAM) alır.

Süreç (Linux/macOS):
  1. Uzak sistemde AVML zaten kuruluysa doğrudan kullanılır; değilse
     ``core/avml_bootstrap.py`` ile geçici olarak /tmp altına yüklenir
     (yalnızca RAM edinimi süresince, sonra silinir).
  2. AVML fiziksel belleği ``/proc/kcore``, ``/dev/crash`` veya ``/dev/mem``
     üzerinden SALT OKUNUR açar.
  3. AVML çıktısını ``/dev/stdout`` üzerinden akıtır (sunucunun diskinde
     RAM imajı OLUŞMAZ). Veri SSH kanalıyla yerel bilgisayara akar.
  4. Yerel taraf **8 MiB parçalar** halinde okur, HER parça için SHA-256
     hesaplar ve akış-boyu (streaming) hash'i günceller.
  5. Aktarım sonunda yerel dosyanın hash'i ile streaming hash birebir
     karşılaştırılır. Eşleşirse sonuç ``verified_continuous`` olur.
  6. Geçici AVML/agent/marker dosyaları güvenli biçimde kaldırılır.

Windows:
  WinPMEM ``-o -`` stdout modu — akış mantığı Linux/macOS ile aynıdır.

RESUME YOK:
  RAM imajı doğası gereği canlı bir görüntüdür. Bağlantı kesilirse imaj
  **kaldığı yerden devam ETMEZ**; yeni bir ``memory-attempt-NNN.001``
  başlatılır. Aynı ``base_output_path`` ile tekrar çağırıldığında
  ``memory-attempt-002`` gibi otomatik artan bir dosya adı seçilir.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from core.avml_bootstrap import bootstrap_avml
from core.error_handler import AcquisitionError, log_exception
from core.os_detector import OSType
from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("ram_imager")

ProgressCallback = Callable[[int, Optional[int]], None]

# RAM imajı için algoritma listesi disk akışından ayrıdır.
RAM_HASH_ALGORITHMS: List[str] = ["sha256"]

# Sabitler
CHUNK_SIZE_BYTES = 8 * 1024 * 1024   # 8 MiB — spesifikasyonda sabit
_MAX_ATTEMPTS_SCAN = 999


@dataclass
class RamInfo:
    """Uzak sistemin RAM bilgisi."""

    total_bytes: int
    available_bytes: int = 0


@dataclass
class RamImageResult:
    """RAM imajlama sonucu."""

    output_path: str = ""
    attempt_number: int = 1
    total_bytes: int = 0
    chunk_size: int = CHUNK_SIZE_BYTES
    chunk_count: int = 0
    stream_sha256: str = ""
    file_sha256: str = ""
    verified_continuous: bool = False
    tool: str = "avml"        # avml | winpmem
    completed: bool = False
    chunk_hashes: List[str] = field(default_factory=list)


class RamImager:
    """Uzak sistemden minimal müdahaleyle RAM imajı alır (8 MiB parça + SHA-256)."""

    DEFAULT_WINPMEM_PATH = r"C:\tools\winpmem.exe"
    _REMOTE_AVML_TMP = "/tmp/yti_avml"
    _REMOTE_MARKER = "/tmp/yti_ram_marker"
    # AVML v0.20+ "acquire" alt-komutu, hedefi (/dev/stdout) bir gerçek
    # dosyaymış gibi çözümlemeye (disk kullanımı kontrolü için) çalışıyor;
    # bu, boru (pipe) üzerinde "sembolik bağlantı döngüsü" hatasına yol
    # açıyor. Çözüm: gerçek bir adlandırılmış boru (FIFO) — disk'e HİÇBİR
    # veri yazılmaz, yalnızca IPC kanalı olarak var olur, iş bitince silinir.
    _REMOTE_RAM_FIFO = "/tmp/yti_ram_pipe"

    def __init__(
        self,
        ssh: SSHConnector,
        os_type: OSType = OSType.LINUX,
        winpmem_path: Optional[str] = None,
    ) -> None:
        self.ssh = ssh
        self.os_type = os_type
        self.winpmem_path = winpmem_path or self.DEFAULT_WINPMEM_PATH
        self._running = False
        self._paused = False
        self._cancelled = False
        # PATH'te bulunan "avml" komutu varsayılan; eğer bulunamaz ve
        # geçici kurulum yapılırsa bu, indirilen ikili dosyanın tam
        # yoluna ("/tmp/yti_avml") çevrilir. Yalnızca bu örnek/edinim
        # için geçerlidir; kalıcı bir yapılandırma DEĞİLDİR.
        self._avml_cmd = "avml"
        self._avml_bootstrapped = False
        # Bu edinim için AVML'ye açıkça bildirilecek RAM kaynağı
        # (/proc/kcore | /dev/crash | /dev/mem). acquire() içinde,
        # AVML çalıştırılmadan ÖNCE salt-okunur testlerle belirlenir.
        self._ram_source = ""

    # --- Kontrol ------------------------------------------------------------
    def pause(self) -> None:
        self._paused = True
        logger.info("RamImager duraklatıldı.")

    def resume(self) -> None:
        self._paused = False
        logger.info("RamImager devam ediyor.")

    def cancel(self) -> None:
        self._cancelled = True
        logger.warning("RamImager iptal istendi.")

    # --- Bilgi --------------------------------------------------------------
    def get_ram_info(self) -> RamInfo:
        """Uzak sistemin RAM boyutunu tespit eder (salt-okunur)."""
        if self.os_type == OSType.WINDOWS:
            cmd = 'wmic os get TotalVisibleMemorySize /value'
        else:
            cmd = "cat /proc/meminfo"
        out, _, code = self.ssh.exec_command(cmd)
        total = 0
        available = 0
        if code == 0 and out:
            if self.os_type == OSType.WINDOWS:
                for line in out.splitlines():
                    if "TotalVisibleMemorySize" in line and "=" in line:
                        try:
                            total = int(line.split("=")[1].strip()) * 1024
                        except ValueError:
                            total = 0
            else:
                for line in out.splitlines():
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        available = int(line.split()[1]) * 1024
        logger.info("RAM bilgisi: total=%d, available=%d", total, available)
        return RamInfo(total_bytes=total, available_bytes=available)

    # --- Dosya adı üretimi (memory-attempt-NNN) -----------------------------
    @staticmethod
    def _next_attempt_path(base_output_path: str) -> tuple[str, int]:
        """Kullanıcının verdiği yol için bir sonraki memory-attempt-NNN.001
        dosya adını üretir.

        Örn: base=/case/ram.lime → /case/memory-attempt-001.001 (varsa 002...)
        Kullanıcı dosya adına ``.001`` uzantısı vermişse yine attempt ekler.
        """
        base_dir = os.path.dirname(os.path.abspath(base_output_path)) or "."
        try:
            os.makedirs(base_dir, exist_ok=True)
        except OSError:
            pass
        # Kullanıcının stem'ini koru: örn "ram.lime" → prefix "ram"
        stem = os.path.splitext(os.path.basename(base_output_path))[0] or "memory"
        prefix = f"{stem}-attempt-"
        # Mevcut attempt'leri tara.
        existing = set()
        try:
            for name in os.listdir(base_dir):
                m = re.match(rf"^{re.escape(prefix)}(\d{{3}})\.001$", name)
                if m:
                    existing.add(int(m.group(1)))
        except OSError:
            pass
        n = 1
        while n in existing and n < _MAX_ATTEMPTS_SCAN:
            n += 1
        path = os.path.join(base_dir, f"{prefix}{n:03d}.001")
        return path, n

    # --- Uzak araç hazırlığı ------------------------------------------------
    def _check_remote_avml(self) -> bool:
        """AVML uzak sistemde çalıştırılabilir mi kontrol et."""
        out, _, code = self.ssh.exec_command("command -v avml")
        return code == 0 and out.strip() != ""

    def _select_ram_source(self) -> str:
        """Uzak sistemde fiilen erişilebilir bellek kaynağını salt-okunur
        biçimde tespit eder.

        Birçok bulut/VM sunucusunda ``/dev/crash`` hiç yoktur (crash kernel
        modülü yüklenmemiş) ve ``/dev/mem`` genelde ``CONFIG_STRICT_DEVMEM``
        ile kısıtlıdır; buna karşın ``/proc/kcore`` çoğu Linux dağıtımında
        okunabilir durumdadır — ama yalnızca ROOT için. SSH kullanıcısı
        root değilse (ör. "ubuntu") testler ``sudo`` olmadan hep başarısız
        görünür; bu yüzden önce ``sudo -n`` ile, olmazsa düz haliyle dener.
        AVML'nin akış (stdout) modunda kaynak yalnızca BİR KEZ seçilir ve
        otomatik geçiş YAPMAZ, bu yüzden en olası çalışan kaynağı burada
        önceden belirleyip ``--source`` ile açıkça veriyoruz.

        Öncelik: /proc/kcore > /dev/crash > /dev/mem.
        """
        def _readable_or_exists(test_cmd: str) -> bool:
            for prefix in ("sudo -n ", ""):
                _out, _err, code = self.ssh.exec_command(f"{prefix}{test_cmd}")
                if code == 0:
                    return True
            return False

        if _readable_or_exists("test -r /proc/kcore"):
            return "/proc/kcore"
        if _readable_or_exists("test -e /dev/crash"):
            return "/dev/crash"
        if _readable_or_exists("test -r /dev/mem"):
            return "/dev/mem"
        # Hiçbiri kesin doğrulanamadıysa AVML'nin varsayılan sırasına
        # bırak; en azından hata mesajı üç kaynağı da deneyip raporlayacak
        # olan orijinal davranışa döner.
        logger.warning(
            "Hiçbir RAM kaynağı (/proc/kcore, /dev/crash, /dev/mem) önceden "
            "doğrulanamadı; AVML varsayılan sırasıyla denenecek."
        )
        return ""

    def _cleanup_remote_temp(self) -> None:
        """Geçici AVML ve marker dosyalarını uzak sistemden temizle."""
        if self.os_type == OSType.WINDOWS:
            # Windows tarafında biz geçici dosya yükleme yapmıyoruz.
            return
        for path in (self._REMOTE_AVML_TMP, self._REMOTE_MARKER, self._REMOTE_RAM_FIFO):
            try:
                self.ssh.exec_command(f"rm -f {path}")
            except Exception:  # noqa: BLE001
                pass
        logger.info("Uzak geçici RAM dosyaları temizlendi.")

    def _build_capture_command(self) -> str:
        """OS'a göre RAM yakalama komutunu döndürür.

        AVML/WinPMEM stdout modu; sunucu diskine hiçbir şey yazılmaz.
        """
        if self.os_type == OSType.WINDOWS:
            # WinPMEM stdout: -o -
            return f'"{self.winpmem_path}" -o -'
        # Linux/macOS: AVML — /dev/stdout, sıkıştırmasız (imaj tutarlılığı için).
        # Not: --compress flag'i sıkıştırma yapar ama SHA-256 doğrulaması
        # aynı akış üzerinde çalışır, dolayısıyla sorun olmaz. Ancak ham imaj
        # istenirse compress kaldırılabilir. Varsayılan: sıkıştırmalı.
        # self._avml_cmd normalde "avml" (PATH'te bulunan); AVML PATH'te
        # yoksa geçici olarak kurulmuş ikili dosyanın tam yoluna
        # ("/tmp/yti_avml") döner (bkz. acquire()).
        # AVML v0.20+ alt-komut tabanlıdır: eski "avml --compress dosya"
        # biçimi artık "unexpected argument" hatası verir; "acquire"
        # alt-komutu zorunlu. Fiziksel belleği okumak kök yetki gerektirir,
        # bu yüzden çalıştırma "sudo -n" ile yapılır (disk imajlamadaki
        # "sudo -n dd" ile aynı desen).
        #
        # /dev/stdout'a DOĞRUDAN yazmak artık güvenilir değil: "acquire"
        # hedefi gerçek bir dosyaymış gibi çözümlemeye (disk kullanımı
        # kontrolü) çalışıyor ve bu, boru üzerinde "sembolik bağlantı
        # döngüsü" hatasına yol açıyor. Bunun yerine gerçek bir adlandırılmış
        # boru (FIFO) kullanılıyor: mkfifo ile oluşturulur, arka planda
        # "cat" onu okuyup SSH kanalının stdout'una aktarır, avml ise bu
        # FIFO'ya yazar. FIFO disk'te veri TUTMAZ (salt IPC kanalı), iş
        # bitince (başarılı/başarısız fark etmeksizin) silinir. avml'nin
        # gerçek çıkış kodu "$ec" ile korunup en sonda "exit $ec" ile
        # döndürülür (yoksa son "rm" komutunun kodu hataları maskelerdi).
        # "catpid" ile arka plan "cat" süreci PID'i tutulup İŞ BİTİNCE
        # (avml hiç açmadan başarısız olsa BİLE) kill+wait ile kesin olarak
        # sonlandırılır — yoksa "cat" sonsuza dek bloke halde hayalet süreç
        # olarak sunucuda kalabilirdi.
        source_flag = f"--source {self._ram_source} " if self._ram_source else ""
        fifo = self._REMOTE_RAM_FIFO
        return (
            f"rm -f {fifo} 2>/dev/null; mkfifo -m 600 {fifo}; "
            f"cat {fifo} & catpid=$!; "
            f"sudo -n {self._avml_cmd} acquire {source_flag}{fifo}; "
            f"ec=$?; kill $catpid 2>/dev/null; wait $catpid 2>/dev/null; "
            f"rm -f {fifo}; exit $ec"
        )

    # --- Ana edinim ---------------------------------------------------------
    def acquire(
        self,
        output_path: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> RamImageResult:
        """RAM imajını 8 MiB parçalar halinde akıtarak alır.

        - Sunucu diskinde imaj oluşturulmaz (AVML/WinPMEM stdout modu).
        - Yerel taraf 8 MiB'lık chunk'lar okur, her chunk için SHA-256
          hesaplar, streaming hash'i günceller.
        - İşlem sonunda yerel dosya hash'i streaming hash ile karşılaştırılır.
        - Bağlantı kesilirse resume YOK — bir sonraki denemede yeni
          ``memory-attempt-NNN.001`` başlatılır.
        """
        self._running = True
        self._paused = False
        self._cancelled = False

        # Dosya adını memory-attempt-NNN.001 formatına çevir.
        attempt_path, attempt_n = self._next_attempt_path(output_path)
        result = RamImageResult(
            output_path=attempt_path,
            attempt_number=attempt_n,
            chunk_size=CHUNK_SIZE_BYTES,
            tool=("winpmem" if self.os_type == OSType.WINDOWS else "avml"),
        )

        info = self.get_ram_info()
        total = info.total_bytes or None

        # Uzak sistemde AVML var mı? (Linux/macOS)
        # NOT: Bu geçici kurulum İSTİSNASI yalnızca RAM edinimi içindir.
        # Disk imajlama akışı (disk_imager.py) bu mantığı hiç kullanmaz ve
        # hedef sisteme herhangi bir yazma/kurulum yapmaz — write_blocker
        # içindeki istisna kalıpları da yalnızca bu sabit RAM geçici
        # dosyasıyla eşleşecek şekilde daraltılmıştır.
        if self.os_type != OSType.WINDOWS:
            self._avml_cmd = "avml"
            self._avml_bootstrapped = False
            if not self._check_remote_avml():
                logger.warning(
                    "AVML uzak sistemde bulunamadı; yalnızca bu RAM edinimi "
                    "için geçici kurulum deneniyor (imaj sonrası silinecek)."
                )
                # Model/mimariye göre uzak sistem türü zaten os_detector ile
                # belirlenmiş durumda (Linux/macOS). Kurulum tamamen geçici:
                # /tmp altına iner, imaj alınır, sonra kaldırılır.
                remote_path = bootstrap_avml(self.ssh)
                self._avml_cmd = remote_path
                self._avml_bootstrapped = True
            # Marker dosyası (temizlik için işaret)
            try:
                self.ssh.exec_command(f"echo yti > {self._REMOTE_MARKER}")
            except Exception:  # noqa: BLE001
                pass
            # AVML'nin akış (stdout) modu kaynağı bir kere seçip sabitler,
            # başarısız olursa OTOMATİK başka kaynağa geçmez. Bu yüzden
            # önceden salt-okunur testlerle en olası çalışan kaynağı
            # belirleyip --source ile açıkça bildiriyoruz (bkz.
            # _select_ram_source: /proc/kcore > /dev/crash > /dev/mem).
            self._ram_source = self._select_ram_source()
            logger.info("RAM kaynağı seçildi: %s", self._ram_source or "(AVML varsayılanı)")

        remote_cmd = self._build_capture_command()
        logger.info(
            "RAM imajı başlıyor (os=%s, tool=%s, chunk=%d, attempt=%d).",
            self.os_type.value, result.tool, CHUNK_SIZE_BYTES, attempt_n,
        )

        stream_hasher = hashlib.sha256()
        file_hasher = hashlib.sha256()  # tam dosya hash'i akışa paralel
        chunks: List[str] = []
        written = 0

        stdout = None
        _stderr = None
        try:
            stdout, _stderr = self.ssh.open_read_stream(remote_cmd)
            channel = stdout.channel
            _PROGRESS_INTERVAL = 0.2
            last_emit_time = time.monotonic()
            last_emit_bytes = 0

            with open(attempt_path, "wb") as out_file:
                buf = bytearray()
                while True:
                    if self._cancelled:
                        raise AcquisitionError("RAM imajı iptal edildi.")
                    while self._paused and not self._cancelled:
                        time.sleep(0.5)
                    # SSH channel'dan 1 MiB oku (paramiko okuma bloklu).
                    chunk = stdout.read(1024 * 1024)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    # 8 MiB dolduysa parçala.
                    while len(buf) >= CHUNK_SIZE_BYTES:
                        piece = bytes(buf[:CHUNK_SIZE_BYTES])
                        del buf[:CHUNK_SIZE_BYTES]
                        piece_hash = hashlib.sha256(piece).hexdigest()
                        chunks.append(piece_hash)
                        stream_hasher.update(piece)
                        file_hasher.update(piece)
                        out_file.write(piece)
                        written += CHUNK_SIZE_BYTES
                        if progress_callback is not None:
                            now = time.monotonic()
                            if now - last_emit_time >= _PROGRESS_INTERVAL or \
                               written - last_emit_bytes >= CHUNK_SIZE_BYTES * 2:
                                progress_callback(written, total)
                                last_emit_time = now
                                last_emit_bytes = written
                # Kalan (< 8 MiB) parça.
                if buf:
                    piece = bytes(buf)
                    piece_hash = hashlib.sha256(piece).hexdigest()
                    chunks.append(piece_hash)
                    stream_hasher.update(piece)
                    file_hasher.update(piece)
                    out_file.write(piece)
                    written += len(piece)
                if progress_callback is not None:
                    progress_callback(written, total)

            exit_status = channel.recv_exit_status()
            if exit_status != 0:
                err_output = _stderr.read().decode("utf-8", errors="replace") if _stderr else ""
                raise AcquisitionError(
                    f"Uzak RAM yakalama komutu başarısız (kod {exit_status}): "
                    f"{err_output.strip()}"
                )

            # Dosya hash'ini disk okuyarak yeniden doğrula (verified_continuous).
            disk_hasher = hashlib.sha256()
            with open(attempt_path, "rb") as fh:
                while True:
                    d = fh.read(4 * 1024 * 1024)
                    if not d:
                        break
                    disk_hasher.update(d)
            result.stream_sha256 = stream_hasher.hexdigest()
            result.file_sha256 = disk_hasher.hexdigest()
            result.verified_continuous = (result.stream_sha256 == result.file_sha256)
            result.total_bytes = written
            result.chunk_count = len(chunks)
            result.chunk_hashes = chunks
            result.completed = True
            logger.info(
                "RAM imajı tamamlandı: %d bayt, %d parça, verified=%s",
                written, len(chunks), result.verified_continuous,
            )
            return result
        except AcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="RamImager.acquire")
            raise AcquisitionError(f"RAM imajı alınamadı: {exc}") from exc
        finally:
            self._running = False
            if stdout is not None:
                try:
                    stdout.channel.close()
                except Exception:  # noqa: BLE001
                    pass
            # Uzak temp temizliği (marker + varsa geçici avml)
            self._cleanup_remote_temp()
