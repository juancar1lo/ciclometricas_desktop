"""Widget StatCard reutilizable — muestra una métrica con icono, valor, unidad, hint y trend badge.

NO usa la propiedad class="card" del QSS global para evitar que el padding
de 20px aplaste el contenido en tarjetas pequeñas.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_XS, FONT_SIZE_LG,
    FONT_SIZE_XL, ICON_MD, RADIUS_LG,
)


class StatCard(QFrame):
    """Tarjeta de métrica individual.

    Params:
        icon:  emoji o texto corto (se muestra grande)
        label: nombre de la métrica
        value: valor numérico como string
        unit:  unidad (W, bpm, kg, etc.)
        hint:  texto secundario opcional
        accent: color de acento (por defecto naranja)
        trend_value: texto del badge de tendencia (ej: "+10")
        trend_label: etiqueta del badge (ej: "En forma")
        trend_color: color del badge (fondo semitransparente)
    """

    def __init__(
        self,
        icon: str = "",
        label: str = "",
        value: str = "\u2014",
        unit: str = "",
        hint: str = "",
        accent: str = "",
        trend_value: str = "",
        trend_label: str = "",
        trend_color: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet(
            f"StatCard {{ "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']}; "
            f"border-radius: {RADIUS_LG}; "
            f"}}"
        )
        self.setMinimumWidth(140)
        self.setMinimumHeight(110)

        _accent = accent or COLORS["primary"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 8)
        layout.setSpacing(3)

        # Fila superior: icono + label
        top = QHBoxLayout()
        top.setSpacing(5)
        if icon:
            ico = QLabel(icon)
            ico.setStyleSheet(f"font-size: {ICON_MD}; background: transparent; border: none;")
            top.addWidget(ico)
        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
            f"font-weight: 600; text-transform: uppercase; background: transparent; border: none;"
        )
        top.addWidget(lbl)
        top.addStretch()
        layout.addLayout(top)

        # Valor + unidad
        val_row = QHBoxLayout()
        val_row.setSpacing(4)
        self._value_label = QLabel(value)
        self._value_label.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: 700; "
            f"color: {COLORS['fg']}; background: transparent; border: none;"
        )
        val_row.addWidget(self._value_label)
        if unit:
            u = QLabel(unit)
            u.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                f"background: transparent; border: none; padding-bottom: 1px;"
            )
            u.setAlignment(Qt.AlignmentFlag.AlignBottom)
            val_row.addWidget(u)
        val_row.addStretch()
        layout.addLayout(val_row)

        # Hint
        self._hint_label: QLabel | None = None
        if hint:
            h = QLabel(hint)
            h.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; "
                f"background: transparent; border: none;"
            )
            h.setWordWrap(True)
            layout.addWidget(h)
            self._hint_label = h

        # Trend badge (ej: "+10 En forma", "-2.2 Decreciente")
        self._trend_frame: QFrame | None = None
        if trend_label:
            tc = trend_color or COLORS["success"]
            badge = QFrame()
            badge.setStyleSheet(
                f"background: {tc}; border-radius: 8px; border: none;"
            )
            badge_lay = QHBoxLayout(badge)
            badge_lay.setContentsMargins(8, 2, 8, 2)
            badge_lay.setSpacing(4)
            badge_text = trend_value + " " + trend_label if trend_value else trend_label
            badge_lbl = QLabel(badge_text.strip())
            badge_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; font-weight: 700; color: #fff; "
                f"background: transparent; border: none;"
            )
            badge_lay.addWidget(badge_lbl)
            badge_lay.addStretch()
            layout.addWidget(badge)
            self._trend_frame = badge

        layout.addStretch()

        # Barra de acento inferior
        bar = QFrame()
        bar.setFixedHeight(3)
        bar.setStyleSheet(
            f"background-color: {_accent}; border-radius: 1px; border: none;"
        )
        layout.addWidget(bar)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_hint(self, text: str) -> None:
        if self._hint_label:
            self._hint_label.setText(text)
