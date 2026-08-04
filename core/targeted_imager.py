"""Custom Content / Targeted (triage) imajlama modülü.

Uzak sistemde uzantı ve/veya dosya imzası (magic number) tabanlı hedefli
tarama yapar; eşleşen dosyaları listeler ve isteğe bağlı olarak yerel hedef
klasöre kopyalar (salt-okunur okuma; hedef sisteme YAZMA YOK).

Ayrıca "bad extension" tespiti yapar: dosyanın uzantısı ile gerçek türü
uyuşmuyorsa işaretler.

Tüm SSH komutları paylaşılan ``WriteBlocker``'dan geçer (SSHConnector içi).
"""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from core.error_handler import AcquisitionError, log_exception
from core.file_signatures import guess_type, is_bad_extension
from core.os_detector import OSType
from core.ssh_connector import SSHConnector
from logs.logger import get_logger

logger = get_logger("targeted_imager")

ProgressCallback = Callable[[int, Optional[int]], None]


@dataclass
class TargetedRule:
    """Bir tarama kuralı: uzantı seti VE/VEYA imza kontrolü."""

    name: str = "custom"
    extensions: Tuple[str, ...] = ()  # ör: (".pdf", ".docx")
    use_signature_match: bool = True  # dosya imzası da kontrol edilsin mi?
    max_size_bytes: int = 500 * 1024 * 1024  # tek dosya için üst sınır (kopya)


@dataclass
class TargetedFileHit:
    """Bulunan bir dosya kaydı."""

    remote_path: str
    size_bytes: int
    detected_type: str = ""
    detected_extensions: Tuple[str, ...] = ()
    bad_extension: bool = False
    copied_to: str = ""


@dataclass
class TargetedResult:
    """Targeted imaging sonucu."""

    hits: List[TargetedFileHit] = field(default_factory=list)
    total_bytes_copied: int = 0
    bad_extension_count: int = 0
    scanned_paths: int = 0


class TargetedImager:
    """Uzak sistemde hedefli dosya arama, imza doğrulama ve kopya alma."""

    HEAD_BYTES = 32  # imza tespiti için okunan ilk N bayt

    def __init__(
        self,
        ssh: SSHConnector,
        os_type: OSType = OSType.LINUX,
    ) -> None:
        self.ssh = ssh
        self.os_type = os_type
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # --- Listeleme ----------------------------------------------------------
    def list_files(
        self,
        remote_root: str,
        extensions: Tuple[str, ...] = (),
        max_depth: int = 10,
    ) -> List[Tuple[str, int]]:
        """Uzak sistemden dosya listesini alır.

        Returns:
            [(remote_path, size_bytes), ...]
        """
        if self.os_type == OSType.WINDOWS:
            return self._list_windows(remote_root, extensions)
        return self._list_posix(remote_root, extensions, max_depth)

    def _list_posix(
        self,
        remote_root: str,
        extensions: Tuple[str, ...],
        max_depth: int,
    ) -> List[Tuple[str, int]]:
        # find whitelist'te. -printf ile boyut alırız.
        depth_flag = f"-maxdepth {max_depth} " if max_depth > 0 else ""
        if extensions:
            # -iname birleşimi
            expr = " -o ".join([f'-iname "*{e}"' for e in extensions])
            find_cmd = (
                f"find {remote_root} {depth_flag}-type f "
                f"\\( {expr} \\) -printf '%s\\t%p\\n'"
            )
        else:
            find_cmd = (
                f"find {remote_root} {depth_flag}-type f -printf '%s\\t%p\\n'"
            )
        out, err, code = self.ssh.exec_command(find_cmd)
        if code != 0:
            logger.warning("find başarısız (%s): %s", remote_root, err.strip())
        results: List[Tuple[str, int]] = []
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0])
            except ValueError:
                continue
            results.append((parts[1], size))
        return results

    def _list_windows(
        self,
        remote_root: str,
        extensions: Tuple[str, ...],
    ) -> List[Tuple[str, int]]:
        # PowerShell Get-ChildItem -Recurse
        if extensions:
            includes = ",".join([f"'*{e}'" for e in extensions])
            ps = (
                f"powershell -NoProfile -Command "
                f"\"Get-ChildItem -Path '{remote_root}' -Recurse -File "
                f"-Include {includes} -ErrorAction SilentlyContinue | "
                f"ForEach-Object {{ '{{0}}`t{{1}}' -f $_.Length, $_.FullName }}\""
            )
        else:
            ps = (
                f"powershell -NoProfile -Command "
                f"\"Get-ChildItem -Path '{remote_root}' -Recurse -File "
                f"-ErrorAction SilentlyContinue | "
                f"ForEach-Object {{ '{{0}}`t{{1}}' -f $_.Length, $_.FullName }}\""
            )
        out, err, code = self.ssh.exec_command(ps)
        if code != 0:
            logger.warning("Get-ChildItem başarısız: %s", err.strip())
        results: List[Tuple[str, int]] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = re.split(r"\s+", line, maxsplit=1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0])
            except ValueError:
                continue
            results.append((parts[1], size))
        return results

    # --- İmza okuma ---------------------------------------------------------
    def _read_head_bytes(self, remote_path: str) -> bytes:
        """Uzak dosyanın ilk N baytını okur (salt-okunur)."""
        if self.os_type == OSType.WINDOWS:
            # PowerShell ile ilk 32 bayt, hex.
            ps = (
                f"powershell -NoProfile -Command "
                f"\"$b = Get-Content -Path '{remote_path}' -Encoding Byte "
                f"-TotalCount {self.HEAD_BYTES} -ErrorAction SilentlyContinue; "
                f"if ($b) {{ ($b | ForEach-Object {{ '{{0:x2}}' -f $_ }}) -join '' }}\""
            )
            out, _, code = self.ssh.exec_command(ps)
            if code != 0:
                return b""
            hex_str = out.strip()
        else:
            # xxd whitelist'te
            cmd = f'head -c {self.HEAD_BYTES} "{remote_path}" | xxd -p -c {self.HEAD_BYTES}'
            out, _, code = self.ssh.exec_command(cmd)
            if code != 0:
                return b""
            hex_str = out.strip().replace("\n", "")
        try:
            return bytes.fromhex(hex_str) if hex_str else b""
        except ValueError:
            return b""

    # --- Ana akış -----------------------------------------------------------
    def scan(
        self,
        remote_root: str,
        rule: TargetedRule,
        output_dir: str = "",
        copy_files: bool = False,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TargetedResult:
        """Kuralı uygular; eşleşen dosyaları toplar, isteğe bağlı yerel kopyalar.

        Args:
            remote_root: Uzak sistemde tarama kökü.
            rule: Uygulanacak tarama kuralı.
            output_dir: Kopya hedefi (yerel).
            copy_files: True ise eşleşenler yerel ``output_dir`` altına kopyalanır.
        """
        result = TargetedResult()
        listing = self.list_files(remote_root, rule.extensions)
        result.scanned_paths = len(listing)
        logger.info("Targeted tarama: %s -> %d dosya bulundu.", remote_root, len(listing))

        for idx, (rpath, size) in enumerate(listing, start=1):
            if self._cancelled:
                raise AcquisitionError("Targeted tarama iptal edildi.")
            hit = TargetedFileHit(remote_path=rpath, size_bytes=size)
            if rule.use_signature_match:
                head = self._read_head_bytes(rpath)
                actual, exts = guess_type(head)
                hit.detected_type = actual
                hit.detected_extensions = exts
                hit.bad_extension = is_bad_extension(actual, exts, rpath)
                if hit.bad_extension:
                    result.bad_extension_count += 1
            result.hits.append(hit)

            if copy_files and output_dir and size <= rule.max_size_bytes:
                try:
                    local_path = self._copy_remote_file(rpath, output_dir)
                    hit.copied_to = local_path
                    result.total_bytes_copied += size
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Dosya kopyalanamadı %s: %s", rpath, exc)

            if progress_callback is not None:
                progress_callback(idx, len(listing))

        logger.info(
            "Targeted tamamlandı: %d dosya, %d bad-extension, %d bayt kopyalandı.",
            len(result.hits), result.bad_extension_count, result.total_bytes_copied,
        )
        return result

    def _copy_remote_file(self, remote_path: str, output_dir: str) -> str:
        """Uzak dosyayı yerel hedefe salt-okunur okuyup kopyalar (cat/type)."""
        os.makedirs(output_dir, exist_ok=True)
        # Yerel dosya adı: uzak yol düzleştirilir.
        flat = remote_path.replace("\\", "/").lstrip("/").replace("/", "__")
        local_path = os.path.join(output_dir, flat)

        if self.os_type == OSType.WINDOWS:
            # 'type' Windows'ta text için; binary güvenli değil.
            # PowerShell Get-Content -Encoding Byte kullanalım — ancak stdout base64 daha güvenli.
            ps = (
                f"powershell -NoProfile -Command "
                f"\"[Convert]::ToBase64String((Get-Content -Path '{remote_path}' "
                f"-Encoding Byte -ReadCount 0))\""
            )
            out, err, code = self.ssh.exec_command(ps, timeout=None)
            if code != 0:
                raise AcquisitionError(f"Dosya okunamadı: {err.strip()}")
            import base64
            data = base64.b64decode(out.strip())
            with open(local_path, "wb") as fh:
                fh.write(data)
        else:
            # cat ile stream olarak oku.
            stdout, _stderr = self.ssh.open_read_stream(f'cat "{remote_path}"')
            try:
                with open(local_path, "wb") as fh:
                    while True:
                        chunk = stdout.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    raise AcquisitionError(f"cat başarısız (kod {exit_status})")
            finally:
                try:
                    stdout.channel.close()
                except Exception:  # noqa: BLE001
                    pass
        return local_path
