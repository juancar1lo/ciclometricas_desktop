"""Vista de Preparación para Competir (Race Readiness Score).

Gauge semicircular con puntuación 0–100, barras de factores,
consejo y texto explicativo.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QConicalGradient
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget, QProgressBar,
)

from db.engine import get_session
from db.models import Activity, ProfileSnapshot
from calc.fitness import build_fitness_series, calc_ramp_rate, last_real_point
from calc.monotony import calc_week_monotony
from calc.race_readiness import calc_race_readiness, RrsInput
from ui.theme import COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_TITLE


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


def _score_color(v: int) -> str:
    if v >= 75:
        return "#22c55e"
    if v >= 50:
        return "#eab308"
    return "#ef4444"


class GaugeWidget(QWidget):
    """Semicircular gauge 0–100."""

    def __init__(self, score: int = 0, level: str = "not_ready", parent=None):
        super().__init__(parent)
        self._score = score
        self._level = level
        self.setFixedSize(240, 150)

    def set_score(self, score: int, level: str):
        self._score = score
        self._level = level
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h - 10
        r = 90

        # Background arc
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        pen_bg = QPen(QColor(COLORS["bg_secondary"]), 14)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 0 * 16, 180 * 16)

        # Filled arc
        color = _score_color(self._score)
        pen_fg = QPen(QColor(color), 14)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        span = int(self._score / 100 * 180 * 16)
        painter.drawArc(rect, 180 * 16, -span)

        # Score text
        painter.setPen(QColor(COLORS["fg"]))
        font_big = QFont("Segoe UI", 32, QFont.Weight.Bold)
        painter.setFont(font_big)
        painter.drawText(QRectF(0, cy - r + 20, w, 50), Qt.AlignmentFlag.AlignCenter, str(self._score))

        font_sm = QFont("Segoe UI", 11)
        painter.setFont(font_sm)
        painter.setPen(QColor(COLORS["fg_muted"]))
        painter.drawText(QRectF(0, cy - r + 58, w, 20), Qt.AlignmentFlag.AlignCenter, "/ 100")

        painter.end()


class ReadinessView(QWidget):
    """Vista de preparación para competir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll, inner, lay = _scrollable()
        root.addWidget(scroll)

        lay.addWidget(_section_title(
            "🎯", "Preparación para Competir",
            "Race Readiness Score · Índice compuesto de tu estado actual"
        ))

        # Main content: gauge + metrics side by side
        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        # Left: Gauge card
        gauge_card = QFrame()
        gauge_card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        gc_lay = QVBoxLayout(gauge_card)
        gc_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        gc_title = QLabel("Race Readiness Score")
        gc_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        gc_lay.addWidget(gc_title, alignment=Qt.AlignmentFlag.AlignCenter)
        gc_sub = QLabel("Puntuación compuesta 0–100")
        gc_sub.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
        gc_lay.addWidget(gc_sub, alignment=Qt.AlignmentFlag.AlignCenter)

        self._gauge = GaugeWidget()
        gc_lay.addWidget(self._gauge, alignment=Qt.AlignmentFlag.AlignCenter)

        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {COLORS['fg']}; border: none;")
        gc_lay.addWidget(self._status_label)

        # Factor bars
        self._bars_container = QVBoxLayout()
        self._bars_container.setSpacing(10)
        gc_lay.addLayout(self._bars_container)

        # Advice
        self._advice_label = QLabel()
        self._advice_label.setWordWrap(True)
        self._advice_label.setStyleSheet(
            f"font-size: 12px; color: {COLORS['fg_muted']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 8px; padding: 12px; background: {COLORS['bg_secondary']};"
        )
        gc_lay.addWidget(self._advice_label)

        content_row.addWidget(gauge_card, stretch=1)

        # Right: Input metrics card
        metrics_card = QFrame()
        metrics_card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        mc_lay = QVBoxLayout(metrics_card)

        mc_title = QLabel("Métricas de entrada")
        mc_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        mc_lay.addWidget(mc_title)
        mc_sub = QLabel("Valores actuales usados en el cálculo")
        mc_sub.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
        mc_lay.addWidget(mc_sub)
        mc_lay.addSpacing(8)

        self._metrics_container = QVBoxLayout()
        self._metrics_container.setSpacing(8)
        mc_lay.addLayout(self._metrics_container)
        mc_lay.addStretch()

        content_row.addWidget(metrics_card, stretch=1)
        lay.addLayout(content_row)

        # Explanation card
        lay.addWidget(self._make_explanation())
        lay.addStretch()

        self._refresh_data()

    def _make_metric_row(self, label: str, value: str, sub: str, highlight: str = "") -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 8px; padding: 10px 14px; }}"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
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

    def _make_factor_bar(self, label: str, weight: str, value: int) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { border: none; background: transparent; }")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        top = QHBoxLayout()
        lbl = QLabel(f"{label} ({weight})")
        lbl.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
        top.addWidget(lbl)
        top.addStretch()
        val = QLabel(str(value))
        val.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {COLORS['fg']}; border: none;")
        top.addWidget(val)
        lay.addLayout(top)

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(value)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        color = _score_color(value)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {COLORS['bg_secondary']}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}"
        )
        lay.addWidget(bar)
        return frame

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
            "El <b>Race Readiness Score</b> combina tres dimensiones clave del entrenamiento:",
            "• <b>Forma (40%)</b> — Tu TSB (Training Stress Balance). El punto óptimo es +5 a +15.",
            "• <b>Fitness (35%)</b> — Tu CTL relativo a tu máximo histórico, más bonus/penalización por tendencia (ramp rate).",
            "• <b>Variabilidad (25%)</b> — Inverso de la monotonía. Mayor variedad diaria = mejor score.",
            "🟢 ≥75 = Listo para competir · 🟡 50–74 = Casi listo · 🔴 &lt;50 = No es el momento",
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

        tsb = lrp.tsb
        ctl = lrp.ctl
        ctl_max = max((p.ctl for p in series if not p.forecast), default=ctl)
        ramp = calc_ramp_rate(series)

        # Monotony for last week
        daily_tss: Dict[date, float] = defaultdict(float)
        for a in acts:
            d = a.started_at.date() if isinstance(a.started_at, datetime) else a.started_at
            daily_tss[d] += a.tss or 0

        last_7 = [daily_tss.get(today - timedelta(days=6 - i), 0.0) for i in range(7)]
        mon_result = calc_week_monotony(last_7)
        monotony = mon_result.monotony

        rrs_input = RrsInput(
            tsb=tsb, ctl=ctl, ctl_max=ctl_max,
            ramp_rate=ramp, monotony=monotony,
        )
        rrs = calc_race_readiness(rrs_input)

        # Update UI
        self._gauge.set_score(rrs.score, rrs.level)
        self._status_label.setText(f"{rrs.emoji}  {rrs.label}")
        self._advice_label.setText(f"💡 Consejo: {rrs.advice}")

        # Clear and rebuild factor bars
        while self._bars_container.count():
            item = self._bars_container.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        factors = [
            ("Forma (TSB)", "40%", rrs.form_score),
            ("Fitness (CTL)", "35%", rrs.fitness_score),
            ("Variabilidad", "25%", rrs.variability_score),
        ]
        for label, weight, val in factors:
            self._bars_container.addWidget(self._make_factor_bar(label, weight, val))

        # Clear and rebuild metrics
        while self._metrics_container.count():
            item = self._metrics_container.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        tsb_color = "#22c55e" if tsb >= 5 else "#eab308" if tsb >= -10 else "#ef4444"
        tsb_str = f"{'+' if tsb > 0 else ''}{tsb:.1f}"
        self._metrics_container.addWidget(self._make_metric_row(
            "TSB (Forma)", tsb_str,
            "Balance de estrés del entrenamiento", tsb_color,
        ))
        self._metrics_container.addWidget(self._make_metric_row(
            "CTL (Fitness)", f"{ctl:.1f}",
            f"Máximo histórico: {ctl_max:.1f}",
        ))
        ramp_str = f"{'+' if ramp and ramp > 0 else ''}{ramp:.1f} TSS/d" if ramp is not None else "N/A"
        self._metrics_container.addWidget(self._make_metric_row(
            "Ramp Rate", ramp_str,
            "Velocidad de cambio del CTL semanal",
        ))
        mon_str = f"{monotony:.2f}" if monotony is not None else "N/A"
        self._metrics_container.addWidget(self._make_metric_row(
            "Monotonía", mon_str,
            "Última semana (ideal < 1.5)",
        ))

    def _show_no_data(self) -> None:
        self._gauge.set_score(0, "not_ready")
        self._status_label.setText("Sin datos suficientes")
        self._advice_label.setText("Importa actividades para calcular tu preparación.")
