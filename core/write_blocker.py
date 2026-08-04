"""Yazılımsal Write Blocker.

Hedef sisteme gönderilen TÜM SSH komutları çalıştırılmadan önce buradan
geçmelidir. Yalnızca salt-okunur (read-only) ve açıkça izin verilmiş
komutların çalışmasına izin verir; hedefe yazma yapan komutları engeller.

v7 notu: whitelist ile gerçek komut string'lerinin örtüşmemesi sorununu
gidermek için normalize adımları (sudo / powershell prefix temizliği ve
cleanup komutları için özel işleyiş) eklenmiştir.
"""

from __future__ import annotations

import re
from typing import List

from core.error_handler import WriteBlockedError
from logs.logger import get_logger

logger = get_logger("write_blocker")

# Salt-okunur / güvenli kabul edilen komut önekleri (Linux + Windows/PowerShell).
ALLOWED_READ_COMMANDS: List[str] = [
    # Linux temel
    "ls", "cat", "head", "tail", "stat", "file", "readlink", "realpath",
    "find", "xxd", "du", "wc",
    "lsblk", "blockdev", "fdisk -l", "sfdisk -l", "parted -l", "hdparm",
    "dd if=", "dc3dd if=", "dcfldd if=",
    "md5sum", "sha1sum", "sha256sum", "sha512sum",
    "b2sum", "sha3sum",  # BLAKE2 / SHA3 (opsiyonel algoritmalar)
    "uname", "hostname", "whoami", "id", "date", "uptime", "df", "free",
    "cat /proc/", "lscpu", "lsmem", "dmidecode",
    "cryptsetup status", "cryptsetup isLuks", "lsblk -f",
    "which", "command -v", "test -", "echo",
    "insmod", "modprobe lime",  # RAM imajı için LiME modülü
    # NOT: "avml"/"winpmem" için genel önek İSTEYEREK burada YOK. Genel bir
    # önek, "avml acquire --compress /tmp/output.lime" gibi UZAK DİSKE
    # yazan bir komutu da geçirirdi — RAM imajının sunucu diskine hiç
    # dokunmaması gerektiği ilkesine aykırı. Bunun yerine RAM aracının
    # çalıştırılması yalnızca _RAM_TOOL_EXEC_PATTERNS'teki kesin kalıplarla
    # (yalnızca /dev/stdout hedefli) izinlidir — bkz. aşağısı.
    # Windows / PowerShell (read-only)
    "powershell", "wmic", "systeminfo", "tasklist", "manage-bde -status",
    "Get-", "Select-", "Where-", "wmic diskdrive", "wmic os",
    "certutil -hashfile",  # Windows hash aracı (read-only)
    "type ", "dir ",  # Windows read-only file cmds
]

# RAM imajı sonrası geçici dosyaların temizlenmesi için izin verilen
# özel cleanup komutları (yalnızca /tmp veya %TEMP% altındaki YTI dosyaları).
_CLEANUP_PATTERNS: List[re.Pattern] = [
    re.compile(r"^rm\s+-f\s+/tmp/yti_[\w.\-]+$"),
    re.compile(r"^rmmod\s+lime$"),
    re.compile(r"^del\s+.*yti_[\w.\-]+.*$", re.IGNORECASE),
]

# RAM edinim aracı (AVML) uzak sistemde yoksa YALNIZCA geçici olarak
# /tmp/yti_avml altına indirip çalıştırılabilir yapmak için izin verilen
# dar kapsamlı kalıplar. Bu kalıplar SADECE bu sabit geçici dosya yolu
# ile eşleşir; genel chmod/curl/wget kullanımı yine engellenir. Disk
# imajlama akışı bu kalıpları hiçbir zaman tetiklemez/kullanmaz — disk
# tarafında hedef sisteme yazma amaçlı hiçbir istisna YOKTUR.
_RAM_BOOTSTRAP_PATTERNS: List[re.Pattern] = [
    re.compile(r"^curl\s+-fsSL\s+https://github\.com/microsoft/avml/releases/[\w\./\-]+\s+-o\s+/tmp/yti_avml$"),
    re.compile(r"^wget\s+-q\s+https://github\.com/microsoft/avml/releases/[\w\./\-]+\s+-O\s+/tmp/yti_avml$"),
    re.compile(r"^chmod\s\+x\s/tmp/yti_avml$"),
]

# RAM edinim aracının BİZZAT ÇALIŞTIRILMASI için kesin (regex) kalıplar.
# Genel "avml"/"winpmem" alt-dize öneki kontrolü, aracın tam yoldan
# ("/tmp/yti_avml ..." veya tırnaklı "C:\...\winpmem.exe" ...) çağrılması
# durumunda ÖNEK EŞLEŞMESİNİ KAÇIRABİLİYORDU (ör. "/tmp/yti_avml" içinde
# "avml" alt-dizesi ilk 12 karakterlik pencereye tam sığmıyor). Bu yüzden
# gerçek RAM edinim komutları için ayrıca, yalnızca beklenen tam biçimle
# eşleşen dar kalıplar tanımlanmıştır — hem PATH'teki "avml" hem geçici
# kurulan "/tmp/yti_avml" için, yalnızca --compress/--source/dev-stdout
# argümanlarıyla; Windows tarafında ise yalnızca "<yol>.exe" -o - biçimiyle.
_RAM_TOOL_EXEC_PATTERNS: List[re.Pattern] = [
    # AVML — sıkıştırmasız ham mod (--compress YOK: Volatility uyumluluğu için).
    # PATH'teki "avml" veya geçici "/tmp/yti_avml"; isteğe bağlı --source;
    # hedef /dev/stdout (eski akış, artık kullanılmıyor — FIFO tercih edilir).
    re.compile(
        r"^(?:avml|/tmp/yti_avml)\s+acquire"
        r"(?:\s+--source\s+(?:/proc/kcore|/dev/crash|/dev/mem))?"
        r"\s+/dev/stdout$"
    ),
    # WinPMEM stdout modu: "<tam_yol>.exe" -o -
    re.compile(r'^"[^"]+\.exe"\s+-o\s+-$'),
]

# AVML v0.20+ "/dev/stdout" hedefini artık güvenilir kabul etmiyor (bkz.
# _RAM_TOOL_EXEC_PATTERNS üstündeki not); bunun yerine gerçek bir
# adlandırılmış boru (FIFO, /tmp/yti_ram_pipe) üzerinden akış yapılıyor.
# Bu TEK bileşik komut dizesi tam olarak bu biçimle eşleşmelidir — FIFO
# disk'te veri TUTMAZ (salt IPC kanalı), yalnızca RAM edinimi için
# kullanılır ve komutun sonunda kendi kendini temizler.
# --compress YOK: sıkıştırmasız ham mod, Volatility doğrudan okur.
_RAM_STREAM_PIPE_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"^rm -f /tmp/yti_ram_pipe 2>/dev/null; mkfifo -m 600 /tmp/yti_ram_pipe; "
        r"cat /tmp/yti_ram_pipe & catpid=\$!; "
        r"sudo -n (?:avml|/tmp/yti_avml) acquire"
        r"(?: --source (?:/proc/kcore|/dev/crash|/dev/mem))? /tmp/yti_ram_pipe; "
        r"ec=\$\?; kill \$catpid 2>/dev/null; wait \$catpid 2>/dev/null; "
        r"rm -f /tmp/yti_ram_pipe; exit \$ec$"
    ),
]

# Kesinlikle engellenen tehlikeli anahtar kelimeler (yazma / değişiklik).
_BLOCKED_KEYWORDS: List[str] = [
    "dd of=/dev", "mkfs", "fdisk /dev", "sfdisk /dev", "parted /dev",
    "mount", "umount -f", "> /dev", ">> /dev", "wipefs", "shred",
    "format ", "diskpart", "chmod", "chown", "mv ", "cp ",
    "cryptsetup luksFormat", "cryptsetup open",
    # Genel "of=" (dd/dc3dd/dcfldd çıktı hedefi) — kod tabanında hiçbir yerde
    # kullanılmıyor (tüm imajlama akışları stdout/SSH kanalı üzerinden okur,
    # uzak sisteme dosya YAZMAZ). Yalnızca "dd of=/dev" değil, TÜM "of="
    # hedeflerini engellemek, uzak sisteme herhangi bir dosya yazılmasını
    # (örn. "of=/root/dump.img") da kapatır.
    " of=",
]


def _normalize(command: str) -> str:
    """Komutu whitelist karşılaştırması için normalize eder.

    - Baştaki/sondaki boşlukları temizler.
    - ``sudo`` ve ``sudo -n`` öneklerini kaldırır.
    - PowerShell çağrı sarmalayıcılarını sadeleştirir.
    """
    cmd = command.strip()
    cmd = re.sub(r"^sudo(\s+-\w+)*\s+", "", cmd)
    cmd = re.sub(r"^powershell(\.exe)?(\s+-\w+(\s+\S+)?)*\s+-Command\s+", "powershell ", cmd, flags=re.IGNORECASE)
    return cmd.strip()


class WriteBlocker:
    """Komutları salt-okunur whitelist'e göre doğrulayan yazma engelleyici.

    SSH komutu gönderen TÜM bileşenler AYNI ``WriteBlocker`` nesnesini
    paylaşmalıdır.
    """

    def __init__(self) -> None:
        self._verified_count = 0
        self._blocked_count = 0
        logger.info("WriteBlocker başlatıldı. İzinli önek sayısı: %d", len(ALLOWED_READ_COMMANDS))

    @property
    def verified_count(self) -> int:
        return self._verified_count

    @property
    def blocked_count(self) -> int:
        return self._blocked_count

    def _is_cleanup(self, cmd: str) -> bool:
        return any(p.match(cmd) for p in _CLEANUP_PATTERNS)

    def _is_ram_bootstrap(self, cmd: str) -> bool:
        """Yalnızca AVML'nin /tmp/yti_avml'ye geçici kurulumu için izinli."""
        return any(p.match(cmd) for p in _RAM_BOOTSTRAP_PATTERNS)

    def _is_ram_tool_exec(self, cmd: str) -> bool:
        """RAM edinim aracının (AVML/WinPMEM) bizzat çalıştırılması için izinli."""
        return any(p.match(cmd) for p in _RAM_TOOL_EXEC_PATTERNS)

    def _is_ram_stream_pipe(self, cmd: str) -> bool:
        """FIFO tabanlı RAM akış bileşik komutu için izinli (bkz. yukarı not)."""
        return any(p.match(cmd) for p in _RAM_STREAM_PIPE_PATTERNS)

    def _is_blocked_keyword(self, cmd: str) -> bool:
        low = cmd.lower()
        return any(kw.lower() in low for kw in _BLOCKED_KEYWORDS)

    def _is_allowed_prefix(self, cmd: str) -> bool:
        return any(cmd.startswith(prefix) or prefix in cmd[: len(prefix) + 8]
                   for prefix in ALLOWED_READ_COMMANDS)

    def verify_command(self, command: str) -> str:
        """Komutu doğrular. İzinliyse normalize halini döndürür.

        Raises:
            WriteBlockedError: Komut engellendiğinde.
        """
        if not command or not command.strip():
            raise WriteBlockedError("Boş komut engellendi.")

        normalized = _normalize(command)

        # Önce açık cleanup istisnası.
        if self._is_cleanup(normalized):
            self._verified_count += 1
            logger.debug("WriteBlocker: cleanup komutu izinli -> %s", normalized)
            return command

        # AVML geçici kurulum istisnası (yalnızca RAM edinimi, yalnızca
        # /tmp/yti_avml). chmod/curl/wget genelde engellidir; bu yalnızca
        # bu tek sabit dosya yolunu hedefleyen tam eşleşmeler için açılır.
        if self._is_ram_bootstrap(normalized):
            self._verified_count += 1
            logger.debug("WriteBlocker: RAM bootstrap (geçici AVML) izinli -> %s", normalized)
            return command

        # RAM edinim aracının çalıştırılması (AVML/WinPMEM) — bkz. yukarıdaki
        # not: alt-dize öneki kontrolü tam yol/tırnaklı çağrıları kaçırdığı
        # için ayrı, kesin kalıplarla doğrulanır.
        if self._is_ram_tool_exec(normalized):
            self._verified_count += 1
            logger.debug("WriteBlocker: RAM aracı çalıştırma izinli -> %s", normalized)
            return command

        if self._is_ram_stream_pipe(normalized):
            self._verified_count += 1
            logger.debug("WriteBlocker: RAM FIFO akış komutu izinli -> %s", normalized)
            return command

        # Tehlikeli anahtar kelime kontrolü.
        if self._is_blocked_keyword(normalized):
            self._blocked_count += 1
            logger.error("WriteBlocker ENGELLEDİ (yazma tespiti): %s", command)
            raise WriteBlockedError(f"Komut yazma içeriyor ve engellendi: {command}")

        # Whitelist prefix kontrolü.
        first_token = normalized.split()[0] if normalized.split() else ""
        allowed = self._is_allowed_prefix(normalized) or any(
            normalized.startswith(p.split()[0]) and p.split()[0] == first_token
            for p in ALLOWED_READ_COMMANDS
        )
        if not allowed:
            self._blocked_count += 1
            logger.error("WriteBlocker ENGELLEDİ (whitelist dışı): %s", command)
            raise WriteBlockedError(f"Komut izinli listede değil: {command}")

        self._verified_count += 1
        logger.debug("WriteBlocker onayladı: %s", normalized)
        return command
