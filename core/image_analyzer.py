"""Yerel imaj (RAW/E01/AFF) inceleme modulu.

Adli bilisim inceleyicisinin daha once alinmis bir imaj dosyasini
salt-okunur acip icindeki dosya sistemini kesfetmesini saglar.

Bu modul SSH GEREKTIRMEZ - yerel imaj dosyasi uzerinde calisir. Yine de
imaj dosyasi hicbir zaman WRITE modunda acilmaz.

Desteklenen backend'ler (varsa):
  - pytsk3 (SleuthKit)  : Tam dosya sistemi agaci (NTFS/FAT/EXT/HFS+/APFS...)
                          Not: guncel SleuthKit surumleri libewf ile derlenmisse
                          E01 imajlarini pyewf OLMADAN da native acabilir.
  - pyewf              : E01 imajlarini RAW gibi sunar (pytsk3'e baglanir),
                          native acma basarisiz olursa yedek yol olarak kullanilir.
  - pyaff              : AFF icin

Hicbiri kurulu degilse "raw hex onizleme + hizli imza taramasi" moduna duser.
Bad extension isaretlemesi icin ``core.file_signatures`` kullanilir.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from core.error_handler import log_exception, YTIError
from core.file_signatures import guess_type, is_bad_extension, has_footer_mismatch, FOOTER_SIGNATURES
from logs.logger import get_logger

logger = get_logger("image_analyzer")


class ImageAnalysisError(YTIError):
    """Imaj inceleme sirasinda olusan hatalar."""


@dataclass
class AnalyzedFile:
    """Imaj icindeki bir dosya girisi."""

    path: str
    size_bytes: int
    is_dir: bool = False
    detected_type: str = ""
    detected_extensions: Tuple[str, ...] = ()
    bad_extension: bool = False
    footer_mismatch: bool = False


@dataclass
class ImageAnalysisResult:
    """Inceleme sonucu."""

    image_path: str
    image_format: str = "raw"   # raw | e01 | aff
    backend: str = "raw-scan"   # tsk | tsk+ewf | tsk-native-ewf | raw-scan
    files: List[AnalyzedFile] = field(default_factory=list)
    bad_extension_files: List[AnalyzedFile] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _detect_image_format(path: str) -> str:
    """Uzanti + magic'e gore imaj formati tahmini."""
    lower = path.lower()
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        head = b""
    if head.startswith(b"EVF\x09\x0d\x0a\xff\x00") or lower.endswith((".e01", ".ex01")):
        return "e01"
    if head.startswith(b"AFF10") or lower.endswith((".aff", ".afd", ".afm")):
        return "aff"
    return "raw"


class ImageAnalyzer:
    """Yerel imaj dosyalarini salt-okunur inceleyen sinif."""

    def __init__(self) -> None:
        self._tsk_available = False
        self._ewf_available = False
        try:
            import pytsk3  # noqa: F401
            self._tsk_available = True
        except Exception:  # noqa: BLE001
            pass
        try:
            import pyewf  # noqa: F401
            self._ewf_available = True
        except Exception:  # noqa: BLE001
            pass

    # --- Ana giris ----------------------------------------------------------
    def analyze(
        self,
        image_path: str,
        max_files: int = 5000,
    ) -> ImageAnalysisResult:
        """Imaj dosyasini acip icerik listesini dondurur."""
        if not os.path.exists(image_path):
            raise ImageAnalysisError(f"Imaj dosyasi bulunamadi: {image_path}")
        # Imaj HER ZAMAN salt-okunur acilir. Asagidaki tum alt akislarda 'rb' zorunlu.

        fmt = _detect_image_format(image_path)
        result = ImageAnalysisResult(image_path=image_path, image_format=fmt)

        try:
            if self._tsk_available and fmt == "raw":
                self._analyze_with_tsk_raw(image_path, result, max_files)
            elif self._tsk_available and fmt == "e01":
                self._analyze_with_tsk_e01_native(image_path, result, max_files)
            else:
                # Backend yoksa: ham imza taramasi yap.
                self._analyze_raw_scan(image_path, result, max_files)

            # Bad extension ozet listesi.
            result.bad_extension_files = [f for f in result.files if f.bad_extension]
            logger.info(
                "Imaj incelendi: %s (backend=%s, %d dosya, %d bad-ext).",
                image_path, result.backend, len(result.files),
                len(result.bad_extension_files),
            )
            return result
        except ImageAnalysisError:
            raise
        except Exception as exc:  # noqa: BLE001
            log_exception(exc, context="ImageAnalyzer.analyze")
            raise ImageAnalysisError(f"Imaj incelenemedi: {exc}") from exc

    # --- Hedefli cikarma (yerel imajdan yeni imaj/klasor) ------------------
    def extract_by_extensions(
        self,
        image_path: str,
        output_dir: str,
        extensions: Tuple[str, ...],
        max_files: int = 5000,
        progress_callback=None,
    ) -> ImageAnalysisResult:
        """Verilen imaj dosyasindan yalnizca secilen uzantilara uyan
        dosyalari ``output_dir`` altina yeni bir imaj/klasor olarak cikarir.

        - Kaynak imaj her zaman salt-okunur acilir.
        - Her dosya icin magic number ile bad extension tespiti yapilir.
        - Sonuc: ``ImageAnalysisResult`` (yalnizca eslesen ve
          kopyalanan dosyalarin girisleri) + ``notes`` istatistikleri.
        """
        if not os.path.exists(image_path):
            raise ImageAnalysisError(f"Imaj dosyasi bulunamadi: {image_path}")
        os.makedirs(output_dir, exist_ok=True)
        exts_lower = tuple(e.lower() for e in extensions)
        fmt = _detect_image_format(image_path)
        result = ImageAnalysisResult(image_path=image_path, image_format=fmt)
        if self._tsk_available and fmt == "raw":
            self._extract_tsk_raw(image_path, output_dir, exts_lower,
                                  result, max_files, progress_callback)
        elif self._tsk_available and self._ewf_available and fmt == "e01":
            self._extract_tsk_ewf(image_path, output_dir, exts_lower,
                                  result, max_files, progress_callback)
        else:
            # Backend yok: karver (carver) - imza taramasi ile cikarma.
            self._extract_raw_scan(image_path, output_dir, exts_lower,
                                   result, max_files, progress_callback)
        result.bad_extension_files = [f for f in result.files if f.bad_extension]
        return result

    def _extract_tsk_raw(self, image_path, output_dir, exts,
                         result, max_files, progress_callback) -> None:
        import pytsk3
        result.backend = "tsk"
        img = pytsk3.Img_Info(image_path)
        try:
            vol = pytsk3.Volume_Info(img)
            for part in vol:
                if part.len < 2:
                    continue
                try:
                    fs = pytsk3.FS_Info(img, offset=part.start * 512)
                except OSError:
                    continue
                self._walk_and_extract(
                    fs, f"/part{part.addr}", output_dir, exts,
                    result, max_files, progress_callback,
                )
        except OSError:
            fs = pytsk3.FS_Info(img)
            self._walk_and_extract(
                fs, "", output_dir, exts, result, max_files, progress_callback,
            )

    def _extract_tsk_ewf(self, image_path, output_dir, exts,
                         result, max_files, progress_callback) -> None:
        import pyewf, pytsk3
        result.backend = "tsk+ewf"
        filenames = pyewf.glob(image_path)
        ewf_handle = pyewf.handle()
        ewf_handle.open(filenames)

        class EWFImgInfo(pytsk3.Img_Info):
            def __init__(self, h):
                self._h = h
                super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)
            def close(self): self._h.close()
            def read(self, off, sz):
                self._h.seek(off); return self._h.read(sz)
            def get_size(self): return self._h.get_media_size()

        img = EWFImgInfo(ewf_handle)
        try:
            vol = pytsk3.Volume_Info(img)
            for part in vol:
                if part.len < 2: continue
                try:
                    fs = pytsk3.FS_Info(img, offset=part.start * 512)
                except OSError:
                    continue
                self._walk_and_extract(
                    fs, f"/part{part.addr}", output_dir, exts,
                    result, max_files, progress_callback,
                )
        except OSError:
            fs = pytsk3.FS_Info(img)
            self._walk_and_extract(
                fs, "", output_dir, exts, result, max_files, progress_callback,
            )

    def _walk_and_extract(self, fs, prefix, output_dir, exts,
                          result, max_files, progress_callback,
                          path: str = "/") -> None:
        if len(result.files) >= max_files:
            return
        try:
            directory = fs.open_dir(path=path)
        except OSError:
            return
        for entry in directory:
            if len(result.files) >= max_files:
                return
            if not hasattr(entry, "info") or entry.info.name is None:
                continue
            try:
                name = entry.info.name.name.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if name in (".", ".."):
                continue
            meta = entry.info.meta
            if meta is None:
                continue
            full = f"{prefix}{path.rstrip('/')}/{name}"
            is_dir = meta.type == 2
            if is_dir:
                self._walk_and_extract(
                    fs, prefix, output_dir, exts, result, max_files,
                    progress_callback, path.rstrip("/") + "/" + name,
                )
                continue
            size = int(meta.size)
            low = name.lower()
            # Uzanti filtresi
            if exts:
                if "." not in low:
                    continue
                ext = "." + low.rsplit(".", 1)[-1]
                if ext not in exts:
                    continue
            # Kopyala
            flat = full.lstrip("/").replace("/", "__")
            out_path = os.path.join(output_dir, flat)
            try:
                data = entry.read_random(0, size) if size else b""
                with open(out_path, "wb") as fh:
                    fh.write(data)
            except OSError:
                continue
            head = data[:32] if data else b""
            actual, sig_exts = guess_type(head)
            bad = is_bad_extension(actual, sig_exts, name)
            af = AnalyzedFile(
                path=full, size_bytes=size, is_dir=False,
                detected_type=actual, detected_extensions=sig_exts,
                bad_extension=bad,
            )
            result.files.append(af)
            if progress_callback is not None:
                progress_callback(len(result.files), None)

    def _extract_raw_scan(self, image_path, output_dir, exts,
                          result, max_files, progress_callback) -> None:
        """pytsk3 yok ya da dosya sistemi bulunamadi: imza taramasiyla carver
        moduna gec. Uzanti filtresi bu modda 'imza uzantilari' olarak
        yorumlanir: secili uzantilara karsilik gelen imzalar aranir.
        """
        from core.file_signatures import KNOWN_SIGNATURES
        result.backend = "raw-scan"
        if self._tsk_available:
            result.notes.append(
                "Dosya sistemi tespit edilemedi - imza (magic) taramasi ile "
                "carver moduna gecildi."
            )
        else:
            result.notes.append(
                "pytsk3 kurulu degil - dosya sistemi agaci yok. "
                "Imza (magic) taramasi ile carver moduna gecildi."
            )
        # Hangi imzalar secilen uzantilari icerir?
        active_sigs = []
        if exts:
            for sig in KNOWN_SIGNATURES:
                if any(e in exts for e in sig.extensions):
                    active_sigs.append(sig)
        else:
            active_sigs = list(KNOWN_SIGNATURES)
        step = 4096
        max_bytes = 512 * 1024 * 1024
        try:
            with open(image_path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                total = fh.tell()
                fh.seek(0)
                limit = min(total, max_bytes)
                pos = 0
                while pos < limit and len(result.files) < max_files:
                    fh.seek(pos)
                    head = fh.read(64)
                    if not head:
                        break
                    for sig in active_sigs:
                        for magic in sig.magics:
                            if head.startswith(magic):
                                # Kucuk bir ornek (imza + 1MB) kaydet.
                                fh.seek(pos)
                                data = fh.read(1024 * 1024)
                                ext = sig.extensions[0] if sig.extensions else ".bin"
                                fname = f"offset_{pos:012d}{ext}"
                                out_path = os.path.join(output_dir, fname)
                                with open(out_path, "wb") as of:
                                    of.write(data)
                                af = AnalyzedFile(
                                    path=f"@offset:{pos}",
                                    size_bytes=len(data), is_dir=False,
                                    detected_type=sig.name,
                                    detected_extensions=sig.extensions,
                                )
                                result.files.append(af)
                                if progress_callback is not None:
                                    progress_callback(len(result.files), None)
                                break
                    pos += step
        except OSError as exc:
            raise ImageAnalysisError(f"Imaj okunamadi: {exc}") from exc

    # --- TSK ile RAW --------------------------------------------------------
    def _analyze_with_tsk_raw(
        self, image_path: str, result: ImageAnalysisResult, max_files: int,
    ) -> None:
        import pytsk3
        result.backend = "tsk"
        img = pytsk3.Img_Info(image_path)
        self._walk_tsk_image(img, result, max_files)

    def _analyze_with_tsk_ewf(
        self, image_path: str, result: ImageAnalysisResult, max_files: int,
    ) -> None:
        import pyewf
        import pytsk3
        result.backend = "tsk+ewf"
        filenames = pyewf.glob(image_path)
        ewf_handle = pyewf.handle()
        ewf_handle.open(filenames)

        class EWFImgInfo(pytsk3.Img_Info):
            def __init__(self, ewf_handle):
                self._ewf_handle = ewf_handle
                super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

            def close(self):
                self._ewf_handle.close()

            def read(self, offset, size):
                self._ewf_handle.seek(offset)
                return self._ewf_handle.read(size)

            def get_size(self):
                return self._ewf_handle.get_media_size()

        img = EWFImgInfo(ewf_handle)
        self._walk_tsk_image(img, result, max_files)

    def _analyze_with_tsk_e01_native(
        self, image_path: str, result: ImageAnalysisResult, max_files: int,
    ) -> None:
        """E01 imajini pyewf OLMADAN, dogrudan pytsk3 (SleuthKit) uzerinden acar.

        SleuthKit libewf destegiyle derlenmisse pytsk3.Img_Info E01 dosyasini
        native olarak acabilir. Bu basarisiz olursa pyewf yoluna, o da yoksa
        raw-scan fallback'ine dusulur.
        """
        import pytsk3
        try:
            img = pytsk3.Img_Info(image_path)
            result.backend = "tsk-native-ewf"
            self._walk_tsk_image(img, result, max_files)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "pytsk3 E01'i native acamadi (%s), pyewf/raw-scan deneniyor.", exc
            )

        if self._ewf_available:
            self._analyze_with_tsk_ewf(image_path, result, max_files)
        else:
            self._analyze_raw_scan(image_path, result, max_files)

    def _walk_tsk_image(self, img, result: ImageAnalysisResult, max_files: int) -> None:
        import pytsk3
        try:
            vol = pytsk3.Volume_Info(img)
        except OSError:
            # Tek partition (partition table yok).
            self._walk_tsk_fs(pytsk3.FS_Info(img), "/", result, max_files)
            return
        for part in vol:
            if part.len < 2:
                continue
            try:
                fs = pytsk3.FS_Info(img, offset=part.start * 512)
            except OSError:
                continue
            prefix = f"/part{part.addr}"
            self._walk_tsk_fs(fs, prefix, result, max_files)

    def _walk_tsk_fs(self, fs, prefix, result: ImageAnalysisResult, max_files: int,
                     path: str = "/") -> None:
        if len(result.files) >= max_files:
            return
        try:
            directory = fs.open_dir(path=path)
        except OSError:
            return
        for entry in directory:
            if len(result.files) >= max_files:
                return
            if not hasattr(entry, "info") or entry.info.name is None:
                continue
            name_bytes = entry.info.name.name
            try:
                name = name_bytes.decode("utf-8", errors="replace")
            except AttributeError:
                name = str(name_bytes)
            if name in (".", ".."):
                continue
            full = prefix.rstrip("/") + path.rstrip("/") + "/" + name
            meta = entry.info.meta
            if meta is None:
                continue
            size = int(meta.size)
            is_dir = meta.type == 2  # TSK_FS_META_TYPE_DIR
            af = AnalyzedFile(path=full, size_bytes=size, is_dir=is_dir)
            if not is_dir and size > 0:
                # Ilk 32 bayti oku (salt-okunur).
                try:
                    f = entry.read_random(0, min(32, size))
                    actual, exts = guess_type(f)
                    af.detected_type = actual
                    af.detected_extensions = exts
                    af.bad_extension = is_bad_extension(actual, exts, name)
                    # Bilinen bir kuyruk imzasi olan formatlarda, dosyanin son
                    # baytlarini da okuyup gercekten tam mi (kesilmemis/eklenmemis)
                    # diye dogrula. Yalnizca uyusmazlik varsa isaretlenir.
                    if actual in FOOTER_SIGNATURES:
                        tail_len = min(32, size)
                        tail = entry.read_random(max(0, size - tail_len), tail_len)
                        af.footer_mismatch = has_footer_mismatch(actual, tail)
                except OSError:
                    pass
            result.files.append(af)
            if is_dir:
                child = path.rstrip("/") + "/" + name
                self._walk_tsk_fs(fs, prefix, result, max_files, child)

    # --- Backend yok: ham imza tarama --------------------------------------
    def _analyze_raw_scan(
        self, image_path: str, result: ImageAnalysisResult, max_files: int,
    ) -> None:
        """pytsk3 yoksa ya da dosya sistemi bulunamadiysa: imaj dosyasini sabit
        adimlarla tarayarak imza eslesmelerini raporla. Bu tam bir dosya
        sistemi listesi degildir; yaklasik bir "gomulu dosya" gostergesidir.
        """
        result.backend = "raw-scan"
        if self._tsk_available:
            result.notes.append(
                "Dosya sistemi tespit edilemedi (bos/bilinmeyen/sifreli olabilir) "
                "- yaklasik imza taramasina dusuldu."
            )
        else:
            result.notes.append(
                "pytsk3 kurulu degil - tam dosya sistemi listelenemez. "
                "Yaklasik imza taramasi yapiliyor."
            )
        step = 4096  # 4 KB block hizasi
        max_scan_bytes = 256 * 1024 * 1024  # ilk 256 MB
        head_len = 32
        try:
            with open(image_path, "rb") as fh:
                pos = 0
                fh.seek(0, os.SEEK_END)
                total = fh.tell()
                fh.seek(0)
                scan_limit = min(total, max_scan_bytes)
                found = 0
                while pos < scan_limit and found < max_files:
                    fh.seek(pos)
                    head = fh.read(head_len)
                    if not head:
                        break
                    actual, exts = guess_type(head)
                    if actual not in ("unknown", "empty", "text/plain"):
                        af = AnalyzedFile(
                            path=f"@offset:{pos}",
                            size_bytes=0,
                            is_dir=False,
                            detected_type=actual,
                            detected_extensions=exts,
                            bad_extension=False,
                        )
                        result.files.append(af)
                        found += 1
                    pos += step
        except OSError as exc:
            raise ImageAnalysisError(f"Imaj okunamadi: {exc}") from exc
