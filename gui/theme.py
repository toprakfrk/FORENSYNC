"""IMAJER — Klasik Windows Forms / adli bilişim aracı tema.

Tasarım dili: FTK Imager, Autopsy, EnCase tarzı — hiyerarşi RENKTEN değil,
ÇERÇEVE + BOŞLUK + TİPOGRAFİDEN gelir. Renk kısıtlı, sadece anlamlı
yerlerde (aktif/seçili/tehlike/başarı).

Renk aileleri (5 ve sadece 5):
    - Gri (zemin, çerçeve, ikincil metin)
    - Mavi (aktif, birincil buton, başlık çubuğu)  #2c5990 / #4a86c8 / #dcebf9
    - Kırmızı (tehlike/iptal)                       #a03d2c / #c26b5c / #fdf0ee
    - Yeşil (başarı durum noktası)                 #5a8f5a
    - Log koyu istisnası                            #1c1c1c
"""

from __future__ import annotations

# --- Zemin -----------------------------------------------------------------
COLOR_BG = "#f0f0f0"              # Pencere zemini
COLOR_PANEL = "#fbfbfb"           # Ağaç, açılır menü açık zemini
COLOR_CARD = "#ffffff"            # Giriş alanı, group box içi
COLOR_INPUT_BG = "#ffffff"

# --- Metin -----------------------------------------------------------------
COLOR_TEXT = "#1e1e1e"
COLOR_TEXT_MUTED = "#555555"
COLOR_TEXT_SUBTLE = "#7a7a7a"

# --- Çerçeveler ------------------------------------------------------------
COLOR_BORDER = "#b5b5b5"          # Group box, ayraç
COLOR_BORDER_INPUT = "#a0a0a0"    # Input, spin
COLOR_BORDER_LIGHT = "#c8c8c8"    # İnce ayraç

# --- Mavi ailesi (accent) --------------------------------------------------
COLOR_ACCENT = "#2c5990"          # Koyu mavi (birincil buton koyu ucu, koyu vurgu)
COLOR_ACCENT_MID = "#4a86c8"      # Orta mavi (buton üst dolgu, hover)
COLOR_ACCENT_LIGHT = "#dcebf9"    # Çok açık mavi (aktif/seçili satır dolgu)
COLOR_ACCENT_BORDER = "#a8c4e0"   # Aktif çerçeve
COLOR_ACCENT_DARK = "#1e4573"     # Buton pressed
# Geriye uyumluluk:
COLOR_ACCENT_HOVER = COLOR_ACCENT_MID

# --- Kırmızı ailesi (danger) ----------------------------------------------
COLOR_DANGER = "#a03d2c"          # Metin/çerçeve
COLOR_DANGER_MID = "#c26b5c"      # Çerçeve
COLOR_DANGER_LIGHT = "#fdf0ee"    # Hover zemin
COLOR_DANGER_HOVER = "#8a3225"

# --- Yeşil (başarı) --------------------------------------------------------
COLOR_OK = "#5a8f5a"

# --- Log kutusu (tek koyu istisna) ----------------------------------------
COLOR_LOG_BG = "#1c1c1c"
COLOR_LOG_TEXT = "#8cc48c"        # Yeşilimsi monospace

# --- Fontlar ---------------------------------------------------------------
# Klasik masaüstü hissi için sistem sans serif'i tercih; monospace log için.
FONT_STACK = "'Segoe UI', 'Tahoma', 'Helvetica Neue', Arial, sans-serif"
FONT_STACK_MONO = "'Consolas', 'Menlo', 'DejaVu Sans Mono', monospace"


APP_STYLESHEET = f"""
/* ---------------- Global ---------------- */
QMainWindow, QDialog {{ background-color: {COLOR_BG}; }}
QWidget {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    font-family: {FONT_STACK};
    font-size: 12px;
}}
QToolTip {{
    background-color: #ffffe1;
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER_INPUT};
    padding: 4px 6px;
}}

/* ---------------- Menü çubuğu ---------------- */
QMenuBar {{
    background-color: {COLOR_BG};
    border-bottom: 1px solid {COLOR_BORDER_LIGHT};
    padding: 2px 4px;
    spacing: 2px;
}}
QMenuBar::item {{
    padding: 5px 10px;
    background: transparent;
    color: {COLOR_TEXT};
}}
QMenuBar::item:selected {{
    background-color: {COLOR_ACCENT_LIGHT};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_ACCENT_BORDER};
    border-bottom: none;
    padding: 4px 9px;
}}
QMenuBar::item:disabled {{ color: {COLOR_TEXT_SUBTLE}; }}
QMenu {{
    background-color: {COLOR_PANEL};
    border: 1px solid {COLOR_BORDER};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
    color: {COLOR_TEXT};
    background: transparent;
}}
QMenu::item:selected {{
    background-color: {COLOR_ACCENT_LIGHT};
    color: {COLOR_TEXT};
}}
QMenu::separator {{
    height: 1px;
    background: {COLOR_BORDER_LIGHT};
    margin: 4px 8px;
}}

/* ---------------- Araç çubuğu ---------------- */
QToolBar {{
    background-color: {COLOR_BG};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER_LIGHT};
    padding: 4px 6px;
    spacing: 4px;
}}
QToolBar::separator {{
    width: 1px;
    background: {COLOR_BORDER_LIGHT};
    margin: 6px 6px;
}}
QToolButton {{
    background-color: transparent;
    color: {COLOR_TEXT};
    border: 1px solid transparent;
    border-radius: 3px;
    padding: 4px 8px;
    min-width: 56px;
    font-size: 11px;
}}
QToolButton:hover {{
    background-color: {COLOR_ACCENT_LIGHT};
    border: 1px solid {COLOR_ACCENT_BORDER};
}}
QToolButton:checked {{
    background-color: {COLOR_ACCENT_LIGHT};
    border: 1px solid {COLOR_ACCENT_BORDER};
}}

/* ---------------- GroupBox ---------------- */
QGroupBox {{
    background-color: {COLOR_BG};
    border: 1px solid {COLOR_BORDER};
    border-radius: 3px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    color: {COLOR_TEXT_MUTED};
    font-size: 11.5px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 8px;
    color: {COLOR_TEXT_MUTED};
    background-color: {COLOR_BG};
}}

/* ---------------- Butonlar ---------------- */
QPushButton {{
    background-color: {COLOR_CARD};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER_INPUT};
    border-radius: 3px;
    padding: 5px 14px;
    min-height: 16px;
    min-width: 68px;
}}
QPushButton:hover {{
    background-color: {COLOR_ACCENT_LIGHT};
    border-color: {COLOR_ACCENT_BORDER};
    color: {COLOR_ACCENT};
}}
QPushButton:pressed {{ background-color: #cddff2; }}
QPushButton:disabled {{
    color: {COLOR_TEXT_SUBTLE};
    background-color: #eaeaea;
    border-color: {COLOR_BORDER_LIGHT};
}}

/* ---------------- Input alanları ---------------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QDateEdit, QTimeEdit,
QPlainTextEdit, QTextEdit {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER_INPUT};
    border-radius: 2px;
    padding: 4px 6px;
    selection-background-color: {COLOR_ACCENT_MID};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus,
QDateTimeEdit:focus {{
    border-color: {COLOR_ACCENT};
}}
QLineEdit:disabled {{ background-color: #eaeaea; color: {COLOR_TEXT_SUBTLE}; }}
QLineEdit[readOnly="true"] {{ background-color: #f5f5f5; }}

/* ---------------- QComboBox (macOS drop-down bug fix'i dahil) ---------------- */
QComboBox {{
    background-color: {COLOR_INPUT_BG};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER_INPUT};
    border-radius: 2px;
    padding: 3px 8px;
    min-height: 18px;
}}
QComboBox:focus, QComboBox:on {{ border-color: {COLOR_ACCENT}; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid {COLOR_BORDER_INPUT};
    background-color: {COLOR_BG};
}}
QComboBox::down-arrow {{
    image: none;
    width: 6px; height: 6px;
    border-left: 2px solid {COLOR_TEXT_MUTED};
    border-bottom: 2px solid {COLOR_TEXT_MUTED};
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    selection-background-color: {COLOR_ACCENT_LIGHT};
    selection-color: {COLOR_TEXT};
    padding: 2px;
    outline: 0;
}}
QComboBox QAbstractItemView::item {{ padding: 4px 8px; min-height: 20px; }}

/* ---------------- CheckBox ---------------- */
QCheckBox, QRadioButton {{ spacing: 6px; color: {COLOR_TEXT}; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{
    background-color: #ffffff;
    border: 1px solid {COLOR_BORDER_INPUT};
    border-radius: 2px;
}}
QCheckBox::indicator:checked {{
    background-color: {COLOR_ACCENT};
    border: 1px solid {COLOR_ACCENT_DARK};
    border-radius: 2px;
}}
QCheckBox::indicator:hover {{ border-color: {COLOR_ACCENT}; }}

/* ---------------- ProgressBar ---------------- */
QProgressBar {{
    border: 1px solid {COLOR_BORDER_INPUT};
    border-radius: 2px;
    text-align: center;
    background-color: {COLOR_CARD};
    color: {COLOR_TEXT};
    min-height: 14px;
    max-height: 16px;
    font-size: 10px;
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACCENT_MID};
}}

/* ---------------- Tree / List ---------------- */
QTreeWidget, QTreeView, QListWidget {{
    background-color: {COLOR_PANEL};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
    alternate-background-color: #f6f6f6;
    outline: 0;
}}
QTreeWidget::item, QTreeView::item, QListWidget::item {{
    padding: 4px 4px;
    min-height: 18px;
}}
QTreeWidget::item:hover, QTreeView::item:hover, QListWidget::item:hover {{
    background-color: #eef4fb;
}}
QTreeWidget::item:selected, QTreeView::item:selected, QListWidget::item:selected {{
    background-color: {COLOR_ACCENT_LIGHT};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_ACCENT_BORDER};
    border-left: none; border-right: none;
}}
QHeaderView::section {{
    background-color: #eaeaea;
    color: {COLOR_TEXT_MUTED};
    padding: 4px 8px;
    border: none;
    border-right: 1px solid {COLOR_BORDER_LIGHT};
    border-bottom: 1px solid {COLOR_BORDER};
    font-size: 11px;
}}

/* ---------------- ScrollBar (klasik incelik) ---------------- */
QScrollBar:vertical {{
    background: {COLOR_BG};
    width: 12px;
    margin: 0;
    border-left: 1px solid {COLOR_BORDER_LIGHT};
}}
QScrollBar::handle:vertical {{
    background: #c8c8c8;
    min-height: 24px;
    border: 1px solid #a0a0a0;
}}
QScrollBar::handle:vertical:hover {{ background: #b0b0b0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {COLOR_BG};
    height: 12px;
    border-top: 1px solid {COLOR_BORDER_LIGHT};
}}
QScrollBar::handle:horizontal {{
    background: #c8c8c8;
    min-width: 24px;
    border: 1px solid #a0a0a0;
}}

/* ---------------- StatusBar ---------------- */
QStatusBar {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT_MUTED};
    border-top: 1px solid {COLOR_BORDER_LIGHT};
    padding: 2px 6px;
}}
QStatusBar::item {{ border: none; }}

/* ---------------- Splitter ---------------- */
QSplitter::handle {{
    background: {COLOR_BORDER_LIGHT};
}}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}

/* ---------------- QTabWidget (İmaj İnceleme'de kalabilir) ---------------- */
QTabWidget::pane {{
    border: 1px solid {COLOR_BORDER};
    background-color: {COLOR_BG};
}}
QTabBar::tab {{
    background-color: #e4e4e4;
    color: {COLOR_TEXT_MUTED};
    padding: 6px 14px;
    border: 1px solid {COLOR_BORDER};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background-color: {COLOR_BG};
    color: {COLOR_TEXT};
    border-bottom: 1px solid {COLOR_BG};
}}

QDockWidget {{
    color: {COLOR_TEXT_MUTED};
    font-size: 11px;
}}
QDockWidget::title {{
    background: #e4e4e4;
    padding: 4px 6px;
    border-bottom: 1px solid {COLOR_BORDER_LIGHT};
}}
"""
