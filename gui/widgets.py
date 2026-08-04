"""IMAJER — Küçük UI yardımcıları.

Klasik Windows Forms tarzında butonlar için stil yardımcıları:
    - make_primary : Tek dolgu-mavi buton (bir ekranda EN FAZLA 1 tane)
    - make_danger  : Kırmızı outline (İptal vb.)
    - make_secondary: Nötr gri outline (Sıfırla vb. — varsayılan zaten bu)
"""

from __future__ import annotations

from gui import theme


def make_primary(btn) -> None:
    """Dolgu mavi degrade (birincil eylem) — ekranda tek olmalı."""
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: {theme.COLOR_ACCENT_MID};
            color: #ffffff;
            border: 1px solid {theme.COLOR_ACCENT_DARK};
            border-radius: 3px;
            padding: 5px 16px;
            min-height: 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {theme.COLOR_ACCENT}; }}
        QPushButton:pressed {{ background-color: {theme.COLOR_ACCENT_DARK}; }}
        QPushButton:disabled {{
            background-color: #b8c8d8;
            color: #ffffff;
            border-color: #b8c8d8;
        }}
    """)


def make_danger(btn) -> None:
    """Kırmızı outline — İptal / tehlikeli eylem."""
    btn.setStyleSheet(f"""
        QPushButton {{
            background-color: #ffffff;
            color: {theme.COLOR_DANGER};
            border: 1px solid {theme.COLOR_DANGER_MID};
            border-radius: 3px;
            padding: 5px 14px;
            min-height: 16px;
        }}
        QPushButton:hover {{
            background-color: {theme.COLOR_DANGER_LIGHT};
            border-color: {theme.COLOR_DANGER};
            color: {theme.COLOR_DANGER_HOVER};
        }}
        QPushButton:disabled {{
            color: #c8a5a0;
            border-color: #d8bfb8;
        }}
    """)


def make_secondary(btn) -> None:
    """Nötr gri outline — Sıfırla vb. (varsayılan stille aynı, açıklık için)."""
    btn.setStyleSheet("")  # global QSS'e bırak


# Geriye uyumluluk (eski kodda `make_ghost` çağrısı yoksa da olsun).
def make_ghost(btn) -> None:
    btn.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {theme.COLOR_TEXT_MUTED};
            border: none;
            padding: 4px 8px;
        }}
        QPushButton:hover {{ color: {theme.COLOR_ACCENT}; }}
    """)
