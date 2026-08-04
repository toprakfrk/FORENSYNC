"""Uygulama geneli hata tipleri ve merkezi hata işleyici.

Yakalanmamış hatalarda uygulamanın sessizce kapanmasını engeller;
tam traceback'i loglar.
"""

from __future__ import annotations

import sys
import traceback
from types import TracebackType
from typing import Callable, Optional, Type

from logs.logger import get_logger

logger = get_logger("error_handler")


class YTIError(Exception):
    """Tüm uygulama hatalarının temel sınıfı."""


class ConnectionError_(YTIError):
    """SSH bağlantısı ile ilgili hatalar."""


class WriteBlockedError(YTIError):
    """Write Blocker tarafından engellenen komutlar için."""


class AcquisitionError(YTIError):
    """İmaj alma sürecindeki hatalar."""


class VerificationError(YTIError):
    """Hash/karşılaştırma doğrulama hataları."""


class ConfigurationError(YTIError):
    """Eksik veya geçersiz yapılandırma hataları."""


def log_exception(exc: BaseException, context: str = "") -> None:
    """Bir istisnayı tam traceback ile loglar."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if context:
        logger.error("Hata (%s): %s\n%s", context, exc, tb)
    else:
        logger.error("Hata: %s\n%s", exc, tb)


def install_global_excepthook(
    on_error: Optional[Callable[[BaseException], None]] = None,
) -> None:
    """Yakalanmamış tüm istisnaları loglayan global excepthook kurar.

    Args:
        on_error: Opsiyonel; GUI'de kullanıcıya hata göstermek için callback.
    """

    def _hook(
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_tb: Optional[TracebackType],
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log_exception(exc_value, context="YAKALANMAMIŞ")
        if on_error is not None:
            try:
                on_error(exc_value)
            except Exception:  # noqa: BLE001
                logger.exception("on_error callback'i başarısız oldu.")

    sys.excepthook = _hook
    logger.info("Global excepthook kuruldu.")
