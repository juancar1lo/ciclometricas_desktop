"""Diálogo para registrar sesiones manuales (fuerza, caminar, otro).

TSS = horas × IF² × 100
Presets de IF percibido por tipo de actividad.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import Qt, QDate, QTime, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QDateEdit, QTimeEdit, QDoubleSpinBox, QSpinBox,
    QFrame, QGridLayout, QPushButton, QLineEdit, QWidget,
)

from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_XS, FONT_SIZE_LG,
    FONT_SIZE_XL, FONT_SIZE_TITLE, RADIUS_LG,
)


# ── Presets de IF por tipo de actividad ──
_TYPE_PRESETS: dict[str, dict] = {
    "strength": {
        "label": "🏋️ Fuerza",
        "sport": "strength",
        "intensities": [
            ("Suave (mantenimiento)", 0.55),
            ("Moderada (hipertrofia)", 0.70),
            ("Alta (fuerza máx.)", 0.82),
        ],
    },
    "walk": {
        "label": "🚶 Caminar",
        "sport": "walking",
        "intensities": [
            ("Paseo suave", 0.35),
            ("Caminata rápida", 0.48),
            ("Marcha intensa", 0.60),
        ],
    },
    "other": {
        "label": "🏃 Otro",
        "sport": "other",
        "intensities": [
            ("Baja intensidad", 0.40),
            ("Intensidad media", 0.60),
            ("Alta intensidad", 0.78),
        ],
    },
}


def _calc_tss(hours: float, if_val: float) -> float:
    """TSS = horas × IF² × 100."""
    return hours * (if_val ** 2) * 100


class ManualSessionDialog(QDialog):
    """Diálogo para registrar una sesión manual."""

    def __init__(self, ftp: int = 0, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Registrar sesión manual")
        self.setMinimumWidth(480)
        self._ftp = ftp
        self._result_data: Optional[dict] = None

        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(24, 20, 24, 16)
        main_lay.setSpacing(14)

        # ── Tipo de actividad ──
        type_lbl = QLabel("Tipo de actividad")
        type_lbl.setStyleSheet(f"font-weight: 600; font-size: {FONT_SIZE_SM}; color: {COLORS['fg']};")
        main_lay.addWidget(type_lbl)

        self._type_combo = QComboBox()
        self._type_combo.setFixedHeight(36)
        for key, preset in _TYPE_PRESETS.items():
            self._type_combo.addItem(preset["label"], key)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        main_lay.addWidget(self._type_combo)

        # ── Nombre personalizado ──
        name_lbl = QLabel("Nombre (opcional)")
        name_lbl.setStyleSheet(f"font-weight: 600; font-size: {FONT_SIZE_SM}; color: {COLORS['fg']};")
        main_lay.addWidget(name_lbl)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Ej: Fuerza tren superior")
        self._name_input.setFixedHeight(36)
        main_lay.addWidget(self._name_input)

        # ── Fecha y hora ──
        dt_row = QHBoxLayout()
        dt_row.setSpacing(12)

        date_col = QVBoxLayout()
        date_lbl = QLabel("Fecha")
        date_lbl.setStyleSheet(f"font-weight: 600; font-size: {FONT_SIZE_SM}; color: {COLORS['fg']};")
        date_col.addWidget(date_lbl)
        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setFixedHeight(36)
        date_col.addWidget(self._date_edit)
        dt_row.addLayout(date_col)

        time_col = QVBoxLayout()
        time_lbl = QLabel("Hora")
        time_lbl.setStyleSheet(f"font-weight: 600; font-size: {FONT_SIZE_SM}; color: {COLORS['fg']};")
        time_col.addWidget(time_lbl)
        self._time_edit = QTimeEdit(QTime.currentTime())
        self._time_edit.setFixedHeight(36)
        time_col.addWidget(self._time_edit)
        dt_row.addLayout(time_col)

        dur_col = QVBoxLayout()
        dur_lbl = QLabel("Duración (min)")
        dur_lbl.setStyleSheet(f"font-weight: 600; font-size: {FONT_SIZE_SM}; color: {COLORS['fg']};")
        dur_col.addWidget(dur_lbl)
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 600)
        self._duration_spin.setValue(60)
        self._duration_spin.setSuffix(" min")
        self._duration_spin.setFixedHeight(36)
        self._duration_spin.valueChanged.connect(self._recalc_tss)
        dur_col.addWidget(self._duration_spin)
        dt_row.addLayout(dur_col)

        main_lay.addLayout(dt_row)

        # ── Intensidad percibida ──
        int_lbl = QLabel("Intensidad percibida (IF)")
        int_lbl.setStyleSheet(f"font-weight: 600; font-size: {FONT_SIZE_SM}; color: {COLORS['fg']};")
        main_lay.addWidget(int_lbl)

        # Preset buttons row
        self._preset_row = QHBoxLayout()
        self._preset_row.setSpacing(8)
        self._preset_buttons: list[QPushButton] = []
        main_lay.addLayout(self._preset_row)

        # Manual IF slider
        if_row = QHBoxLayout()
        if_row.setSpacing(10)
        if_manual_lbl = QLabel("IF manual:")
        if_manual_lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        if_row.addWidget(if_manual_lbl)
        self._if_spin = QDoubleSpinBox()
        self._if_spin.setRange(0.10, 1.50)
        self._if_spin.setSingleStep(0.01)
        self._if_spin.setDecimals(2)
        self._if_spin.setValue(0.55)
        self._if_spin.setFixedHeight(36)
        self._if_spin.valueChanged.connect(self._recalc_tss)
        if_row.addWidget(self._if_spin)
        if_row.addStretch()
        main_lay.addLayout(if_row)

        # ── TSS preview ──
        tss_frame = QFrame()
        tss_frame.setStyleSheet(
            f"background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: {RADIUS_LG}; padding: 12px;"
        )
        tss_inner = QVBoxLayout(tss_frame)
        tss_inner.setContentsMargins(16, 10, 16, 10)
        tss_inner.setSpacing(4)
        tss_title = QLabel("TSS ESTIMADO")
        tss_title.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; font-weight: 600;"
        )
        tss_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tss_inner.addWidget(tss_title)
        self._tss_label = QLabel("—")
        self._tss_label.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: 700; color: {COLORS['fg']};"
        )
        self._tss_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tss_inner.addWidget(self._tss_label)
        self._tss_formula = QLabel("")
        self._tss_formula.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']};"
        )
        self._tss_formula.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tss_inner.addWidget(self._tss_formula)
        main_lay.addWidget(tss_frame)

        # ── Buttons ──
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("Guardar")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        main_lay.addWidget(btn_box)

        # Initialize
        self._on_type_changed(0)
        self._recalc_tss()

    def _on_type_changed(self, _idx: int) -> None:
        """Update intensity presets when activity type changes."""
        # Clear old buttons
        while self._preset_row.count():
            item = self._preset_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._preset_buttons.clear()

        key = self._type_combo.currentData()
        preset = _TYPE_PRESETS.get(key, _TYPE_PRESETS["other"])

        for label, if_val in preset["intensities"]:
            btn = QPushButton(f"{label} ({if_val:.2f})")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; padding: 4px 12px; "
                f"background: {COLORS['bg_card']}; color: {COLORS['fg']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 6px;"
            )
            _if = if_val
            btn.clicked.connect(lambda checked=False, v=_if: self._if_spin.setValue(v))
            self._preset_row.addWidget(btn)
            self._preset_buttons.append(btn)
        self._preset_row.addStretch()

        # Set default IF for this type
        if preset["intensities"]:
            self._if_spin.setValue(preset["intensities"][0][1])

    def _recalc_tss(self, _=None) -> None:
        """Recalculate and display TSS preview."""
        dur_min = self._duration_spin.value()
        if_val = self._if_spin.value()
        hours = dur_min / 60.0
        tss = _calc_tss(hours, if_val)
        self._tss_label.setText(f"{tss:.1f}")
        self._tss_formula.setText(f"{hours:.2f}h × {if_val:.2f}² × 100 = {tss:.1f}")

    def _on_accept(self) -> None:
        """Build result dict and accept dialog."""
        key = self._type_combo.currentData()
        preset = _TYPE_PRESETS.get(key, _TYPE_PRESETS["other"])
        dur_min = self._duration_spin.value()
        if_val = self._if_spin.value()
        hours = dur_min / 60.0
        tss = _calc_tss(hours, if_val)

        qd = self._date_edit.date()
        qt = self._time_edit.time()
        started = datetime(
            qd.year(), qd.month(), qd.day(),
            qt.hour(), qt.minute(), 0,
            tzinfo=timezone.utc,
        )

        custom_name = self._name_input.text().strip()
        if not custom_name:
            custom_name = preset["label"]

        self._result_data = {
            "started_at": started,
            "sport": preset["sport"],
            "activity_type": key,
            "is_manual": True,
            "source": "manual",
            "duration_sec": dur_min * 60,
            "distance_km": 0.0,
            "tss": round(tss, 1),
            "intensity_factor": round(if_val, 2),
            "perceived_if": round(if_val, 2),
            "custom_name": custom_name,
            "ftp_used": self._ftp,
        }
        self.accept()

    def get_result(self) -> Optional[dict]:
        """Return the manual session data (None if cancelled)."""
        return self._result_data
