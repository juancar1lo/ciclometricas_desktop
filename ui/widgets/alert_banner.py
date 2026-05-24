"""Widget AlertBanner — barra informativa o de advertencia."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, ICON_MD, ICON_LG,
)


class AlertBanner(QFrame):
    """Banner de alerta con icono, texto y botón opcional de cerrar."""

    VARIANTS = {
        "info":    {"bg": "rgba(0, 188, 212, 0.12)",  "border": COLORS["accent"],      "fg": COLORS["accent"]},
        "warning": {"bg": "rgba(245, 158, 11, 0.12)", "border": COLORS["warning"],     "fg": COLORS["warning"]},
        "success": {"bg": "rgba(34, 197, 94, 0.12)",  "border": COLORS["success"],     "fg": COLORS["success"]},
        "error":   {"bg": "rgba(239, 68, 68, 0.12)",  "border": COLORS["destructive"], "fg": COLORS["destructive"]},
    }

    def __init__(
        self,
        text: str,
        variant: str = "info",
        icon: str = "\u2139\ufe0f",
        dismissable: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        style = self.VARIANTS.get(variant, self.VARIANTS["info"])
        self.setStyleSheet(
            f"background-color: {style['bg']}; "
            f"border: 1px solid {style['border']}; "
            f"border-radius: 6px; padding: 10px 14px;"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        ico = QLabel(icon)
        ico.setStyleSheet(f"font-size: {ICON_MD}; background: transparent;")
        layout.addWidget(ico)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"color: {style['fg']}; font-size: {FONT_SIZE_BASE}; background: transparent;"
        )
        layout.addWidget(msg, stretch=1)

        if dismissable:
            btn = QPushButton("\u2715")
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"background: transparent; color: {style['fg']}; "
                f"border: none; font-size: {FONT_SIZE_BASE}; font-weight: bold;"
            )
            btn.clicked.connect(self._dismiss)
            layout.addWidget(btn)

    def _dismiss(self) -> None:
        self.setVisible(False)
        self.deleteLater()
