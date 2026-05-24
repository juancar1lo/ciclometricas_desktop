"""Vista Panel (Dashboard) — Visión general de carga, forma y zonas.

Replica la experiencia de la app web con pestañas:
  Resumen · Carga y Forma · Zonas · Rendimiento · Análisis avanzado · Entrenamientos
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QSize, QDate
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
    QPushButton, QSpinBox, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from db.engine import get_session
from db.models import Activity, PowerTestSet, ProfileSnapshot

from calc.fitness import (
    build_fitness_series, calc_ramp_rate, last_real_point, FitnessPoint,
)
from calc.zones import (
    POWER_ZONES, HR_ZONES, bucket_series, resolve_zone_ref, ZoneDef,
)
from calc.cp_model import (
    fit_cp_model, PowerTestPoint, CpModelResult,
    estimate_vo2max, estimate_mftp, calc_tte, TteResult,
    reliability_from_r2, calc_mftp_vo2max_percentage,
)
from calc.mmp import compute_mmp, PR_DURATIONS, MMP_DURATIONS, merge_mmp_max
# calc.pdc_fatigue no se usa directamente; DCP se calcula desde MMP global
from calc.activity_metrics import calc_ef, calc_vf, calc_pw_hr_decoupling

from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_XS, FONT_SIZE_LG,
    FONT_SIZE_XL, FONT_SIZE_TITLE, FONT_SIZE_MD, FONT_SIZE_HERO,
    ICON_MD, ICON_SM, ICON_LG, RADIUS, RADIUS_LG,
)
from ui.widgets.stat_card import StatCard
from ui.charts.chart_utils import (
    make_plot, configure_axis, CHART_COLORS, make_bar_chart,
    date_to_ts, make_date_ticks, add_horizontal_band, add_horizontal_line,
    _qcolor, attach_tooltip, ChartTooltip,
    tooltip_line, tooltip_header, tooltip_html,
)

# ── Constantes de eje X — idénticas a la versión web ─────────────

# DCP: 5s – hasta la duración máxima de los recorridos
_DCP_X_TICKS: list[int] = [
    5, 8, 10, 12, 15, 20, 30, 45, 60, 75, 80, 90, 105, 120,
    180, 240, 300, 360, 420, 480, 600, 720, 900, 1200, 1800, 2700,
    3600, 5400, 7200, 10800, 14400, 18000, 21600,
]
_DCP_X_LABELS: dict[int, str] = {
    5: "5s", 8: "8s", 10: "10s", 12: "12s", 15: "15s", 20: "20s",
    30: "30s", 45: "45s", 60: "1min", 75: "1m15s", 80: "1m20s",
    90: "1m30s", 105: "1m45s", 120: "2min",
    180: "3min", 240: "4min", 300: "5min", 360: "6min", 420: "7min",
    480: "8min", 600: "10min", 720: "12min", 900: "15min",
    1200: "20min", 1800: "30min", 2700: "45min",
    3600: "1h", 5400: "1h30m", 7200: "2h", 10800: "3h",
    14400: "4h", 18000: "5h", 21600: "6h",
}

# Interval targeting: 5s – 45min (mismo rango que la web)
_INTV_X_TICKS: list[int] = [
    5, 8, 10, 12, 15, 20, 30, 45, 60, 75, 80, 90, 105, 120,
    180, 240, 300, 360, 420, 480, 600, 720, 900, 1200, 1800, 2700,
]
_INTV_X_LABELS: dict[int, str] = {
    5: "5s", 8: "8s", 10: "10s", 12: "12s", 15: "15s", 20: "20s",
    30: "30s", 45: "45s", 60: "1min", 75: "1m15s", 80: "1m20s",
    90: "1m30s", 105: "1m45s", 120: "2min",
    180: "3min", 240: "4min", 300: "5min", 360: "6min", 420: "7min",
    480: "8min", 600: "10min", 720: "12min", 900: "15min",
    1200: "20min", 1800: "30min", 2700: "45min",
}

# Duraciones para tarjetas de intervalos sugeridos (como en la web)
_INTERVAL_CARD_DURATIONS: list[tuple[int, str]] = [
    (5, "5s"), (8, "8s"), (10, "10s"), (12, "12s"), (15, "15s"),
    (20, "20s"), (30, "30s"), (45, "45s"),
    (60, "1 min"), (75, "1m15s"), (80, "1m20s"), (90, "1m30s"),
    (105, "1m45s"), (120, "2 min"),
    (180, "3 min"), (240, "4 min"), (300, "5 min"), (360, "6 min"),
    (420, "7 min"), (480, "8 min"),
    (600, "10 min"), (720, "12 min"), (900, "15 min"),
    (1200, "20 min"), (1800, "30 min"), (2700, "45 min"),
]


# ── Helpers ──────────────────────────────────────────────────────

def _fmt_duration(seconds: int | float | None) -> str:
    """Formato natural: 1h 32m, 5m 06s, 45s."""
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _fmt_hms(seconds: int | float | None) -> str:
    if not seconds:
        return "00:00:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _safe(v: Any, digits: int = 0) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    if digits == 0:
        return str(round(v))
    return f"{v:.{digits}f}"


def _period_days(label: str) -> int:
    _MAP = {
        "Últimos 7 días": 7, "Últimos 14 días": 14,
        "Últimos 30 días": 30, "Últimos 60 días": 60,
        "Últimos 90 días": 90, "Últimos 180 días": 180,
        "Últimos 365 días": 365, "Todo el histórico": 9999,
    }
    return _MAP.get(label, 90)


def _forecast_days(label: str) -> int:
    """Devuelve cuántos días de predicción añadir, o 0."""
    if "+7 días predicción" in label:
        return 7
    if "+14 días predicción" in label:
        return 14
    return 0


PERIOD_OPTIONS = [
    "Últimos 7 días", "Últimos 14 días", "Últimos 30 días",
    "Últimos 60 días", "Últimos 90 días", "Últimos 180 días",
    "Últimos 365 días", "Todo el histórico",
    "── Predicción ──",
    "90 d +7 días predicción", "90 d +14 días predicción",
    "── Rango ──",
    "Rango personalizado",
]


_MONTH_SHORT = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic",
}


def _tsb_state(tsb: float) -> Tuple[str, str, str]:
    """(label, color, hint)."""
    if tsb >= 25:
        return "Transición", COLORS["fg_dim"], "Puede que estés perdiendo forma."
    if tsb >= 5:
        return "Fresco", COLORS["success"], "Buen estado de forma para competir."
    if tsb >= -10:
        return "Productivo", COLORS["accent"], "Entrenamiento productivo."
    if tsb >= -30:
        return "Óptimo", "#FF9149", "Carga óptima para mejorar."
    return "Alto riesgo", COLORS["destructive"], "Cuidado con el sobreentrenamiento."


def _ramp_hint(rr: Optional[float]) -> Tuple[str, str]:
    if rr is None:
        return "Sin datos", COLORS["fg_dim"]
    if rr > 1:
        return "Incrementas carga.", COLORS["success"]
    if rr > -1:
        return "Carga estable.", COLORS["accent"]
    return "Pierdes forma; valora cargar más.", COLORS["warning"]


def _acwr_state(acwr: float) -> Tuple[str, str]:
    if acwr < 0.8:
        return "Infracarga", "#60B5FF"
    if acwr <= 1.3:
        return "Óptimo", COLORS["success"]
    if acwr <= 1.5:
        return "Alto", COLORS["warning"]
    return "Peligro", COLORS["destructive"]


# ── Scrollable tab base ─────────────────────────────────────────

def _scrollable_widget() -> Tuple[QScrollArea, QWidget, QVBoxLayout]:
    """Crea un QScrollArea con un widget interior + layout vertical."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    inner = QWidget()
    inner.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    scroll.setWidget(inner)
    return scroll, inner, lay


def _section_title(icon: str, text: str, desc: str = "") -> QWidget:
    """Bloque de título de sección con icono + descripción."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 8, 0, 4)
    lay.setSpacing(2)
    row = QHBoxLayout()
    row.setSpacing(8)
    ico = QLabel(icon)
    ico.setStyleSheet(f"font-size: {FONT_SIZE_XL}; background: transparent; border: none;")
    row.addWidget(ico)
    title = QLabel(text)
    title.setStyleSheet(
        f"font-size: {FONT_SIZE_LG}; font-weight: 700; "
        f"color: {COLORS['fg']}; background: transparent; border: none;"
    )
    row.addWidget(title)
    row.addStretch()
    lay.addLayout(row)
    if desc:
        d = QLabel(desc)
        d.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
            f"background: transparent; border: none;"
        )
        d.setWordWrap(True)
        lay.addWidget(d)
    return w


def _card_frame() -> QFrame:
    f = QFrame()
    f.setProperty("class", "card")
    return f


# ═══════════════════════════════════════════════════════════════════
# DashboardView — Vista principal del Panel
# ═══════════════════════════════════════════════════════════════════

class DashboardView(QWidget):
    """Panel principal con pestañas de métricas."""

    open_activity = Signal(int)  # emite activity.id
    request_import = Signal()    # navegar a importación

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self._activities: List[Activity] = []       # all activities (incl. warmup window)
        self._activities_display: List[Activity] = []  # only within display range
        self._fitness_points: List[FitnessPoint] = []
        self._cp_model: Optional[CpModelResult] = None
        self._tests: List[PowerTestSet] = []
        self._snapshots: List[ProfileSnapshot] = []
        self._custom_range: Optional[Tuple[date, date]] = None
        # Tooltips dict — se crean una vez al construir cada chart
        self._tooltips: Dict[str, ChartTooltip] = {}

        self._build_ui()

    # ── UI build ─────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 10)
        root.setSpacing(12)

        # Header: título + período
        header = QHBoxLayout()
        title = QLabel("Panel")
        title.setProperty("class", "title")
        header.addWidget(title)
        header.addStretch()

        self._period_combo = QComboBox()
        self._period_combo.addItems(PERIOD_OPTIONS)
        # Deshabilitar separadores
        model = self._period_combo.model()
        for i, opt in enumerate(PERIOD_OPTIONS):
            if opt.startswith("──"):
                item = model.item(i)
                if item:
                    item.setEnabled(False)
        self._period_combo.setCurrentIndex(4)  # 90 días
        self._period_combo.setMinimumWidth(200)
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        header.addWidget(QLabel("📅"))
        header.addWidget(self._period_combo)
        root.addLayout(header)

        desc = QLabel("Visión general de tu carga, forma y zonas de entrenamiento.")
        desc.setProperty("class", "muted")
        root.addWidget(desc)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        root.addWidget(self._tabs, 1)

        # Build each tab
        self._build_resumen_tab()
        self._build_carga_forma_tab()
        self._build_zonas_tab()
        self._build_rendimiento_tab()
        self._build_analisis_tab()
        self._build_entrenamientos_tab()

    # ── Data loading ─────────────────────────────────────────────

    def refresh(self) -> None:
        """Carga datos y actualiza todas las pestañas."""
        self._load_data()
        self._update_resumen()
        self._update_carga_forma()
        self._update_zonas()
        self._update_rendimiento()
        self._update_analisis()
        self._update_entrenamientos()

    def _load_data(self) -> None:
        label = self._period_combo.currentText()
        today = date.today()

        # Determinar rango de fechas
        if self._custom_range:
            from_date, to_date = self._custom_range
        else:
            days = _period_days(label)
            if days >= 9999:
                from_date = today - timedelta(days=3650)
            else:
                from_date = today - timedelta(days=days)
            forecast = _forecast_days(label)
            to_date = today + timedelta(days=forecast) if forecast else today

        # Pre-warm window: 90 days (minimum) before from_date for CTL/ATL EMA convergence
        # For longer periods, extend warmup so the EMA has more history to converge
        display_span = (to_date - from_date).days
        warmup_days = max(90, display_span)
        warmup_date = from_date - timedelta(days=warmup_days)

        with get_session() as session:
            # Activities — include warmup window for fitness model pre-warm
            query = session.query(Activity).filter(
                Activity.started_at >= datetime(warmup_date.year, warmup_date.month, warmup_date.day)
            ).order_by(Activity.started_at.desc())
            self._activities = query.all()
            session.expunge_all()

            # Power tests
            self._tests = session.query(PowerTestSet).order_by(
                PowerTestSet.tested_at.desc()
            ).all()
            session.expunge_all()

            # Profile snapshots
            self._snapshots = session.query(ProfileSnapshot).order_by(
                ProfileSnapshot.effective_at.asc()
            ).all()
            session.expunge_all()

        # Split: display activities (within user range) vs all (for fitness pre-warm)
        from_dt = datetime(from_date.year, from_date.month, from_date.day)
        self._activities_display = [
            a for a in self._activities
            if a.started_at >= from_dt
        ]

        # Fitness series — uses ALL activities (incl. warmup) for accurate EMA
        acts_dicts = [
            {"started_at": a.started_at, "tss": a.tss}
            for a in self._activities if a.tss
        ]
        self._fitness_points = build_fitness_series(acts_dicts, from_date, to_date)

        # CP model from latest test
        self._cp_model = None
        if self._tests:
            t = self._tests[0]  # más reciente
            pts = [
                PowerTestPoint(t.short_duration, t.short_power),
                PowerTestPoint(t.mid_duration, t.mid_power),
                PowerTestPoint(t.long_duration, t.long_power),
            ]
            self._cp_model = fit_cp_model(pts)

    def _on_period_changed(self, _idx: int) -> None:
        text = self._period_combo.currentText()
        # Ignorar separadores
        if text.startswith("──"):
            return
        # Rango personalizado → diálogo con dos calendarios
        if text == "Rango personalizado":
            self._show_custom_range_dialog()
            return
        self._custom_range = None  # reset
        self.refresh()

    def _show_custom_range_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Seleccionar rango de fechas")
        dlg.setMinimumWidth(520)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(12)

        lbl = QLabel("Selecciona el rango de fechas para el análisis:")
        lbl.setStyleSheet(f"color: {COLORS['fg']}; font-weight: 600;")
        lay.addWidget(lbl)

        cals_row = QHBoxLayout()
        from_lbl = QLabel("Desde:")
        from_lbl.setStyleSheet(f"color: {COLORS['fg_muted']};")
        to_lbl = QLabel("Hasta:")
        to_lbl.setStyleSheet(f"color: {COLORS['fg_muted']};")

        # Estilo para que el día seleccionado destaque visualmente
        _cal_ss = f"""
            QCalendarWidget {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['fg']};
            }}
            QCalendarWidget QAbstractItemView {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['fg']};
                selection-background-color: {COLORS['primary']};
                selection-color: #ffffff;
                font-weight: bold;
                outline: none;
            }}
            QCalendarWidget QAbstractItemView::item:selected {{
                background-color: {COLORS['primary']};
                color: #ffffff;
                border: 2px solid {COLORS['primary_hover']};
                border-radius: 4px;
            }}
            QCalendarWidget QAbstractItemView::item:hover {{
                background-color: {COLORS['primary_dim']};
                border: 1px solid {COLORS['primary']};
                border-radius: 3px;
            }}
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background-color: {COLORS['bg']};
            }}
            QCalendarWidget QToolButton {{
                color: {COLORS['fg']};
                background-color: transparent;
                border: none;
                padding: 4px 8px;
                font-weight: 600;
            }}
            QCalendarWidget QToolButton:hover {{
                background-color: {COLORS['primary_dim']};
                border-radius: 4px;
            }}
            QCalendarWidget QSpinBox {{
                color: {COLORS['fg']};
                background-color: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
            }}
        """

        from_cal = QCalendarWidget()
        from_cal.setStyleSheet(_cal_ss)
        from_cal.setSelectedDate(QDate.currentDate().addDays(-90))
        to_cal = QCalendarWidget()
        to_cal.setStyleSheet(_cal_ss)
        to_cal.setSelectedDate(QDate.currentDate())

        from_col = QVBoxLayout()
        from_col.addWidget(from_lbl)
        from_col.addWidget(from_cal)
        to_col = QVBoxLayout()
        to_col.addWidget(to_lbl)
        to_col.addWidget(to_cal)
        cals_row.addLayout(from_col)
        cals_row.addLayout(to_col)
        lay.addLayout(cals_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            qd_from = from_cal.selectedDate()
            qd_to = to_cal.selectedDate()
            self._custom_range = (
                date(qd_from.year(), qd_from.month(), qd_from.day()),
                date(qd_to.year(), qd_to.month(), qd_to.day()),
            )
            self.refresh()
        else:
            # Revert combo to previous safe option
            self._period_combo.blockSignals(True)
            self._period_combo.setCurrentIndex(4)
            self._period_combo.blockSignals(False)

    # ── Tooltip helpers ──────────────────────────────────────────

    @staticmethod
    def _interp_at(xs: np.ndarray, ys: np.ndarray, x: float) -> Optional[float]:
        """Devuelve el valor Y del punto más cercano a X en una serie."""
        if len(xs) == 0:
            return None
        idx = int(np.argmin(np.abs(xs - x)))
        return float(ys[idx])

    @staticmethod
    def _date_label(ts: float) -> str:
        """Timestamp → '14 may 2025'."""
        try:
            d = datetime.fromtimestamp(ts).date()
            ms = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
                  7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic"}
            return f"{d.day} {ms[d.month]} {d.year}"
        except Exception:
            return ""

    def _setup_tooltip(self, key: str, pw: pg.PlotWidget,
                       format_fn, snap_xs=None) -> ChartTooltip:
        """Crea o reemplaza tooltip para un PlotWidget."""
        old = self._tooltips.pop(key, None)
        if old:
            old.clear()
        tt = attach_tooltip(pw, format_fn, snap_xs=snap_xs)
        self._tooltips[key] = tt
        return tt

    # ══════════════════════════════════════════════════════════════
    # TAB 1: RESUMEN
    # ══════════════════════════════════════════════════════════════

    def _build_resumen_tab(self) -> None:
        scroll, inner, lay = _scrollable_widget()
        self._tabs.addTab(scroll, "◉ Resumen")

        # Botón subir entrenamiento
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_import = QPushButton("📤  Subir entrenamiento")
        btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_import.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: #fff; "
            f"font-weight: 700; padding: 8px 20px; border-radius: 8px; "
            f"font-size: {FONT_SIZE_SM}; border: none; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_hover']}; }}"
        )
        btn_import.clicked.connect(self.request_import.emit)
        btn_row.addWidget(btn_import)
        lay.addLayout(btn_row)

        # Row 1: KPIs fitness — se reconstruyen en _update_resumen con datos reales
        self._kpi_container1 = QVBoxLayout()
        self._kpi_grid1 = QHBoxLayout()
        self._kpi_grid1.setSpacing(10)
        self._kpi_container1.addLayout(self._kpi_grid1)
        lay.addLayout(self._kpi_container1)

        # Row 2: Volume KPIs — se reconstruyen en _update_resumen
        self._kpi_container2 = QVBoxLayout()
        self._kpi_grid2 = QHBoxLayout()
        self._kpi_grid2.setSpacing(10)
        self._kpi_container2.addLayout(self._kpi_grid2)
        lay.addLayout(self._kpi_container2)

        lay.addStretch()

    @staticmethod
    def _clear_layout(layout):
        """Elimina todos los widgets de un layout."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _update_resumen(self) -> None:
        lp = last_real_point(self._fitness_points)
        rr = calc_ramp_rate(self._fitness_points, 7)

        # Limpiar tarjetas anteriores
        self._clear_layout(self._kpi_grid1)
        self._clear_layout(self._kpi_grid2)

        # ── Row 1: KPIs de fitness ──

        # TSB
        if lp:
            tsb_label, tsb_color, tsb_hint = _tsb_state(lp.tsb)
            tsb_val = str(round(lp.tsb))
            tsb_trend_val = f"{lp.tsb:+.0f}"
        else:
            tsb_val = "—"
            tsb_hint = ""
            tsb_label = ""
            tsb_color = ""
            tsb_trend_val = ""

        sc_tsb = StatCard(
            "🎯", "FORMA (TSB)", tsb_val, "TSB",
            hint=tsb_hint,
            trend_value=tsb_trend_val if lp else "",
            trend_label=tsb_label if lp else "",
            trend_color=tsb_color if lp else "",
        )
        self._kpi_grid1.addWidget(sc_tsb)

        # CTL
        ctl_val = str(round(lp.ctl)) if lp else "—"
        sc_ctl = StatCard(
            "📈", "CTL (FORMA CRÓNICA)", ctl_val, "CTL",
            hint="Media exponencial de TSS · 42 d",
            accent="#FF9149",
        )
        self._kpi_grid1.addWidget(sc_ctl)

        # ATL
        atl_val = str(round(lp.atl)) if lp else "—"
        sc_atl = StatCard(
            "🔥", "ATL (FATIGA)", atl_val, "ATL",
            hint="Media exponencial de TSS · 7 d",
            accent=COLORS["destructive"],
        )
        self._kpi_grid1.addWidget(sc_atl)

        # Ramp Rate
        if rr is not None:
            rr_val = f"{rr:+.1f}" if rr >= 0 else f"{rr:.1f}"
            rr_hint_text, rr_hint_color = _ramp_hint(rr)
            rr_label = "Creciente" if rr > 1 else ("Estable" if rr > -1 else "Decreciente")
            rr_badge_color = COLORS["success"] if rr > 1 else (COLORS["accent"] if rr > -1 else "#a78bfa")
        else:
            rr_val = "—"
            rr_hint_text = "Sin datos"
            rr_label = ""
            rr_badge_color = ""

        sc_ramp = StatCard(
            "📈", "RAMP RATE (7 D)", rr_val, "CTL/sem",
            hint=rr_hint_text,
            trend_value=f"{rr:.1f}" if rr is not None else "",
            trend_label=rr_label,
            trend_color=rr_badge_color,
        )
        self._kpi_grid1.addWidget(sc_ramp)

        # W/kg
        ftp = self.profile.config.get("ftp", 0)
        weight = self.profile.config.get("weight_kg", 0)
        if ftp and weight and weight > 0:
            wpkg_val = f"{ftp / weight:.2f}"
            wpkg_hint = f"{ftp} W · {weight} kg"
        else:
            wpkg_val = "—"
            wpkg_hint = "Configura tu perfil"

        sc_wpkg = StatCard(
            "⚡", "VATIOS POR KILO", wpkg_val, "W/kg",
            hint=wpkg_hint,
            accent="#22d3ee",
        )
        self._kpi_grid1.addWidget(sc_wpkg)

        # ── Row 2: Volume KPIs ──
        count = len(self._activities_display)
        total_sec = sum(a.duration_sec or 0 for a in self._activities_display)
        total_dist = sum(a.distance_km or 0 for a in self._activities_display)
        total_tss = sum(a.tss or 0 for a in self._activities_display)
        total_kj = sum(a.work_kj or 0 for a in self._activities_display)

        h = total_sec // 3600
        m = (total_sec % 3600) // 60

        sc_count = StatCard(
            "🚴", "ENTRENAMIENTOS", str(count), "",
            hint="En el periodo seleccionado",
            accent="#a78bfa",
        )
        self._kpi_grid2.addWidget(sc_count)

        sc_time = StatCard(
            "⏱️", "TIEMPO TOTAL", f"{h}h {m:02d}m", "",
            hint=f"{total_sec / 3600:.1f} h",
            accent="#FF9149",
        )
        self._kpi_grid2.addWidget(sc_time)

        avg_dist = total_dist / max(1, count)
        sc_dist = StatCard(
            "🛣️", "DISTANCIA", f"{total_dist:.1f}", "km",
            hint=f"{avg_dist:.1f} km/sesión",
            accent="#22d3ee",
        )
        self._kpi_grid2.addWidget(sc_dist)

        sc_tss = StatCard(
            "🔥", "TSS ACUMULADO", str(round(total_tss)), "",
            hint=f"{round(total_kj)} kJ trabajo",
            accent="#e879a0",
        )
        self._kpi_grid2.addWidget(sc_tss)

    # ══════════════════════════════════════════════════════════════
    # TAB 2: CARGA Y FORMA
    # ══════════════════════════════════════════════════════════════

    def _build_carga_forma_tab(self) -> None:
        scroll, inner, lay = _scrollable_widget()
        self._tabs.addTab(scroll, "🔥 Carga y Forma")

        # CTL/ATL/TSB chart
        lay.addWidget(_section_title(
            "📈", "Carga de entrenamiento (CTL · ATL · TSB)",
            "CTL = forma a largo plazo (42 d) · ATL = fatiga (7 d) · TSB = forma del día (CTL – ATL)."
        ))
        self._pw_fitness = make_plot(height=300)
        lay.addWidget(self._pw_fitness)

        # TSB Form bands chart
        lay.addWidget(_section_title(
            "🔄", "Forma (TSB)",
            "Estado del día según el balance carga–fatiga (CTL – ATL). Cada banda indica un estado de forma."
        ))
        self._pw_form = make_plot(height=260)
        lay.addWidget(self._pw_form)

        # ACWR chart
        lay.addWidget(_section_title(
            "🛡️", "Ratio de carga aguda:crónica (ACWR)",
            "Relación ATL/CTL — mide cuánta carga reciente acumulas respecto a tu base crónica."
        ))
        self._pw_acwr = make_plot(height=240)
        lay.addWidget(self._pw_acwr)

        # TSS semanal
        lay.addWidget(_section_title(
            "📊", "TSS semanal",
            "Suma de TSS por semana ISO. El ramp rate es el ΔCTL semanal."
        ))
        self._pw_tss_weekly = make_plot(height=220)
        lay.addWidget(self._pw_tss_weekly)

        lay.addStretch()

    def _update_carga_forma(self) -> None:
        pts = self._fitness_points
        if not pts:
            return

        dates = [p.date for p in pts]
        xs = np.array([date_to_ts(d) for d in dates])
        ticks = make_date_ticks(dates, 14)

        # ─── CTL/ATL/TSB + TSS bars ───
        pw = self._pw_fitness
        pw.clear()
        configure_axis(pw, "bottom", ticks)

        ctl_y = np.array([p.ctl for p in pts])
        atl_y = np.array([p.atl for p in pts])
        tsb_y = np.array([p.tsb for p in pts])
        tss_y = np.array([p.tss for p in pts])

        # TSS bars (eje derecho)
        pw.getPlotItem().showAxis("right")
        pw.getAxis("right").setTextPen(_qcolor(CHART_COLORS["fg_muted"]))

        # Barras TSS
        if len(xs) > 1:
            bar_width = (xs[1] - xs[0]) * 0.7
        else:
            bar_width = 3600 * 18
        make_bar_chart(pw, xs, tss_y, width=bar_width, color=CHART_COLORS["tss"], alpha=140)

        # Líneas
        pw.plot(xs, ctl_y, pen=pg.mkPen(CHART_COLORS["ctl"], width=2), name="CTL")
        pw.plot(xs, atl_y, pen=pg.mkPen(CHART_COLORS["atl"], width=2), name="ATL")
        pw.plot(xs, tsb_y, pen=pg.mkPen(CHART_COLORS["tsb"], width=2), name="TSB")

        # Leyenda
        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(_qcolor(COLORS["fg_muted"]))

        # Tooltip CTL/ATL/TSB con colores de leyenda
        _xs, _ctl, _atl, _tsb, _tss = xs, ctl_y, atl_y, tsb_y, tss_y
        def _fmt_fitness(x, _y):
            c = self._interp_at(_xs, _ctl, x)
            a = self._interp_at(_xs, _atl, x)
            t = self._interp_at(_xs, _tsb, x)
            ts = self._interp_at(_xs, _tss, x)
            dl = self._date_label(x)
            lines = [tooltip_header(dl)]
            if c is not None: lines.append(tooltip_line("CTL", f"{c:.1f}", CHART_COLORS["ctl"]))
            if a is not None: lines.append(tooltip_line("ATL", f"{a:.1f}", CHART_COLORS["atl"]))
            if t is not None: lines.append(tooltip_line("TSB", f"{t:.1f}", CHART_COLORS["tsb"]))
            if ts is not None: lines.append(tooltip_line("TSS", f"{ts:.0f}", CHART_COLORS["tss"]))
            return tooltip_html(lines)
        self._setup_tooltip("fitness", pw, _fmt_fitness, snap_xs=xs)

        # ─── Forma (TSB) con bandas ───
        pw2 = self._pw_form
        pw2.clear()
        configure_axis(pw2, "bottom", ticks)

        # Bandas TSB
        y_min = min(tsb_y) - 5
        y_max = max(tsb_y) + 5
        add_horizontal_band(pw2, -100, -30, "#ef4444", 40)   # Alto riesgo
        add_horizontal_band(pw2, -30, -10, "#22c55e", 40)    # Óptimo
        add_horizontal_band(pw2, -10, 5, "#60B5FF", 35)      # Productivo (gris-azul)
        add_horizontal_band(pw2, 5, 20, "#3b82f6", 35)       # Fresco
        add_horizontal_band(pw2, 20, 100, "#a78bfa", 30)     # Transición

        pw2.plot(xs, tsb_y, pen=pg.mkPen("#fbbf24", width=2.5))  # amarillo
        pw2.setYRange(min(y_min, -42), max(y_max, 35))

        # Labels de bandas (vía TextItem)
        bands_labels = [
            (-30, "Alto riesgo", "#ef4444"),
            (-10, "Óptimo", "#22c55e"),
            (5, "Fresco", "#60B5FF"),
            (20, "Transición", "#a78bfa"),
        ]
        x_label = xs[0] + (xs[-1] - xs[0]) * 0.01  # ligeramente a la derecha
        for y_pos, text, color in bands_labels:
            txt = pg.TextItem(text, color=_qcolor(color), anchor=(0, 1))
            txt.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            txt.setPos(x_label, y_pos)
            pw2.addItem(txt)

        # Tooltip TSB Form — coloreado
        _tsb2 = tsb_y
        def _fmt_form(x, _y):
            v = self._interp_at(xs, _tsb2, x)
            dl = self._date_label(x)
            if v is None: return tooltip_html([tooltip_header(dl)])
            st, st_color, _ = _tsb_state(v)
            lines = [
                tooltip_header(dl),
                tooltip_line("TSB", f"{v:.1f}", "#fbbf24"),
                tooltip_line("Estado", st, st_color),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("form", pw2, _fmt_form, snap_xs=xs)

        # ─── ACWR ───
        pw3 = self._pw_acwr
        pw3.clear()
        configure_axis(pw3, "bottom", ticks)

        # ACWR — solo fiable cuando CTL >= 10 (evitar picos ruidosos)
        CTL_MIN_ACWR = 10
        valid_xs = []
        valid_ys = []
        for i, p in enumerate(pts):
            if p.ctl >= CTL_MIN_ACWR:
                ratio = p.atl / p.ctl
                valid_xs.append(xs[i])
                valid_ys.append(ratio)

        # Bandas ACWR
        acwr_max = max(2.0, max(valid_ys) + 0.1) if valid_ys else 2.0
        add_horizontal_band(pw3, 0, 0.8, "#3b4a8a", 45)     # Infracarga
        add_horizontal_band(pw3, 0.8, 1.3, "#22c55e", 40)    # Óptimo
        add_horizontal_band(pw3, 1.3, 1.5, "#a0742e", 40)    # Alto
        add_horizontal_band(pw3, 1.5, acwr_max + 1, "#ef4444", 35)  # Peligro

        if valid_xs:
            vx = np.array(valid_xs)
            vy = np.array(valid_ys)
            pw3.plot(vx, vy, pen=pg.mkPen("#22d3ee", width=2))
        add_horizontal_line(pw3, 1.0, "#ffffff", Qt.PenStyle.DotLine, 1)
        pw3.setYRange(0, acwr_max)

        # Band labels
        x_lbl = xs[0] + (xs[-1] - xs[0]) * 0.01
        for y, text, col in [(0.4, "Infracarga", "#60B5FF"), (1.0, "Óptimo", "#22c55e"),
                              (1.35, "Alto", "#FF9149"), (1.6, "Peligro", "#ef4444")]:
            t = pg.TextItem(text, color=_qcolor(col), anchor=(0, 1))
            t.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            t.setPos(x_lbl, y)
            pw3.addItem(t)

        # Tooltip ACWR — coloreado (solo puntos válidos)
        _vx = np.array(valid_xs) if valid_xs else np.array([])
        _vy = np.array(valid_ys) if valid_ys else np.array([])
        def _fmt_acwr(x, _y):
            dl = self._date_label(x)
            if len(_vx) == 0:
                return tooltip_html([tooltip_header(dl)])
            v = self._interp_at(_vx, _vy, x)
            if v is None:
                return tooltip_html([tooltip_header(dl)])
            st, st_col = _acwr_state(v)
            lines = [
                tooltip_header(dl),
                tooltip_line("ACWR", f"{v:.2f}", "#22d3ee"),
                tooltip_line("Estado", st, st_col),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("acwr", pw3, _fmt_acwr, snap_xs=_vx if len(_vx) else None)

        # ─── TSS Semanal ───
        pw4 = self._pw_tss_weekly
        pw4.clear()

        # Agrupar TSS y último CTL por semana ISO
        weekly_tss: Dict[str, float] = defaultdict(float)
        weekly_ctl: Dict[str, float] = {}
        for p in pts:
            if p.forecast:
                continue
            d = date.fromisoformat(p.date)
            iso_year, iso_week, _ = d.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
            weekly_tss[key] += p.tss
            weekly_ctl[key] = p.ctl  # se sobrescribe → queda el último (más reciente)

        if weekly_tss:
            sorted_weeks = sorted(weekly_tss.keys())
            week_x = np.arange(len(sorted_weeks), dtype=np.float64)
            week_h = np.array([weekly_tss[w] for w in sorted_weeks])
            make_bar_chart(pw4, week_x, week_h, width=0.7, color="#FF9149", alpha=200)

            # Calcular ramp rate semanal (ΔCTL entre semanas consecutivas)
            week_ramp: list = []
            for i, wk in enumerate(sorted_weeks):
                ctl_end = weekly_ctl.get(wk)
                ctl_prev = weekly_ctl.get(sorted_weeks[i - 1]) if i > 0 else None
                if ctl_end is not None and ctl_prev is not None:
                    week_ramp.append(round(ctl_end - ctl_prev, 1))
                else:
                    week_ramp.append(None)

            # Ticks: fecha del lunes de cada semana
            week_ticks = []
            for i, wk in enumerate(sorted_weeks):
                parts = wk.split("-W")
                y, w = int(parts[0]), int(parts[1])
                d = date.fromisocalendar(y, w, 1)
                label = f"{d.day:02d} {_MONTH_SHORT[d.month]}"
                week_ticks.append((float(i), label))
            configure_axis(pw4, "bottom", week_ticks)

            # Tooltip TSS semanal con Ramp Rate
            _wk_x, _wk_h, _wk_names, _wk_ramp = week_x, week_h, sorted_weeks, week_ramp
            def _fmt_tss_wk(x, _y):
                if len(_wk_x) == 0: return ""
                idx = int(np.argmin(np.abs(_wk_x - x)))
                lines = [
                    tooltip_header(f"Semana {_wk_names[idx]}"),
                    tooltip_line("TSS", f"{_wk_h[idx]:.0f}", CHART_COLORS["tss"]),
                ]
                ramp_val = _wk_ramp[idx]
                if ramp_val is not None:
                    ramp_sign = "+" if ramp_val > 0 else ""
                    ramp_color = "#4ade80" if ramp_val > 0 else ("#f87171" if ramp_val < 0 else "#a1a1aa")
                    lines.append(tooltip_line("Ramp", f"{ramp_sign}{ramp_val} pts/sem", ramp_color))
                return tooltip_html(lines)
            self._setup_tooltip("tss_weekly", pw4, _fmt_tss_wk, snap_xs=week_x)

    # ══════════════════════════════════════════════════════════════
    # TAB 3: ZONAS
    # ══════════════════════════════════════════════════════════════

    def _build_zonas_tab(self) -> None:
        scroll, inner, lay = _scrollable_widget()
        self._tabs.addTab(scroll, "📊 Zonas")

        # Tiempo en zonas de potencia
        lay.addWidget(_section_title(
            "🔄", "Tiempo en zonas de potencia",
            "Coggan · % de FTP"
        ))
        self._pw_zones_power = make_plot(height=280)
        lay.addWidget(self._pw_zones_power)

        # Tiempo en zonas HR
        lay.addWidget(_section_title(
            "💜", "Tiempo en zonas cardíacas",
            "Friel · % de FCL"
        ))
        self._pw_zones_hr = make_plot(height=280)
        lay.addWidget(self._pw_zones_hr)

        # % en zonas (power + hr)
        lay.addWidget(_section_title(
            "🔄", "% en zonas de potencia",
            "Distribución relativa al periodo."
        ))
        self._pw_zones_pct_power = make_plot(height=250)
        lay.addWidget(self._pw_zones_pct_power)

        lay.addWidget(_section_title(
            "💜", "% en zonas cardíacas",
            "Distribución relativa al periodo."
        ))
        self._pw_zones_pct_hr = make_plot(height=250)
        lay.addWidget(self._pw_zones_pct_hr)

        # Rangos visuales
        lay.addWidget(_section_title(
            "🔄", "Rangos visuales de zonas Coggan",
            "Cada barra muestra desde el mínimo hasta el máximo de la zona en vatios reales."
        ))
        self._pw_zone_ranges = make_plot(height=260)
        lay.addWidget(self._pw_zone_ranges)

        # Zone tables
        lay.addWidget(_section_title("🔄", "Zonas de potencia (Coggan)"))
        self._table_zones_power = self._make_zone_table()
        lay.addWidget(self._table_zones_power)

        lay.addWidget(_section_title("💜", "Zonas de Friel"))
        self._table_zones_hr = self._make_zone_table()
        lay.addWidget(self._table_zones_hr)

        lay.addStretch()

    def _make_zone_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["ZONA", "% REF", "RANGO"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setMinimumHeight(200)
        table.setMaximumHeight(400)
        return table

    def _update_zonas(self) -> None:
        ftp = self.profile.config.get("ftp", 0)
        hr_max = self.profile.config.get("hr_max", 0)
        zone_src = self.profile.config.get("zone_source", "ftp")

        # Resolve reference for power zones
        cp_val = self._cp_model.cp if self._cp_model else None
        mftp_val = estimate_mftp(self._cp_model) if self._cp_model else None
        zone_ref = resolve_zone_ref(zone_src, ftp, cp_val, mftp_val)
        ref_watts = zone_ref.value

        # Aggregate zones across activities
        total_power_zones: Dict[str, int] = {z.key: 0 for z in POWER_ZONES}
        total_hr_zones: Dict[str, int] = {z.key: 0 for z in HR_ZONES}
        max_power_all = 0

        for a in self._activities_display:
            pz = a.get_zones_power()
            if pz:
                for k, v in pz.items():
                    if k in total_power_zones:
                        total_power_zones[k] += int(v)
            hz = a.get_zones_hr()
            if hz:
                for k, v in hz.items():
                    if k in total_hr_zones:
                        total_hr_zones[k] += int(v)
            if a.max_power and a.max_power > max_power_all:
                max_power_all = a.max_power

        # ─── Bar charts: time in zones ───
        self._draw_zone_bars(self._pw_zones_power, POWER_ZONES, total_power_zones,
                             show_time=True, tooltip_key="zones_power_time")
        self._draw_zone_bars(self._pw_zones_hr, HR_ZONES, total_hr_zones,
                             show_time=True, tooltip_key="zones_hr_time")

        # ─── Bar charts: % in zones ───
        self._draw_zone_bars(self._pw_zones_pct_power, POWER_ZONES, total_power_zones,
                             show_time=False, tooltip_key="zones_power_pct")
        self._draw_zone_bars(self._pw_zones_pct_hr, HR_ZONES, total_hr_zones,
                             show_time=False, tooltip_key="zones_hr_pct")

        # ─── Zone ranges (horizontal bars) ───
        self._draw_zone_ranges(ref_watts, max_power_all)

        # ─── Zone tables ───
        self._fill_zone_table(self._table_zones_power, POWER_ZONES, ref_watts, "W",
                              zone_ref.label, max_power_all)
        # Zonas HR: usar FCL si disponible, si no FCmáx
        hr_lthr = self.profile.config.get("hr_lthr")
        hr_zone_ref = hr_lthr if hr_lthr and hr_lthr > 0 else hr_max
        hr_zone_label = "FCL" if (hr_lthr and hr_lthr > 0) else "FCmáx"
        self._fill_zone_table(self._table_zones_hr, HR_ZONES, hr_zone_ref, "ppm", hr_zone_label, 0)

    def _draw_zone_bars(
        self, pw: pg.PlotWidget, zones: list, data: dict, show_time: bool,
        tooltip_key: str = "",
    ) -> None:
        pw.clear()
        n = len(zones)
        x = np.arange(n, dtype=np.float64)
        total_sec = sum(data.values())

        if show_time:
            heights = np.array([data.get(z.key, 0) for z in zones], dtype=np.float64)
        else:
            if total_sec > 0:
                heights = np.array(
                    [data.get(z.key, 0) / total_sec * 100 for z in zones],
                    dtype=np.float64,
                )
            else:
                heights = np.zeros(n)

        # Barras individuales con colores de zona
        for i, z in enumerate(zones):
            bar = pg.BarGraphItem(
                x=[float(i)], height=[heights[i]], width=0.65,
                brush=_qcolor(z.color, 200),
                pen=pg.mkPen(None),
            )
            pw.addItem(bar)

            # Label encima
            val_text = _fmt_hms(heights[i]) if show_time else f"{heights[i]:.1f}%"
            txt = pg.TextItem(val_text, color=_qcolor(z.color), anchor=(0.5, 1))
            txt.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            txt.setPos(float(i), heights[i])
            pw.addItem(txt)

        ticks = [(float(i), z.short_label) for i, z in enumerate(zones)]
        configure_axis(pw, "bottom", ticks)

        if show_time:
            max_val = max(heights) if len(heights) else 1
            pw.setYRange(0, max_val * 1.15)
        else:
            pw.setYRange(0, max(heights) * 1.2 if len(heights) and max(heights) > 0 else 100)

        # Tooltip para zonas
        if tooltip_key:
            _zones = zones
            _heights = heights
            _show_t = show_time
            _total = total_sec
            def _fmt_zone(xv, _y):
                idx = max(0, min(int(round(xv)), n - 1))
                z = _zones[idx]
                lines = [tooltip_header(z.label)]
                if _show_t:
                    lines.append(tooltip_line("Tiempo", _fmt_hms(_heights[idx]), z.color))
                    if _total > 0:
                        pct = _heights[idx] / _total * 100
                        lines.append(tooltip_line("% total", f"{pct:.1f}%", z.color))
                else:
                    lines.append(tooltip_line("% total", f"{_heights[idx]:.1f}%", z.color))
                    lines.append(tooltip_line("Tiempo", _fmt_hms(data.get(z.key, 0)), z.color))
                return tooltip_html(lines)
            snap = np.arange(n, dtype=np.float64)
            self._setup_tooltip(tooltip_key, pw, _fmt_zone, snap_xs=snap)

    def _draw_zone_ranges(self, ref_watts: int, max_power: int) -> None:
        pw = self._pw_zone_ranges
        pw.clear()
        if ref_watts <= 0:
            return

        n = len(POWER_ZONES)
        cap = max(max_power, ref_watts * 3) if max_power > 0 else ref_watts * 3

        # Store zone data for tooltip lookup
        self._zone_range_data: list = []

        for i, z in enumerate(POWER_ZONES):
            lo = z.min_pct / 100 * ref_watts
            hi_pct = z.max_pct if math.isfinite(z.max_pct) else (max_power / ref_watts * 100 if max_power > 0 else 303)
            hi = hi_pct / 100 * ref_watts
            hi = min(hi, cap)
            y = n - 1 - i

            self._zone_range_data.append({
                "y": y, "lo": lo, "hi": hi, "label": z.label,
                "color": z.color, "min_pct": z.min_pct, "hi_pct": hi_pct,
            })

            bar = pg.BarGraphItem(
                x0=[lo], y=[float(y)], width=[hi - lo], height=[0.5],
                brush=_qcolor(z.color, 180),
                pen=pg.mkPen(None),
            )
            pw.addItem(bar)

            # Label a la derecha
            txt = pg.TextItem(f"{round(hi)} W", color=_qcolor(z.color), anchor=(0, 0.5))
            txt.setFont(QFont("Segoe UI", 9))
            txt.setPos(hi + 5, float(y))
            pw.addItem(txt)

        # Ticks Y: nombres de zona
        y_ticks = [(float(n - 1 - i), z.short_label) for i, z in enumerate(POWER_ZONES)]
        configure_axis(pw, "left", y_ticks)
        pw.setXRange(0, cap * 1.1)
        pw.setYRange(-0.5, float(n) - 0.5)

        # Interactive tooltip via ChartTooltip (same system as other zone charts)
        _zrd = self._zone_range_data
        def _fmt_zone_range(x, y):
            # Find which zone the cursor is near
            hit = None
            for zd in _zrd:
                if abs(y - zd["y"]) < 0.45 and zd["lo"] <= x <= zd["hi"]:
                    hit = zd
                    break
            if hit is None:
                # Check just by Y proximity (user may be above/below bar)
                for zd in _zrd:
                    if abs(y - zd["y"]) < 0.45:
                        hit = zd
                        break
            if hit is None:
                return ""
            lines = [
                tooltip_header(hit["label"]),
                tooltip_line("Rango", f'{round(hit["lo"])} – {round(hit["hi"])} W', hit["color"]),
                tooltip_line("% ref", f'{hit["min_pct"]:.0f}–{hit["hi_pct"]:.0f}%', "#94a3b8"),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("zone_ranges", pw, _fmt_zone_range)

    # Sub-zonas de referencia que se intercalan entre zonas principales (solo potencia)
    _POWER_SUBZONES = [
        {"key": "pmr", "label": "PMR · Potencia Mínima de Rodaje", "min_pct": 65, "max_pct": 70, "color": "#A7C7E7", "after": "z2"},
        {"key": "ss",  "label": "SS · Sweet Spot",                  "min_pct": 88, "max_pct": 95, "color": "#A19AD3", "after": "z3"},
    ]

    def _fill_zone_table(
        self, table: QTableWidget, zones: list, ref: int, unit: str,
        ref_label: str, max_power: int
    ) -> None:
        # Construir lista de filas: zonas principales + sub-zonas intercaladas
        # Para zonas de potencia intercalamos PMR (tras Z2) y SS (tras Z3)
        # Para zonas HR simplemente listamos las zonas sin sub-zonas
        is_power = any(z.key == "z7" for z in zones)
        rows: list[dict] = []
        for z in zones:
            if is_power and z.key == "z3p":
                continue  # Sweet Spot ya se añade como sub-zona
            rows.append({
                "label": z.label, "min_pct": z.min_pct, "max_pct": z.max_pct,
                "color": z.color, "key": z.key, "sub": False,
            })
            if is_power:
                for sz in self._POWER_SUBZONES:
                    if sz["after"] == z.key:
                        rows.append({
                            "label": sz["label"], "min_pct": sz["min_pct"],
                            "max_pct": sz["max_pct"], "color": sz["color"],
                            "key": sz["key"], "sub": True,
                        })

        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            # Zona
            prefix = "  ┊ " if row["sub"] else "  ● "
            item = QTableWidgetItem(f"{prefix}{row['label']}")
            item.setForeground(QColor(row["color"]))
            if row["sub"]:
                f = item.font()
                f.setItalic(True)
                item.setFont(f)
            table.setItem(i, 0, item)

            # % ref
            hi_pct = row["max_pct"] if math.isfinite(row["max_pct"]) else 303
            table.setItem(i, 1, QTableWidgetItem(
                f"{row['min_pct']:.0f}–{hi_pct:.0f}%"
            ))

            # Rango en vatios/ppm
            lo = round(row["min_pct"] / 100 * ref) if ref > 0 else 0
            if math.isfinite(row["max_pct"]):
                hi = round(row["max_pct"] / 100 * ref) if ref > 0 else 0
            else:
                hi = max_power if max_power > 0 else round(3.03 * ref) if ref > 0 else 0
            table.setItem(i, 2, QTableWidgetItem(f"{lo}\u00a0–\u00a0{hi}\u00a0{unit}"))

    # ══════════════════════════════════════════════════════════════
    # TAB 4: RENDIMIENTO
    # ══════════════════════════════════════════════════════════════

    def _build_rendimiento_tab(self) -> None:
        scroll, inner, lay = _scrollable_widget()
        self._tabs.addTab(scroll, "🔬 Rendimiento")

        # ── Modelo Critical Power card ──
        lay.addWidget(_section_title(
            "🔬", "Modelo Critical Power",
            "Resultados del último conjunto de tests (regresión lineal: P = CP + W'/t)."
        ))
        self._cp_model_frame = _card_frame()
        self._cp_model_grid = QGridLayout(self._cp_model_frame)
        self._cp_model_grid.setContentsMargins(16, 12, 16, 12)
        self._cp_model_grid.setSpacing(10)
        lay.addWidget(self._cp_model_frame)

        # TTE Calculator
        lay.addWidget(_section_title(
            "⏳", "Calculadora TTE (Time-To-Exhaustion)",
            "Estima cuánto puedes sostener una potencia dada según tu modelo CP."
        ))
        self._tte_widget = self._build_tte_widget()
        lay.addWidget(self._tte_widget)

        # Records personales
        lay.addWidget(_section_title(
            "🏆", "Records personales",
            "Tus mejores potencias sostenidas por duración. La banderita verde marca records de los últimos 30 días."
        ))
        self._table_records = QTableWidget()
        self._table_records.setColumnCount(4)
        self._table_records.setHorizontalHeaderLabels(["DURACIÓN", "POTENCIA", "FECHA", "ACTIVIDAD"])
        self._table_records.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table_records.verticalHeader().setVisible(False)
        self._table_records.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table_records.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table_records.setMinimumHeight(320)
        lay.addWidget(self._table_records)

        # Evolución CP y W'
        lay.addWidget(_section_title(
            "📈", "Evolución de CP y W'",
            "Necesitas al menos 2 tests para ver la tendencia."
        ))
        self._pw_cp_trend = make_plot(height=250)
        lay.addWidget(self._pw_cp_trend)

        # Evolución del perfil
        lay.addWidget(_section_title(
            "📈", "Evolución del perfil",
            "Seguimiento histórico de peso, potencia y eficiencia."
        ))
        self._pw_profile_evo = make_plot(height=250)
        lay.addWidget(self._pw_profile_evo)

        lay.addStretch()

    def _build_tte_widget(self) -> QFrame:
        frame = _card_frame()
        main_lay = QHBoxLayout(frame)
        main_lay.setContentsMargins(16, 14, 16, 14)
        main_lay.setSpacing(20)

        # Left: input
        left = QVBoxLayout()
        left.setSpacing(8)
        lbl = QLabel("Potencia objetivo (W)")
        lbl.setStyleSheet(f"font-weight: 600; color: {COLORS['fg']}; background: transparent; border: none;")
        left.addWidget(lbl)
        self._tte_input = QLineEdit()
        self._tte_input.setPlaceholderText("Ej: 350")
        self._tte_input.setMinimumWidth(160)
        self._tte_input.textChanged.connect(self._update_tte_result)
        left.addWidget(self._tte_input)
        hint = QLabel("Fórmula: TTE = W' / (P – CP)")
        hint.setProperty("class", "caption")
        left.addWidget(hint)
        left.addStretch()
        main_lay.addLayout(left)

        # Center: result
        center = QVBoxLayout()
        center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tte_lbl = QLabel("TTE ESTIMADO")
        tte_lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
            f"font-weight: 600; background: transparent; border: none;"
        )
        tte_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addWidget(tte_lbl)
        self._tte_result_label = QLabel("—")
        self._tte_result_label.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: 700; "
            f"color: {COLORS['fg']}; background: transparent; border: none;"
        )
        self._tte_result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self._tte_result_label)
        main_lay.addLayout(center, 1)

        # Right: quick references
        right = QVBoxLayout()
        right.setSpacing(4)
        ref_lbl = QLabel("REFERENCIAS RÁPIDAS")
        ref_lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
            f"font-weight: 600; background: transparent; border: none;"
        )
        right.addWidget(ref_lbl)
        self._tte_refs_layout = QVBoxLayout()
        self._tte_refs_layout.setSpacing(2)
        right.addLayout(self._tte_refs_layout)
        right.addStretch()
        main_lay.addLayout(right)

        return frame

    def _update_tte_result(self) -> None:
        if not self._cp_model:
            self._tte_result_label.setText("Sin modelo CP")
            return
        text = self._tte_input.text().strip()
        if not text:
            self._tte_result_label.setText("—")
            return
        try:
            power = int(text)
        except ValueError:
            self._tte_result_label.setText("—")
            return
        if power < 10:
            self._tte_result_label.setText("—")
            return
        result = calc_tte(power, self._cp_model.cp, self._cp_model.w_prime)
        self._tte_result_label.setText(result.label)

    def _update_rendimiento(self) -> None:
        self._update_cp_model_card()
        self._update_tte_refs()
        self._update_tte_result()
        self._update_records()
        self._update_cp_trend()
        self._update_profile_evo()

    def _update_cp_model_card(self) -> None:
        """Populate the Critical Power model card with 7 metrics + reliability badge."""
        grid = self._cp_model_grid
        # Clear previous widgets
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        test = self._tests[0] if self._tests else None
        model = self._cp_model

        if not test or not model:
            placeholder = QLabel("Registra tests de potencia en Ajustes para ver tu modelo CP.")
            placeholder.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; "
                f"padding: 20px; background: transparent; border: 1px dashed {COLORS['border']}; "
                f"border-radius: {RADIUS_LG};"
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(placeholder, 0, 0, 1, 4)
            return

        # Compute derived values
        weight = self._snapshots[0].weight_kg if self._snapshots else 0
        mftp = estimate_mftp(model)
        vo2max_val = test.vo2max if test.vo2max else estimate_vo2max(test.p5min or 0, weight)
        mftp_pct = calc_mftp_vo2max_percentage(mftp, vo2max_val, weight)
        reliability = reliability_from_r2(model.r_squared)

        # 7 metrics to display
        metrics = [
            ("⚡", "CP", f"{round(model.cp)} W" if model.cp else "—", "Critical Power"),
            ("🔋", "W'", f"{model.w_prime_kj:.1f} kJ" if model.w_prime_kj else "—", "Trabajo anaeróbico"),
            ("🏔️", "P5min", f"{round(test.p5min)} W" if test.p5min else "—", "Potencia 5 min interpolada"),
            ("📊", "mFTP", f"{round(mftp)} W" if mftp else "—", "FTP modelado (0.96 · CP)"),
            ("🫁", "VO₂max", f"{vo2max_val:.2f}" if vo2max_val else "—", "ml/kg/min"),
            ("📐", "mFTP/VO₂max", f"{mftp_pct:.2f}%" if mftp_pct else "—", "Aprovechamiento aeróbico"),
            ("💥", "P máx", f"{round(test.max_power)} W" if test.max_power else "—", "Pico de sprint"),
        ]

        # Add metric tiles in a 4-column grid (row 0: 4 items, row 1: 3 items + badge)
        for i, (icon, label, value, hint) in enumerate(metrics):
            row = i // 4
            col = i % 4
            card = StatCard(icon, label, value, "", hint=hint, accent=COLORS["primary"])
            card.setMinimumHeight(100)
            grid.addWidget(card, row, col)

        # Reliability badge in the last cell
        r_colors = {"high": COLORS["success"], "ok": COLORS["accent"], "low": COLORS["destructive"], "na": COLORS["fg_muted"]}
        badge_frame = QFrame()
        badge_frame.setStyleSheet(
            f"background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: {RADIUS_LG};"
        )
        badge_lay = QVBoxLayout(badge_frame)
        badge_lay.setContentsMargins(14, 10, 14, 8)
        badge_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        r_emoji = QLabel(reliability.emoji)
        r_emoji.setStyleSheet(f"font-size: {FONT_SIZE_XL}; background: transparent; border: none;")
        r_emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_lay.addWidget(r_emoji)
        r_text = QLabel(reliability.text)
        r_text.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {r_colors.get(reliability.level, COLORS['fg_muted'])}; "
            f"font-weight: 700; background: transparent; border: none;"
        )
        r_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_lay.addWidget(r_text)
        r_val = QLabel(f"R² = {model.r_squared:.4f}" if model.r_squared is not None else "")
        r_val.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; "
            f"background: transparent; border: none;"
        )
        r_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_lay.addWidget(r_val)
        badge_frame.setMinimumHeight(100)
        grid.addWidget(badge_frame, 1, 3)

    def _update_tte_refs(self) -> None:
        # Clear existing
        while self._tte_refs_layout.count():
            item = self._tte_refs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._cp_model:
            return

        cp = self._cp_model.cp
        w_prime = self._cp_model.w_prime
        refs = [
            ("CP · 100%", cp, 1.0),
            ("CP +5%", cp * 1.05, 1.05),
            ("CP +10%", cp * 1.10, 1.10),
            ("CP +20%", cp * 1.20, 1.20),
            ("CP +40%", cp * 1.40, 1.40),
        ]
        for label, power, _mult in refs:
            result = calc_tte(power, cp, w_prime)
            btn = QPushButton(f"{label}: {round(power)} W → {result.label}")
            btn.setStyleSheet(
                f"text-align: left; font-size: {FONT_SIZE_SM}; "
                f"color: {COLORS['fg_muted']}; background: transparent; "
                f"border: none; padding: 2px 4px;"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            _pw = round(power)
            btn.clicked.connect(lambda checked=False, w=_pw: self._tte_input.setText(str(w)))
            self._tte_refs_layout.addWidget(btn)

    def _update_records(self) -> None:
        table = self._table_records
        global_mmp: Dict[int, Tuple[int, int, str, str]] = {}
        # {duration: (power, activity_id, date_str, display_name)}
        today = date.today()
        thirty_ago = today - timedelta(days=30)

        for a in self._activities_display:
            mmp_data = a.get_mmp()
            if not mmp_data:
                continue
            a_date = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            for dur in PR_DURATIONS:
                val = mmp_data.get(str(dur), 0)
                if val and (dur not in global_mmp or val > global_mmp[dur][0]):
                    global_mmp[dur] = (int(val), a.id, a_date.isoformat(), a.display_name)

        table.setRowCount(len(PR_DURATIONS))
        for i, dur in enumerate(PR_DURATIONS):
            # Duration label
            if dur < 60:
                dur_label = f"{dur}s"
            else:
                dur_label = f"{dur // 60} min"
            table.setItem(i, 0, QTableWidgetItem(dur_label))

            if dur in global_mmp:
                power, aid, date_str, name = global_mmp[dur]
                d = date.fromisoformat(date_str)
                is_recent = d >= thirty_ago

                pw_item = QTableWidgetItem(f"{power} W")
                pw_item.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                table.setItem(i, 1, pw_item)

                d_label = f"{d.day} {_MONTH_SHORT[d.month]} {d.year}"
                table.setItem(i, 2, QTableWidgetItem(d_label))

                flag = " 🏴 nuevo" if is_recent else ""
                name_item = QTableWidgetItem(name + flag)
                if is_recent:
                    name_item.setForeground(QColor(COLORS["success"]))
                else:
                    name_item.setForeground(QColor(COLORS["accent"]))
                table.setItem(i, 3, name_item)
            else:
                for col in (1, 2, 3):
                    table.setItem(i, col, QTableWidgetItem("—"))

    def _update_cp_trend(self) -> None:
        pw = self._pw_cp_trend
        pw.clear()
        tests = self._tests
        if len(tests) < 2:
            txt = pg.TextItem(
                "Registra más tests de potencia para ver la tendencia.",
                color=_qcolor(COLORS["fg_muted"]),
            )
            txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(txt)
            return

        # Ordenar cronológicamente
        sorted_tests = sorted(tests, key=lambda t: t.tested_at)
        dates = []
        cp_vals = []
        wp_vals = []
        for t in sorted_tests:
            if t.cp and t.w_prime:
                d = t.tested_at.date() if isinstance(t.tested_at, datetime) else t.tested_at
                dates.append(d)
                cp_vals.append(t.cp)
                wp_vals.append(t.w_prime / 1000)  # kJ

        if len(dates) < 2:
            return

        xs = np.array([date_to_ts(d) for d in dates])
        ticks = [(date_to_ts(d), f"{d.day} {_MONTH_SHORT[d.month]} {str(d.year)[2:]}") for d in dates]

        pw.plot(xs, np.array(cp_vals), pen=pg.mkPen(CHART_COLORS["cp"], width=2),
                symbol='o', symbolSize=7, symbolBrush=_qcolor(CHART_COLORS["cp"]))
        configure_axis(pw, "bottom", ticks)

        # W' en eje derecho (simulado con segunda línea escalada)
        # Para simplificar, mostramos W' como segunda línea
        pw.getPlotItem().showAxis("right")
        pw.getAxis("right").setTextPen(_qcolor(CHART_COLORS["w_prime"]))

        # Plot W' datos
        vb2 = pg.ViewBox()
        vb2.setMouseEnabled(x=False, y=False)
        vb2.wheelEvent = lambda ev: ev.ignore()
        pw.getPlotItem().scene().addItem(vb2)
        pw.getPlotItem().getAxis("right").linkToView(vb2)
        vb2.setXLink(pw.getPlotItem().getViewBox())

        # Disable mouse interaction on main ViewBox too (prevents cursor trapping)
        main_vb = pw.getPlotItem().getViewBox()
        main_vb.setMouseEnabled(x=False, y=False)
        main_vb.wheelEvent = lambda ev: ev.ignore()

        wp_curve = pg.PlotCurveItem(xs, np.array(wp_vals),
                                     pen=pg.mkPen(CHART_COLORS["w_prime"], width=2))
        vb2.addItem(wp_curve)

        def update_views():
            vb2.setGeometry(pw.getPlotItem().getViewBox().sceneBoundingRect())
            vb2.linkedViewChanged(pw.getPlotItem().getViewBox(), vb2.XAxis)

        pw.getPlotItem().getViewBox().sigResized.connect(update_views)
        update_views()

        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(_qcolor(COLORS["fg_muted"]))

        # Tooltip CP trend — coloreado
        _cp_xs, _cp_v, _wp_v = xs, np.array(cp_vals), np.array(wp_vals)
        def _fmt_cp_trend(x, _y):
            if len(_cp_xs) == 0: return ""
            idx = int(np.argmin(np.abs(_cp_xs - x)))
            dl = self._date_label(_cp_xs[idx])
            lines = [
                tooltip_header(dl),
                tooltip_line("CP", f"{_cp_v[idx]:.0f} W", CHART_COLORS["cp"]),
                tooltip_line("W'", f"{_wp_v[idx]:.1f} kJ", CHART_COLORS["w_prime"]),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("cp_trend", pw, _fmt_cp_trend, snap_xs=xs)

    def _update_profile_evo(self) -> None:
        pw = self._pw_profile_evo
        pw.clear()

        snaps = self._snapshots
        if len(snaps) < 1:
            return

        dates = []
        ftp_vals = []
        weight_vals = []
        for s in snaps:
            d = s.effective_at.date() if isinstance(s.effective_at, datetime) else s.effective_at
            dates.append(d)
            ftp_vals.append(s.ftp)
            weight_vals.append(s.weight_kg)

        xs = np.array([date_to_ts(d) for d in dates])

        pw.plot(xs, np.array(ftp_vals), pen=pg.mkPen(CHART_COLORS["ftp"], width=2),
                symbol='o', symbolSize=7, symbolBrush=_qcolor(CHART_COLORS["ftp"]),
                name="FTP")

        # CP y mFTP from tests that match dates
        for t in self._tests:
            if t.cp:
                d = t.tested_at.date() if isinstance(t.tested_at, datetime) else t.tested_at
                x = date_to_ts(d)
                pw.plot([x], [t.cp], symbol='o', symbolSize=7,
                        symbolBrush=_qcolor(CHART_COLORS["cp"]),
                        pen=pg.mkPen(None), name="CP")
                if t.m_ftp:
                    pw.plot([x], [t.m_ftp], symbol='o', symbolSize=7,
                            symbolBrush=_qcolor(CHART_COLORS["mftp"]),
                            pen=pg.mkPen(None), name="mFTP")

        # Weight on right axis
        pw.getPlotItem().showAxis("right")
        pw.getAxis("right").setTextPen(_qcolor(CHART_COLORS["weight"]))

        vb2 = pg.ViewBox()
        vb2.setMouseEnabled(x=False, y=False)
        vb2.wheelEvent = lambda ev: ev.ignore()
        pw.getPlotItem().scene().addItem(vb2)
        pw.getPlotItem().getAxis("right").linkToView(vb2)
        vb2.setXLink(pw.getPlotItem().getViewBox())

        # Disable mouse on main ViewBox
        main_vb_pe = pw.getPlotItem().getViewBox()
        main_vb_pe.setMouseEnabled(x=False, y=False)
        main_vb_pe.wheelEvent = lambda ev: ev.ignore()

        weight_curve = pg.PlotCurveItem(xs, np.array(weight_vals),
                                         pen=pg.mkPen(CHART_COLORS["weight"], width=2))
        vb2.addItem(weight_curve)

        def update_views():
            vb2.setGeometry(pw.getPlotItem().getViewBox().sceneBoundingRect())
            vb2.linkedViewChanged(pw.getPlotItem().getViewBox(), vb2.XAxis)

        pw.getPlotItem().getViewBox().sigResized.connect(update_views)
        update_views()

        ticks = [(date_to_ts(d), f"{d.day} {_MONTH_SHORT[d.month]} {str(d.year)[2:]}") for d in dates]
        configure_axis(pw, "bottom", ticks)

        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(_qcolor(COLORS["fg_muted"]))

        # Tooltip perfil evolución — coloreado
        _pe_xs = xs
        _pe_ftp = np.array(ftp_vals)
        _pe_w = np.array(weight_vals)
        def _fmt_profile(x, _y):
            if len(_pe_xs) == 0: return ""
            idx = int(np.argmin(np.abs(_pe_xs - x)))
            dl = self._date_label(_pe_xs[idx])
            lines = [
                tooltip_header(dl),
                tooltip_line("FTP", f"{_pe_ftp[idx]:.0f} W", CHART_COLORS["ftp"]),
                tooltip_line("Peso", f"{_pe_w[idx]:.1f} kg", CHART_COLORS["weight"]),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("profile_evo", pw, _fmt_profile, snap_xs=xs)

    # ══════════════════════════════════════════════════════════════
    # TAB 5: ANÁLISIS AVANZADO
    # ══════════════════════════════════════════════════════════════

    def _build_analisis_tab(self) -> None:
        scroll, inner, lay = _scrollable_widget()
        self._tabs.addTab(scroll, "🔬 Análisis avanzado")

        # Tendencias de eficiencia
        lay.addWidget(_section_title(
            "📈", "Tendencias de eficiencia",
            "EF (NP/FC), VF (NP/Pmedia), Pw:Hr (desacople potencia/FC) por actividad."
        ))
        self._pw_efficiency = make_plot(height=280)
        lay.addWidget(self._pw_efficiency)

        # ── DCP — Duración de Curva de Potencia ──
        lay.addWidget(_section_title(
            "🔋", "DCP — Duración de Curva de Potencia",
            "Potencia máxima por duración (5 s – 3 h). Basado en tus mejores esfuerzos registrados."
        ))
        self._pw_dcp = make_plot(height=300)
        lay.addWidget(self._pw_dcp)

        # ── Selección de rangos para series ──
        lay.addWidget(_section_title(
            "🎯", "Selección de rangos para series",
            "Banda de potencia objetivo (rosa) sobre tu curva MMP para planificar intervalos."
        ))
        self._pw_interval_targeting = make_plot(height=300)
        lay.addWidget(self._pw_interval_targeting)

        # Tarjetas de intervalos sugeridos
        self._interval_cards_container = QWidget()
        self._interval_cards_layout = QGridLayout(self._interval_cards_container)
        self._interval_cards_layout.setContentsMargins(0, 4, 0, 8)
        self._interval_cards_layout.setSpacing(6)
        lay.addWidget(self._interval_cards_container)

        lay.addStretch()

    def _update_analisis(self) -> None:
        self._update_efficiency()
        self._update_dcp()
        self._update_interval_targeting()

    def _update_efficiency(self) -> None:
        pw = self._pw_efficiency
        pw.clear()

        # Limpiar ViewBoxes y ejes auxiliares de actualizaciones previas
        pi = pw.getPlotItem()
        if hasattr(self, '_eff_vb_vf'):
            try:
                pi.scene().removeItem(self._eff_vb_vf)
            except Exception:
                pass
            self._eff_vb_vf = None
        if hasattr(self, '_eff_vb_pwhr'):
            try:
                pi.scene().removeItem(self._eff_vb_pwhr)
            except Exception:
                pass
            self._eff_vb_pwhr = None
        if hasattr(self, '_eff_ax_pwhr') and self._eff_ax_pwhr is not None:
            try:
                pi.layout.removeItem(self._eff_ax_pwhr)
                self._eff_ax_pwhr.scene().removeItem(self._eff_ax_pwhr)
            except Exception:
                try:
                    self._eff_ax_pwhr.deleteLater()
                except Exception:
                    pass
            self._eff_ax_pwhr = None
        # Ocultar eje derecho estándar (VF) para reiniciarlo limpio
        try:
            pi.hideAxis('right')
        except Exception:
            pass

        ef_data: list[tuple[float, float]] = []
        vf_data: list[tuple[float, float]] = []
        pwhr_data: list[tuple[float, float]] = []

        sorted_acts = sorted(self._activities_display, key=lambda a: a.started_at)
        for a in sorted_acts:
            if not a.normalized_power:
                continue
            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            ts = date_to_ts(d)

            # EF requiere FC media
            if a.avg_hr:
                ef = calc_ef(a.normalized_power, a.avg_hr)
                if ef is not None:
                    ef_data.append((ts, ef))

            # VF requiere potencia media
            vf = calc_vf(a.normalized_power, a.avg_power)
            if vf is not None:
                vf_data.append((ts, vf))

            # Pw:Hr requiere muestras con HR
            if a.avg_hr:
                samples_raw = a.get_samples()
                if samples_raw and len(samples_raw) > 60:
                    sample_tuples = [
                        (s.get("t", 0), s.get("p") or s.get("power"), s.get("hr"))
                        for s in samples_raw
                    ]
                    phr = calc_pw_hr_decoupling(sample_tuples)
                    if phr:
                        pwhr_data.append((ts, phr.decoupling))

        if not ef_data and not vf_data:
            return

        main_vb = pi.getViewBox()

        # ── EF (eje izquierdo) ──────────────────────────────────
        # Etiqueta del eje izquierdo
        pw.getAxis("left").setTextPen(_qcolor(CHART_COLORS["ef"]))
        pw.getAxis("left").setLabel("EF", color=CHART_COLORS["ef"], units=None)

        if ef_data:
            ef_x = np.array([d[0] for d in ef_data])
            ef_y = np.array([d[1] for d in ef_data])

            scatter_ef = pg.ScatterPlotItem(
                ef_x, ef_y, size=6,
                brush=_qcolor(CHART_COLORS["ef"]),
                pen=pg.mkPen(None),
            )
            pw.addItem(scatter_ef)
            pw.plot(ef_x, ef_y, pen=pg.mkPen(CHART_COLORS["ef"], width=1.5), name="EF (NP/FC)")

        # ── VF (ViewBox propio — eje derecho interno) ─────────
        # Usamos un ViewBox independiente para que la escala de VF
        # no se mezcle con la de EF (paridad con la web).
        if vf_data:
            vf_x = np.array([d[0] for d in vf_data])
            vf_y = np.array([d[1] for d in vf_data])

            vb_vf = pg.ViewBox()
            vb_vf.setMouseEnabled(x=False, y=False)
            vb_vf.wheelEvent = lambda ev: ev.ignore()
            pi.scene().addItem(vb_vf)
            # Mostrar eje derecho y vincular a VF
            pi.showAxis("right")
            pi.getAxis("right").linkToView(vb_vf)
            pi.getAxis("right").setTextPen(_qcolor(CHART_COLORS["vf"]))
            pi.getAxis("right").setLabel("VF", color=CHART_COLORS["vf"], units=None)
            vb_vf.setXLink(main_vb)

            scatter_vf = pg.ScatterPlotItem(
                vf_x, vf_y, size=6,
                brush=_qcolor(CHART_COLORS["vf"]),
                pen=pg.mkPen(None),
            )
            vb_vf.addItem(scatter_vf)
            curve_vf = pg.PlotCurveItem(
                vf_x, vf_y,
                pen=pg.mkPen(CHART_COLORS["vf"], width=1.5),
            )
            vb_vf.addItem(curve_vf)

            # Línea invisible en el plot principal para la leyenda
            pw.plot([], [], pen=pg.mkPen(CHART_COLORS["vf"], width=1.5), name="VF (NP/Pmedia)")

            self._eff_vb_vf = vb_vf

            def _sync_vf():
                vb_vf.setGeometry(main_vb.sceneBoundingRect())
                vb_vf.linkedViewChanged(main_vb, vb_vf.XAxis)

            main_vb.sigResized.connect(_sync_vf)
            _sync_vf()

        # ── Pw:Hr (ViewBox propio — eje derecho externo) ──────
        if pwhr_data:
            pwhr_x = np.array([d[0] for d in pwhr_data])
            pwhr_y = np.array([d[1] for d in pwhr_data])

            vb_pwhr = pg.ViewBox()
            vb_pwhr.setMouseEnabled(x=False, y=False)
            vb_pwhr.wheelEvent = lambda ev: ev.ignore()
            pi.scene().addItem(vb_pwhr)
            vb_pwhr.setXLink(main_vb)

            # Crear un tercer eje a la derecha para Pw:Hr
            ax_pwhr = pg.AxisItem("right")
            ax_pwhr.setTextPen(_qcolor(CHART_COLORS["pwhr"]))
            ax_pwhr.setLabel("Pw:Hr %", color=CHART_COLORS["pwhr"], units=None)
            ax_pwhr.linkToView(vb_pwhr)
            pi.layout.addItem(ax_pwhr, 2, pi.layout.columnCount())
            self._eff_ax_pwhr = ax_pwhr

            scatter_pwhr = pg.ScatterPlotItem(
                pwhr_x, pwhr_y, size=6,
                brush=_qcolor(CHART_COLORS["pwhr"]),
                pen=pg.mkPen(None),
            )
            vb_pwhr.addItem(scatter_pwhr)
            curve_pwhr = pg.PlotCurveItem(
                pwhr_x, pwhr_y,
                pen=pg.mkPen(CHART_COLORS["pwhr"], width=1.5),
            )
            vb_pwhr.addItem(curve_pwhr)

            # Línea invisible para la leyenda
            pw.plot([], [], pen=pg.mkPen(CHART_COLORS["pwhr"], width=1.5), name="Pw:Hr (%)")

            self._eff_vb_pwhr = vb_pwhr

            def _sync_pwhr():
                vb_pwhr.setGeometry(main_vb.sceneBoundingRect())
                vb_pwhr.linkedViewChanged(main_vb, vb_pwhr.XAxis)

            main_vb.sigResized.connect(_sync_pwhr)
            _sync_pwhr()

        # Date ticks
        all_ts = set()
        for lst in (ef_data, vf_data, pwhr_data):
            all_ts.update(d[0] for d in lst)
        all_dates = sorted(all_ts)
        if len(all_dates) > 1:
            step = max(1, len(all_dates) // 14)
            ticks = []
            for i in range(0, len(all_dates), step):
                d = datetime.fromtimestamp(all_dates[i]).date()
                ticks.append((all_dates[i], f"{d.day} {_MONTH_SHORT[d.month]}"))
            configure_axis(pw, "bottom", ticks)

        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(_qcolor(COLORS["fg_muted"]))

        # Tooltip eficiencia — coloreado (paridad web: EF, VF, Pw:Hr)
        _ef = ef_data
        _vf = vf_data
        _phr = pwhr_data
        def _fmt_eff(x, _y):
            dl = self._date_label(x)
            lines = [tooltip_header(dl)]
            if _ef:
                ef_xs = np.array([d[0] for d in _ef])
                ef_ys = np.array([d[1] for d in _ef])
                idx = int(np.argmin(np.abs(ef_xs - x)))
                lines.append(tooltip_line("EF", f"{ef_ys[idx]:.2f}", CHART_COLORS["ef"]))
            if _vf:
                vf_xs = np.array([d[0] for d in _vf])
                vf_ys = np.array([d[1] for d in _vf])
                idx_v = int(np.argmin(np.abs(vf_xs - x)))
                lines.append(tooltip_line("VF", f"{vf_ys[idx_v]:.2f}", CHART_COLORS["vf"]))
            if _phr:
                phr_xs = np.array([d[0] for d in _phr])
                phr_ys = np.array([d[1] for d in _phr])
                idx2 = int(np.argmin(np.abs(phr_xs - x)))
                phr_val = phr_ys[idx2]
                sign = "+" if phr_val > 0 else ""
                lines.append(tooltip_line("Pw:Hr", f"{sign}{phr_val:.1f}%", CHART_COLORS["pwhr"]))
            return tooltip_html(lines)
        # Snap to nearest data point across all series
        all_snap = sorted(all_ts) if all_ts else None
        snap = np.array(all_snap) if all_snap else None
        self._setup_tooltip("efficiency", pw, _fmt_eff, snap_xs=snap)

    # ── DCP — Duración de Curva de Potencia ─────────────────────

    def _update_dcp(self) -> None:
        """Gráfico DCP independiente: curva de potencia-duración."""
        pw = self._pw_dcp
        pw.clear()

        # Construir MMP global
        global_mmp: Dict[int, int] = {}
        for a in self._activities_display:
            mmp_data = a.get_mmp()
            if mmp_data:
                int_mmp = {int(k): int(v) for k, v in mmp_data.items()}
                global_mmp = merge_mmp_max(global_mmp, int_mmp)

        if len(global_mmp) < 5:
            return

        # Referencia (mFTP > CP > FTP)
        ref_val = 0
        ref_label = ""
        if self._cp_model:
            mftp = estimate_mftp(self._cp_model)
            ref_val = mftp
            ref_label = "mFTP"
        if not ref_val:
            ftp = self.profile.config.get("ftp", 0)
            if ftp:
                ref_val = ftp
                ref_label = "FTP"

        # Datos ordenados (5s – duración máxima disponible)
        sorted_durs = sorted(d for d in global_mmp.keys() if d >= 5)
        if len(sorted_durs) < 3:
            return

        max_dur = sorted_durs[-1]

        xs_log = np.array([np.log10(d) for d in sorted_durs])
        ys_mmp = np.array([global_mmp[d] for d in sorted_durs])

        DCP_COLOR = "#ef4444"

        # Curva DCP
        pw.plot(xs_log, ys_mmp, pen=pg.mkPen(DCP_COLOR, width=2.5), name="DCP")

        # Línea de referencia
        if ref_val > 0:
            add_horizontal_line(pw, ref_val, "#FF9149", Qt.PenStyle.DashLine, 1)
            txt = pg.TextItem(f"{ref_label} {round(ref_val)} W",
                              color=_qcolor("#FF9149"))
            txt.setFont(QFont("Segoe UI", 8))
            txt.setPos(xs_log[0], ref_val)
            pw.addItem(txt)

        # Eje X — 5s → duración máxima (ticks filtrados)
        visible_ticks = [d for d in _DCP_X_TICKS if d <= max_dur]
        x_ticks = [(np.log10(d), _DCP_X_LABELS.get(d, _fmt_duration(d)))
                    for d in visible_ticks]
        configure_axis(pw, "bottom", x_ticks)
        pw.setXRange(np.log10(5), np.log10(max_dur))

        # Eje Y
        y_min = min(ys_mmp)
        y_max = max(ys_mmp)
        if ref_val > 0:
            y_min = min(y_min, ref_val)
            y_max = max(y_max, ref_val)
        y_min = max(0, (y_min // 50) * 50 - 50)
        y_max = (y_max // 100 + 1) * 100 + 50
        pw.setYRange(y_min, y_max)

        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(_qcolor(COLORS["fg_muted"]))

        # Tooltip — snap a la duración más cercana, no atrapa al gráfico
        _gm = global_mmp
        _sd = sorted_durs
        def _fmt_dcp(x, _y):
            t_sec = 10 ** x
            closest = min(_sd, key=lambda d: abs(d - t_sec))
            pw_val = _gm[closest]
            t_str = _fmt_duration(closest)
            lines = [
                tooltip_header(t_str),
                tooltip_line("DCP", f"{pw_val} W", DCP_COLOR),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("dcp", pw, _fmt_dcp)

    # ── Interval Targeting ──────────────────────────────────────

    def _update_interval_targeting(self) -> None:
        """Gráfico de selección de intervalos con banda de targeting."""
        pw = self._pw_interval_targeting
        pw.clear()

        # Construir MMP global
        global_mmp: Dict[int, int] = {}
        for a in self._activities_display:
            mmp_data = a.get_mmp()
            if mmp_data:
                int_mmp = {int(k): int(v) for k, v in mmp_data.items()}
                global_mmp = merge_mmp_max(global_mmp, int_mmp)

        if len(global_mmp) < 5:
            return

        # Referencia (mFTP > CP > FTP)
        ref_val = 0
        ref_label = ""
        if self._cp_model:
            mftp = estimate_mftp(self._cp_model)
            ref_val = mftp
            ref_label = "mFTP"
        if not ref_val:
            ftp = self.profile.config.get("ftp", 0)
            if ftp:
                ref_val = ftp
                ref_label = "FTP"

        # Datos de la curva MMP ordenados (5s – 2700s como en la web)
        sorted_durs = sorted(d for d in global_mmp.keys() if 5 <= d <= 2700)
        if len(sorted_durs) < 3:
            return

        xs_log = np.array([np.log10(d) for d in sorted_durs])
        ys_mmp = np.array([global_mmp[d] for d in sorted_durs])

        # Bandas de targeting
        def _band_factors(dur_sec: int):
            longness = min(1.0, max(0.0, np.log10(dur_sec) / np.log10(3600)))
            low_pct = 0.85 + 0.10 * longness
            high_pct = 1.05 - 0.03 * longness
            return low_pct, high_pct

        ys_low = np.array([global_mmp[d] * _band_factors(d)[0] for d in sorted_durs])
        ys_high = np.array([global_mmp[d] * _band_factors(d)[1] for d in sorted_durs])

        # Dibujar banda (FillBetweenItem)
        curve_low = pg.PlotCurveItem(xs_log, ys_low, pen=pg.mkPen(None))
        curve_high = pg.PlotCurveItem(xs_log, ys_high, pen=pg.mkPen(None))
        fill = pg.FillBetweenItem(curve_low, curve_high,
                                   brush=pg.mkBrush(QColor(244, 114, 182, 50)))
        pw.addItem(fill)

        # Líneas de banda
        pw.plot(xs_log, ys_low, pen=pg.mkPen("#f9a8d4", width=1,
                style=Qt.PenStyle.DashLine), name="Int inf")
        pw.plot(xs_log, ys_high, pen=pg.mkPen("#f472b6", width=1,
                style=Qt.PenStyle.DashLine), name="Int sup")

        # Curva MMP (referencia para las bandas de targeting)
        pw.plot(xs_log, ys_mmp, pen=pg.mkPen("#ef4444", width=2.5), name="MMP")

        # Línea de referencia mFTP/FTP
        if ref_val > 0:
            add_horizontal_line(pw, ref_val, "#FF9149", Qt.PenStyle.DashLine, 1)
            txt = pg.TextItem(f"{ref_label} {round(ref_val)} W",
                              color=_qcolor("#FF9149"))
            txt.setFont(QFont("Segoe UI", 8))
            txt.setPos(xs_log[0], ref_val)
            pw.addItem(txt)

        # Eje X — idéntico a la versión web (5s → 45min)
        x_ticks = [(np.log10(d), _INTV_X_LABELS.get(d, _fmt_duration(d)))
                    for d in _INTV_X_TICKS]
        configure_axis(pw, "bottom", x_ticks)
        pw.setXRange(np.log10(5), np.log10(2700))

        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(_qcolor(COLORS["fg_muted"]))

        # Tooltip — coloreado
        _gm = global_mmp
        def _fmt_it(x, _y):
            t_sec = 10 ** x
            t_str = _fmt_duration(t_sec)
            durs = sorted(_gm.keys())
            closest = min(durs, key=lambda d: abs(d - t_sec))
            pw_val = _gm[closest]
            lo_pct, hi_pct = _band_factors(closest)
            lines = [
                tooltip_header(t_str),
                tooltip_line("MMP", f"{pw_val} W", "#ef4444"),
                tooltip_line("Int sup", f"{round(pw_val * hi_pct)} W", "#f472b6"),
                tooltip_line("Int inf", f"{round(pw_val * lo_pct)} W", "#f9a8d4"),
            ]
            return tooltip_html(lines)
        self._setup_tooltip("interval_targeting", pw, _fmt_it)

        # ── Tarjetas de intervalos sugeridos ──
        layout = self._interval_cards_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols_per_row = 6  # 6 tarjetas por fila
        idx = 0
        for dur_sec, label in _INTERVAL_CARD_DURATIONS:
            mmp_val = global_mmp.get(dur_sec)
            if not mmp_val:
                # Buscar duración más cercana
                durs = sorted(global_mmp.keys())
                closest = min(durs, key=lambda d: abs(d - dur_sec))
                if abs(closest - dur_sec) / max(dur_sec, 1) < 0.25:
                    mmp_val = global_mmp[closest]
            if not mmp_val:
                continue
            lo_pct, hi_pct = _band_factors(dur_sec)
            low_w = round(mmp_val * lo_pct)
            high_w = round(mmp_val * hi_pct)

            card = QFrame()
            card.setStyleSheet(
                "QFrame { background: #1e293b; border: 1px solid #334155;"
                " border-radius: 8px; padding: 8px; }"
            )
            cl = QVBoxLayout(card)
            cl.setContentsMargins(8, 6, 8, 6)
            cl.setSpacing(2)

            lbl_dur = QLabel(label)
            lbl_dur.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lbl_dur.setStyleSheet("color: #e2e8f0;")
            cl.addWidget(lbl_dur, alignment=Qt.AlignmentFlag.AlignCenter)

            lbl_range = QLabel(f"{low_w}–{high_w} W")
            lbl_range.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            lbl_range.setStyleSheet("color: #f472b6;")
            cl.addWidget(lbl_range, alignment=Qt.AlignmentFlag.AlignCenter)

            lbl_mmp = QLabel(f"MMP: {mmp_val} W")
            lbl_mmp.setFont(QFont("Segoe UI", 8))
            lbl_mmp.setStyleSheet("color: #94a3b8;")
            cl.addWidget(lbl_mmp, alignment=Qt.AlignmentFlag.AlignCenter)

            row = idx // cols_per_row
            col = idx % cols_per_row
            layout.addWidget(card, row, col)
            idx += 1

    # ══════════════════════════════════════════════════════════════
    # TAB 6: ENTRENAMIENTOS
    # ══════════════════════════════════════════════════════════════

    def _build_entrenamientos_tab(self) -> None:
        scroll, inner, lay = _scrollable_widget()
        self._tabs.addTab(scroll, "🚴 Entrenamientos")

        # Calendario — estado de mes/año para navegación
        today = date.today()
        self._cal_year = today.year
        self._cal_month = today.month

        lay.addWidget(_section_title(
            "📅", "Calendario de entrenamiento",
        ))
        self._calendar_container = QVBoxLayout()
        lay.addLayout(self._calendar_container)

        # Últimos entrenamientos
        lay.addWidget(_section_title(
            "📋", "Últimos entrenamientos",
            "Tus últimas sesiones procesadas."
        ))
        self._table_recent = QTableWidget()
        self._table_recent.setColumnCount(5)
        self._table_recent.setHorizontalHeaderLabels(
            ["ACTIVIDAD", "FECHA", "DURACIÓN · DISTANCIA", "NP · IF", "TSS"]
        )
        self._table_recent.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table_recent.verticalHeader().setVisible(False)
        self._table_recent.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table_recent.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table_recent.setMinimumHeight(400)
        # Centrar encabezados
        for col in range(self._table_recent.columnCount()):
            hdr = self._table_recent.horizontalHeaderItem(col)
            if hdr:
                hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table_recent.cellDoubleClicked.connect(self._on_activity_double_click)
        lay.addWidget(self._table_recent)

        lay.addStretch()

    def _update_entrenamientos(self) -> None:
        self._update_calendar()
        self._update_recent_activities()

    def _cal_prev_month(self) -> None:
        if self._cal_month == 1:
            self._cal_month = 12
            self._cal_year -= 1
        else:
            self._cal_month -= 1
        self._update_calendar()

    def _cal_next_month(self) -> None:
        if self._cal_month == 12:
            self._cal_month = 1
            self._cal_year += 1
        else:
            self._cal_month += 1
        self._update_calendar()

    def _update_calendar(self) -> None:
        # Clear existing calendar
        while self._calendar_container.count():
            item = self._calendar_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        today = date.today()
        year = self._cal_year
        month = self._cal_month

        # Build calendar widget
        cal_frame = _card_frame()
        cal_lay = QVBoxLayout(cal_frame)
        cal_lay.setContentsMargins(16, 12, 16, 12)
        cal_lay.setSpacing(8)

        month_names = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                       "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

        # Header: ◀  Month Year  ▶
        header = QHBoxLayout()
        header.addStretch()

        btn_style = (
            f"QPushButton {{ background: {COLORS['bg_card']}; color: {COLORS['fg']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 4px; "
            f"font-size: {FONT_SIZE_BASE}; padding: 4px 10px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {COLORS['border']}; }}"
        )
        btn_prev = QPushButton("◀")
        btn_prev.setFixedSize(36, 28)
        btn_prev.setStyleSheet(btn_style)
        btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_prev.clicked.connect(self._cal_prev_month)
        header.addWidget(btn_prev)

        title = QLabel(f"{month_names[month]} {year}")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: 700; "
            f"color: {COLORS['fg']}; background: transparent; border: none;"
        )
        title.setMinimumWidth(160)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(title)

        btn_next = QPushButton("▶")
        btn_next.setFixedSize(36, 28)
        btn_next.setStyleSheet(btn_style)
        btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_next.clicked.connect(self._cal_next_month)
        header.addWidget(btn_next)

        header.addStretch()
        cal_lay.addLayout(header)

        # Subtitle: N actividades · hh:mm:ss · Y TSS en Mes Año
        month_acts = [a for a in self._activities_display
                      if (a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at).year == year
                      and (a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at).month == month]
        total_tss = sum(a.tss or 0 for a in month_acts)
        total_dur = sum(a.duration_sec or 0 for a in month_acts)
        n_acts = len(month_acts)
        # Formato hh:mm:ss
        _h, _rem = divmod(int(total_dur), 3600)
        _m, _s = divmod(_rem, 60)
        dur_str = f"{_h:02d}:{_m:02d}:{_s:02d}" if total_dur > 0 else ""
        subtitle_parts = [f"{n_acts} actividad{'es' if n_acts != 1 else ''}"]
        if dur_str:
            subtitle_parts.append(dur_str)
        subtitle_parts.append(f"{round(total_tss)} TSS en {month_names[month]} {year}")
        subtitle = QLabel(" · ".join(subtitle_parts))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; "
            f"background: transparent; border: none;"
        )
        cal_lay.addWidget(subtitle)

        # Day headers
        days_row = QHBoxLayout()
        days_row.setSpacing(4)
        for d_name in ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]:
            lbl = QLabel(d_name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                f"font-weight: 600; background: transparent; border: none;"
            )
            lbl.setFixedWidth(100)
            days_row.addWidget(lbl)
        cal_lay.addLayout(days_row)

        # Aggregate TSS + duration by date for current month
        # day -> (tss, count, duration_sec)
        tss_by_date: Dict[int, Tuple[float, int, float]] = {}
        for a in self._activities_display:
            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            if d.year == year and d.month == month:
                day = d.day
                existing = tss_by_date.get(day, (0.0, 0, 0.0))
                tss_by_date[day] = (
                    existing[0] + (a.tss or 0),
                    existing[1] + 1,
                    existing[2] + (a.duration_sec or 0),
                )

        # Build calendar grid
        import calendar
        cal = calendar.monthcalendar(year, month)
        for week in cal:
            week_row = QHBoxLayout()
            week_row.setSpacing(4)
            for day in week:
                cell = QFrame()
                cell.setFixedSize(100, 70)
                cell_lay = QVBoxLayout(cell)
                cell_lay.setContentsMargins(4, 4, 4, 4)
                cell_lay.setSpacing(1)

                if day == 0:
                    cell.setStyleSheet("background: transparent; border: none;")
                else:
                    is_today = (day == today.day and month == today.month and year == today.year)
                    has_activity = day in tss_by_date

                    if has_activity:
                        tss_val, count, dur_sec = tss_by_date[day]
                        # Color based on TSS
                        if tss_val >= 200:
                            bg = "rgba(239, 68, 68, 0.3)"
                        elif tss_val >= 150:
                            bg = "rgba(255, 145, 73, 0.3)"
                        elif tss_val >= 100:
                            bg = "rgba(255, 145, 73, 0.2)"
                        elif tss_val >= 60:
                            bg = "rgba(34, 197, 94, 0.25)"
                        else:
                            bg = "rgba(34, 197, 94, 0.15)"
                        border = f"2px solid {COLORS['primary']}" if is_today else f"1px solid {COLORS['border']}"
                    else:
                        bg = "transparent"
                        border = f"2px solid {COLORS['primary']}" if is_today else f"1px solid transparent"

                    cell.setStyleSheet(
                        f"QFrame {{ background: {bg}; border: {border}; "
                        f"border-radius: 6px; }}"
                    )

                    day_lbl = QLabel(str(day))
                    day_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
                    day_lbl.setStyleSheet(
                        f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                        f"background: transparent; border: none;"
                    )
                    cell_lay.addWidget(day_lbl)

                    if has_activity:
                        tss_val, count, dur_sec = tss_by_date[day]
                        tss_lbl = QLabel(f"{round(tss_val)} TSS")
                        tss_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        tss_lbl.setStyleSheet(
                            f"font-size: {FONT_SIZE_SM}; font-weight: 700; "
                            f"color: {COLORS['fg']}; background: transparent; border: none;"
                        )
                        cell_lay.addWidget(tss_lbl)

                        # Duration below TSS
                        dur_str = _fmt_duration(dur_sec)
                        dur_lbl = QLabel(dur_str)
                        dur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        dur_lbl.setStyleSheet(
                            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                            f"background: transparent; border: none;"
                        )
                        cell_lay.addWidget(dur_lbl)

                        # Tooltip with details
                        tip_lines = [
                            f"{day} {month_names[month]}",
                            f"TSS: {round(tss_val)}",
                            f"Duración: {dur_str}",
                        ]
                        if count > 1:
                            tip_lines.append(f"Actividades: {count}")
                        cell.setToolTip("\n".join(tip_lines))
                    cell_lay.addStretch()

                week_row.addWidget(cell)
            cal_lay.addLayout(week_row)

        # TSS legend
        legend_row = QHBoxLayout()
        legend_row.addStretch()
        for label, color in [("<60", "rgba(34, 197, 94, 0.15)"), ("60", "rgba(34, 197, 94, 0.25)"),
                              ("100", "rgba(255, 145, 73, 0.2)"), ("150", "rgba(255, 145, 73, 0.3)"),
                              ("200+", "rgba(239, 68, 68, 0.3)")]:
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent; border: none;")
            legend_row.addWidget(dot)
            txt = QLabel(label)
            txt.setStyleSheet(f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; background: transparent; border: none;")
            legend_row.addWidget(txt)
        cal_lay.addLayout(legend_row)

        self._calendar_container.addWidget(cal_frame)

    def _update_recent_activities(self) -> None:
        table = self._table_recent
        recent = self._activities_display[:20]  # top 20 most recent
        table.setRowCount(len(recent))

        _center = Qt.AlignmentFlag.AlignCenter

        for i, a in enumerate(recent):
            # Activity name (left-aligned)
            name_item = QTableWidgetItem(f"  🚴 {a.display_name}")
            table.setItem(i, 0, name_item)

            # Date
            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            date_str = f"{d.day:02d} {_MONTH_SHORT[d.month]} {d.year}"
            date_item = QTableWidgetItem(date_str)
            date_item.setTextAlignment(_center)
            table.setItem(i, 1, date_item)

            # Duration + distance
            dur = _fmt_duration(a.duration_sec)
            dist = f"{a.distance_km:.1f} km" if a.distance_km else "—"
            dur_item = QTableWidgetItem(f"{dur} · {dist}")
            dur_item.setTextAlignment(_center)
            table.setItem(i, 2, dur_item)

            # NP + IF
            np_val = f"{round(a.normalized_power)} W" if a.normalized_power else "—"
            if_val = f"{a.intensity_factor:.2f}" if a.intensity_factor else "—"
            np_item = QTableWidgetItem(f"NP {np_val}  IF {if_val}")
            np_item.setTextAlignment(_center)
            table.setItem(i, 3, np_item)

            # TSS
            tss_val = f"{round(a.tss)}" if a.tss else "—"
            tss_item = QTableWidgetItem(f"TSS {tss_val}")
            tss_item.setTextAlignment(_center)
            if a.tss:
                if a.tss >= 200:
                    tss_item.setForeground(QColor(COLORS["destructive"]))
                elif a.tss >= 100:
                    tss_item.setForeground(QColor(COLORS["primary"]))
                else:
                    tss_item.setForeground(QColor(COLORS["fg_muted"]))
            table.setItem(i, 4, tss_item)

    def _on_activity_double_click(self, row: int, _col: int) -> None:
        """Abre detalle de la actividad al hacer doble clic."""
        recent = self._activities_display[:20]
        if 0 <= row < len(recent):
            self.open_activity.emit(recent[row].id)