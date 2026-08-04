"""Uzantı kategorileri — GUI'deki 'Uzantı Hedefli Tarama' seçicisinin veri kaynağı.

Adli bilişimde sık taranan dosya türleri, kullanıcı dostu kategorilere
ayrılmıştır. GUI, bu tablodan checkbox paneli oluşturur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ExtensionCategory:
    """Bir uzantı kategorisi (görünen ad + uzantılar)."""

    name: str
    extensions: Tuple[str, ...]


# Kategoriler — sıra GUI'de bu şekilde görünür.
CATEGORIES: List[ExtensionCategory] = [
    ExtensionCategory(
        "Belgeler",
        (".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt",
         ".odt", ".ods", ".odp", ".rtf", ".txt"),
    ),
    ExtensionCategory(
        "Görseller",
        (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif",
         ".webp", ".heic", ".svg", ".raw", ".psd"),
    ),
    ExtensionCategory(
        "Video / Ses",
        (".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".flv",
         ".mp3", ".wav", ".flac", ".ogg", ".aac", ".m4a"),
    ),
    ExtensionCategory(
        "Arşivler",
        (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso"),
    ),
    ExtensionCategory(
        "Yürütülebilir",
        (".exe", ".dll", ".sys", ".scr", ".msi",
         ".sh", ".bat", ".ps1", ".apk", ".app", ".pkg", ".deb", ".rpm"),
    ),
    ExtensionCategory(
        "Veritabanı",
        (".sqlite", ".sqlite3", ".db", ".mdb", ".accdb", ".sql", ".dbf"),
    ),
    ExtensionCategory(
        "E-posta / Ajanda",
        (".pst", ".ost", ".eml", ".msg", ".mbox", ".ics", ".vcf"),
    ),
    ExtensionCategory(
        "Kod / Script",
        (".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs",
         ".go", ".rs", ".rb", ".php", ".pl", ".swift", ".kt", ".sql"),
    ),
    ExtensionCategory(
        "Kripto / Anahtar",
        (".key", ".pem", ".p12", ".pfx", ".gpg", ".asc", ".wallet",
         ".keystore"),
    ),
    ExtensionCategory(
        "Sanal disk / İmaj",
        (".vhd", ".vhdx", ".vmdk", ".vdi", ".dd", ".raw", ".img",
         ".e01", ".ex01", ".aff"),
    ),
    ExtensionCategory(
        "Web / Konfig",
        (".html", ".htm", ".xml", ".json", ".yaml", ".yml", ".ini",
         ".conf", ".cfg", ".log", ".csv"),
    ),
]


def all_extensions() -> Tuple[str, ...]:
    """Tüm kategorilerdeki uzantıları döndürür (tekilleştirilmiş)."""
    seen: set = set()
    out: List[str] = []
    for cat in CATEGORIES:
        for ext in cat.extensions:
            if ext not in seen:
                seen.add(ext)
                out.append(ext)
    return tuple(out)


def category_by_name(name: str) -> ExtensionCategory | None:
    for cat in CATEGORIES:
        if cat.name == name:
            return cat
    return None
