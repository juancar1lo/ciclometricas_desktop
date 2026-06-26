"""ACWR Chart Debug Module — Ratio de Carga Aguda:Crónica.

Archivo autocontenido extraído de Ciclométricas Desktop para depuración.
Incluye:
  1. Modelo de fitness (Banister): CTL / ATL / TSB
  2. Clasificación ACWR
  3. Lógica de renderizado del gráfico (pyqtgraph)
  4. Sistema de tooltip interactivo

Fuentes originales:
  - calc/fitness.py                  → modelo Banister
  - ui/views/dashboard_view.py L808-863 → gráfico ACWR
  - ui/charts/chart_utils.py         → helpers de gráfico y tooltip
  - ui/theme.py → constantes de color

Autor: Ciclométricas · https://ciclometricas.abacusai.app
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 1: Constantes de color (extraídas de ui/theme.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COLORS = {
    "bg":           "#0b1120",
    "bg_card":      "#111827",
    "bg_hover":     "#1e293b",
    "bg_secondary": "#1a2236",
    "fg":           "#f8fafc",
    "fg_muted":     "#6b7d99",
    "fg_dim":       "#475569",
    "primary":      "#FF6B35",
    "success":      "#22c55e",
    "warning":      "#f59e0b",
    "destructive":  "#ef4444",
    "info":         "#22d3ee",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 2: Modelo de fitness — CTL / ATL / TSB (calc/fitness.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class FitnessPoint:
    """Un punto diario de la serie de fitness."""
    date: str       # ISO yyyy-mm-dd
    tss: float      # TSS del día
    ctl: float      # Chronic Training Load (EMA 42 días)
    atl: float      # Acute Training Load  (EMA 7 días)
    tsb: float      # Training Stress Balance = CTL − ATL
    forecast: bool = False


def aggregate_daily_tss(
    activities: Sequence[dict],
) -> Dict[str, float]:
    """Agrega TSS por día.

    activities: lista de dicts con claves:
        - 'started_at': datetime | date
        - 'tss': float
    """
    result: Dict[str, float] = {}
    for a in (activities or []):
        started = a.get("started_at")
        if started is None:
            continue
        if isinstance(started, datetime):
            d = started.date()
        elif isinstance(started, date):
            d = started
        else:
            continue
        iso = d.isoformat()
        tss = a.get("tss", 0) or 0
        if not isinstance(tss, (int, float)) or not math.isfinite(tss):
            tss = 0
        result[iso] = result.get(iso, 0) + tss
    return result


def build_fitness_series(
    activities: Sequence[dict],
    from_date: date,
    to_date: date,
) -> List[FitnessPoint]:
    """Construye serie CTL/ATL/TSB con pre-warm de 90 días.

    Modelo exponencial de Banister:
      CTL_t = CTL_{t-1} + (TSS_t - CTL_{t-1}) × (1 - e^(-1/42))
      ATL_t = ATL_{t-1} + (TSS_t - ATL_{t-1}) × (1 - e^(-1/7))
      TSB_t = CTL_t - ATL_t
    """
    daily_tss = aggregate_daily_tss(activities)

    start = from_date - timedelta(days=90)
    end = to_date
    today = date.today()

    ctl_alpha = 1 - math.exp(-1 / 42)
    atl_alpha = 1 - math.exp(-1 / 7)

    points: List[FitnessPoint] = []
    ctl = 0.0
    atl = 0.0
    cur = start

    while cur <= end:
        iso = cur.isoformat()
        is_forecast = cur > today
        tss = 0.0 if is_forecast else daily_tss.get(iso, 0.0)
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        if cur >= from_date:
            points.append(FitnessPoint(
                date=iso,
                tss=tss,
                ctl=round(ctl, 2),
                atl=round(atl, 2),
                tsb=round(ctl - atl, 2),
                forecast=is_forecast,
            ))
        cur += timedelta(days=1)

    return points


def calc_ramp_rate(points: List[FitnessPoint], days: int = 7) -> Optional[float]:
    """Ramp rate semanal: ΔCTL en `days` días (solo puntos reales)."""
    if not points:
        return None
    last_idx = len(points) - 1
    while last_idx >= 0 and points[last_idx].forecast:
        last_idx -= 1
    if last_idx < days:
        return None
    return round(points[last_idx].ctl - points[last_idx - days].ctl, 2)


def last_real_point(points: List[FitnessPoint]) -> Optional[FitnessPoint]:
    """Último punto real (no proyectado)."""
    for p in reversed(points or []):
        if not p.forecast:
            return p
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 3: Clasificación ACWR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _acwr_state(acwr: float) -> Tuple[str, str]:
    """Clasifica ACWR y devuelve (etiqueta, color_hex).

    Bandas (Gabbett, 2016; Hulin et al., 2014):
      < 0.80  → Infracarga  (azul)
      0.80–1.30 → Óptimo    (verde)
      1.30–1.50 → Alto      (ámbar)
      > 1.50  → Peligro     (rojo)
    """
    if acwr < 0.8:
        return "Infracarga", "#60B5FF"
    if acwr <= 1.3:
        return "Óptimo", COLORS["success"]      # #22c55e
    if acwr <= 1.5:
        return "Alto", COLORS["warning"]         # #f59e0b
    return "Peligro", COLORS["destructive"]      # #ef4444


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 4: Helpers de gráfico (ui/charts/chart_utils.py)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# NOTA: Para ejecutar la parte gráfica necesitas:
#   pip install PySide6 pyqtgraph numpy

try:
    import pyqtgraph as pg
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont
    HAS_GUI = True
except ImportError:
    HAS_GUI = False


def _qcolor(hex_str: str, alpha: int = 255) -> "QColor":
    c = QColor(hex_str)
    c.setAlpha(alpha)
    return c


def make_plot(
    title: str = "",
    height: int = 280,
    bg: str = "#111827",
) -> "pg.PlotWidget":
    """Crea un PlotWidget con estilo oscuro."""
    pw = pg.PlotWidget()
    pw.setBackground(_qcolor(bg))
    pw.setMinimumHeight(height)
    pw.setMouseEnabled(x=False, y=False)
    pw.hideButtons()
    pw.getPlotItem().setContentsMargins(4, 4, 4, 4)
    pw.showGrid(x=True, y=True, alpha=0.15)
    for axis_name in ("bottom", "left", "right"):
        ax = pw.getAxis(axis_name)
        ax.setStyle(tickFont=QFont("Segoe UI", 10))
        ax.setTextPen(_qcolor("#cbd5e1"))
        ax.setPen(_qcolor("#1e293b"))
    return pw


def configure_axis(
    pw: "pg.PlotWidget",
    axis: str = "bottom",
    ticks: Optional[list] = None,
    label: str = "",
) -> None:
    """Configura un eje con ticks personalizados."""
    ax = pw.getAxis(axis)
    if ticks is not None:
        ax.setTicks([ticks])
    if label:
        ax.setLabel(label, color="#6b7d99")


def date_to_ts(d) -> float:
    """Convierte fecha ISO o date a timestamp."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return datetime(d.year, d.month, d.day).timestamp()


def make_date_ticks(dates: List[str], max_ticks: int = 12) -> list:
    """Genera ticks legibles para eje de fechas."""
    _MONTH_SHORT = {
        1: "ene", 2: "feb", 3: "mar", 4: "abr",
        5: "may", 6: "jun", 7: "jul", 8: "ago",
        9: "sept", 10: "oct", 11: "nov", 12: "dic",
    }
    if not dates:
        return []
    n = len(dates)
    step = max(1, n // max_ticks)
    ticks = []
    for i in range(0, n, step):
        d = date.fromisoformat(dates[i])
        label = f"{d.day:02d} {_MONTH_SHORT[d.month]}"
        ticks.append((date_to_ts(d), label))
    return ticks


def add_horizontal_band(
    pw: "pg.PlotWidget",
    y_min: float, y_max: float,
    color: str, alpha: int = 50,
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
    pw: "pg.PlotWidget",
    y: float,
    color: str = "#ffffff",
    style=None,
    width: int = 1,
) -> None:
    """Agrega una línea horizontal punteada."""
    if style is None and HAS_GUI:
        style = Qt.PenStyle.DashLine
    line = pg.InfiniteLine(
        pos=y, angle=0,
        pen=pg.mkPen(color=_qcolor(color), style=style, width=width),
    )
    pw.addItem(line)


# ── Tooltip HTML helpers ──────────────────────────────────────────

def tooltip_line(label: str, value: str, color: str = "#f1f5f9") -> str:
    """Genera una línea HTML coloreada para un tooltip."""
    return (
        f'<span style="color:{color};font-weight:600">{label}:</span> '
        f'<span style="color:#f1f5f9">{value}</span>'
    )


def tooltip_header(text: str) -> str:
    """Genera una cabecera HTML para un tooltip."""
    return f'<span style="color:#94a3b8;font-weight:700">{text}</span>'


def tooltip_html(lines: list) -> str:
    """Empaqueta líneas (ya en HTML) en un bloque de tooltip."""
    body = "<br>".join(lines)
    return (
        f'<div style="font-family:Segoe UI,sans-serif;font-size:10pt;'
        f'padding:2px 4px;">{body}</div>'
    )


# ── ChartTooltip (crosshair + etiqueta) ──────────────────────────

class ChartTooltip:
    """Crosshair vertical + etiqueta HTML que sigue al ratón."""

    def __init__(
        self,
        pw: "pg.PlotWidget",
        format_fn: Callable[[float, float], str],
        is_date_axis: bool = False,
        snap_xs: Optional[np.ndarray] = None,
    ):
        self.pw = pw
        self.format_fn = format_fn
        self.is_date_axis = is_date_axis
        self.snap_xs = snap_xs

        self.vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(color=_qcolor("#ffffff", 150), width=1,
                         style=Qt.PenStyle.DashLine),
        )
        pw.addItem(self.vline, ignoreBounds=True)
        self.vline.setVisible(False)

        self.label = pg.TextItem(
            "", color=_qcolor("#f1f5f9"), anchor=(0, 1),
            fill=_qcolor("#0f172a", 240),
            border=pg.mkPen("#334155", width=1),
        )
        self.label.setFont(QFont("Segoe UI", 10))
        self.label.setZValue(1000)
        pw.addItem(self.label, ignoreBounds=True)
        self.label.setVisible(False)

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

        if self.snap_xs is not None and len(self.snap_xs) > 0:
            idx = int(np.argmin(np.abs(self.snap_xs - x)))
            x = float(self.snap_xs[idx])

        self.vline.setPos(x)
        self.vline.setVisible(True)

        try:
            text = self.format_fn(x, y)
        except Exception:
            text = ""

        if text:
            if text.lstrip().startswith("<"):
                self.label.setHtml(text)
            else:
                self.label.setText(text)

            view_range = vb.viewRange()
            x_range = view_range[0]
            y_range = view_range[1]
            mid_x = (x_range[0] + x_range[1]) / 2

            if x > mid_x:
                self.label.setAnchor((1, 0))
                lbl_x = x - (x_range[1] - x_range[0]) * 0.01
            else:
                self.label.setAnchor((0, 0))
                lbl_x = x + (x_range[1] - x_range[0]) * 0.01

            lbl_y = y_range[1] - (y_range[1] - y_range[0]) * 0.02
            self.label.setPos(lbl_x, lbl_y)
            self.label.setVisible(True)
        else:
            self.label.setVisible(False)

    def clear(self):
        try:
            self.pw.removeItem(self.vline)
            self.pw.removeItem(self.label)
        except Exception:
            pass


def attach_tooltip(pw, format_fn, is_date_axis=False, snap_xs=None) -> ChartTooltip:
    """Atajo para crear y adjuntar un tooltip a un PlotWidget."""
    return ChartTooltip(pw, format_fn, is_date_axis, snap_xs)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 5: Renderizado del gráfico ACWR
#   (extraído de dashboard_view.py → _update_load_form → bloque ACWR)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def render_acwr_chart(
    pw: "pg.PlotWidget",
    pts: List[FitnessPoint],
    xs: np.ndarray,
    ticks: list,
    date_label_fn: Callable[[float], str],
    interp_fn: Callable[[np.ndarray, np.ndarray, float], Optional[float]],
) -> Optional[ChartTooltip]:
    """Renderiza el gráfico ACWR completo en un PlotWidget dado.

    Este es el bloque exacto de dashboard_view.py L808–L863, extraído
    como función reutilizable para depuración.

    Args:
        pw: PlotWidget donde dibujar.
        pts: lista de FitnessPoint (desde build_fitness_series).
        xs: array de timestamps correspondientes a cada punto en pts.
        ticks: ticks del eje X [(ts, label), ...].
        date_label_fn: función(ts) → "14 may 2025" para tooltip.
        interp_fn: función(xs, ys, x) → valor Y interpolado.

    Returns:
        ChartTooltip adjuntado, o None si no hay datos válidos.
    """
    pw.clear()
    configure_axis(pw, "bottom", ticks)

    # ── ACWR — solo fiable cuando CTL >= 10 ──
    CTL_MIN_ACWR = 10
    valid_xs: List[float] = []
    valid_ys: List[float] = []
    for i, p in enumerate(pts):
        if p.ctl >= CTL_MIN_ACWR:
            ratio = p.atl / p.ctl
            valid_xs.append(xs[i])
            valid_ys.append(ratio)

    # ── Bandas ACWR ──
    acwr_max = max(2.0, max(valid_ys) + 0.1) if valid_ys else 2.0
    add_horizontal_band(pw, 0,   0.8,          "#3b4a8a", 45)   # Infracarga
    add_horizontal_band(pw, 0.8, 1.3,          "#22c55e", 40)   # Óptimo
    add_horizontal_band(pw, 1.3, 1.5,          "#a0742e", 40)   # Alto
    add_horizontal_band(pw, 1.5, acwr_max + 1, "#ef4444", 35)   # Peligro

    # ── Curva ACWR ──
    if valid_xs:
        vx = np.array(valid_xs)
        vy = np.array(valid_ys)
        pw.plot(vx, vy, pen=pg.mkPen("#22d3ee", width=2))   # cyan
    add_horizontal_line(pw, 1.0, "#ffffff", Qt.PenStyle.DotLine, 1)
    pw.setYRange(0, acwr_max)

    # ── Etiquetas de banda ──
    if len(xs) >= 2:
        x_lbl = xs[0] + (xs[-1] - xs[0]) * 0.01
        for y, text, col in [
            (0.4,  "Infracarga", "#60B5FF"),
            (1.0,  "Óptimo",    "#22c55e"),
            (1.35, "Alto",      "#FF9149"),
            (1.6,  "Peligro",   "#ef4444"),
        ]:
            t = pg.TextItem(text, color=_qcolor(col), anchor=(0, 1))
            t.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            t.setPos(x_lbl, y)
            pw.addItem(t)

    # ── Tooltip ACWR — coloreado ──
    _vx = np.array(valid_xs) if valid_xs else np.array([])
    _vy = np.array(valid_ys) if valid_ys else np.array([])

    def _fmt_acwr(x, _y):
        dl = date_label_fn(x)
        if len(_vx) == 0:
            return tooltip_html([tooltip_header(dl)])
        v = interp_fn(_vx, _vy, x)
        if v is None:
            return tooltip_html([tooltip_header(dl)])
        st, st_col = _acwr_state(v)
        lines = [
            tooltip_header(dl),
            tooltip_line("ACWR", f"{v:.2f}", "#22d3ee"),
            tooltip_line("Estado", st, st_col),
        ]
        return tooltip_html(lines)

    tt = attach_tooltip(pw, _fmt_acwr,
                        snap_xs=_vx if len(_vx) else None)
    return tt


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 6: Utilidades de integración (usadas por dashboard_view)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def interp_at(xs: np.ndarray, ys: np.ndarray, x: float) -> Optional[float]:
    """Devuelve el valor Y del punto más cercano a X.

    Es la función estática _interp_at de DashboardView.
    """
    if len(xs) == 0:
        return None
    idx = int(np.argmin(np.abs(xs - x)))
    return float(ys[idx])


def date_label(ts: float) -> str:
    """Timestamp → '14 may 2025'.

    Es la función estática _date_label de DashboardView.
    """
    _MONTHS = {
        1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
        7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic",
    }
    try:
        d = datetime.fromtimestamp(ts).date()
        return f"{d.day} {_MONTHS[d.month]} {d.year}"
    except Exception:
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SECCIÓN 7: Ejemplo de uso / ejecución standalone
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import random
    import sys

    # 1) Generar datos ficticios
    today = date.today()
    activities = []
    for i in range(180):
        d = today - timedelta(days=179 - i)
        # Patrón: semana de 5 entrenos + 2 descanso
        if i % 7 >= 5:
            tss = 0
        else:
            tss = random.uniform(40, 130)
        activities.append({"started_at": d, "tss": tss})

    pts = build_fitness_series(activities, today - timedelta(days=120), today)
    print(f"Puntos de fitness: {len(pts)}")
    print(f"Último: CTL={pts[-1].ctl:.1f}  ATL={pts[-1].atl:.1f}  TSB={pts[-1].tsb:.1f}")

    # 2) Calcular ACWR
    xs = np.array([date_to_ts(p.date) for p in pts])
    CTL_MIN = 10
    valid = [(xs[i], p.atl / p.ctl) for i, p in enumerate(pts) if p.ctl >= CTL_MIN]
    if valid:
        last_acwr = valid[-1][1]
        st, col = _acwr_state(last_acwr)
        print(f"\nACWR actual: {last_acwr:.2f} → {st}")
    else:
        print("\nInsuficientes datos para ACWR.")

    # 3) Abrir gráfico (opcional: necesita PySide6 + display)
    if HAS_GUI and "--plot" in sys.argv:
        from PySide6.QtWidgets import QApplication, QMainWindow
        app = QApplication.instance() or QApplication(sys.argv)
        win = QMainWindow()
        win.setWindowTitle("ACWR Debug")
        win.resize(900, 400)
        pw = make_plot(height=350)
        win.setCentralWidget(pw)
        ticks = make_date_ticks([p.date for p in pts])
        render_acwr_chart(pw, pts, xs, ticks, date_label, interp_at)
        win.show()
        app.exec()
    elif "--plot" in sys.argv:
        print("\n⚠ PySide6/pyqtgraph no disponible. Ejecuta: pip install PySide6 pyqtgraph")
    else:
        print("\n💡 Pasa --plot para abrir el gráfico interactivo.")
