"""Vista de Recuperación Estimada.

Gauge de estado, métricas CTL/ATL/TSB, gráfico de proyección TSB,
tabla de recuperación por actividad y texto explicativo.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from db.engine import get_session
from db.models import Activity
from calc.fitness import build_fitness_series, last_real_point
from calc.recovery import project_recovery, estimate_activity_recovery
from ui.theme import COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_TITLE
from ui.charts.chart_utils import (
    make_plot, _qcolor, attach_tooltip, tooltip_html,
    tooltip_header, tooltip_line, add_horizontal_line,
    add_horizontal_band,
)

_MONTH_SHORT = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic",
}


def _scrollable():
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
    h.setStyleSheet(f"font-size: {FONT_SIZE_TITLE}; font-weight: 700; color: {COLORS['fg']};")
    box.addWidget(h)
    if subtitle:
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        s.setWordWrap(True)
        box.addWidget(s)
    return frame


def _format_recovery_time(hours: Optional[int]) -> str:
    if hours is None:
        return "¡Ya estás fresco!"
    if hours < 1:
        return "Menos de 1 hora"
    if hours < 24:
        return f"~{hours}h"
    days = hours // 24
    remain_h = hours % 24
    if remain_h == 0:
        return f"{days} día{'s' if days > 1 else ''}"
    return f"{days}d {remain_h}h"


def _format_duration(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _status_color(status: str) -> str:
    return {
        "fresh": "#22c55e",
        "recovering": "#eab308",
        "fatigued": "#ef4444",
    }.get(status, COLORS["fg_dim"])


class RecoveryGaugeWidget(QWidget):
    """Visual gauge for recovery status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = "fresh"
        self._emoji = "🟢"
        self._label = "Fresco"
        self._hours = None
        self._tsb = 0.0
        self.setFixedSize(240, 170)

    def set_data(self, status: str, emoji: str, label: str,
                 hours: Optional[int], tsb: float):
        self._status = status
        self._emoji = emoji
        self._label = label
        self._hours = hours
        self._tsb = tsb
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, 70
        r = 50

        # Circle background
        painter.setPen(QPen(QColor(COLORS["bg_secondary"]), 6))
        painter.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))

        # Colored arc (proportion based on status)
        color = _status_color(self._status)
        pct = 1.0 if self._status == "fresh" else (0.6 if self._status == "recovering" else 0.3)
        pen = QPen(QColor(color), 6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = int(pct * 360 * 16)
        painter.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r), 90 * 16, -span)

        # Emoji
        painter.setPen(QColor(COLORS["fg"]))
        font_emoji = QFont("Segoe UI", 28)
        painter.setFont(font_emoji)
        painter.drawText(QRectF(0, cy - 22, w, 44), Qt.AlignmentFlag.AlignCenter, self._emoji)

        # Label
        font_lbl = QFont("Segoe UI", 14, QFont.Weight.Bold)
        painter.setFont(font_lbl)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(0, cy + r + 6, w, 24), Qt.AlignmentFlag.AlignCenter, self._label)

        # Recovery time
        font_sm = QFont("Segoe UI", 11)
        painter.setFont(font_sm)
        painter.setPen(QColor(COLORS["fg_muted"]))
        painter.drawText(QRectF(0, cy + r + 28, w, 20), Qt.AlignmentFlag.AlignCenter,
            _format_recovery_time(self._hours))

        painter.end()


class RecoveryView(QWidget):
    """Vista de recuperación estimada."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proj_tooltip: Optional[object] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll, inner, lay = _scrollable()
        root.addWidget(scroll)

        lay.addWidget(_section_title(
            "🔋", "Recuperación Estimada",
            "Proyección de tu estado de recuperación basada en el modelo CTL/ATL/TSB"
        ))

        # Top row: gauge + metrics
        top_row = QHBoxLayout()
        top_row.setSpacing(16)

        # Gauge card
        gauge_card = QFrame()
        gauge_card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        gc_lay = QVBoxLayout(gauge_card)
        gc_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        gc_title = QLabel("⏰  Estado de Recuperación")
        gc_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        gc_lay.addWidget(gc_title)
        gc_sub = QLabel("Tiempo estimado hasta estar fresco (TSB ≥ +5)")
        gc_sub.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
        gc_sub.setWordWrap(True)
        gc_lay.addWidget(gc_sub)

        self._gauge = RecoveryGaugeWidget()
        gc_lay.addWidget(self._gauge, alignment=Qt.AlignmentFlag.AlignCenter)

        self._advice_label = QLabel()
        self._advice_label.setWordWrap(True)
        self._advice_label.setStyleSheet(
            f"font-size: 12px; color: {COLORS['fg_muted']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 8px; padding: 12px; background: {COLORS['bg_secondary']};"
        )
        gc_lay.addWidget(self._advice_label)

        top_row.addWidget(gauge_card, stretch=1)

        # Metrics card
        metrics_card = QFrame()
        metrics_card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        mc_lay = QVBoxLayout(metrics_card)
        mc_title = QLabel("📈  Métricas Actuales")
        mc_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        mc_lay.addWidget(mc_title)
        mc_sub = QLabel("Valores de fitness y fatiga en este momento")
        mc_sub.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
        mc_lay.addWidget(mc_sub)
        mc_lay.addSpacing(8)

        self._metrics_container = QVBoxLayout()
        self._metrics_container.setSpacing(8)
        mc_lay.addLayout(self._metrics_container)
        mc_lay.addStretch()

        top_row.addWidget(metrics_card, stretch=1)
        lay.addLayout(top_row)

        # Projection chart
        lay.addWidget(_section_title("📉", "Proyección de TSB (próximos 14 días)",
            "Simulación asumiendo descanso completo. La línea verde marca TSB = +5 (fresco)"))
        self._proj_chart = make_plot(height=280)
        lay.addWidget(self._proj_chart)

        # Activity recovery table
        lay.addWidget(_section_title("📋", "Recuperación por Actividad",
            "Tiempo de recuperación estimado para las últimas sesiones"))
        self._table = self._make_table()
        lay.addWidget(self._table)

        # Explanation
        lay.addWidget(self._make_explanation())
        lay.addStretch()

        self._refresh_data()

    def _make_metric_row(self, icon: str, label: str, value: str,
                         sub: str, highlight: str = "") -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 8px; padding: 10px 14px; }}"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"font-size: 16px; border: none;")
        rl.addWidget(icon_lbl)
        left = QVBoxLayout()
        left.setSpacing(1)
        ll = QLabel(label)
        ll.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLORS['fg']}; border: none;")
        left.addWidget(ll)
        sl = QLabel(sub)
        sl.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_muted']}; border: none;")
        left.addWidget(sl)
        rl.addLayout(left)
        rl.addStretch()
        vl = QLabel(value)
        color = highlight if highlight else COLORS["fg"]
        vl.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {color}; border: none;")
        rl.addWidget(vl)
        return row

    def _make_table(self) -> QTableWidget:
        tbl = QTableWidget()
        tbl.setColumnCount(5)
        tbl.setHorizontalHeaderLabels([
            "Actividad", "Fecha", "TSS", "Duración", "Recuperación",
        ])
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

        title = QLabel("¿Cómo se calcula?")
        title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        lay.addWidget(title)

        texts = [
            ("La <b>Recuperación Estimada</b> usa el modelo Banister de CTL/ATL/TSB. "
             "Proyecta hacia adelante asumiendo descanso completo (TSS = 0 cada día):"),
            "• <b>ATL (fatiga aguda)</b> decae con constante τ = 7 días → baja rápidamente sin carga",
            "• <b>CTL (fitness crónico)</b> decae con τ = 42 días → se mantiene más estable",
            "• Como ATL baja más rápido que CTL, el <b>TSB sube</b> hasta cruzar el umbral de frescura (+5)",
            "",
            "🟢 TSB ≥ +5 = Fresco · 🟡 -10 a +5 = Recuperando · 🔴 &lt; -10 = Fatigado",
            "",
            "La recuperación por actividad estima el impacto individual de cada sesión sobre tu estado previo.",
        ]
        for t in texts:
            lbl = QLabel(t)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-size: 14px; color: {COLORS['fg_muted']}; border: none; line-height: 1.6;")
            lay.addWidget(lbl)
        return card

    # ── Data ──

    def refresh(self) -> None:
        self._refresh_data()

    def _refresh_data(self) -> None:
        today = date.today()
        cutoff = datetime(today.year, today.month, today.day) - timedelta(days=365)

        with get_session() as session:
            acts = (
                session.query(Activity)
                .filter(Activity.started_at >= cutoff)
                .order_by(Activity.started_at.asc())
                .all()
            )
            session.expunge_all()

        if not acts:
            self._show_no_data()
            return

        # Build fitness series
        act_dicts = [{"started_at": a.started_at, "tss": a.tss or 0} for a in acts]
        series = build_fitness_series(act_dicts, cutoff.date(), today)
        lrp = last_real_point(series)

        if lrp is None:
            self._show_no_data()
            return

        # Project recovery
        recovery = project_recovery(lrp.ctl, lrp.atl)

        # Update gauge
        self._gauge.set_data(
            recovery.status, recovery.status_emoji, recovery.status_label,
            recovery.hours_to_recovery, recovery.current_tsb,
        )
        self._advice_label.setText(f"💡 {recovery.advice}")

        # Update metrics
        while self._metrics_container.count():
            item = self._metrics_container.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        self._metrics_container.addWidget(self._make_metric_row(
            "⚡", "CTL (Fitness)", f"{recovery.current_ctl:.1f}",
            "Carga crónica de entrenamiento", "#60a5fa",
        ))
        self._metrics_container.addWidget(self._make_metric_row(
            "🏃", "ATL (Fatiga)", f"{recovery.current_atl:.1f}",
            "Carga aguda de entrenamiento", "#f97316",
        ))
        tsb = recovery.current_tsb
        tsb_color = "#22c55e" if tsb >= 5 else "#eab308" if tsb >= -10 else "#ef4444"
        tsb_str = f"{'+' if tsb > 0 else ''}{tsb:.1f}"
        self._metrics_container.addWidget(self._make_metric_row(
            "📈", "TSB (Forma)", tsb_str,
            "Balance de estrés del entrenamiento", tsb_color,
        ))
        self._metrics_container.addWidget(self._make_metric_row(
            "⏰", "Tiempo hasta recuperación",
            _format_recovery_time(recovery.hours_to_recovery),
            "Asumiendo descanso completo (TSS=0)" if recovery.hours_to_recovery else "Listo para entrenar a tope",
            "#a855f7",
        ))

        # Draw projection chart
        self._draw_projection(recovery.projection)

        # Activity recovery table
        self._fill_activity_table(acts, series)

    def _show_no_data(self) -> None:
        self._gauge.set_data("fresh", "❓", "Sin datos", None, 0)
        self._advice_label.setText("Importa actividades para calcular tu recuperación.")

    # ── Projection Chart ──

    def _draw_projection(self, projection) -> None:
        pw = self._proj_chart
        if self._proj_tooltip is not None:
            self._proj_tooltip.clear()
            self._proj_tooltip = None
        pw.clear()
        if pw.plotItem.legend is not None:
            pw.plotItem.legend.scene().removeItem(pw.plotItem.legend)
            pw.plotItem.legend = None
        pw.viewport().setMouseTracking(True)

        if not projection:
            return

        n = len(projection)
        x = np.arange(n, dtype=float)
        tsb_vals = np.array([p.tsb for p in projection])
        ctl_vals = np.array([p.ctl for p in projection])
        atl_vals = np.array([p.atl for p in projection])

        # TSB line
        tsb_line = pg.PlotCurveItem(x, tsb_vals,
            pen=pg.mkPen(color="#22c55e", width=2.5))
        pw.addItem(tsb_line)

        # CTL line
        ctl_line = pg.PlotCurveItem(x, ctl_vals,
            pen=pg.mkPen(color="#ff9149", width=1.5, style=Qt.PenStyle.DashLine))
        pw.addItem(ctl_line)

        # ATL line
        atl_line = pg.PlotCurveItem(x, atl_vals,
            pen=pg.mkPen(color="#ff6363", width=1.5, style=Qt.PenStyle.DashLine))
        pw.addItem(atl_line)

        # Fresh threshold
        add_horizontal_line(pw, 5.0, "#22c55e", Qt.PenStyle.DashDotLine)
        add_horizontal_line(pw, 0.0, COLORS["fg_dim"], Qt.PenStyle.DotLine)

        # Band for fresh zone
        add_horizontal_band(pw, 5, max(float(tsb_vals.max()) + 5, 15), "#22c55e", 15)

        # X ticks (days)
        ticks = [(i, f"D+{p.day}") for i, p in enumerate(projection)]
        pw.getAxis("bottom").setTicks([ticks])
        pw.setLabel("left", "TSB")

        # Legend
        for i, (clr, lbl) in enumerate([
            ("#22c55e", "TSB"), ("#ff9149", "CTL"), ("#ff6363", "ATL"),
        ]):
            t = pg.TextItem(f"■ {lbl}", color=QColor(clr))
            t.setFont(QFont("Segoe UI", 8))
            max_y = float(max(tsb_vals.max(), ctl_vals.max(), atl_vals.max()))
            t.setPos(n - 3 + i * 0, max_y + 3 - i * 3)
            pw.addItem(t, ignoreBounds=True)

        # Tooltip
        proj_ref = projection
        def _fmt(xv, yv):
            idx = int(round(xv))
            if idx < 0 or idx >= len(proj_ref):
                return ""
            p = proj_ref[idx]
            lines = [
                tooltip_header(f"Día +{p.day} ({p.date})"),
                tooltip_line("CTL", f"{p.ctl:.1f}", "#ff9149"),
                tooltip_line("ATL", f"{p.atl:.1f}", "#ff6363"),
                tooltip_line("TSB", f"{p.tsb:+.1f}", "#22c55e"),
            ]
            return tooltip_html(lines)

        self._proj_tooltip = attach_tooltip(pw, _fmt, snap_xs=x)

    # ── Activity Recovery Table ──

    def _fill_activity_table(self, acts: List[Activity], series) -> None:
        tbl = self._table

        # Build CTL/ATL per day from series for each activity
        day_fitness = {}
        for p in series:
            if not p.forecast:
                day_fitness[p.date] = (p.ctl, p.atl)

        recent = [a for a in reversed(acts) if a.tss and a.tss > 10][:15]
        tbl.setRowCount(len(recent))

        for i, a in enumerate(recent):
            tbl.setRowHeight(i, 36)
            name = a.display_name
            if len(name) > 30:
                name = name[:27] + "..."
            tbl.setItem(i, 0, QTableWidgetItem(name))

            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            d_str = f"{d.day:02d} {_MONTH_SHORT[d.month]}"
            date_item = QTableWidgetItem(d_str)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            date_item.setForeground(QColor(COLORS["fg_muted"]))
            tbl.setItem(i, 1, date_item)

            tss_item = QTableWidgetItem(f"{a.tss:.0f}")
            tss_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tss_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 2, tss_item)

            dur_item = QTableWidgetItem(_format_duration(a.duration_sec or 0))
            dur_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dur_item.setForeground(QColor(COLORS["fg_muted"]))
            tbl.setItem(i, 3, dur_item)

            # Estimate recovery
            d_iso = d.isoformat()
            # Get CTL/ATL from day before activity
            prev_day = (d - timedelta(days=1)).isoformat()
            ctl_before, atl_before = day_fitness.get(prev_day, (0.0, 0.0))
            rec_hours = estimate_activity_recovery(a.tss or 0, ctl_before, atl_before)

            rec_text = _format_recovery_time(rec_hours if rec_hours > 0 else None)
            rec_item = QTableWidgetItem(rec_text)
            rec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Color based on hours
            if rec_hours >= 72:
                rec_item.setForeground(QColor("#ef4444"))
            elif rec_hours >= 48:
                rec_item.setForeground(QColor("#f97316"))
            elif rec_hours >= 24:
                rec_item.setForeground(QColor("#eab308"))
            else:
                rec_item.setForeground(QColor("#22c55e"))
            rec_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 4, rec_item)
