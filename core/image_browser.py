"""İmaj dosyası gezgini — FTK Imager benzeri.

Bir yerel imaj (.dd/.raw/.001/.E01) dosyasını salt-okunur açar; içindeki
partition/filesystem yapısını ağaç halinde, seçili dizindeki dosyaları
liste halinde ve seçili dosyanın ilk N baytını hex+ASCII olarak sunar.

Backend'ler:
    - pytsk3 (SleuthKit) : Tam dosya sistemi (NTFS/FAT/EXT/HFS+/APFS…)
    - pyewf              : E01 desteği (pytsk3 ile birlikte)
    - fallback           : Ham imza taraması modu (klasik dosya listesi yok)

Bu modül GUI tarafı için basit, tipli bir facade sağlar; gerçek karmaşık
işi pytsk3 (varsa) yapar. Silinmiş dosyaları da (varsa) listeler.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from core.error_handler import YTIError, log_exception
from core.file_signatures import (
    FOOTER_SIGNATURES,
    guess_type,
    has_footer_mismatch,
    is_bad_extension,
)
from logs.logger import get_logger

logger = get_logger("image_browser")


class ImageBrowserError(YTIError):
    """İmaj gezgininde oluşan hatalar."""


@dataclass
class BrowserNode:
    """Ağaç düğümü — partition veya klasör."""

    name: str
    kind: str = "partition"  # image | partition | unpartitioned | unallocated | dir
    fs_type: str = ""
    offset_bytes: int = 0
    size_bytes: int = 0
    partition_id: int = -1  # tsk part.addr — dosya listeleme için
    path: str = "/"  # bu düğümün dosya sistemi içindeki yolu (dir için)


@dataclass
class BrowserFile:
    """Dosya listesi girişi."""

    name: str
    is_dir: bool = False
    size_bytes: int = 0
    deleted: bool = False
    accessed: str = ""  # ISO
    created: str = ""
    modified: str = ""
    fs_path: str = ""  # dosya sistemi içindeki tam yol
    detected_type: str = ""
    detected_extensions: Tuple[str, ...] = ()
    bad_extension: bool = False
    footer_mismatch: bool = False
    meta_addr: int = 0  # tsk inode/mft numarası — hex okumak için
    partition_id: int = -1
    partition_offset: int = 0


def _iso(ts: Optional[int]) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (OSError, ValueError, OverflowError):
        return ""


class ImageBrowser:
    """Bir imaj dosyasını açık tutar; GUI'nin ağaç/dosya/hex sorgularına yanıt verir."""

    def __init__(self) -> None:
        self.image_path: str = ""
        self.image_format: str = "raw"  # raw | e01
        self.backend: str = "raw-scan"
        self._img = None  # pytsk3.Img_Info or EWFImgInfo
        self._ewf = None  # pyewf handle
        self._fs_cache: dict = {}  # partition_id -> FS_Info
        self._nodes: List[BrowserNode] = []
        self._tsk_available = False
        self._ewf_available = False
        try:
            import pytsk3  # noqa: F401

            self._tsk_available = True
        except Exception:
            pass
        try:
            import pyewf  # noqa: F401

            self._ewf_available = True
        except Exception:
            pass

    # --- Açma / Kapatma ---------------------------------------------------
    def open(self, image_path: str) -> List[BrowserNode]:
        """İmajı salt-okunur açar; kök ağaç düğümlerini döndürür."""
        if not os.path.exists(image_path):
            raise ImageBrowserError(f"İmaj dosyası bulunamadı: {image_path}")
        self.close()
        self.image_path = image_path
        lower = image_path.lower()
        if lower.endswith((".e01", ".ex01")):
            self.image_format = "e01"
        else:
            self.image_format = "raw"

        if not self._tsk_available:
            # Fallback: sadece imaj kök düğümü + "Unpartitioned Space"
            self.backend = "raw-scan"
            size = os.path.getsize(image_path)
            self._nodes = [
                BrowserNode(
                    name=os.path.basename(image_path),
                    kind="image",
                    size_bytes=size,
                    partition_id=-1,
                ),
                BrowserNode(
                    name="Unpartitioned Space",
                    kind="unpartitioned",
                    size_bytes=size,
                    partition_id=-2,
                ),
            ]
            return self._nodes

        try:
            self._open_tsk()
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="ImageBrowser.open(tsk)")
            # Fallback moda düş.
            self.backend = "raw-scan"
            size = os.path.getsize(image_path)
            self._nodes = [
                BrowserNode(
                    name=os.path.basename(image_path),
                    kind="image",
                    size_bytes=size,
                    partition_id=-1,
                ),
                BrowserNode(
                    name="Unpartitioned Space",
                    kind="unpartitioned",
                    size_bytes=size,
                    partition_id=-2,
                ),
            ]
        return self._nodes

    def _open_tsk(self) -> None:
        import pytsk3

        if self.image_format == "e01" and self._ewf_available:
            import pyewf

            self.backend = "tsk+ewf"
            filenames = pyewf.glob(self.image_path)
            self._ewf = pyewf.handle()
            self._ewf.open(filenames)

            class EWFImgInfo(pytsk3.Img_Info):

                def __init__(self, h):
                    self._h = h
                    super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

                def close(self):
                    pass

                def read(self, off, sz):
                    self._h.seek(off)
                    return self._h.read(sz)

                def get_size(self):
                    return self._h.get_media_size()

            self._img = EWFImgInfo(self._ewf)
        else:
            self.backend = "tsk"
            self._img = pytsk3.Img_Info(self.image_path)

        # Kök: imaj + partition'lar
        nodes = [
            BrowserNode(
                name=os.path.basename(self.image_path),
                kind="image",
                size_bytes=self._img.get_size(),
                partition_id=-1,
            )
        ]
        try:
            vol = pytsk3.Volume_Info(self._img)
            for part in vol:
                # Boş / meta partition'ları atla ama boş alan olarak göster
                if part.len < 2:
                    nodes.append(
                        BrowserNode(
                            name=f"Unallocated ({part.desc.decode('utf-8', errors='ignore')})",
                            kind="unallocated",
                            offset_bytes=part.start * 512,
                            size_bytes=part.len * 512,
                            partition_id=part.addr,
                        )
                    )
                    continue
                fs_type = ""
                try:
                    fs = pytsk3.FS_Info(self._img, offset=part.start * 512)
                    self._fs_cache[part.addr] = fs
                    fs_type = self._fs_name(fs)
                except OSError:
                    fs_type = self._guess_unknown_fs(part.start * 512)
                desc = (
                    part.desc.decode("utf-8", errors="ignore")
                    if part.desc
                    else ""
                )
                label = f"Partition {part.addr + 1}: {fs_type}"
                if desc:
                    label += f" — {desc}"
                nodes.append(
                    BrowserNode(
                        name=label,
                        kind="partition",
                        fs_type=fs_type,
                        offset_bytes=part.start * 512,
                        size_bytes=part.len * 512,
                        partition_id=part.addr,
                        path="/",
                    )
                )
        except OSError:
            # Volume yok — tek partition/fs dene.
            try:
                fs = pytsk3.FS_Info(self._img)
                self._fs_cache[0] = fs
                fs_type = self._fs_name(fs)
                nodes.append(
                    BrowserNode(
                        name=f"Partition 1: {fs_type}",
                        kind="partition",
                        fs_type=fs_type,
                        offset_bytes=0,
                        size_bytes=self._img.get_size(),
                        partition_id=0,
                        path="/",
                    )
                )
            except OSError:
                nodes.append(
                    BrowserNode(
                        name="Unpartitioned Space",
                        kind="unpartitioned",
                        size_bytes=self._img.get_size(),
                        partition_id=-2,
                    )
                )
        self._nodes = nodes

    @staticmethod
    def _fs_name(fs) -> str:
        """fs.info.ftype değerini pytsk3'ün GERÇEK TSK_FS_TYPE_* sabitleriyle
        dinamik eşleştirir. Eski kod elle yazılmış 1,2,3... gibi sıralı bir
        tablo kullanıyordu; TSK'nin gerçek sabitleri bit-bayrak (bitmask)
        değerleridir, o yüzden çoğu dosya sistemi yanlış/eksik gösteriliyordu.
        """
        try:
            import pytsk3

            info = fs.info
            t = getattr(info, "ftype", None)
            if not t:
                return "unknown"
            for const_name in dir(pytsk3):
                if not const_name.startswith("TSK_FS_TYPE_"):
                    continue
                if const_name.endswith("_DETECT"):
                    # *_DETECT sabitleri birden çok tipi kapsayan bileşik
                    # maskelerdir (örn. FAT_DETECT = FAT12|FAT16|FAT32),
                    # gerçek/tekil tip değildir — atla.
                    continue
                if getattr(pytsk3, const_name) == t:
                    return const_name[len("TSK_FS_TYPE_") :]
            return f"unknown(0x{int(t):x})"
        except Exception:  # noqa: BLE001
            return "unknown"

    def _guess_unknown_fs(self, offset_bytes: int) -> str:
        """FS_Info açılamayan bir alan için ham imzalara bakarak en iyi
        tahmini döndürür. pytsk3/libtsk LVM'i native ayrıştıramaz; bu yüzden
        bir LVM Physical Volume'u sadece "(bilinmiyor)" demek yerine doğru
        adlandırıp kullanıcıyı yanıltmamak için buradaki imza kontrolü var.
        """
        try:
            head = self._img.read(offset_bytes, 4096)
        except Exception:  # noqa: BLE001
            return "(bilinmiyor)"
        if not head:
            return "(bilinmiyor)"
        # LVM2 Physical Volume label'ı ilk sektörlerde "LABELONE" ile başlar.
        if b"LABELONE" in head[:1024]:
            return "LVM2 Physical Volume (ayrıştırma desteklenmiyor)"
        # Linux swap imzası, sayfa boyutunun son 10 baytında bulunur
        # (yaygın olarak 4 KiB sayfa varsayılır — farklı sayfa boyutunda
        # bu kontrol kaçırabilir, bu yüzden kesin değil, en iyi tahmindir).
        if head[4086:4096] in (b"SWAPSPACE2", b"SWAP-SPACE"):
            return "Linux Swap"
        if all(b == 0 for b in head[:64]):
            return "(bilinmiyor — muhtemelen boş/ayrıştırılmamış alan)"
        return "(bilinmiyor)"

    def close(self) -> None:
        try:
            if self._ewf is not None:
                self._ewf.close()
        except Exception:  # noqa: BLE001
            pass
        self._ewf = None
        self._img = None
        self._fs_cache.clear()
        self._nodes = []

    # --- Dosya listesi ----------------------------------------------------
    def list_dir(
        self, partition_id: int, path: str = "/"
    ) -> List[BrowserFile]:
        """Bir partition'ın verilen dizinini listeler. Silinmiş dosyaları da içerir."""
        if not self._tsk_available or partition_id < 0:
            return self._list_dir_fallback()
        import pytsk3

        fs = self._fs_cache.get(partition_id)
        if fs is None:
            return []
        try:
            directory = fs.open_dir(path=path)
        except OSError:
            return []
        results: List[BrowserFile] = []
        for entry in directory:
            if not hasattr(entry, "info") or entry.info.name is None:
                continue
            try:
                name = entry.info.name.name.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if name in (".", ".."):
                continue
            meta = entry.info.meta
            # Silinmiş: name flags TSK_FS_NAME_FLAG_UNALLOC == 2
            deleted = bool(entry.info.name.flags & 2)
            if meta is None:
                # Silinmiş ve meta yok
                bf = BrowserFile(
                    name=name,
                    deleted=deleted,
                    partition_id=partition_id,
                    fs_path=(path.rstrip("/") + "/" + name),
                )
                results.append(bf)
                continue
            is_dir = meta.type == 2
            size = int(getattr(meta, "size", 0) or 0)
            bf = BrowserFile(
                name=name,
                is_dir=is_dir,
                size_bytes=size,
                deleted=deleted,
                accessed=_iso(getattr(meta, "atime", 0)),
                created=_iso(
                    getattr(meta, "crtime", 0) or getattr(meta, "ctime", 0)
                ),
                modified=_iso(getattr(meta, "mtime", 0)),
                fs_path=(path.rstrip("/") + "/" + name),
                meta_addr=int(getattr(meta, "addr", 0) or 0),
                partition_id=partition_id,
                partition_offset=self._get_partition_offset(partition_id),
            )
            # İlk 32 bayttan magic tespit (dosyaysa).
            if not is_dir and size > 0:
                try:
                    head = entry.read_random(0, min(32, size))
                    actual, exts = guess_type(head)
                    bf.detected_type = actual
                    bf.detected_extensions = exts
                    bf.bad_extension = is_bad_extension(actual, exts, name)
                    if actual in FOOTER_SIGNATURES:
                        tail_len = min(32, size)
                        tail = entry.read_random(
                            max(0, size - tail_len), tail_len
                        )
                        bf.footer_mismatch = has_footer_mismatch(actual, tail)
                except OSError:
                    pass
            results.append(bf)
        # Klasörler önce
        results.sort(key=lambda x: (not x.is_dir, x.name.lower()))
        return results

    def has_subdirs(self, partition_id: int, path: str = "/") -> bool:
        """Bir dizinin en az bir alt klasör içerip içermediğini hızlıca
        kontrol eder (tam listeleme yapmadan)."""
        if not self._tsk_available or partition_id < 0:
            return False
        fs = self._fs_cache.get(partition_id)
        if fs is None:
            return False
        try:
            directory = fs.open_dir(path=path)
        except OSError:
            return False
        for entry in directory:
            if not hasattr(entry, "info") or entry.info.name is None:
                continue
            try:
                name = entry.info.name.name.decode("utf-8", errors="replace")
            except Exception:
                continue
            if name in (".", ".."):
                continue
            meta = entry.info.meta
            if meta is None:
                continue
            if meta.type == 2:
                return True
        return False

    def _get_partition_offset(self, partition_id: int) -> int:
        for n in self._nodes:
            if n.partition_id == partition_id:
                return n.offset_bytes
        return 0

    def _list_dir_fallback(
        self,
        max_bytes: int = 0,
        max_files: int = 20000,
        step: int = 4096,
        progress_callback=None,
        cancel_flag=None,
    ) -> List[BrowserFile]:
        """pytsk3 yok — imza taraması ile sanal dosya listesi (offset bazlı).

        - ``max_bytes=0`` verilirse imajın tamamı taranır.
        - ``step`` = 4096: 4 KiB sektörlerin başlangıcını tarar (hızlı).
        - Aşırı büyük imajlarda (100+ GB) ``step=65536`` kullanılabilir.
        - ``progress_callback(pos, total)`` düzenli çağrılır.
        - ``cancel_flag`` = ``lambda: bool`` verilirse tarama iptal edilebilir.
        """
        from core.file_signatures import KNOWN_SIGNATURES

        results: List[BrowserFile] = []
        try:
            with open(self.image_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                total = fh.tell()
                fh.seek(0)
                limit = total if max_bytes <= 0 else min(total, max_bytes)
                pos = 0
                # Daha büyük buffer: 1 MiB oku, içinde 4 KiB adım at.
                buf_size = 1024 * 1024
                last_report = 0
                while pos < limit and len(results) < max_files:
                    if cancel_flag is not None and cancel_flag():
                        break
                    fh.seek(pos)
                    buf = fh.read(min(buf_size, limit - pos))
                    if not buf:
                        break
                    # Buffer içinde adım adım tara.
                    for offset in range(0, len(buf), step):
                        head = buf[offset : offset + 32]
                        if len(head) < 2:
                            continue
                        for sig in KNOWN_SIGNATURES:
                            for magic in sig.magics:
                                if head.startswith(magic):
                                    abs_pos = pos + offset
                                    ext = (
                                        sig.extensions[0]
                                        if sig.extensions
                                        else ".bin"
                                    )
                                    results.append(
                                        BrowserFile(
                                            name=f"offset_{abs_pos:012d}{ext}",
                                            is_dir=False,
                                            size_bytes=0,
                                            fs_path=f"@offset:{abs_pos}",
                                            detected_type=sig.name,
                                            detected_extensions=sig.extensions,
                                            partition_id=-2,
                                            partition_offset=abs_pos,
                                        )
                                    )
                                    if len(results) >= max_files:
                                        break
                            if len(results) >= max_files:
                                break
                    pos += len(buf)
                    # Progress her 32 MB'ta bir
                    if (
                        progress_callback is not None
                        and (pos - last_report) >= 32 * 1024 * 1024
                    ):
                        progress_callback(pos, limit)
                        last_report = pos
                if progress_callback is not None:
                    progress_callback(pos, limit)
        except OSError:
            pass
        return results

    def scan_fallback(
        self,
        max_bytes: int = 0,
        max_files: int = 20000,
        step: int = 4096,
        progress_callback=None,
        cancel_flag=None,
    ) -> List[BrowserFile]:
        """Public API — fallback (imza taraması) modunu tetikler."""
        return self._list_dir_fallback(
            max_bytes=max_bytes,
            max_files=max_files,
            step=step,
            progress_callback=progress_callback,
            cancel_flag=cancel_flag,
        )

    def has_tsk(self) -> bool:
        """pytsk3 kurulu mu."""
        return self._tsk_available

    def has_ewf(self) -> bool:
        """pyewf kurulu mu."""
        return self._ewf_available

    # --- Hex okuma --------------------------------------------------------
    def read_bytes(
        self, bf: BrowserFile, offset: int = 0, length: int = 4096
    ) -> bytes:
        """Bir dosyanın veya offset'in ham baytlarını salt-okunur okur."""
        if bf.partition_id == -2:
            # Fallback offset — doğrudan imajdan oku.
            try:
                with open(self.image_path, "rb") as fh:
                    fh.seek(bf.partition_offset + offset)
                    return fh.read(length)
            except OSError:
                return b""
        if not self._tsk_available:
            return b""
        fs = self._fs_cache.get(bf.partition_id)
        if fs is None:
            return b""
        try:
            # meta_addr veya path ile aç.
            if bf.meta_addr:
                f = fs.open_meta(inode=bf.meta_addr)
            else:
                f = fs.open(bf.fs_path)
            return f.read_random(
                offset, min(length, max(bf.size_bytes - offset, length))
            )
        except Exception:  # noqa: BLE001
            return b""


def format_hex_dump(
    data: bytes, base_offset: int = 0, width: int = 16
) -> str:
    """FTK-tarzı hex+ASCII dump (offset | hex | ASCII)."""
    lines: List[str] = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hex_part = " ".join(f"{b:02X}" for b in chunk)
        # Sağa doldur (kısa son satır)
        hex_part = hex_part.ljust(width * 3 - 1)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base_offset + i:08X}  {hex_part}  {ascii_part}")
    return "\n".join(lines)