"""Vista de Resistencia a la Fatiga (Fatigue Resistance Index).

Gráfico de scatter + tendencia, tarjetas resumen, tabla de actividades
y texto explicativo.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from db.engine import get_session
from db.models import Activity
from calc.fatigue_resistance import calc_fatigue_resistance, classify_fr
from ui.theme import COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_TITLE
from ui.charts.chart_utils import (
    make_plot, _qcolor, attach_tooltip, tooltip_html,
    tooltip_header, tooltip_line, date_to_ts, make_date_ticks,
    add_horizontal_band, add_horizontal_line,
)


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
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    val = QLabel(value)
    val.setStyleSheet(f"font-size: 26px; font-weight: 700; color: {color}; border: none;")
    val.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(val)
    if sub:
        s = QLabel(sub)
        s.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_muted']}; border: none;")
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)
    return card


def _fr_color(classification: str) -> str:
    return {
        "excellent": "#22c55e",
        "good": "#84cc16",
        "normal": "#eab308",
        "moderate_fade": "#f97316",
        "significant_fade": "#ef4444",
    }.get(classification, COLORS["fg_dim"])


def _format_duration(sec: int) -> str:
    h = sec // 3600
    m = (sec % 3600) // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


class FatigueResistanceView(QWidget):
    """Vista de resistencia a la fatiga."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fr_data: List[dict] = []
        self._tooltip: Optional[object] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll, inner, lay = _scrollable()
        root.addWidget(scroll)

        lay.addWidget(_section_title(
            "📉", "Resistencia a la Fatiga",
            "Fatigue Resistance Index · Ratio NP segunda mitad / primera mitad"
        ))

        # Summary cards
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        lay.addLayout(self._cards_row)

        # Chart
        lay.addWidget(_section_title("📈", "Evolución temporal",
            "Índice de resistencia a la fatiga por actividad con línea de tendencia"))
        self._chart = make_plot(height=350)
        lay.addWidget(self._chart)

        # Table
        lay.addWidget(_section_title("📋", "Últimas actividades"))
        self._table = self._make_table()
        lay.addWidget(self._table)

        # Explanation
        lay.addWidget(self._make_explanation())
        lay.addStretch()

        self._refresh_data()

    def _make_table(self) -> QTableWidget:
        tbl = QTableWidget()
        tbl.setColumnCount(6)
        tbl.setHorizontalHeaderLabels([
            "Fecha", "Duración", "NP 1ª mitad", "NP 2ª mitad", "FR", "Estado",
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
            ("El <b>Fatigue Resistance Index (FR)</b> mide tu capacidad para mantener la potencia "
             "durante una actividad. Se calcula dividiendo la <b>Potencia Normalizada de la segunda "
             "mitad</b> entre la <b>primera mitad</b>."),
            "• <b>≥ 0.95</b> — Excelente: mantuviste o mejoraste la potencia",
            "• <b>0.90 – 0.95</b> — Buena: caída mínima, buen pacing",
            "• <b>0.85 – 0.90</b> — Normal: caída moderada típica",
            "• <b>0.80 – 0.85</b> — Fade moderado: necesitas mejorar resistencia o pacing",
            "• <b>< 0.80</b> — Fade significativo: revisa nutrición, hidratación y estrategia de ritmo",
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
        with get_session() as session:
            acts = (
                session.query(Activity)
                .filter(Activity.tss.isnot(None))
                .order_by(Activity.started_at.asc())
                .all()
            )
            session.expunge_all()

        results = []
        for a in acts:
            samples = a.get_samples()
            if not samples:
                continue
            power_series = [s.get("p", 0) or 0 for s in samples]
            # Each sample is ~5s; expand to approximate 1Hz for NP calculation
            expanded = []
            for val in power_series:
                expanded.extend([val] * 5)
            fr = calc_fatigue_resistance(expanded)
            if fr.fr_index is None:
                continue

            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            results.append({
                "id": a.id,
                "date": d.isoformat(),
                "date_label": f"{d.day:02d}/{d.month:02d}/{d.year}",
                "duration_sec": a.duration_sec or 0,
                "fr_index": fr.fr_index,
                "np_first": fr.np_first,
                "np_second": fr.np_second,
                "classification": fr.classification,
                "class_label": fr.class_label,
            })

        self._fr_data = results
        self._update_cards()
        self._draw_chart()
        self._fill_table()

    # ── Cards ──

    def _update_cards(self) -> None:
        while self._cards_row.count():
            item = self._cards_row.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        count = len(self._fr_data)
        avg_fr = sum(r["fr_index"] for r in self._fr_data) / count if count else None
        last_fr = self._fr_data[-1]["fr_index"] if self._fr_data else None

        avg_cls, avg_label = classify_fr(avg_fr)
        last_cls, last_label = classify_fr(last_fr)

        self._cards_row.addWidget(_stat_card(
            "Actividades analizadas", str(count), COLORS["fg"]
        ))
        self._cards_row.addWidget(_stat_card(
            "FR promedio",
            f"{avg_fr:.3f}" if avg_fr is not None else "—",
            _fr_color(avg_cls), avg_label,
        ))
        self._cards_row.addWidget(_stat_card(
            "Último FR",
            f"{last_fr:.3f}" if last_fr is not None else "—",
            _fr_color(last_cls), last_label,
        ))

    # ── Chart ──

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

        if not self._fr_data:
            txt = pg.TextItem("Sin datos de resistencia a la fatiga", color=QColor(COLORS["fg_muted"]))
            txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(txt)
            txt.setPos(0, 0.9)
            return

        n = len(self._fr_data)
        x = np.arange(n, dtype=float)
        y = np.array([r["fr_index"] for r in self._fr_data])
        colors = [_fr_color(r["classification"]) for r in self._fr_data]

        # Reference bands
        bands = [
            (0.95, 1.15, "#22c55e", 15),
            (0.90, 0.95, "#84cc16", 15),
            (0.85, 0.90, "#eab308", 15),
            (0.80, 0.85, "#f97316", 15),
            (0.60, 0.80, "#ef4444", 15),
        ]
        for y1, y2, clr, alpha in bands:
            add_horizontal_band(pw, y1, y2, clr, alpha)

        # Reference lines
        add_horizontal_line(pw, 1.0, "#22c55e", Qt.PenStyle.DashLine)
        add_horizontal_line(pw, 0.95, "#84cc16", Qt.PenStyle.DashDotLine)
        add_horizontal_line(pw, 0.85, "#f97316", Qt.PenStyle.DashDotLine)

        # Scatter points
        spots = [
            {"pos": (i, y[i]), "brush": QColor(colors[i]), "pen": pg.mkPen("#ffffff", width=1.5), "size": 10}
            for i in range(n)
        ]
        scatter = pg.ScatterPlotItem(spots=spots)
        pw.addItem(scatter)

        # Moving average trend line
        window = min(5, n)
        if n >= 2:
            trend = np.convolve(y, np.ones(window) / window, mode="valid")
            tx = x[window - 1:]
            trend_line = pg.PlotCurveItem(
                tx, trend,
                pen=pg.mkPen(color="#8b5cf6", width=2, style=Qt.PenStyle.DashLine),
            )
            pw.addItem(trend_line)

        # Axes
        pw.setYRange(0.60, 1.15)
        pw.setXRange(-0.5, n - 0.5)

        tick_labels = []
        for r in self._fr_data:
            parts = r["date"].split("-")
            tick_labels.append(f"{parts[2]}/{parts[1]}")
        step = max(1, n // 12)
        ticks = [(i, tick_labels[i]) for i in range(0, n, step)]
        pw.getAxis("bottom").setTicks([ticks])

        # Legend
        legend_items = [
            ("#8b5cf6", "Tendencia"),
        ]
        for i, (clr, lbl) in enumerate(legend_items):
            t = pg.TextItem(f"■ {lbl}", color=QColor(clr))
            t.setFont(QFont("Segoe UI", 8))
            t.setPos(0, 1.13 - i * 0.04)
            pw.addItem(t, ignoreBounds=True)

        # Tooltip
        data_ref = self._fr_data
        def _fmt(xv, yv):
            idx = int(round(xv))
            if idx < 0 or idx >= len(data_ref):
                return ""
            r = data_ref[idx]
            lines = [
                tooltip_header(r["date_label"]),
                tooltip_line("FR", f"{r['fr_index']:.3f} ({r['class_label']})", _fr_color(r["classification"])),
            ]
            if r["np_first"] is not None and r["np_second"] is not None:
                lines.append(tooltip_line("NP", f"{r['np_first']}W → {r['np_second']}W"))
            lines.append(tooltip_line("Duración", _format_duration(r["duration_sec"])))
            return tooltip_html(lines)

        self._tooltip = attach_tooltip(pw, _fmt, snap_xs=x.astype(float))

    # ── Table ──

    def _fill_table(self) -> None:
        tbl = self._table
        rows = list(reversed(self._fr_data))[:20]
        tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            tbl.setRowHeight(i, 36)
            # Fecha
            tbl.setItem(i, 0, QTableWidgetItem(r["date_label"]))
            # Duración
            di = QTableWidgetItem(_format_duration(r["duration_sec"]))
            di.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 1, di)
            # NP 1ª
            np1 = QTableWidgetItem(f"{r['np_first']}W" if r["np_first"] else "—")
            np1.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 2, np1)
            # NP 2ª
            np2 = QTableWidgetItem(f"{r['np_second']}W" if r["np_second"] else "—")
            np2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 3, np2)
            # FR
            fr_item = QTableWidgetItem(f"{r['fr_index']:.3f}")
            fr_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            fr_item.setForeground(QColor(_fr_color(r["classification"])))
            fr_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 4, fr_item)
            # Estado
            si = QTableWidgetItem(r["class_label"])
            si.setForeground(QColor(_fr_color(r["classification"])))
            si.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 5, si)
