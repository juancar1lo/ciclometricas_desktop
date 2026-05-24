"""Vista de Monotonía — Modelo de Foster (1998).

Muestra gráfico de barras (carga semanal) + línea (monotonía),
tabla detallada con TSS diario y texto explicativo.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from db.engine import get_session
from db.models import Activity
from calc.monotony import calc_week_monotony, classify_monotony, classify_strain
from ui.theme import COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_TITLE, FONT_SIZE_XS
from ui.charts.chart_utils import make_plot, _qcolor, attach_tooltip, tooltip_html, tooltip_header, tooltip_line


_MONTHS_MAP = {0: 3, 1: 6, 2: 12, 3: 24}
_DAY_LABELS = ["L", "M", "X", "J", "V", "S", "D"]
_MONTH_SHORT = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic",
}

COLOR_LOAD = "#60a5fa"      # blue-400
COLOR_MONOTONY = "#f59e0b"  # amber-500


def _scrollable() -> Tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(24, 20, 24, 20)
    lay.setSpacing(16)
    scroll.setWidget(inner)
    return scroll, inner, lay


def _section_title(icon: str, title: str, subtitle: str = "") -> QFrame:
    frame = QFrame()
    frame.setStyleSheet("QFrame { background: transparent; }")
    box = QVBoxLayout(frame)
    box.setContentsMargins(0, 8, 0, 0)
    box.setSpacing(2)
    h = QLabel(f"{icon}  {title}")
    h.setStyleSheet(
        f"font-size: {FONT_SIZE_TITLE}; font-weight: 700; color: {COLORS['fg']};"
    )
    box.addWidget(h)
    if subtitle:
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        s.setWordWrap(True)
        box.addWidget(s)
    return frame


def _stat_card(label: str, value: str, color: str, sub: str = "") -> QFrame:
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
        f"border-radius: 10px; padding: 14px; }}"
    )
    lay = QVBoxLayout(card)
    lay.setContentsMargins(10, 8, 10, 8)
    lay.setSpacing(2)
    lbl = QLabel(label)
    lbl.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_muted']}; text-transform: uppercase; border: none;")
    lay.addWidget(lbl)
    val = QLabel(value)
    val.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {color}; border: none;")
    lay.addWidget(val)
    if sub:
        s = QLabel(sub)
        s.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_muted']}; border: none;")
        lay.addWidget(s)
    return card


def _class_color(classification: str) -> str:
    return {
        "low": "#22c55e",
        "moderate": "#f59e0b",
        "high": "#f97316",
        "very_high": "#ef4444",
    }.get(classification, COLORS["fg_dim"])


class MonotonyView(QWidget):
    """Vista de monotonía del entrenamiento."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._weeks: List[dict] = []
        self._tooltip: Optional[object] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll, inner, lay = _scrollable()
        root.addWidget(scroll)

        lay.addWidget(_section_title(
            "❤️", "Monotonía",
            "Índice de monotonía de Foster · Variabilidad del entrenamiento"
        ))

        # Controls
        ctrl = QHBoxLayout()
        self._months_combo = QComboBox()
        self._months_combo.addItems([
            "Últimos 3 meses", "Últimos 6 meses",
            "Último año", "Últimos 2 años",
        ])
        self._months_combo.setCurrentIndex(1)
        self._months_combo.setMinimumWidth(160)
        self._months_combo.currentIndexChanged.connect(self._on_months_changed)
        ctrl.addWidget(self._months_combo)
        ctrl.addStretch()
        lay.addLayout(ctrl)

        # Summary cards
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        lay.addLayout(self._cards_row)

        # Chart
        self._chart = make_plot(height=340)
        lay.addWidget(self._chart)

        # Reference legend
        legend_row = QHBoxLayout()
        legend_row.setSpacing(16)
        for color, label in [(COLOR_LOAD, "Carga semanal (TSS)"), (COLOR_MONOTONY, "Monotonía")]:
            dot = QLabel("■")
            dot.setStyleSheet(f"color: {color}; font-size: 12px; border: none;")
            txt = QLabel(label)
            txt.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
            pair = QHBoxLayout()
            pair.setSpacing(4)
            pair.addWidget(dot)
            pair.addWidget(txt)
            legend_row.addLayout(pair)
        legend_row.addStretch()
        lay.addLayout(legend_row)

        # Table
        lay.addWidget(_section_title("📋", "Detalle semanal", "TSS diario y monotonía por semana"))
        self._table = self._make_table()
        lay.addWidget(self._table)

        # Explanation
        lay.addWidget(self._make_explanation())

        lay.addStretch()
        self._refresh_data()

    def _make_table(self) -> QTableWidget:
        cols = ["Semana", "Carga"] + _DAY_LABELS + ["Días", "Mon.", "Estado"]
        tbl = QTableWidget()
        tbl.setColumnCount(len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setStyleSheet(
            f"QTableWidget {{ background: {COLORS['bg_card']}; color: {COLORS['fg']}; "
            f"gridline-color: {COLORS['bg_hover']}; border: 1px solid {COLORS['bg_hover']}; "
            f"border-radius: 8px; font-size: {FONT_SIZE_SM}; }}"
            f"QHeaderView::section {{ background: {COLORS['bg_secondary']}; "
            f"color: {COLORS['fg_muted']}; font-weight: 600; padding: 6px; "
            f"border: none; border-bottom: 1px solid {COLORS['bg_hover']}; }}"
        )
        return tbl

    def _make_explanation(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setSpacing(8)

        title = QLabel("📖  Cómo leer esta métrica")
        title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        lay.addWidget(title)

        texts = [
            (f"El modelo de <b>Foster (1998)</b> mide la <b>variabilidad</b> de tu "
             f"entrenamiento semanal, algo que el modelo PMC (CTL/ATL/TSB) no captura."),
            (f"<span style='color:{COLOR_MONOTONY};font-weight:600'>Monotonía = Media / Desv. Estándar</span><br/>"
             f"Mide cuán uniforme es tu entrenamiento. Valores altos (&gt; 2.0) indican poca variabilidad."),
            (f"<span style='color:#22c55e'>Monotonía &lt; 1.5 — Buena variabilidad.</span> "
             f"Entrenamientos variados: días duros + días suaves + descanso. Ideal."),
            (f"<span style='color:#ef4444'>Monotonía &gt; 2.0 — ⚠️ Riesgo.</span> "
             f"Todos los días con TSS similar. Añade días de descanso o varía la intensidad."),
            (f"<b>Consejo:</b> Alterna días de alta carga (intervalos, series) con días "
             f"de recuperación activa (Z1-Z2) y al menos un día de descanso completo por semana."),
        ]
        for t in texts:
            lbl = QLabel(t)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-size: 14px; color: {COLORS['fg_muted']}; border: none; line-height: 1.6;")
            lay.addWidget(lbl)

        return card

    # ── Data ─────────────────────────────────────────

    def _build_data(self, months: int):
        today = date.today()
        cutoff = datetime(today.year, today.month, today.day) - timedelta(days=months * 30)

        with get_session() as session:
            acts = (
                session.query(Activity)
                .filter(Activity.started_at >= cutoff)
                .order_by(Activity.started_at.asc())
                .all()
            )
            session.expunge_all()

        # Aggregate daily TSS
        daily: Dict[date, float] = defaultdict(float)
        for a in acts:
            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            daily[d] += a.tss or 0

        # Build ISO weeks
        if not acts:
            return []

        first = min(daily.keys())
        last = max(daily.keys())
        # Align to Monday
        first_mon = first - timedelta(days=first.weekday())
        last_mon = last - timedelta(days=last.weekday())

        weeks = []
        cur = first_mon
        while cur <= last_mon:
            iso = cur.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
            sun = cur + timedelta(days=6)
            week_label = f"{cur.day} {_MONTH_SHORT[cur.month]} – {sun.day} {_MONTH_SHORT[sun.month]}"
            daily_tss = [daily.get(cur + timedelta(days=i), 0.0) for i in range(7)]

            result = calc_week_monotony(daily_tss)
            mon_cls, mon_label = classify_monotony(result.monotony)
            strain_cls, strain_label = classify_strain(result.strain)

            weeks.append({
                "week_key": week_key,
                "week_label": week_label,
                "daily_tss": daily_tss,
                "week_load": result.week_load,
                "mean_daily_tss": result.mean_daily_tss,
                "std_daily_tss": result.std_daily_tss,
                "monotony": result.monotony,
                "strain": result.strain,
                "active_days": result.active_days,
                "classification": mon_cls,
                "class_label": mon_label,
                "strain_class": strain_cls,
                "strain_label": strain_label,
            })
            cur += timedelta(days=7)

        return weeks

    # ── Refresh ──────────────────────────────────────

    def refresh(self) -> None:
        self._refresh_data()

    def _refresh_data(self) -> None:
        months = _MONTHS_MAP.get(self._months_combo.currentIndex(), 6)
        self._weeks = self._build_data(months)
        self._update_cards()
        self._draw_chart()
        self._fill_table()

    def _on_months_changed(self, _idx: int = 0) -> None:
        self._refresh_data()

    # ── Cards ────────────────────────────────────────

    def _update_cards(self) -> None:
        while self._cards_row.count():
            item = self._cards_row.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        valid = [w for w in self._weeks if w["monotony"] is not None]
        avg_mon = sum(w["monotony"] for w in valid) / len(valid) if valid else None
        mon_cls, mon_label = classify_monotony(avg_mon)

        self._cards_row.addWidget(_stat_card(
            "Monotonía media",
            f"{avg_mon:.2f}" if avg_mon is not None else "—",
            COLOR_MONOTONY,
            mon_label,
        ))
        self._cards_row.addWidget(_stat_card(
            "Semanas analizadas",
            str(len(valid)),
            COLOR_LOAD,
            "con datos suficientes",
        ))
        self._cards_row.addWidget(_stat_card(
            "Objetivo",
            "< 1.5",
            "#22c55e",
            "monotonía ideal",
        ))

    # ── Chart ────────────────────────────────────────

    def _draw_chart(self) -> None:
        pw = self._chart
        if self._tooltip is not None:
            self._tooltip.clear()
            self._tooltip = None
        pw.clear()
        if pw.plotItem.legend is not None:
            pw.plotItem.legend.scene().removeItem(pw.plotItem.legend)
            pw.plotItem.legend = None
        pw.viewport().setMouseTracking(True)

        if not self._weeks:
            txt = pg.TextItem("Sin datos para el periodo seleccionado", color=QColor(COLORS["fg_muted"]))
            txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(txt)
            txt.setPos(0, 1.5)
            return

        n = len(self._weeks)
        x = np.arange(n)
        loads = np.array([w["week_load"] for w in self._weeks], dtype=float)
        monots = np.array([w["monotony"] if w["monotony"] is not None else np.nan for w in self._weeks])

        # Create second viewbox for dual Y axes
        p1 = pw.plotItem
        p1.setLabels(left="TSS")

        # Add right axis for monotony
        p2 = pg.ViewBox()
        p2.setMouseEnabled(x=False, y=False)
        p2.wheelEvent = lambda ev: ev.ignore()
        p1.showAxis("right")
        p1.scene().addItem(p2)
        p1.getAxis("right").linkToView(p2)
        p2.setXLink(p1)
        p1.getAxis("right").setLabel("Monotonía", color=COLOR_MONOTONY)
        p1.getAxis("right").setTextPen(pg.mkPen(COLOR_MONOTONY))

        def update_views():
            p2.setGeometry(p1.vb.sceneBoundingRect())
            p2.linkedViewChanged(p1.vb, p2.XAxis)
        p1.vb.sigResized.connect(update_views)

        # Horizontal reference bands for monotony
        from ui.charts.chart_utils import add_horizontal_band, add_horizontal_line
        # Danger zone (in p2 viewbox)
        danger_region = pg.LinearRegionItem(
            values=(2.0, 3.5), orientation="horizontal", movable=False,
            brush=_qcolor("#ef4444", 15), pen=pg.mkPen(None),
        )
        p2.addItem(danger_region)
        warn_region = pg.LinearRegionItem(
            values=(1.5, 2.0), orientation="horizontal", movable=False,
            brush=_qcolor("#f59e0b", 15), pen=pg.mkPen(None),
        )
        p2.addItem(warn_region)

        # Reference lines
        line_20 = pg.InfiniteLine(pos=2.0, angle=0,
            pen=pg.mkPen(color="#ef4444", style=Qt.PenStyle.DashLine, width=1))
        p2.addItem(line_20)
        line_15 = pg.InfiniteLine(pos=1.5, angle=0,
            pen=pg.mkPen(color="#f59e0b", style=Qt.PenStyle.DashLine, width=1))
        p2.addItem(line_15)

        # Bars (load) on primary
        bar = pg.BarGraphItem(x=x, height=loads, width=0.6,
            brush=_qcolor(COLOR_LOAD, 150), pen=pg.mkPen(None))
        pw.addItem(bar)

        # Monotony line on secondary
        valid_mask = ~np.isnan(monots)
        if valid_mask.any():
            x_valid = x[valid_mask]
            m_valid = monots[valid_mask]
            line = pg.PlotCurveItem(x_valid, m_valid,
                pen=pg.mkPen(color=COLOR_MONOTONY, width=2.5))
            p2.addItem(line)
            dots = pg.ScatterPlotItem(x_valid, m_valid,
                pen=pg.mkPen(None), brush=_qcolor(COLOR_MONOTONY),
                size=7)
            p2.addItem(dots)

        # Set ranges
        p2.setYRange(0, 3.5)
        max_load = float(np.max(loads)) if len(loads) > 0 else 100
        pw.setYRange(0, max_load * 1.15)
        pw.setXRange(-0.5, n - 0.5)

        # X ticks
        tick_labels = []
        for w in self._weeks:
            wn = w["week_key"].split("-W")[-1] if "-W" in w["week_key"] else w["week_key"]
            tick_labels.append(f"S{wn}")
        ticks = [list(zip(range(n), tick_labels))]
        pw.getAxis("bottom").setTicks(ticks)

        update_views()

        # Tooltip
        weeks_ref = self._weeks
        def _fmt(xv, yv):
            idx = int(round(xv))
            if idx < 0 or idx >= len(weeks_ref):
                return ""
            w = weeks_ref[idx]
            lines = [
                tooltip_header(f"{w['week_key']}  —  {w['week_label']}"),
                tooltip_line("Carga semanal", f"{w['week_load']:.0f} TSS", COLOR_LOAD),
                tooltip_line("Media diaria", f"{w['mean_daily_tss']:.0f} TSS · DE: {w['std_daily_tss']:.1f}"),
                tooltip_line("Días activos", f"{w['active_days']}/7"),
            ]
            if w["monotony"] is not None:
                lines.append(tooltip_line("Monotonía", f"{w['monotony']} — {w['class_label']}", COLOR_MONOTONY))
            # Mini daily
            day_str = "  ".join(
                f"{_DAY_LABELS[i]}:{round(w['daily_tss'][i])}" for i in range(7)
            )
            lines.append(f'<span style="color:{COLORS["fg_dim"]};font-size:9pt">{day_str}</span>')
            return tooltip_html(lines)

        self._tooltip = attach_tooltip(pw, _fmt, snap_xs=x.astype(float))

    # ── Table ────────────────────────────────────────

    def _fill_table(self) -> None:
        tbl = self._table
        rows = list(reversed(self._weeks))
        tbl.setRowCount(len(rows))
        for i, w in enumerate(rows):
            tbl.setRowHeight(i, 36)
            # Week
            item0 = QTableWidgetItem(w["week_label"])
            item0.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 0, item0)
            # Load
            load_item = QTableWidgetItem(f"{w['week_load']:.0f}")
            load_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            load_item.setForeground(QColor(COLOR_LOAD))
            tbl.setItem(i, 1, load_item)
            # Daily TSS (cols 2-8)
            for j, t in enumerate(w["daily_tss"]):
                val = f"{round(t)}" if t > 0 else "·"
                di = QTableWidgetItem(val)
                di.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if t <= 0:
                    di.setForeground(QColor(COLORS["fg_dim"]))
                tbl.setItem(i, 2 + j, di)
            # Active days
            ad = QTableWidgetItem(f"{w['active_days']}/7")
            ad.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ad.setForeground(QColor(COLORS["fg_muted"]))
            tbl.setItem(i, 9, ad)
            # Monotony
            mon_val = f"{w['monotony']}" if w["monotony"] is not None else "—"
            mi = QTableWidgetItem(mon_val)
            mi.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            mi.setForeground(QColor(COLOR_MONOTONY))
            mi.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 10, mi)
            # Estado
            si = QTableWidgetItem(w["class_label"])
            si.setForeground(QColor(_class_color(w["classification"])))
            si.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 11, si)
