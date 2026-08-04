"""Merkezi loglama modülü.

Oturum bazlı (session_id) ve detaylı loglama sağlar. Tüm modüller
``logging.getLogger('yti.<modul_adi>')`` çağrısı ile bu yapıyı kullanır.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Optional

APP_SHORT_NAME = "YTI"
LOGGER_ROOT = "yti"

_SESSION_ID: Optional[str] = None
_INITIALIZED = False


def new_session_id() -> str:
    """Yeni bir oturum kimliği üretir ve global olarak saklar."""
    global _SESSION_ID
    _SESSION_ID = uuid.uuid4().hex[:12]
    return _SESSION_ID


def get_session_id() -> str:
    """Aktif oturum kimliğini döndürür, yoksa oluşturur."""
    global _SESSION_ID
    if _SESSION_ID is None:
        new_session_id()
    return _SESSION_ID  # type: ignore[return-value]


class _SessionFilter(logging.Filter):
    """Her log kaydına session_id ekleyen filtre."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.session_id = get_session_id()
        return True


def _default_log_dir() -> str:
    """Log dizinini belirler (executable yanında ``logs/`` klasörü)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base, "logs", "runtime")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def setup_logging(level: int = logging.INFO, log_dir: Optional[str] = None) -> str:
    """Loglama altyapısını kurar. İdempotenttir.

    Returns:
        Oluşturulan log dosyasının tam yolu.
    """
    global _INITIALIZED

    session_id = get_session_id()
    log_dir = log_dir or _default_log_dir()
    os.makedirs(log_dir, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"{APP_SHORT_NAME}_{stamp}_{session_id}.log")

    root = logging.getLogger(LOGGER_ROOT)
    root.setLevel(level)

    if _INITIALIZED:
        return log_path

    fmt = logging.Formatter(
        "%(asctime)s | %(session_id)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(_SessionFilter())

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    stream_handler.addFilter(_SessionFilter())

    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    root.propagate = False

    _INITIALIZED = True
    root.info("Loglama başlatıldı. Oturum: %s | Dosya: %s", session_id, log_path)
    return log_path


def get_logger(module_name: str) -> logging.Logger:
    """``yti.<module_name>`` isimli logger döndürür."""
    return logging.getLogger(f"{LOGGER_ROOT}.{module_name}")
