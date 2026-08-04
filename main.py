"""Yildizlar Takimi Imager — uygulama giriş noktası.

Loglamayı başlatır, global excepthook kurar (yakalanmamış hatalarda sessiz
kapanmayı engeller) ve ana pencereyi açar.
"""

from __future__ import annotations

import os
import sys

from logs.logger import new_session_id, setup_logging, get_logger


def main() -> int:
    """Uygulamayı başlatır."""
    new_session_id()
    log_path = setup_logging()
    logger = get_logger("main")
    logger.info("Yildizlar Takimi Imager başlatılıyor. Log: %s", log_path)

    # --- HiDPI / macOS ölçeklendirme uyumu (Qt her zaman değişkeni saygılı okur)
    # macOS Retina + Windows HiDPI + Linux fractional scaling için:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    # Fractional (1.5x, 1.25x) ölçek yuvarlama politikası — macOS'ta pastır önlenir.
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtWidgets import QApplication
        from core import APP_NAME, APP_VERSION
        from core.error_handler import install_global_excepthook
        from gui.main_window import MainWindow
    except Exception as exc:  # noqa: BLE001
        logger.error("Bağımlılıklar yüklenemedi: %s", exc)
        print(f"HATA: Gerekli bağımlılıklar yüklenemedi: {exc}", file=sys.stderr)
        return 1

    # Qt 6'da fractional scaling politikasını kodda da uygula (env yeterli
    # olmazsa; macOS'ta buton/label kesintisiz görünsün diye).
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:  # noqa: BLE001
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    window = MainWindow()

    def _on_fatal(exc: BaseException) -> None:
        try:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(
                window,
                "Kritik Hata",
                f"Beklenmeyen bir hata oluştu:\n{exc}\n\nDetaylar log dosyasında.",
            )
        except Exception:  # noqa: BLE001
            pass

    install_global_excepthook(on_error=_on_fatal)

    window.show()
    logger.info("Ana pencere gösterildi.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())