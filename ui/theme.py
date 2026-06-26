"""Sistema de tema para Ciclométricas Desktop.

Tema único: Dark Navy.
Incluye estilos explícitos para QMenu (evita problemas con modo claro de Windows).
"""
from __future__ import annotations

from typing import Dict

# ─── Paleta de colores ───────────────────────────────────────────────

COLORS: Dict[str, str] = {
    # Fondos
    "bg":             "#0a0f1e",
    "bg_card":        "#111827",
    "bg_secondary":   "#1a2236",
    "bg_hover":       "#1e293b",
    "bg_input":       "#151d2e",

    # Texto
    "fg":             "#f8fafc",
    "fg_muted":       "#a1b0c8",
    "fg_dim":         "#6b7d99",

    # Acentos
    "primary":        "#ff6b35",
    "primary_hover":  "#ff8c5a",
    "primary_dim":    "rgba(255, 107, 53, 0.18)",
    "accent":         "#22d3ee",
    "accent_hover":   "#67e8f9",
    "accent_dim":     "rgba(34, 211, 238, 0.15)",

    # Bordes
    "border":         "#1e293b",
    "border_focus":   "#ff6b35",

    # Estado
    "destructive":    "#ef4444",
    "success":        "#22c55e",
    "warning":        "#f59e0b",

    # Scrollbar
    "scrollbar":      "#1e293b",
    "scrollbar_hover": "#334155",

    # Menú contextual (QMenu)
    "menu_bg":        "#1e293b",
    "menu_border":    "#334155",
    "menu_selected":  "rgba(255, 107, 53, 0.25)",
}


# ─── Fuentes ─────────────────────────────────────────────────────────

FONT_FAMILY = "'Segoe UI', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif"

FONT_SIZE_XS   = "11px"
FONT_SIZE_SM   = "12px"
FONT_SIZE_BASE = "14px"
FONT_SIZE_MD   = "15px"
FONT_SIZE_LG   = "17px"
FONT_SIZE_XL   = "20px"
FONT_SIZE_TITLE = "26px"
FONT_SIZE_HERO  = "32px"

ICON_SM   = "16px"
ICON_MD   = "20px"
ICON_LG   = "24px"
ICON_XL   = "32px"
ICON_HERO = "48px"

RADIUS    = "6px"
RADIUS_LG = "10px"
RADIUS_XL = "14px"


# ─── Hoja de estilos QSS ────────────────────────────────────────────

def get_stylesheet() -> str:
    """Devuelve la hoja de estilos QSS completa."""
    c = COLORS
    return f"""
    /* ===== Global ===== */
    * {{
        font-family: {FONT_FAMILY};
        font-size: {FONT_SIZE_BASE};
        color: {c['fg']};
        outline: none;
    }}

    QMainWindow, QDialog {{
        background-color: {c['bg']};
    }}

    /* ===== Labels ===== */
    QLabel {{
        background: transparent;
        padding: 0;
    }}
    QLabel[class="hero"] {{
        font-size: {FONT_SIZE_HERO};
        font-weight: bold;
        letter-spacing: -0.5px;
    }}
    QLabel[class="title"] {{
        font-size: {FONT_SIZE_TITLE};
        font-weight: bold;
        letter-spacing: -0.3px;
    }}
    QLabel[class="subtitle"] {{
        font-size: {FONT_SIZE_LG};
        font-weight: 600;
    }}
    QLabel[class="body"] {{
        font-size: {FONT_SIZE_BASE};
        color: {c['fg']};
    }}
    QLabel[class="muted"] {{
        color: {c['fg_muted']};
        font-size: {FONT_SIZE_SM};
    }}
    QLabel[class="caption"] {{
        color: {c['fg_dim']};
        font-size: {FONT_SIZE_XS};
    }}

    /* ===== Cards ===== */
    QFrame[class="card"] {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS_LG};
        padding: 20px;
    }}

    /* ===== Sidebar ===== */
    QFrame[class="sidebar"] {{
        background-color: {c['bg_card']};
        border-right: 1px solid {c['border']};
    }}

    /* ===== Buttons ===== */
    QPushButton {{
        background-color: {c['primary']};
        color: {c['bg']};
        border: none;
        border-radius: {RADIUS};
        padding: 8px 20px;
        font-weight: 600;
        font-size: {FONT_SIZE_BASE};
    }}
    QPushButton:hover {{
        background-color: {c['primary_hover']};
    }}
    QPushButton:pressed {{
        background-color: {c['primary']};
    }}
    QPushButton:disabled {{
        background-color: {c['bg_secondary']};
        color: {c['fg_dim']};
    }}
    QPushButton[class="ghost"] {{
        background-color: transparent;
        color: {c['fg_muted']};
        padding: 6px 14px;
        font-size: {FONT_SIZE_SM};
    }}
    QPushButton[class="ghost"]:hover {{
        background-color: {c['bg_hover']};
        color: {c['fg']};
    }}
    QPushButton[class="sidebar-item"] {{
        background-color: transparent;
        color: {c['fg_muted']};
        text-align: left;
        padding: 9px 14px;
        border-radius: {RADIUS};
        font-weight: 500;
        font-size: {FONT_SIZE_MD};
    }}
    QPushButton[class="sidebar-item"]:hover {{
        background-color: {c['bg_secondary']};
        color: {c['fg']};
    }}
    QPushButton[class="sidebar-item-active"] {{
        background-color: {c['primary_dim']};
        color: {c['primary']};
        text-align: left;
        padding: 9px 14px;
        border-radius: {RADIUS};
        font-weight: 700;
        font-size: {FONT_SIZE_MD};
    }}
    QPushButton[class="destructive"] {{
        background-color: {c['destructive']};
        color: white;
    }}

    /* ===== Inputs ===== */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {c['bg_input']};
        border: 2px solid {c['border']};
        border-radius: {RADIUS};
        padding: 7px 11px;
        color: {c['fg']};
        font-size: {FONT_SIZE_BASE};
        selection-background-color: {c['primary_dim']};
        min-height: 22px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {c['border_focus']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 28px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border']};
        selection-background-color: {c['primary_dim']};
        font-size: {FONT_SIZE_BASE};
    }}

    /* ===== TextEdit ===== */
    QTextEdit, QPlainTextEdit {{
        background-color: {c['bg_input']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS};
        padding: 10px;
        color: {c['fg']};
        font-size: {FONT_SIZE_BASE};
    }}

    /* ===== Tables ===== */
    QTableWidget, QTableView {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS};
        gridline-color: {c['border']};
        alternate-background-color: {c['bg_secondary']};
        font-size: {FONT_SIZE_BASE};
    }}
    QHeaderView::section {{
        background-color: {c['bg_secondary']};
        color: {c['fg_muted']};
        border: none;
        border-bottom: 1px solid {c['border']};
        padding: 8px 12px;
        font-weight: 600;
        font-size: {FONT_SIZE_SM};
    }}
    QTableWidget::item {{
        padding: 6px 10px;
    }}
    QTableWidget::item:selected {{
        background-color: {c['primary_dim']};
        color: {c['fg']};
    }}

    /* ===== ScrollBars ===== */
    QScrollBar:vertical {{
        background-color: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {c['scrollbar']};
        min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {c['scrollbar_hover']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 8px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {c['scrollbar']};
        min-width: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {c['scrollbar_hover']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}

    /* ===== Tabs ===== */
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: {RADIUS};
        background-color: {c['bg_card']};
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {c['fg_muted']};
        padding: 10px 20px;
        border: none;
        border-bottom: 2px solid transparent;
        font-weight: 500;
        font-size: {FONT_SIZE_BASE};
    }}
    QTabBar::tab:selected {{
        color: {c['primary']};
        border-bottom-color: {c['primary']};
        font-weight: 600;
    }}
    QTabBar::tab:hover:!selected {{
        color: {c['fg']};
    }}

    /* ===== ToolTips ===== */
    QToolTip {{
        background-color: {c['bg_card']};
        color: {c['fg']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 6px 10px;
        font-size: {FONT_SIZE_SM};
    }}

    /* ===== QMenu (menú contextual) ===== */
    QMenu {{
        background-color: {c['menu_bg']};
        border: 1px solid {c['menu_border']};
        border-radius: {RADIUS};
        padding: 4px 0px;
    }}
    QMenu::item {{
        background-color: transparent;
        color: {c['fg']};
        padding: 6px 28px 6px 20px;
        font-size: {FONT_SIZE_BASE};
    }}
    QMenu::item:selected {{
        background-color: {c['menu_selected']};
        color: {c['fg']};
    }}
    QMenu::item:disabled {{
        color: {c['fg_dim']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 4px 10px;
    }}
    QMenu::indicator {{
        width: 16px;
        height: 16px;
        margin-left: 4px;
    }}

    /* ===== Diálogos nativos estilizados ===== */
    QInputDialog, QMessageBox, QProgressDialog {{
        background-color: {c['bg']};
    }}
    QFileDialog {{
        background-color: {c['bg']};
    }}

    /* ===== Separators ===== */
    QFrame[class="separator"] {{
        background-color: {c['border']};
        max-height: 1px;
    }}

    /* ===== Progress Bar ===== */
    QProgressBar {{
        background-color: {c['bg_secondary']};
        border: none;
        border-radius: 5px;
        text-align: center;
        color: {c['fg']};
        font-size: {FONT_SIZE_SM};
        min-height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: {c['primary']};
        border-radius: 5px;
    }}

    /* ===== GroupBox ===== */
    QGroupBox {{
        border: 1px solid {c['border']};
        border-radius: {RADIUS};
        margin-top: 14px;
        padding-top: 20px;
        font-weight: 600;
        font-size: {FONT_SIZE_BASE};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 8px;
        color: {c['fg_muted']};
    }}

    /* ===== ListWidget ===== */
    QListWidget {{
        background-color: {c['bg_card']};
        border: 1px solid {c['border']};
        border-radius: {RADIUS};
        font-size: {FONT_SIZE_MD};
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 10px 14px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {c['primary_dim']};
        color: {c['primary']};
    }}
    QListWidget::item:hover:!selected {{
        background-color: {c['bg_hover']};
    }}
    """
