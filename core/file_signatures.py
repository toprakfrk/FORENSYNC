"""Dosya imzası (magic number) tabanlı tür tespiti — ortak çekirdek.

Hem uzak sistemden targeted imaging yaparken hem de yerel imaj dosyasını
incelerken paylaşılan tek imza tablosu. Kod tekrarını önler.

Bilinen sihirli baytlar (ilk N bayt). Her giriş:
    (name, extensions, [signatures])
signatures: bytes prefix listesi (None-optional offset yok, prefix=başlangıç)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class Signature:
    """Bir dosya türü için sihirli bayt/uzantı eşlemesi."""

    name: str
    extensions: Tuple[str, ...]
    magics: Tuple[bytes, ...]


# Sık kullanılan adli bilişim ilgili dosya türleri.
KNOWN_SIGNATURES: List[Signature] = [
    Signature("PNG image", (".png",), (b"\x89PNG\r\n\x1a\n",)),
    Signature("JPEG image", (".jpg", ".jpeg"), (b"\xff\xd8\xff",)),
    Signature("GIF image", (".gif",), (b"GIF87a", b"GIF89a")),
    Signature("BMP image", (".bmp",), (b"BM",)),
    Signature("WebP image", (".webp",), (b"RIFF",)),  # Ek doğrulama: 8. bayttan itibaren 'WEBP'
    Signature("PDF document", (".pdf",), (b"%PDF-",)),
    Signature(
        "Office (OOXML/ZIP)",
        (".docx", ".xlsx", ".pptx", ".zip", ".jar", ".apk"),
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ),
    Signature("Legacy Office (OLE)", (".doc", ".xls", ".ppt", ".msi"),
              (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)),
    Signature("RAR archive", (".rar",), (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")),
    Signature("7z archive", (".7z",), (b"7z\xbc\xaf\x27\x1c",)),
    Signature("gzip", (".gz", ".tgz"), (b"\x1f\x8b",)),
    Signature("bzip2", (".bz2",), (b"BZh",)),
    Signature("xz", (".xz",), (b"\xfd7zXZ\x00",)),
    Signature("Windows PE (exe/dll)", (".exe", ".dll", ".sys", ".scr"), (b"MZ",)),
    Signature("ELF (Linux exe)", (), (b"\x7fELF",)),
    Signature("Mach-O (macOS exe)", (), (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                                            b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe")),
    Signature("Java class", (".class",), (b"\xca\xfe\xba\xbe",)),
    Signature("MP3 audio", (".mp3",), (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")),
    Signature("WAV audio", (".wav",), (b"RIFF",)),  # 8. bayt 'WAVE'
    Signature("MP4 / MOV video", (".mp4", ".mov", ".m4a", ".m4v"),
              (b"\x00\x00\x00\x18ftyp", b"\x00\x00\x00\x20ftyp",
               b"\x00\x00\x00\x1cftyp", b"\x00\x00\x00\x14ftyp")),
    Signature("MKV/WebM video", (".mkv", ".webm"), (b"\x1a\x45\xdf\xa3",)),
    Signature("SQLite database", (".sqlite", ".db", ".sqlite3"),
              (b"SQLite format 3\x00",)),
    Signature("PST (Outlook)", (".pst",), (b"!BDN",)),
    Signature("E01 (EWF)", (".e01",), (b"EVF\x09\x0d\x0a\xff\x00",)),
    Signature("AFF", (".aff",), (b"AFF10\r\n\x00",)),
    Signature("VMDK", (".vmdk",), (b"KDMV", b"# Disk DescriptorFile")),
    Signature("VHD/VHDX", (".vhd", ".vhdx"), (b"conectix", b"vhdxfile")),
    Signature("ISO 9660", (".iso",), (b"CD001",)),  # ofset 0x8001'de; basit tarama için burada
    Signature("Text (UTF-8 BOM)", (".txt", ".log", ".csv"), (b"\xef\xbb\xbf",)),
]


def guess_type(head_bytes: bytes) -> Tuple[str, Tuple[str, ...]]:
    """İlk N baytı verilen bir dosyanın türünü ve tipik uzantılarını tahmin eder.

    Returns:
        (type_name, allowed_extensions). Bilinmiyorsa ("unknown", ()).
    """
    if not head_bytes:
        return ("empty", ())
    for sig in KNOWN_SIGNATURES:
        for magic in sig.magics:
            if head_bytes.startswith(magic):
                # RIFF ekstra doğrulama (webp vs wav)
                if magic == b"RIFF" and len(head_bytes) >= 12:
                    tag = head_bytes[8:12]
                    if tag == b"WEBP":
                        return ("WebP image", (".webp",))
                    if tag == b"WAVE":
                        return ("WAV audio", (".wav",))
                    if tag == b"AVI ":
                        return ("AVI video", (".avi",))
                    continue
                return (sig.name, sig.extensions)
    # Text heuristik: yüksek oranda yazdırılabilir karakterse "text/plain"
    printable = sum(1 for b in head_bytes if 32 <= b < 127 or b in (9, 10, 13))
    if printable / max(1, len(head_bytes)) > 0.9:
        return ("text/plain", (".txt", ".log", ".csv", ".xml", ".html", ".json"))
    return ("unknown", ())


def is_bad_extension(actual_type: str, allowed_exts: Tuple[str, ...], filename: str) -> bool:
    """Uzantı gerçek türle uyuşmuyor mu?

    ``allowed_exts`` boşsa uzantı kontrolü anlamsız (örn. ELF, Mach-O).
    Dosya uzantısı yoksa da 'bad' saymayız (kasten uzantısız olabilir).
    """
    if not allowed_exts or actual_type in ("unknown", "empty", "text/plain"):
        # "text/plain" güçlü bir imza değil, yazdırılabilir karakter oranına
        # dayalı bir tahmindir — meşru metin-tabanlı uzantılar (.py, .js, .css,
        # .yml, .ini, .conf, .plist, .strings, .md vb.) çok geniş bir küme
        # olduğu için bunu bad-extension kriteri olarak kullanmak aşırı sayıda
        # yanlış pozitif üretir.
        return False
    lower = filename.lower()
    # Uzantı yok -> uyarı vermeyelim (gerçek durum: gizlenmiş dosya olabilir ama false-positive fazla).
    if "." not in lower.split("/")[-1]:
        return False
    ext = "." + lower.rsplit(".", 1)[-1]
    # Herhangi bir izinli uzantıyla eşleşiyorsa iyi.
    return not any(ext == a for a in allowed_exts)


# Bilinen formatlar için kuyruk (footer/EOF) imzaları — sadece header'ı değil,
# dosyanın gerçekten tam ve kesilmemiş olup olmadığını da doğrulamak için.
# Yalnızca kesin/istikrarlı bir bitiş imzası olan formatlar burada — belirsiz
# formatlar (ör. bazı video/ses konteynerleri) kasıtlı olarak dışarıda
# bırakıldı, aksi halde yanlış pozitif üretir.
FOOTER_SIGNATURES: dict[str, Tuple[bytes, ...]] = {
    "JPEG image": (b"\xff\xd9",),
    "PNG image": (b"IEND\xae\x42\x60\x82",),
    "GIF image": (b"\x3b",),
    "PDF document": (b"%%EOF", b"%%EOF\n", b"%%EOF\r\n"),
    "Office (OOXML/ZIP)": (b"PK\x05\x06",),  # End of Central Directory (footer'da yer alır, sonrasında yorum alanı olabilir)
}


def has_footer_mismatch(actual_type: str, tail_bytes: bytes) -> bool:
    """Header türüne göre beklenen kuyruk imzası kuyrukta yoksa True döner.

    ``actual_type`` için bilinen bir kuyruk imzası yoksa (tabloda değilse)
    kontrol anlamsızdır -> False (uyuşmazlık YOK sayılır, yani ikon
    tetiklenmez). PDF/OOXML gibi formatlarda kuyruktan sonra birkaç bayt
    dolgu/yorum olabileceği için ``in`` ile arıyoruz, salt suffix eşleşmesi
    aramıyoruz.
    """
    footers = FOOTER_SIGNATURES.get(actual_type)
    if not footers or not tail_bytes:
        return False
    return not any(f in tail_bytes for f in footers)
