"""Vista Resumen de entrenamiento — réplica de la web.

Agregados semanales y mensuales con tendencias, sparklines KPI,
mini-barras de zonas Coggan y gráfico de evolución de zonas.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPainterPath, QLinearGradient
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QStyledItemDelegate, QTabWidget, QTableWidget,
    QTableWidgetItem, QToolTip, QVBoxLayout, QWidget,
)

from db.engine import get_session
from db.models import Activity
from calc.zones import POWER_ZONES, ZoneDef
from ui.theme import COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_TITLE
from ui.charts.chart_utils import make_plot, configure_axis


# ── Constants ────────────────────────────────────────────────────

_MONTH_SHORT = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sept", 10: "oct", 11: "nov", 12: "dic",
}

_MONTH_FULL = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

_MONTHS_MAP = {0: 3, 1: 6, 2: 12, 3: 24}

_ZONE_KEYS = ["z1", "z2", "z3", "z3p", "z4", "z5", "z6", "z7"]
_ZONE_COLORS = {z.key: z.color for z in POWER_ZONES}
_ZONE_LABELS = {z.key: z.short_label for z in POWER_ZONES}


# ── Helpers ──────────────────────────────────────────────────────

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


# ── Sparkline Widget ─────────────────────────────────────────────

class SparklineCard(QFrame):
    """KPI card with title, sparkline, and last value."""

    def __init__(self, title: str, data: List[float], color: str, parent=None):
        super().__init__(parent)
        self._data = data
        self._color = QColor(color)
        self._title = title
        self.setFixedHeight(90)
        self.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['bg_hover']}; "
            f"border-radius: 10px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"font-size: 11px; color: {COLORS['fg_muted']}; border: none;")
        lay.addWidget(lbl)

        # Sparkline drawn in paintEvent
        self._spark_area = QWidget()
        self._spark_area.setMinimumHeight(32)
        lay.addWidget(self._spark_area, 1)

        # Last value
        val_text = f"{data[-1]:.1f}" if data else "—"
        val_lbl = QLabel(val_text)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        val_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {color}; border: none;"
        )
        lay.addWidget(val_lbl)

    def paintEvent(self, event):
        super().paintEvent(event)
        if len(self._data) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Map sparkline area coordinates
        sa = self._spark_area
        rect = sa.geometry()
        x0, y0 = rect.x(), rect.y()
        w, h = rect.width(), rect.height()
        if w < 5 or h < 5:
            painter.end()
            return

        data = self._data
        mn, mx = min(data), max(data)
        rng = mx - mn if mx != mn else 1.0
        pad = 2
        uh = h - pad * 2
        step = (w - pad * 2) / (len(data) - 1)

        points = []
        for i, v in enumerate(data):
            px = x0 + pad + i * step
            py = y0 + pad + uh - ((v - mn) / rng) * uh
            points.append(QPointF(px, py))

        # Gradient area
        grad = QLinearGradient(0, y0, 0, y0 + h)
        c = QColor(self._color)
        c.setAlpha(60)
        grad.setColorAt(0.0, c)
        c2 = QColor(self._color)
        c2.setAlpha(0)
        grad.setColorAt(1.0, c2)

        area_path = QPainterPath()
        area_path.moveTo(points[0])
        for p in points[1:]:
            area_path.lineTo(p)
        area_path.lineTo(QPointF(points[-1].x(), y0 + h))
        area_path.lineTo(QPointF(points[0].x(), y0 + h))
        area_path.closeSubpath()
        painter.fillPath(area_path, QBrush(grad))

        # Line
        pen = QPen(self._color, 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i + 1])

        painter.end()


# ── Zone Mini-Bar Delegate ───────────────────────────────────────

class ZoneMiniBarDelegate(QStyledItemDelegate):
    """Custom delegate to paint vertical stacked mini-bars in a table cell."""

    def paint(self, painter: QPainter, option, index):
        # Get zones data from item's UserRole
        zones = index.data(Qt.ItemDataRole.UserRole)
        if not zones:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(4, 3, -4, -3)

        total = sum(zones.get(k, 0) for k in _ZONE_KEYS)
        if total <= 0:
            painter.setPen(QPen(QColor(COLORS["fg_dim"])))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "—")
            painter.restore()
            return

        # Draw vertical stacked bars (each zone = one thin column)
        bar_w = min(8, max(3, rect.width() // (len(_ZONE_KEYS) + 1)))
        gap = 1
        total_bars_w = len(_ZONE_KEYS) * bar_w + (len(_ZONE_KEYS) - 1) * gap
        start_x = rect.x() + (rect.width() - total_bars_w) / 2
        max_h = rect.height()

        for i, k in enumerate(_ZONE_KEYS):
            secs = zones.get(k, 0)
            pct = secs / total
            if pct < 0.005:
                continue
            bh = max(1, int(pct * max_h))
            bx = start_x + i * (bar_w + gap)
            by = rect.y() + max_h - bh
            c = QColor(_ZONE_COLORS.get(k, "#888"))
            c.setAlpha(210)
            painter.fillRect(int(bx), int(by), bar_w, bh, c)

        painter.restore()

    def helpEvent(self, event, view, option, index):
        """Show tooltip with zone breakdown on hover."""
        from PySide6.QtCore import QEvent
        zones = index.data(Qt.ItemDataRole.UserRole)
        if zones and event.type() == QEvent.Type.ToolTip:
            total = sum(zones.get(k, 0) for k in _ZONE_KEYS)
            if total > 0:
                lines = ["Distribución por zonas:"]
                for k in _ZONE_KEYS:
                    secs = zones.get(k, 0)
                    if secs < 30:
                        continue
                    pct = secs / total * 100
                    mins = round(secs / 60)
                    lbl = _ZONE_LABELS.get(k, k)
                    lines.append(f"  {lbl}: {pct:.0f}% ({mins} min)")
                QToolTip.showText(event.globalPos(), "\n".join(lines), view)
                return True
        return super().helpEvent(event, view, option, index)


# ── Trend formatting ─────────────────────────────────────────────

def _trend_text(current: float, previous: Optional[float]) -> str:
    """Return trend string like '↗ +33%' or '↘ -12%' or '= ' """
    if previous is None or previous == 0:
        return ""
    pct = (current - previous) / abs(previous) * 100
    if abs(pct) < 1:
        return "— ="
    arrow = "↗" if pct > 0 else "↘"
    sign = "+" if pct > 0 else ""
    return f"{arrow} {sign}{pct:.0f}%"


def _trend_color(current: float, previous: Optional[float]) -> str:
    if previous is None or previous == 0:
        return COLORS["fg_dim"]
    pct = (current - previous) / abs(previous) * 100
    if abs(pct) < 1:
        return COLORS["fg_dim"]
    return "#34d399" if pct > 0 else "#f87171"  # emerald-400 / red-400


# ═══════════════════════════════════════════════════════════════
#  SummaryView — main widget
# ═══════════════════════════════════════════════════════════════

class SummaryView(QWidget):
    """Resumen de entrenamiento — agregados semanales/mensuales."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary_weeks: List[dict] = []
        self._summary_months: List[dict] = []
        self._all_activities: List = []  # raw activities for PDF export
        self._build_ui()

    # ── Build UI ─────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll, inner, lay = _scrollable()
        root.addWidget(scroll)

        # Title
        lay.addWidget(_section_title(
            "📈", "Resumen de entrenamiento",
            "Agregados semanales y mensuales con tendencias."
        ))

        # ── Controls row ──
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

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

        btn_pdf = QPushButton("📥  Descargar PDF")
        btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_pdf.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {COLORS['fg_muted']}; "
            f"font-weight: 600; padding: 6px 14px; border-radius: 6px; "
            f"font-size: {FONT_SIZE_SM}; border: 1px solid {COLORS['fg_dim']}; }}"
            f"QPushButton:hover {{ background: {COLORS['bg_card']}; color: {COLORS['fg']}; }}"
        )
        btn_pdf.clicked.connect(self._export_pdf)
        ctrl.addWidget(btn_pdf)
        lay.addLayout(ctrl)

        # ── Sparkline KPI cards ──
        self._spark_grid = QHBoxLayout()
        self._spark_grid.setSpacing(10)
        lay.addLayout(self._spark_grid)

        # ── Tabs (Semanal / Mensual) ──
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Weekly table
        self._tbl_weekly = self._make_table("Semana")
        self._tabs.addTab(self._tbl_weekly, "📅 Semanal")

        # Monthly table
        self._tbl_monthly = self._make_table("Mes")
        self._tabs.addTab(self._tbl_monthly, "📊 Mensual")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        lay.addWidget(self._tabs)

        # ── Zones Evolution chart ──
        lay.addWidget(_section_title(
            "🔄", "Evolución de zonas Coggan",
            "Distribución porcentual del tiempo por zona de potencia."
        ))
        self._pw_zones = make_plot(height=320)
        lay.addWidget(self._pw_zones)

        lay.addStretch()

        # Initial load
        self._refresh_data()

    def _make_table(self, first_col: str) -> QTableWidget:
        tbl = QTableWidget()
        tbl.setColumnCount(9)
        tbl.setHorizontalHeaderLabels([
            first_col, "Entrenos", "Horas", "Km", "Desnivel",
            "TSS", "kJ", "IF med", "Zonas",
        ])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(8, 100)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setMouseTracking(True)  # needed for tooltip delegate
        tbl.setStyleSheet(
            f"QTableWidget {{ background: {COLORS['bg_card']}; color: {COLORS['fg']}; "
            f"gridline-color: {COLORS['bg_hover']}; border: 1px solid {COLORS['bg_hover']}; "
            f"border-radius: 8px; font-size: {FONT_SIZE_SM}; }}"
            f"QHeaderView::section {{ background: {COLORS['bg_secondary']}; "
            f"color: {COLORS['fg_muted']}; font-weight: 600; padding: 6px; "
            f"border: none; border-bottom: 1px solid {COLORS['bg_hover']}; }}"
        )
        # Center header labels for data columns (1-7)
        header = tbl.horizontalHeader()
        for col in range(1, 8):
            item = tbl.horizontalHeaderItem(col)
            if item:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        # Set zone mini-bar delegate for column 8
        tbl.setItemDelegateForColumn(8, ZoneMiniBarDelegate(tbl))
        return tbl

    # ── Data aggregation ─────────────────────────────────────

    def _build_data(self, months: int):
        """Query activities and aggregate into weekly + monthly rows."""
        from db.models import ProfileSnapshot
        from calc.zones import bucket_series, POWER_ZONES

        today = date.today()
        cutoff = datetime(today.year, today.month, today.day) - timedelta(days=months * 30)

        with get_session() as session:
            acts = (
                session.query(Activity)
                .filter(Activity.started_at >= cutoff)
                .order_by(Activity.started_at.asc())
                .all()
            )
            # Fetch current FTP for on-the-fly zone recalculation
            snap = session.query(ProfileSnapshot).order_by(
                ProfileSnapshot.effective_at.desc()
            ).first()
            current_ftp = snap.ftp if snap and snap.ftp else 0
            session.expunge_all()

        # Helpers
        def _iso_key(dt: datetime) -> str:
            iso = dt.date().isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"

        def _week_label(dt: datetime) -> str:
            d = dt.date()
            mon = d - timedelta(days=d.weekday())
            sun = mon + timedelta(days=6)
            return f"{mon.day} {_MONTH_SHORT[mon.month]} – {sun.day} {_MONTH_SHORT[sun.month]}"

        def _month_key(dt: datetime) -> str:
            return f"{dt.year}-{dt.month:02d}"

        def _month_label(dt: datetime) -> str:
            return f"{_MONTH_FULL[dt.month]} {dt.year}"

        def _compute_zones_for_activity(a: Activity) -> Dict[str, float]:
            """Compute zones from stored samples using current FTP.

            If the activity's ftp_used matches current FTP, use stored zones
            (faster). Otherwise, recompute from downsampled samples so the chart
            always reflects the current profile FTP.
            """
            if current_ftp <= 0:
                zp = a.get_zones_power()
                return zp if zp else {k: 0.0 for k in _ZONE_KEYS}

            # If FTP matches, use stored zones
            if a.ftp_used and a.ftp_used == current_ftp:
                zp = a.get_zones_power()
                if zp:
                    return zp

            # Recompute from samples with current FTP
            samples = a.get_samples()
            if samples:
                power_series = [s.get("p") for s in samples]
                # Each sample represents ~5 seconds; bucket_series counts
                # occurrences so percentages stay correct regardless.
                zp_int = bucket_series(power_series, current_ftp, POWER_ZONES)
                return {k: float(v) for k, v in zp_int.items()}

            # Fallback to stored zones
            zp = a.get_zones_power()
            return zp if zp else {k: 0.0 for k in _ZONE_KEYS}

        # Group
        w_buckets: Dict[str, List[Activity]] = defaultdict(list)
        m_buckets: Dict[str, List[Activity]] = defaultdict(list)
        w_labels: Dict[str, str] = {}
        m_labels: Dict[str, str] = {}
        w_week_labels: Dict[str, str] = {}  # sub-label "11 may – 17 may"

        for a in acts:
            wk = _iso_key(a.started_at)
            w_buckets[wk].append(a)
            if wk not in w_labels:
                w_labels[wk] = wk
                w_week_labels[wk] = _week_label(a.started_at)
            mk = _month_key(a.started_at)
            m_buckets[mk].append(a)
            if mk not in m_labels:
                m_labels[mk] = _month_label(a.started_at)

        def _agg(bucket: List[Activity]) -> dict:
            count = len(bucket)
            dur = sum(a.duration_sec or 0 for a in bucket)
            km = sum(a.distance_km or 0 for a in bucket)
            elev = sum(a.elevation_gain_m or 0 for a in bucket)
            tss = sum(a.tss or 0 for a in bucket)
            kj = sum(a.work_kj or 0 for a in bucket)
            s_if, s_dur = 0.0, 0.0
            for a in bucket:
                if a.intensity_factor and a.duration_sec:
                    s_if += a.intensity_factor * a.duration_sec
                    s_dur += a.duration_sec
            avg_if = (s_if / s_dur) if s_dur > 0 else 0.0
            zones: Dict[str, float] = {k: 0.0 for k in _ZONE_KEYS}
            for a in bucket:
                zp = _compute_zones_for_activity(a)
                for k in _ZONE_KEYS:
                    zones[k] += zp.get(k, 0.0)
            return {
                "activities": count, "hours": dur / 3600.0,
                "km": km, "elevation": elev, "tss": tss, "kj": kj,
                "avgIf": avg_if, "zonesPower": zones,
            }

        weeks = []
        for wk in sorted(w_buckets):
            row = _agg(w_buckets[wk])
            row["key"] = wk
            row["label"] = w_labels[wk]  # "2026-W20"
            row["sublabel"] = w_week_labels[wk]  # "11 may – 17 may"
            weeks.append(row)

        months_list = []
        for mk in sorted(m_buckets):
            row = _agg(m_buckets[mk])
            row["key"] = mk
            row["label"] = m_labels[mk]
            months_list.append(row)

        self._all_activities = acts
        return weeks, months_list

    # ── Refresh ──────────────────────────────────────────────

    def refresh(self) -> None:
        self._refresh_data()

    def _refresh_data(self) -> None:
        months = _MONTHS_MAP.get(self._months_combo.currentIndex(), 6)
        self._summary_weeks, self._summary_months = self._build_data(months)
        self._update_sparklines()
        self._fill_weekly_table()
        self._fill_monthly_table()
        self._draw_zones_chart()

    # ── Sparklines ───────────────────────────────────────────

    def _update_sparklines(self) -> None:
        # Clear existing
        while self._spark_grid.count():
            item = self._spark_grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        w_tss = [r["tss"] for r in self._summary_weeks]
        w_hrs = [r["hours"] for r in self._summary_weeks]
        m_tss = [r["tss"] for r in self._summary_months]
        m_hrs = [r["hours"] for r in self._summary_months]

        for title, data, color in [
            ("TSS / semana", w_tss, "#FF6B35"),
            ("Horas / semana", w_hrs, "#22D3EE"),
            ("TSS / mes", m_tss, "#FF6B35"),
            ("Horas / mes", m_hrs, "#22D3EE"),
        ]:
            card = SparklineCard(title, data, color)
            self._spark_grid.addWidget(card)

    # ── Tables ───────────────────────────────────────────────

    def _fill_weekly_table(self) -> None:
        tbl = self._tbl_weekly
        rows = list(reversed(self._summary_weeks))  # newest first
        tbl.setRowCount(len(rows))
        for i, row in enumerate(rows):
            prev = rows[i + 1] if i + 1 < len(rows) else None
            self._set_row(tbl, i, row, prev, is_weekly=True)

    def _fill_monthly_table(self) -> None:
        tbl = self._tbl_monthly
        rows = list(reversed(self._summary_months))
        tbl.setRowCount(len(rows))
        for i, row in enumerate(rows):
            prev = rows[i + 1] if i + 1 < len(rows) else None
            self._set_row(tbl, i, row, prev, is_weekly=False)

    def _set_row(self, tbl: QTableWidget, i: int, row: dict,
                 prev: Optional[dict], is_weekly: bool) -> None:
        """Populate one table row with data + trend."""
        # Column 0: label (two lines for weekly: key + date range)
        tbl.setRowHeight(i, 44)
        if is_weekly:
            cell_w = QWidget()
            cell_lay = QVBoxLayout(cell_w)
            cell_lay.setContentsMargins(6, 2, 4, 2)
            cell_lay.setSpacing(0)
            key_lbl = QLabel(row["label"])
            key_lbl.setStyleSheet(
                f"font-weight: 700; font-size: 12px; color: {COLORS['fg']}; border: none;"
            )
            cell_lay.addWidget(key_lbl)
            sub_lbl = QLabel(row.get("sublabel", ""))
            sub_lbl.setStyleSheet(
                f"font-size: 10px; color: {COLORS['fg_muted']}; border: none;"
            )
            cell_lay.addWidget(sub_lbl)
            tbl.setCellWidget(i, 0, cell_w)
        else:
            item0 = QTableWidgetItem(row["label"])
            item0.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            f = QFont()
            f.setBold(True)
            f.setPointSize(9)
            item0.setFont(f)
            tbl.setItem(i, 0, item0)

        # Metrics columns with trend
        metrics = [
            (1, "activities", 0, ""),
            (2, "hours", 1, "h"),
            (3, "km", 0, "km"),
            (4, "elevation", 0, "m"),
            (5, "tss", 0, ""),
            (6, "kj", 0, ""),
        ]
        for col, key, dec, unit in metrics:
            val = row[key]
            prev_val = prev[key] if prev else None
            self._set_metric_cell(tbl, i, col, val, prev_val, dec, unit)

        # IF med (col 7)
        avg_if = row["avgIf"]
        prev_if = prev["avgIf"] if prev else None
        if avg_if > 0:
            self._set_metric_cell(tbl, i, 7, avg_if, prev_if if prev_if and prev_if > 0 else None, 2, "")
        else:
            lbl_dash = QLabel("—")
            lbl_dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_dash.setStyleSheet(f"color: {COLORS['fg_dim']}; border: none;")
            tbl.setCellWidget(i, 7, lbl_dash)

        # Zones (col 8) — custom painted via delegate
        zones_item = QTableWidgetItem()
        zones_item.setData(Qt.ItemDataRole.UserRole, row["zonesPower"])
        tbl.setItem(i, 8, zones_item)

    def _set_metric_cell(self, tbl: QTableWidget, row_idx: int, col: int,
                         value: float, prev: Optional[float],
                         decimals: int, unit: str) -> None:
        """Set a metric cell with value on line 1 and trend on line 2."""
        if decimals > 0:
            val_str = f"{value:.{decimals}f}"
        else:
            val_str = f"{value:.0f}"
        if unit:
            val_str += f" {unit}"

        trend = _trend_text(value, prev)
        tc = _trend_color(value, prev)

        cell_w = QWidget()
        cell_lay = QVBoxLayout(cell_w)
        cell_lay.setContentsMargins(2, 2, 2, 2)
        cell_lay.setSpacing(0)
        cell_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        val_lbl = QLabel(val_str)
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val_lbl.setStyleSheet(
            f"font-weight: 600; font-size: 12px; color: {COLORS['fg']}; border: none;"
        )
        cell_lay.addWidget(val_lbl)

        if trend:
            trend_lbl = QLabel(trend)
            trend_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            trend_lbl.setStyleSheet(
                f"font-size: 11px; font-weight: 500; color: {tc}; border: none;"
            )
            cell_lay.addWidget(trend_lbl)

        tbl.setCellWidget(row_idx, col, cell_w)

    # ── Zones Evolution Chart ────────────────────────────────

    def _draw_zones_chart(self, _idx: int = 0) -> None:
        pw = self._pw_zones
        pw.clear()
        # Remove any previous legend to avoid stale legend artifacts
        if pw.plotItem.legend is not None:
            pw.plotItem.legend.scene().removeItem(pw.plotItem.legend)
            pw.plotItem.legend = None

        is_weekly = self._tabs.currentIndex() == 0
        rows = self._summary_weeks if is_weekly else self._summary_months

        if not rows:
            empty_txt = pg.TextItem(
                "Sin datos para el periodo seleccionado",
                color=QColor(COLORS["fg_muted"]),
            )
            empty_txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(empty_txt)
            empty_txt.setPos(0, 50)
            return

        n = len(rows)
        x = np.arange(n)
        width = 0.7

        # Compute % matrix + store raw seconds
        pct_matrix: Dict[str, np.ndarray] = {k: np.zeros(n) for k in _ZONE_KEYS}
        secs_matrix: Dict[str, np.ndarray] = {k: np.zeros(n) for k in _ZONE_KEYS}
        for i, row in enumerate(rows):
            zp = row["zonesPower"]
            total = sum(zp.values())
            for k in _ZONE_KEYS:
                secs_matrix[k][i] = zp[k]
                if total > 0:
                    pct_matrix[k][i] = zp[k] / total * 100.0

        # Draw stacked bars (no legend — colors are self-explanatory via tooltip)
        bottom = np.zeros(n)
        for k in _ZONE_KEYS:
            heights = pct_matrix[k]
            color = _ZONE_COLORS.get(k, "#888")
            bar = pg.BarGraphItem(
                x=x, height=heights, y0=bottom, width=width,
                brush=QColor(color), pen=pg.mkPen(None),
            )
            pw.addItem(bar)
            bottom = bottom + heights

        # X-axis
        if is_weekly:
            tick_labels = []
            for r in rows:
                m = r["key"]
                wn = m.split("-W")[-1] if "-W" in m else m
                tick_labels.append(f"S{wn}")
        else:
            tick_labels = []
            for r in rows:
                parts = r["key"].split("-")
                if len(parts) == 2:
                    tick_labels.append(f"{parts[1]}/{parts[0][2:]}")
                else:
                    tick_labels.append(r["key"])

        ticks = [list(zip(range(n), tick_labels))]
        ax_b = pw.getAxis("bottom")
        ax_b.setTicks(ticks)
        ax_b.setStyle(tickTextOffset=6)
        ax_b.setTextPen(pg.mkPen(COLORS["fg_muted"]))

        pw.setYRange(0, 100, padding=0.02)
        ax_l = pw.getAxis("left")
        ax_l.setLabel("% tiempo")
        ax_l.setTextPen(pg.mkPen(COLORS["fg_muted"]))

        # Inline legend row above chart — spread evenly across x-axis
        total_zones = len(_ZONE_KEYS)
        spacing = max(n / total_zones, 1.2)
        # Center the legend above the bars
        legend_start = max(0, (n - spacing * total_zones) / 2)
        for zi, k in enumerate(_ZONE_KEYS):
            lbl = _ZONE_LABELS.get(k, k)
            clr = _ZONE_COLORS.get(k, "#888")
            txt = pg.TextItem(f"■ {lbl}", color=QColor(clr))
            txt.setFont(QFont("Segoe UI", 7))
            txt.setPos(legend_start + zi * spacing, 108)
            pw.addItem(txt, ignoreBounds=True)

        # Tooltip proxy
        self._zones_tooltip = _ZonesTooltipProxy(pw, rows, pct_matrix, secs_matrix, tick_labels, is_weekly)

    # ── Signals ──────────────────────────────────────────────

    def _on_months_changed(self, _idx: int = 0) -> None:
        self._refresh_data()

    def _on_tab_changed(self, _idx: int = 0) -> None:
        self._draw_zones_chart()

    # ── CSV Export ───────────────────────────────────────────

    def _export_pdf(self) -> None:
        """Export monthly report matching web's Informe mensual style."""
        try:
            self._export_pdf_impl()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            print(f"[PDF EXPORT ERROR]\n{tb}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error al generar PDF:\n{tb[:600]}")

    def _export_pdf_impl(self) -> None:
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtPrintSupport import QPrinter
        from PySide6.QtCore import QMarginsF

        is_weekly = self._tabs.currentIndex() == 0
        rows = self._summary_weeks if is_weekly else self._summary_months
        if not rows:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Sin datos", "No hay datos para exportar.")
            return

        # Get profile info for header
        from db.models import ProfileSnapshot
        from db.engine import get_session
        ftp_val = 0
        weight_val = 0.0
        with get_session() as session:
            snap = session.query(ProfileSnapshot).order_by(
                ProfileSnapshot.effective_at.desc()
            ).first()
            if snap:
                ftp_val = snap.ftp or 0
                weight_val = snap.weight_kg or 0.0

        kind = "semanal" if is_weekly else "mensual"
        today = date.today()
        _MF = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
               5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
               9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}
        month_name = _MF[today.month].capitalize()

        default_name = f"informe-ciclometricas-{today.strftime('%Y-%m')}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", default_name,
            "Archivos PDF (*.pdf);;Todos los archivos (*)",
        )
        if not path:
            return

        # ── Aggregate totals for KPI cards ──
        total_acts = sum(r["activities"] for r in rows)
        total_hours = sum(r["hours"] for r in rows)
        total_km = sum(r["km"] for r in rows)
        total_elev = sum(r["elevation"] for r in rows)
        total_tss = sum(r["tss"] for r in rows)
        total_kj = sum(r["kj"] for r in rows)

        # Previous period for trends (compare last 2 entries if monthly)
        def _trend_html(current: float, previous: float) -> str:
            if previous <= 0:
                return ""
            pct = (current - previous) / abs(previous) * 100
            arrow = "▲" if pct > 0 else "▼"
            color = "#22c55e" if pct > 0 else "#ef4444"
            return f"<span style='color:{color};font-size:11px'>{arrow} {pct:+.0f}%</span>"

        # Trends vs previous month (if 2+ monthly rows)
        trend_acts = trend_hrs = trend_km = trend_elev = trend_tss = trend_kj = ""
        if not is_weekly and len(rows) >= 2:
            prev = rows[-2]
            cur = rows[-1]
            trend_acts = _trend_html(cur["activities"], prev["activities"])
            trend_hrs = _trend_html(cur["hours"], prev["hours"])
            trend_km = _trend_html(cur["km"], prev["km"])
            trend_elev = _trend_html(cur["elevation"], prev["elevation"])
            trend_tss = _trend_html(cur["tss"], prev["tss"])
            trend_kj = _trend_html(cur["kj"], prev["kj"])
            prev_label = f"vs {prev['label']}"
            if trend_acts:
                trend_acts += f" <span style='color:#6b7d99;font-size:9px'>{prev_label}</span>"

        # ── Color palette (light theme – Qt PDF compatible) ──
        BG = "#ffffff"
        TEXT = "#0f172a"
        TEXT_MUT = "#475569"
        TEXT_DIM = "#64748b"
        ACCENT = "#FF6B35"
        CARD_BG = "#f1f5f9"
        BORD = "#e2e8f0"
        BORD_D = "#cbd5e1"
        ROW_ALT = "#f8fafc"

        # ── KPI cards HTML ──
        def _kpi(label: str, value: str, unit: str, trend: str) -> str:
            return (
                f"<td style='padding:12px 14px;background:{CARD_BG};"
                f"border:1px solid {BORD};vertical-align:top;width:33%'>"
                f"<div style='color:{TEXT_MUT};font-size:10px;text-transform:uppercase;"
                f"font-weight:600;letter-spacing:0.5px'>{label}</div>"
                f"<div style='color:{TEXT};font-size:22px;font-weight:700;"
                f"margin:4px 0'>{value} <span style='font-size:14px;"
                f"color:{TEXT_DIM}'>{unit}</span></div>"
                f"<div>{trend}</div></td>"
            )

        kpi_row1 = (
            "<tr>"
            + _kpi("Entrenamientos", str(total_acts), "", trend_acts)
            + _kpi("Horas totales", f"{total_hours:.1f}", "h", trend_hrs)
            + _kpi("Distancia", f"{total_km:.0f}", "km", trend_km)
            + "</tr>"
        )
        kpi_row2 = (
            "<tr>"
            + _kpi("Desnivel", f"{total_elev:,.0f}".replace(",", "."), "m", trend_elev)
            + _kpi("TSS total", f"{total_tss:.0f}", "", trend_tss)
            + _kpi("Trabajo", f"{total_kj:,.0f}".replace(",", "."), "kJ", trend_kj)
            + "</tr>"
        )

        # ── Breakdown table ──
        weekly_rows_html = ""
        display_rows = list(reversed(rows))
        col_label = "Semana" if is_weekly else "Mes"
        for ri, r in enumerate(display_rows):
            h = r["hours"]
            hrs = int(h)
            mins = int((h - hrs) * 60)
            wk = r["key"].split("-W")[-1] if is_weekly and "-W" in r["key"] else r["label"]
            label = f"S{wk}" if is_weekly else r["label"]
            row_bg = ROW_ALT if ri % 2 == 0 else BG
            weekly_rows_html += (
                f"<tr style='background:{row_bg};border-bottom:1px solid {BORD}'>"
                f"<td style='padding:7px 10px;color:{TEXT};font-weight:600'>{label}</td>"
                f"<td style='padding:7px 10px;text-align:center;color:{TEXT}'>"
                f"{r['activities']}</td>"
                f"<td style='padding:7px 10px;text-align:center;color:{TEXT}'>"
                f"{hrs}h {mins:02d}m</td>"
                f"<td style='padding:7px 10px;text-align:center;color:{TEXT}'>"
                f"{r['km']:.0f}</td>"
                f"<td style='padding:7px 10px;text-align:center;color:{TEXT}'>"
                f"{r['tss']:.0f}</td>"
                f"</tr>"
            )

        # ── Zone distribution ──
        all_zones = {k: 0.0 for k in _ZONE_KEYS}
        for r in rows:
            for k in _ZONE_KEYS:
                all_zones[k] += r["zonesPower"].get(k, 0.0)
        total_z = sum(all_zones.values())

        zone_bar_parts = ""
        zone_legend_parts = ""
        if total_z > 0:
            for k in _ZONE_KEYS:
                pct = all_zones[k] / total_z * 100
                if pct < 0.5:
                    continue
                clr = _ZONE_COLORS.get(k, "#888")
                zone_bar_parts += (
                    f"<td style='background:{clr};width:{pct}%;height:18px'></td>"
                )
                mins_z = round(all_zones[k] / 60)
                lbl = _ZONE_LABELS.get(k, k)
                hrs_z = mins_z // 60
                rm_z = mins_z % 60
                t_str = f"{hrs_z}h{rm_z:02d}m" if hrs_z else f"{mins_z}min"
                zone_legend_parts += (
                    f"<tr>"
                    f"<td style='padding:2px 6px'>"
                    f"<span style='color:{clr};font-size:14px'>■</span></td>"
                    f"<td style='padding:2px 6px;color:{TEXT};font-size:11px'>"
                    f"{lbl}</td>"
                    f"<td style='padding:2px 6px;color:{TEXT};font-size:11px;"
                    f"text-align:right'>{pct:.0f}%</td>"
                    f"<td style='padding:2px 6px;color:{TEXT_MUT};font-size:11px'>"
                    f"{t_str}</td>"
                    f"</tr>"
                )

        # ── Top activities by TSS ──
        top_acts_html = ""
        if self._all_activities:
            sorted_acts = sorted(
                self._all_activities, key=lambda a: a.tss or 0, reverse=True
            )
            act_i = 0
            for a in sorted_acts[:10]:
                if not a.tss or a.tss < 5:
                    continue
                d = (a.started_at.date()
                     if isinstance(a.started_at, datetime) else a.started_at)
                d_str = f"{d.day:02d} {_MONTH_SHORT[d.month]}"
                name = (getattr(a, 'custom_name', None)
                        or getattr(a, 'file_name', '') or "Actividad")
                if len(name) > 30:
                    name = name[:27] + "..."
                dur_s = a.duration_sec or 0
                dh, dm = divmod(dur_s // 60, 60)
                dur_str = f"{dh}h {dm:02d}m" if dh else f"{dm}m"
                km_str = f"{a.distance_km:.1f}" if a.distance_km else "—"
                tss_str = f"{a.tss:.0f}" if a.tss else "—"
                np_str = f"{a.normalized_power:.0f}" if a.normalized_power else "—"
                if_str = f"{a.intensity_factor:.2f}" if a.intensity_factor else "—"
                row_bg = ROW_ALT if act_i % 2 == 0 else BG
                top_acts_html += (
                    f"<tr style='background:{row_bg};"
                    f"border-bottom:1px solid {BORD}'>"
                    f"<td style='padding:5px 8px;color:{TEXT_MUT};"
                    f"font-size:11px'>{d_str}</td>"
                    f"<td style='padding:5px 8px;color:{TEXT};"
                    f"font-size:11px'>{name}</td>"
                    f"<td style='padding:5px 8px;text-align:center;"
                    f"color:{TEXT};font-size:11px'>{dur_str}</td>"
                    f"<td style='padding:5px 8px;text-align:center;"
                    f"color:{TEXT};font-size:11px'>{km_str}</td>"
                    f"<td style='padding:5px 8px;text-align:center;"
                    f"color:{TEXT};font-weight:600;font-size:11px'>{tss_str}</td>"
                    f"<td style='padding:5px 8px;text-align:center;"
                    f"color:{TEXT};font-size:11px'>{np_str}</td>"
                    f"<td style='padding:5px 8px;text-align:center;"
                    f"color:{TEXT};font-size:11px'>{if_str}</td>"
                    f"</tr>"
                )
                act_i += 1

        # ── Compose full HTML ──
        ftp_line = ""
        if ftp_val:
            ftp_line = f"FTP: {ftp_val} W"
            if weight_val:
                ftp_line += f"&nbsp;&nbsp;·&nbsp;&nbsp;Peso: {weight_val:.0f} kg"

        generated = f"Generado: {today.day} de {_MF[today.month]} de {today.year}"

        TH = (f"text-align:center;padding:8px 10px;color:{TEXT_MUT};font-size:11px;"
              f"font-weight:700;text-transform:uppercase;"
              f"border-bottom:2px solid {BORD_D}")
        TH_L = TH.replace("text-align:center", "text-align:left")
        ATH = (f"text-align:center;padding:6px 8px;color:{TEXT_MUT};font-size:10px;"
               f"font-weight:700;text-transform:uppercase;"
               f"border-bottom:2px solid {BORD_D}")
        ATH_L = ATH.replace("text-align:center", "text-align:left")

        html = f"""
        <html><body style="font-family:'Segoe UI',Arial,sans-serif;
            background:{BG};color:{TEXT};margin:0;padding:30px 36px">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td><h1 style="color:{ACCENT};font-size:22px;margin:0">
                Informe {kind} — {month_name} {today.year}</h1>
                <div style="color:{TEXT_MUT};font-size:12px;margin-top:4px">
                    Resumen de entrenamiento</div>
            </td>
            <td style="text-align:right;vertical-align:top;
                color:{TEXT_DIM};font-size:11px">
                Ciclométricas<br/>{generated}
            </td>
        </tr></table>
        <hr style="border:none;border-top:2px solid {ACCENT};
            margin:10px 0 14px 0"/>
        <div style="color:{TEXT_MUT};font-size:12px;margin-bottom:14px">
            {ftp_line}</div>

        <table width="100%" cellspacing="6" cellpadding="0"
               style="border-collapse:separate">{kpi_row1}</table>
        <table width="100%" cellspacing="6" cellpadding="0"
               style="border-collapse:separate;margin-top:6px">{kpi_row2}</table>

        <h3 style="color:{ACCENT};font-size:15px;margin:22px 0 6px 0">
            Desglose {kind}</h3>
        <table width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse">
            <thead><tr>
                <th style="{TH_L}">{col_label.upper()}</th>
                <th style="{TH}">ENTRENOS</th>
                <th style="{TH}">HORAS</th>
                <th style="{TH}">KM</th>
                <th style="{TH}">TSS</th>
            </tr></thead>
            <tbody>{weekly_rows_html}</tbody>
        </table>

        <h3 style="color:{ACCENT};font-size:15px;margin:22px 0 6px 0">
            Distribución por zonas de potencia</h3>
        <table width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse">
            <tr>{zone_bar_parts}</tr>
        </table>
        <table cellspacing="0" cellpadding="0"
               style="border-collapse:collapse;margin-top:6px">
            {zone_legend_parts}
        </table>

        <h3 style="color:{ACCENT};font-size:15px;margin:22px 0 6px 0">
            Entrenamientos destacados (por TSS)</h3>
        <table width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse">
            <thead><tr>
                <th style="{ATH_L}">FECHA</th>
                <th style="{ATH_L}">ACTIVIDAD</th>
                <th style="{ATH}">DUR.</th>
                <th style="{ATH}">KM</th>
                <th style="{ATH}">TSS</th>
                <th style="{ATH}">NP</th>
                <th style="{ATH}">IF</th>
            </tr></thead>
            <tbody>{top_acts_html}</tbody>
        </table>

        <hr style="border:none;border-top:1px solid {BORD};
            margin:28px 0 8px 0"/>
        <div style="text-align:center;color:{TEXT_DIM};font-size:9px">
            Ciclométricas · Informe generado automáticamente ·
            {month_name} {today.year}
        </div>
        </body></html>
        """

        # Render to PDF
        printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        layout = QPageLayout(
            QPageSize(QPageSize.PageSizeId.A4),
            QPageLayout.Orientation.Portrait,
            QMarginsF(15, 15, 15, 15),
        )
        printer.setPageLayout(layout)

        from PySide6.QtWidgets import QTextEdit
        doc = QTextEdit()
        doc.setHtml(html)
        doc.document().print_(printer)

        import os
        if os.path.exists(path):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "PDF generado",
                f"Informe guardado correctamente:\n{path}",
            )


# ── Zones chart tooltip (crosshair + text overlay) ───────────

class _ZonesTooltipProxy:
    """Adds a vertical crosshair + styled tooltip on hover to the zones chart."""

    def __init__(self, pw: pg.PlotWidget, rows: list,
                 pct_matrix: Dict[str, np.ndarray],
                 secs_matrix: Dict[str, np.ndarray],
                 tick_labels: list, is_weekly: bool):
        self._pw = pw
        self._rows = rows
        self._pct = pct_matrix
        self._secs = secs_matrix
        self._labels = tick_labels
        self._is_weekly = is_weekly

        # Crosshair line
        self._vline = pg.InfiniteLine(angle=90, movable=False,
                                       pen=pg.mkPen(COLORS["fg_dim"], width=1, style=Qt.PenStyle.DashLine))
        self._vline.setVisible(False)
        pw.addItem(self._vline, ignoreBounds=True)

        # HTML text item for rich tooltip
        self._text = pg.TextItem(
            html="",
            anchor=(0, 1),
            border=pg.mkPen(COLORS["fg_dim"], width=1),
            fill=QColor(COLORS["bg_card"]),
        )
        self._text.setVisible(False)
        pw.addItem(self._text, ignoreBounds=True)

        pw.scene().sigMouseMoved.connect(self._on_mouse_moved)

    def _on_mouse_moved(self, pos):
        vb = self._pw.plotItem.vb
        if not vb.sceneBoundingRect().contains(pos):
            self._vline.setVisible(False)
            self._text.setVisible(False)
            return

        mouse_point = vb.mapSceneToView(pos)
        idx = int(round(mouse_point.x()))
        if idx < 0 or idx >= len(self._rows):
            self._vline.setVisible(False)
            self._text.setVisible(False)
            return

        self._vline.setPos(idx)
        self._vline.setVisible(True)

        # Build HTML tooltip
        row = self._rows[idx]
        if self._is_weekly:
            header = f"{row['key']}<br/><span style='color:{COLORS['fg_muted']};font-size:9px'>{row.get('sublabel', '')}</span>"
        else:
            header = row["label"]

        lines = [f"<div style='font-weight:600;font-size:11px;color:{COLORS['fg']};margin-bottom:4px'>{header}</div>"]
        # Show all zones in reverse order (highest zone first) for better readability
        for k in reversed(_ZONE_KEYS):
            pct_val = self._pct[k][idx]
            secs = self._secs[k][idx]
            if pct_val < 0.3:
                continue
            mins = round(secs / 60)
            hrs = mins // 60
            rm = mins % 60
            t_str = f"{hrs}h{rm:02d}m" if hrs > 0 else f"{mins}min"
            lbl = _ZONE_LABELS.get(k, k)
            clr = _ZONE_COLORS.get(k, "#888")
            lines.append(
                f"<div style='font-size:10px;color:{COLORS['fg']};margin:1px 0'>"
                f"<span style='color:{clr}'>●</span> "
                f"<b>{lbl}</b>  {pct_val:.0f}%  "
                f"<span style='color:{COLORS['fg_muted']}'>{t_str}</span>"
                f"</div>"
            )

        html = (
            f"<div style='background:{COLORS['bg_card']};padding:6px 10px;"
            f"border-radius:6px;min-width:120px'>"
            + "\n".join(lines)
            + "</div>"
        )
        self._text.setHtml(html)

        # Position tooltip near the mouse Y, clamped within chart range
        mouse_y = min(95, max(10, mouse_point.y()))
        if idx > len(self._rows) * 0.7:
            self._text.setAnchor((1, 0))
            self._text.setPos(idx - 0.5, mouse_y)
        else:
            self._text.setAnchor((0, 0))
            self._text.setPos(idx + 0.5, mouse_y)
        self._text.setVisible(True)