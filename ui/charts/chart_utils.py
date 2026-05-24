"""Utilidades comunes para gráficos pyqtgraph.

Proporciona helpers para crear PlotWidgets con estilo consistente.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ui.theme import COLORS, FONT_FAMILY

# Paleta de colores para series
CHART_COLORS = {
    "ctl":      "#FF9149",   # naranja
    "atl":      "#FF6363",   # rojo-coral
    "tsb":      "#60B5FF",   # azul claro
    "tss":      "#80D8C3",   # verde-menta
    "cp":       "#FF9149",
    "w_prime":  "#22d3ee",   # cyan
    "mmp":      "#22d3ee",
    "model":    "#FF6B35",   # naranja primario
    "ftp":      "#60B5FF",
    "mftp":     "#80D8C3",
    "weight":   "#A19AD3",   # lavanda
    "ef":       "#34D399",   # esmeralda (paridad web)
    "vf":       "#FBBF24",   # ámbar (paridad web)
    "pwhr":     "#22d3ee",
    "grid":     "#1e293b",
    "bg":       "#111827",
    "fg":       "#f8fafc",
    "fg_muted": "#6b7d99",
}

# Fuente global para ejes — tamaño 10 para legibilidad
_AXIS_FONT = QFont("Segoe UI", 10)
_TITLE_FONT = QFont("Segoe UI", 10, QFont.Weight.Bold)

# Color de texto de ejes — claro para contraste contra fondo oscuro
_AXIS_TEXT_COLOR = "#cbd5e1"   # slate-300 — alta legibilidad


def _qcolor(hex_str: str, alpha: int = 255) -> QColor:
    c = QColor(hex_str)
    c.setAlpha(alpha)
    return c


def make_plot(
    title: str = "",
    height: int = 280,
    bg: str = CHART_COLORS["bg"],
) -> pg.PlotWidget:
    """Crea un PlotWidget con estilo oscuro."""
    pw = pg.PlotWidget()
    pw.setBackground(_qcolor(bg))
    pw.setMinimumHeight(height)
    pw.setMouseEnabled(x=False, y=False)
    # Deshabilitar zoom con rueda del ratón en el ViewBox principal
    vb = pw.getPlotItem().getViewBox()
    vb.setMouseEnabled(x=False, y=False)
    vb.wheelEvent = lambda ev: ev.ignore()
    pw.hideButtons()
    pw.getPlotItem().setContentsMargins(4, 4, 4, 4)
    
    # Grid
    pw.showGrid(x=True, y=True, alpha=0.15)
    
    # Ejes — texto claro para contraste
    for axis_name in ("bottom", "left", "right"):
        ax = pw.getAxis(axis_name)
        ax.setStyle(tickFont=_AXIS_FONT)
        ax.setTextPen(_qcolor(_AXIS_TEXT_COLOR))
        ax.setPen(_qcolor(CHART_COLORS["grid"]))
    
    return pw


def configure_axis(
    pw: pg.PlotWidget,
    axis: str = "bottom",
    ticks: Optional[list] = None,
    label: str = "",
) -> None:
    """Configura un eje con ticks personalizados."""
    ax = pw.getAxis(axis)
    if ticks is not None:
        ax.setTicks([ticks])
    if label:
        ax.setLabel(label, color=CHART_COLORS["fg_muted"])


def date_to_ts(d: str | date) -> float:
    """Convierte fecha ISO o date a timestamp."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return datetime(d.year, d.month, d.day).timestamp()


def make_date_ticks(dates: List[str], max_ticks: int = 12) -> list:
    """Genera ticks legibles para eje de fechas."""
    if not dates:
        return []
    n = len(dates)
    step = max(1, n // max_ticks)
    ticks = []
    import locale
    for i in range(0, n, step):
        d = date.fromisoformat(dates[i])
        label = f"{d.day:02d} {_MONTH_SHORT[d.month]}"
        ticks.append((date_to_ts(d), label))
    return ticks


_MONTH_SHORT = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr",
    5: "may", 6: "jun", 7: "jul", 8: "ago",
    9: "sept", 10: "oct", 11: "nov", 12: "dic",
}


def make_bar_chart(
    pw: pg.PlotWidget,
    x: np.ndarray,
    heights: np.ndarray,
    width: float = 0.6,
    color: str = "#FF9149",
    alpha: int = 200,
) -> pg.BarGraphItem:
    """Agrega barras a un PlotWidget."""
    bar = pg.BarGraphItem(
        x=x,
        height=heights,
        width=width,
        brush=_qcolor(color, alpha),
        pen=pg.mkPen(None),
    )
    pw.addItem(bar)
    return bar


def add_horizontal_band(
    pw: pg.PlotWidget,
    y_min: float,
    y_max: float,
    color: str,
    alpha: int = 50,
) -> None:
    """Agrega una banda horizontal coloreada."""
    region = pg.LinearRegionItem(
        values=(y_min, y_max),
        orientation="horizontal",
        movable=False,
        brush=_qcolor(color, alpha),
        pen=pg.mkPen(None),
    )
    pw.addItem(region)


def add_horizontal_line(
    pw: pg.PlotWidget,
    y: float,
    color: str = "#ffffff",
    style: Qt.PenStyle = Qt.PenStyle.DashLine,
    width: int = 1,
) -> None:
    """Agrega una línea horizontal punteada."""
    line = pg.InfiniteLine(
        pos=y,
        angle=0,
        pen=pg.mkPen(color=_qcolor(color), style=style, width=width),
    )
    pw.addItem(line)


# ══════════════════════════════════════════════════════════════
# TOOLTIP INTERACTIVO (Crosshair + etiqueta flotante)
# ══════════════════════════════════════════════════════════════

def tooltip_line(label: str, value: str, color: str = "#f1f5f9") -> str:
    """Genera una línea HTML coloreada para un tooltip.

    Ejemplo: tooltip_line("CTL", "72.3", "#FF9149")
    """
    return (
        f'<span style="color:{color};font-weight:600">{label}:</span> '
        f'<span style="color:#f1f5f9">{value}</span>'
    )


def tooltip_header(text: str) -> str:
    """Genera una cabecera HTML para un tooltip."""
    return f'<span style="color:#94a3b8;font-weight:700">{text}</span>'


def tooltip_html(lines: list[str]) -> str:
    """Empaqueta líneas (ya en HTML) en un bloque de tooltip."""
    body = "<br>".join(lines)
    return (
        f'<div style="font-family:Segoe UI,sans-serif;font-size:11pt;'
        f'padding:4px 6px;">{body}</div>'
    )


class ChartTooltip:
    """Crosshair vertical + etiqueta HTML que sigue al ratón.

    El tooltip usa un TextItem con fondo opaco y borde visible para
    máximo contraste sobre el fondo oscuro del gráfico.
    Soporta tanto texto plano (vía format_fn que devuelve str) como
    HTML rico (si format_fn devuelve cadena que empieza con '<').
    """

    def __init__(
        self,
        pw: pg.PlotWidget,
        format_fn: Callable[[float, float], str],
        is_date_axis: bool = False,
        snap_xs: Optional[np.ndarray] = None,
        series_data: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None,
    ):
        self.pw = pw
        self.format_fn = format_fn
        self.is_date_axis = is_date_axis
        self.snap_xs = snap_xs
        self.series_data = series_data or {}

        # Crosshair vertical — blanco semi-transparente
        self.vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(color=_qcolor("#ffffff", 150), width=1,
                         style=Qt.PenStyle.DashLine),
        )
        pw.addItem(self.vline, ignoreBounds=True)
        self.vline.setVisible(False)

        # Etiqueta flotante — fondo opaco oscuro con borde
        self.label = pg.TextItem(
            "",
            color=_qcolor("#f1f5f9"),        # texto slate-100
            anchor=(0, 1),
            fill=_qcolor("#0f172a", 240),    # fondo slate-900
            border=pg.mkPen("#334155", width=1),  # borde slate-700
        )
        self.label.setFont(QFont("Segoe UI", 11))
        self.label.setZValue(1000)
        pw.addItem(self.label, ignoreBounds=True)
        self.label.setVisible(False)

        # Conectar señal de movimiento del ratón
        pw.setMouseEnabled(x=False, y=False)
        self._proxy = pg.SignalProxy(
            pw.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved,
        )

    def _on_mouse_moved(self, evt):
        pos = evt[0]
        vb = self.pw.getPlotItem().getViewBox()
        if not vb.sceneBoundingRect().contains(pos):
            self.vline.setVisible(False)
            self.label.setVisible(False)
            return

        mouse_point = vb.mapSceneToView(pos)
        x = mouse_point.x()
        y = mouse_point.y()

        # Snap a datos discretos si se proporcionaron
        if self.snap_xs is not None and len(self.snap_xs) > 0:
            idx = int(np.argmin(np.abs(self.snap_xs - x)))
            x = float(self.snap_xs[idx])

        self.vline.setPos(x)
        self.vline.setVisible(True)

        # Generar texto
        try:
            text = self.format_fn(x, y)
        except Exception:
            text = ""

        if text:
            # Detectar si es HTML o texto plano
            if text.lstrip().startswith("<"):
                self.label.setHtml(text)
            else:
                self.label.setText(text)

            view_range = vb.viewRange()
            x_range = view_range[0]
            y_range = view_range[1]
            mid_x = (x_range[0] + x_range[1]) / 2

            # Posicionar: esquina superior, lado opuesto al cursor
            if x > mid_x:
                self.label.setAnchor((1, 0))
                lbl_x = x - (x_range[1] - x_range[0]) * 0.01
            else:
                self.label.setAnchor((0, 0))
                lbl_x = x + (x_range[1] - x_range[0]) * 0.01

            # Y: cerca del tope del gráfico (no en el borde exacto)
            lbl_y = y_range[1] - (y_range[1] - y_range[0]) * 0.02

            self.label.setPos(lbl_x, lbl_y)
            self.label.setVisible(True)
        else:
            self.label.setVisible(False)

    def clear(self):
        """Limpia las referencias (llamar antes de pw.clear())."""
        try:
            self.pw.removeItem(self.vline)
            self.pw.removeItem(self.label)
        except Exception:
            pass

    def update_snap_xs(self, xs: np.ndarray):
        self.snap_xs = xs

    def update_series(self, name: str, xs: np.ndarray, ys: np.ndarray):
        self.series_data[name] = (xs, ys)


def attach_tooltip(
    pw: pg.PlotWidget,
    format_fn: Callable[[float, float], str],
    is_date_axis: bool = False,
    snap_xs: Optional[np.ndarray] = None,
    series_data: Optional[Dict[str, Tuple[np.ndarray, np.ndarray]]] = None,
) -> ChartTooltip:
    """Atajo para crear y adjuntar un tooltip a un PlotWidget."""
    return ChartTooltip(pw, format_fn, is_date_axis, snap_xs, series_data)
