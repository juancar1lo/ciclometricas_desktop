"""Gráfico de series temporales para detalle de actividad.

Replica la vista web: potencia/FC/cadencia/velocidad/W'bal/altitud
con toggles, tooltip y altitud renderizada como banda inferior.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_LG,
    FONT_SIZE_XS, FONT_SIZE_XL,
)
from ui.charts.chart_utils import (
    _qcolor, make_plot, ChartTooltip, tooltip_line, tooltip_header, tooltip_html,
)
from calc.wbal import compute_wbal_from_samples


# Colores de las series (coherentes con la web)
SERIES_COLORS = {
    "power":    "#FF9149",
    "hr":       "#F87171",
    "cadence":  "#34D399",
    "speed":    "#22D3EE",
    "wbal":     "#FBBF24",
    "altitude": "#A8A29E",
}


def _fmt_hms(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


class TimeSeriesChart(QFrame):
    """Gráfico de series temporales con toggles y tooltip."""

    def __init__(
        self,
        samples: list[dict],
        duration_sec: int,
        cp: float | None = None,
        w_prime_j: float | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("class", "card")

        self._samples = sorted(samples, key=lambda s: s.get("t", 0))
        self._duration = duration_sec or (self._samples[-1]["t"] if self._samples else 0)
        self._cp = cp
        self._w_prime_j = w_prime_j

        # Detectar series disponibles
        self._has_power = any(s.get("p") is not None for s in self._samples)
        self._has_hr = any(s.get("hr") is not None for s in self._samples)
        self._has_cadence = any(s.get("c") is not None for s in self._samples)
        self._has_speed = any(
            s.get("v") is not None or s.get("s") is not None for s in self._samples
        )

        # Altitud con variación significativa
        alt_vals = [s["alt"] for s in self._samples if s.get("alt") is not None]
        if len(alt_vals) >= 2:
            self._alt_min = min(alt_vals)
            self._alt_max = max(alt_vals)
            self._has_alt = (self._alt_max - self._alt_min) > 10
        else:
            self._alt_min, self._alt_max = 0, 0
            self._has_alt = False

        # W'bal
        self._has_wbal = False
        self._wbal_map: Dict[int, int] = {}
        if cp and cp > 0 and w_prime_j and w_prime_j > 0:
            wbal_samples = [(s.get("t", 0), s.get("p")) for s in self._samples]
            wbal_pts = compute_wbal_from_samples(wbal_samples, cp, w_prime_j)
            if wbal_pts:
                self._has_wbal = True
                self._wbal_map = {wp.t: wp.pct for wp in wbal_pts}

        # Estados toggle (defaults: potencia + FC + altitud + W'bal si disponibles)
        self._show = {
            "power":    self._has_power,
            "hr":       self._has_hr,
            "cadence":  False,
            "speed":    False,
            "wbal":     self._has_wbal,
            "altitude": self._has_alt,
        }

        # Referencia al tooltip (importante para evitar GC)
        self._tooltip: Optional[ChartTooltip] = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # Header (título + toggles)
        header = QHBoxLayout()
        header.setSpacing(8)

        title_col = QVBoxLayout()
        title = QLabel("📈 Series temporales")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: bold; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        title_col.addWidget(title)
        desc = QLabel("Potencia, FC, cadencia, velocidad y altitud a lo largo del entrenamiento.")
        desc.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        title_col.addWidget(desc)
        header.addLayout(title_col, stretch=1)

        # Toggle buttons
        toggles_layout = QHBoxLayout()
        toggles_layout.setSpacing(6)

        self._toggle_btns: Dict[str, QPushButton] = {}
        toggle_defs = [
            ("altitude", "Altitud",   self._has_alt,     SERIES_COLORS["altitude"]),
            ("wbal",     "W' bal",    self._has_wbal,    SERIES_COLORS["wbal"]),
            ("hr",       "FC",        self._has_hr,      SERIES_COLORS["hr"]),
            ("cadence",  "Cadencia",  self._has_cadence, SERIES_COLORS["cadence"]),
            ("speed",    "Velocidad", self._has_speed,   SERIES_COLORS["speed"]),
        ]

        for key, label, available, color in toggle_defs:
            if not available:
                continue
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("toggle_key", key)
            btn.setProperty("toggle_color", color)
            self._style_toggle_btn(btn, key, color)
            btn.clicked.connect(
                lambda checked=False, k=key, c=color, b=btn: self._on_toggle(k, c, b)
            )
            toggles_layout.addWidget(btn)
            self._toggle_btns[key] = btn

        header.addLayout(toggles_layout)
        layout.addLayout(header)

        # Gráfico
        self._pw = make_plot(height=340)
        self._pw.setBackground(_qcolor(COLORS["bg_card"]))
        layout.addWidget(self._pw)

        self._draw()

    def _style_toggle_btn(self, btn: QPushButton, key: str, color: str):
        """Pill button style: solid color cuando activo, outline cuando inactivo."""
        active = self._show.get(key, False)
        if active:
            # Pill activo: fondo color marca, texto blanco con punto a la izquierda
            btn.setText(f"\u25cf  {self._toggle_label(key)}")
            btn.setStyleSheet(
                f"QPushButton {{ "
                f"  background: {color}; color: #ffffff; "
                f"  border: 1px solid {color}; border-radius: 6px; "
                f"  font-size: {FONT_SIZE_XS}; padding: 4px 12px; font-weight: 600; "
                f"}}"
                f"QPushButton:hover {{ background: {color}; }}"
            )
        else:
            # Pill inactivo: outline gris, punto coloreado a la izquierda
            btn.setText(f"\u25cf  {self._toggle_label(key)}")
            btn.setStyleSheet(
                f"QPushButton {{ "
                f"  background: transparent; color: {COLORS['fg_muted']}; "
                f"  border: 1px solid {COLORS['border']}; border-radius: 6px; "
                f"  font-size: {FONT_SIZE_XS}; padding: 4px 12px; font-weight: 500; "
                f"}}"
                f"QPushButton:hover {{ background: {COLORS['bg_hover']}; "
                f"  color: {COLORS['fg']}; border-color: {color}; }}"
            )

    @staticmethod
    def _toggle_label(key: str) -> str:
        return {
            "altitude": "Altitud",
            "wbal":     "W' bal",
            "hr":       "FC",
            "cadence":  "Cadencia",
            "speed":    "Velocidad",
        }.get(key, key)

    def _on_toggle(self, key: str, color: str, btn: QPushButton):
        self._show[key] = not self._show[key]
        self._style_toggle_btn(btn, key, color)
        self._draw()

    def _draw(self):
        # Limpiar tooltip viejo antes de pw.clear()
        if self._tooltip is not None:
            try:
                self._tooltip.clear()
            except Exception:
                pass
            self._tooltip = None

        self._pw.clear()
        self._pw.showGrid(x=True, y=True, alpha=0.12)

        if not self._samples:
            return

        ts = np.array([s.get("t", 0) for s in self._samples], dtype=float)

        # X-axis ticks adaptados a la duración
        dur = self._duration
        if dur < 600:
            step = 60
        elif dur < 1800:
            step = 300
        elif dur < 3600:
            step = 600
        elif dur < 7200:
            step = 900
        else:
            step = 1800

        x_ticks = []
        t = 0
        while t <= dur:
            x_ticks.append((t, _fmt_hms(t)))
            t += step
        ax_bottom = self._pw.getAxis("bottom")
        ax_bottom.setTicks([x_ticks])

        # ── Determinar y_max_val antes para escalar altitud
        y_max_val = 0.0
        if self._show.get("power") and self._has_power:
            p_vals_pre = [s.get("p") or 0 for s in self._samples]
            if p_vals_pre:
                y_max_val = max(y_max_val, float(max(p_vals_pre)))
        if self._show.get("hr") and self._has_hr:
            hr_pre = [s.get("hr") or 0 for s in self._samples]
            if hr_pre:
                y_max_val = max(y_max_val, float(max(hr_pre)))
        if self._show.get("cadence") and self._has_cadence:
            c_pre = [s.get("c") or 0 for s in self._samples]
            if c_pre:
                y_max_val = max(y_max_val, float(max(c_pre)))
        if self._show.get("speed") and self._has_speed:
            s_pre = [(s.get("v") or s.get("s") or 0) * 3.6 for s in self._samples]
            if s_pre:
                y_max_val = max(y_max_val, float(max(s_pre)))
        if self._show.get("wbal") and self._has_wbal:
            scale = max(y_max_val, 600) / 100.0
            y_max_val = max(y_max_val, 100.0 * scale)

        if y_max_val <= 0:
            y_max_val = 100.0
        y_top = y_max_val * 1.1

        # ── ALTITUD primero (al fondo) en banda inferior 40%
        if self._show.get("altitude") and self._has_alt:
            alt_vals = np.array(
                [s.get("alt", np.nan) for s in self._samples], dtype=float
            )
            valid_mask = ~np.isnan(alt_vals)
            if valid_mask.any():
                ts_v = ts[valid_mask]
                alt_v = alt_vals[valid_mask]
                # Escalar [alt_min, alt_max] -> [0, y_top * 0.4]
                alt_rng = max(self._alt_max - self._alt_min, 1.0)
                target_top = y_top * 0.40
                alt_scaled = (alt_v - self._alt_min) / alt_rng * target_top
                # Curva
                curve_top = pg.PlotDataItem(
                    ts_v, alt_scaled,
                    pen=pg.mkPen(color=SERIES_COLORS["altitude"], width=1.0),
                )
                curve_bottom = pg.PlotDataItem(
                    ts_v, np.zeros_like(alt_scaled),
                    pen=pg.mkPen(None),
                )
                fill = pg.FillBetweenItem(
                    curve_top, curve_bottom,
                    brush=_qcolor(SERIES_COLORS["altitude"], 50),
                )
                self._pw.addItem(fill)
                self._pw.addItem(curve_top)

        # ── POTENCIA (área rellena)
        if self._show.get("power") and self._has_power:
            p_vals = np.array(
                [s.get("p") or 0 for s in self._samples], dtype=float
            )
            self._pw.plot(
                ts, p_vals,
                pen=pg.mkPen(color=SERIES_COLORS["power"], width=1.5),
                fillLevel=0,
                fillBrush=_qcolor(SERIES_COLORS["power"], 80),
                name="Potencia (W)",
            )

        # ── W'BAL (escalado a y_top)
        if self._show.get("wbal") and self._has_wbal:
            scale = max(y_max_val, 600) / 100.0
            wbal_ts: list[float] = []
            wbal_vs: list[float] = []
            for s in self._samples:
                t_int = int(s.get("t", 0))
                if t_int in self._wbal_map:
                    wbal_ts.append(s["t"])
                    wbal_vs.append(self._wbal_map[t_int] * scale)
            if wbal_ts:
                self._pw.plot(
                    np.array(wbal_ts), np.array(wbal_vs),
                    pen=pg.mkPen(color=SERIES_COLORS["wbal"], width=1.8),
                    name="W' bal (%)",
                )

        # ── FC
        if self._show.get("hr") and self._has_hr:
            hr_vals = np.array(
                [s.get("hr") or 0 for s in self._samples], dtype=float
            )
            self._pw.plot(
                ts, hr_vals,
                pen=pg.mkPen(color=SERIES_COLORS["hr"], width=1.5),
                name="FC (bpm)",
            )

        # ── Cadencia
        if self._show.get("cadence") and self._has_cadence:
            c_vals = np.array(
                [s.get("c") or 0 for s in self._samples], dtype=float
            )
            self._pw.plot(
                ts, c_vals,
                pen=pg.mkPen(color=SERIES_COLORS["cadence"], width=1.2),
                name="Cadencia (rpm)",
            )

        # ── Velocidad (convertir m/s → km/h)
        if self._show.get("speed") and self._has_speed:
            v_vals = np.array(
                [(s.get("v") or s.get("s") or 0) * 3.6 for s in self._samples], dtype=float
            )
            self._pw.plot(
                ts, v_vals,
                pen=pg.mkPen(color=SERIES_COLORS["speed"], width=1.2),
                name="Velocidad (km/h)",
            )

        # Rango Y final
        self._pw.setYRange(0, y_top, padding=0)
        self._pw.setXRange(0, dur, padding=0)

        # Tooltip — guardar referencia para que no sea recolectado
        self._attach_tooltip(ts)

    def _attach_tooltip(self, ts: np.ndarray):
        samples = self._samples
        show = self._show
        wbal_map = self._wbal_map
        has = {
            "power":    self._has_power,
            "hr":       self._has_hr,
            "cadence":  self._has_cadence,
            "speed":    self._has_speed,
            "wbal":     self._has_wbal,
            "altitude": self._has_alt,
        }

        def format_fn(x: float, y: float) -> str:
            if len(samples) == 0:
                return ""
            idx = int(np.argmin(np.abs(ts - x)))
            idx = max(0, min(idx, len(samples) - 1))
            s = samples[idx]
            lines = [tooltip_header(_fmt_hms(s.get("t", 0)))]

            if has["power"] and show.get("power") and s.get("p") is not None:
                lines.append(tooltip_line("Potencia", f"{int(s['p'])} W", SERIES_COLORS["power"]))

            if has["wbal"] and show.get("wbal"):
                t_int = int(s.get("t", 0))
                pct = wbal_map.get(t_int)
                if pct is not None:
                    lines.append(tooltip_line("W' bal", f"{pct}%", SERIES_COLORS["wbal"]))

            if has["hr"] and show.get("hr") and s.get("hr") is not None:
                lines.append(tooltip_line("FC", f"{int(s['hr'])} bpm", SERIES_COLORS["hr"]))

            if has["cadence"] and show.get("cadence") and s.get("c") is not None:
                lines.append(tooltip_line("Cadencia", f"{int(s['c'])} rpm", SERIES_COLORS["cadence"]))

            if has["speed"] and show.get("speed"):
                spd = s.get("v") or s.get("s")
                if spd is not None:
                    spd_kmh = spd * 3.6  # m/s → km/h
                    lines.append(tooltip_line("Velocidad", f"{spd_kmh:.1f} km/h", SERIES_COLORS["speed"]))

            if has["altitude"] and show.get("altitude") and s.get("alt") is not None:
                lines.append(tooltip_line("Altitud", f"{int(s['alt'])} m", SERIES_COLORS["altitude"]))

            return tooltip_html(lines)

        # CRUCIAL: guardar referencia en self para evitar garbage collection
        self._tooltip = ChartTooltip(self._pw, format_fn, snap_xs=ts)
