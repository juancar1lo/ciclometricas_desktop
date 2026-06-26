"""Vista de métricas de salud — Health Metrics module.

Formulario de entrada, gráficos activos (pyqtgraph) y tabla historial
con edición/borrado inline.

Orden de campos / columnas:
  FC reposo → HRV → Fuente Readiness → Readiness → PA sist → PA diast → Peso → Grasa corp → Grasa subc

Orden de gráficos:
  1. Cardiovascular (FC reposo, HRV, Readiness)
  2. Presión arterial (candlestick: vela de diast→sist)
  3. Composición corporal (Peso, Grasa corp, Grasa subc)
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone, date
from typing import Optional, List, Tuple

from PySide6.QtCore import Qt, Signal, QPointF
from i18n import tr, hr_unit
from PySide6.QtWidgets import (
    QCalendarWidget, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor, QPen, QBrush, QFont

try:
    import pyqtgraph as pg
    from pyqtgraph import SignalProxy
    import numpy as np
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from db.engine import get_session
from db.models import HealthMetric
from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_LG, FONT_SIZE_TITLE,
    FONT_SIZE_XS, FONT_SIZE_MD,
)
from ui.dialogs import confirmar


# ── Normalización de Readiness a escala 1-10 ─────────────────────────
def _readiness_sources():
    return [
        (tr("manual"), tr("Manual (1-10)")),
        ("garmin", "Garmin (1-100)"),
        ("whoop", "Whoop (1-100)"),
        ("oura", "Oura (1-100)"),
        ("coros", "COROS (1-100)"),
        ("ehrv", "Elite HRV (1-10)"),
    ]


def normalize_readiness(raw: float, source: str) -> float:
    """Normaliza un valor de readiness a escala 1-10."""
    if source in (tr("manual"), "ehrv"):
        return max(1.0, min(10.0, raw))
    # Garmin, Whoop, Oura, COROS → 1-100 → 1-10
    clamped = max(1.0, min(100.0, raw))
    return round(1 + (clamped - 1) * 9 / 99, 1)


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d %b %Y")


def _make_card(title_text: str, description: str = "") -> QFrame:
    card = QFrame()
    card.setProperty("class", "card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(12)
    t = QLabel(title_text)
    t.setStyleSheet(
        f"font-size: {FONT_SIZE_LG}; font-weight: 600; color: {COLORS['fg']};"
    )
    layout.addWidget(t)
    if description:
        d = QLabel(description)
        d.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        d.setWordWrap(True)
        layout.addWidget(d)
    return card


# ── BP classification ─────────────────────────────────────────────────
def _bp_bands():
    return [
        {"label": tr("Óptima"),  "s_min": 60,  "s_max": 120, "color": "#22C55E"},
        {"label": tr("Normal"),  "s_min": 120, "s_max": 130, "color": "#84CC16"},
        {"label": tr("Elevada"), "s_min": 130, "s_max": 140, "color": "#EAB308"},
        {"label": tr("Alta"),    "s_min": 140, "s_max": 250, "color": "#EF4444"},
    ]


def _classify_bp(sys: float) -> dict:
    bands = _bp_bands()
    for b in reversed(bands):
        if sys >= b["s_min"]:
            return b
    return bands[0]


# ── Tooltip flotante para pyqtgraph ───────────────────────────────────
class ChartTooltip:
    """Crosshair vertical + texto flotante que muestra datos del punto más cercano.

    No requiere 'atrapar' un punto: basta con mover el ratón sobre el gráfico.
    Se recrea completamente tras cada chart.clear() para evitar conexiones rotas.
    """

    def __init__(self, plot_widget: "pg.PlotWidget", format_fn):
        self.pw = plot_widget
        self.format_fn = format_fn
        self.data_points: list = []  # [(timestamp, dict_of_values), ...]
        self.proxy = None

        self._create_items()
        self._connect_proxy()

    def _create_items(self):
        """Crea los items visuales (crosshair + label) y los añade al plot."""
        # Línea vertical (crosshair)
        self.vline = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen(COLORS["fg_muted"], width=1, style=Qt.PenStyle.DashLine))
        self.vline.setZValue(100)
        self.pw.addItem(self.vline, ignoreBounds=True)
        self.vline.setVisible(False)

        # Etiqueta de texto
        self.label = pg.TextItem(anchor=(0, 1), fill=pg.mkBrush(COLORS["bg_card"] + "E6"),
                                 border=pg.mkPen(COLORS["fg_muted"], width=1))
        self.label.setZValue(110)
        self.pw.addItem(self.label, ignoreBounds=True)
        self.label.setVisible(False)

    def _connect_proxy(self):
        """(Re)conecta el SignalProxy al sigMouseMoved de la escena."""
        self.proxy = SignalProxy(self.pw.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_move)

    def set_data(self, points: list):
        """points = [(timestamp, {key: value, ...}), ...] ya ordenados por timestamp."""
        self.data_points = points

    def reattach(self):
        """Recrea items visuales y reconecta el proxy tras chart.clear()."""
        self._create_items()
        self._connect_proxy()

    def _on_mouse_move(self, evt):
        pos = evt[0]
        if not self.data_points:
            self.vline.setVisible(False)
            self.label.setVisible(False)
            return

        vb = self.pw.plotItem.vb
        if not self.pw.sceneBoundingRect().contains(pos):
            self.vline.setVisible(False)
            self.label.setVisible(False)
            return

        mouse_point = vb.mapSceneToView(pos)
        mx = mouse_point.x()

        # Buscar punto más cercano por timestamp
        best_idx = 0
        best_dist = abs(self.data_points[0][0] - mx)
        for i, (ts, _) in enumerate(self.data_points):
            d = abs(ts - mx)
            if d < best_dist:
                best_dist = d
                best_idx = i

        ts, values = self.data_points[best_idx]
        self.vline.setPos(ts)
        self.vline.setVisible(True)

        text = self.format_fn(ts, values)
        self.label.setHtml(text)

        # Detectar si el tooltip se saldría por la derecha y voltear ancla
        view_range = vb.viewRange()
        x_min, x_max = view_range[0]
        visible_width = x_max - x_min
        if mx > x_max - visible_width * 0.20:
            self.label.setAnchor((1, 1))   # renderizar a la izquierda del cursor
        else:
            self.label.setAnchor((0, 1))   # renderizar a la derecha (normal)

        self.label.setPos(mouse_point.x(), mouse_point.y())
        self.label.setVisible(True)


# ── CSV import/export constants ───────────────────────────────────
_CSV_HEADER = (
    "Fecha;Peso (kg);FC reposo (ppm);HRV (ms);"
    "Grasa corporal (%);Grasa subcutánea (%);"
    "PA sistólica (mmHg);PA diastólica (mmHg);"
    "Readiness (1-10);Fuente Readiness;Notas"
)

# Mapeo bidireccional: clave interna ↔ etiqueta CSV
_SOURCE_KEY_TO_LABEL = {
    "ehrv": "EHRV", "garmin": "Garmin", "whoop": "Whoop",
    "oura": "Oura", "coros": "COROS", "manual": "Manual",
}
_SOURCE_LABEL_TO_KEY = {v.lower(): k for k, v in _SOURCE_KEY_TO_LABEL.items()}


def _parse_float(val: str) -> Optional[float]:
    """Parse a float from a CSV cell, return None if empty/invalid."""
    val = val.strip().replace(",", ".")
    if not val or val == "—":
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_int(val: str) -> Optional[int]:
    """Parse an int from a CSV cell, return None if empty/invalid."""
    f = _parse_float(val)
    return int(round(f)) if f is not None else None


def _parse_date(val: str) -> Optional[datetime]:
    """Parse a date string (YYYY-MM-DD or DD/MM/YYYY) to datetime UTC."""
    val = val.strip()
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            dt = datetime.strptime(val, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class HealthView(QWidget):
    """Vista completa de métricas de salud."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing_id: Optional[int] = None  # id del registro siendo editado
        self._custom_range: Optional[Tuple[date, date]] = None  # rango personalizado

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 28)
        main_layout.setSpacing(18)

        # Título
        title = QLabel(f"❤️\u200d🩹  {tr('Salud')}")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; color: {COLORS['fg']};"
        )
        main_layout.addWidget(title)
        desc = QLabel(
            tr("Registra FC reposo, HRV, Readiness, presión arterial, peso, composición corporal y notas. ") +
            tr("Los gráficos se actualizan en tiempo real.")
        )
        desc.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']};")
        desc.setWordWrap(True)
        main_layout.addWidget(desc)

        # ScrollArea para todo el contenido
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(18)

        # ── Formulario ──
        self._build_form(content_lay)

        # ── Importar / Exportar CSV ──
        self._build_csv_buttons(content_lay)

        # ── Selector de periodo para gráficos y tabla ──
        self._build_period_selector(content_lay)

        # ── Gráficos ──
        if HAS_PYQTGRAPH:
            self._build_charts(content_lay)
        else:
            lbl = QLabel(tr("⚠️ pyqtgraph no instalado — los gráficos no están disponibles."))
            lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
            content_lay.addWidget(lbl)

        # ── Tabla historial ──
        self._build_history_table(content_lay)

        content_lay.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll, stretch=1)

        self.refresh()

    # ================================================================
    # Formulario  (orden: FC rep → HRV → Fuente → Readiness → PA sist → PA diast → Peso → Grasa corp → Grasa subc)
    # ================================================================
    def _build_form(self, parent_lay: QVBoxLayout):
        card = _make_card(f"📝  {tr('Nuevo registro')}", tr("Introduce las métricas del día. Todos los campos son opcionales."))
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 1. Fecha
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setDisplayFormat("dd/MM/yyyy")
        # Estilo naranja para el día seleccionado (paridad con calendario del panel)
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
        cal_widget = self.date_input.calendarWidget()
        if cal_widget:
            cal_widget.setStyleSheet(_cal_ss)
        form.addRow(f"📅 {tr('Fecha')}:", self.date_input)

        # 2. FC reposo
        self.resting_hr_input = QSpinBox()
        self.resting_hr_input.setRange(0, 120)
        self.resting_hr_input.setSuffix(f" {hr_unit()}")
        self.resting_hr_input.setSpecialValueText("—")
        form.addRow(f"❤️ {tr('FC reposo')} ({hr_unit()}):", self.resting_hr_input)

        # 3. HRV
        self.hrv_input = QDoubleSpinBox()
        self.hrv_input.setRange(0, 300)
        self.hrv_input.setDecimals(1)
        self.hrv_input.setSuffix(" ms")
        self.hrv_input.setSpecialValueText("—")
        form.addRow("📈 HRV (RMSSD, ms):", self.hrv_input)

        # 4. Fuente Readiness
        readiness_row = QHBoxLayout()
        self.readiness_source_input = QComboBox()
        for key, label in _readiness_sources():
            self.readiness_source_input.addItem(label, key)
        readiness_row.addWidget(self.readiness_source_input)
        # 5. Readiness valor
        self.readiness_input = QDoubleSpinBox()
        self.readiness_input.setRange(0, 100)
        self.readiness_input.setDecimals(1)
        self.readiness_input.setSpecialValueText("—")
        readiness_row.addWidget(self.readiness_input)
        form.addRow(f"🎯 {tr('Readiness')}:", readiness_row)

        # 6. PA sistólica
        self.bp_sys_input = QSpinBox()
        self.bp_sys_input.setRange(0, 250)
        self.bp_sys_input.setSuffix(" mmHg")
        self.bp_sys_input.setSpecialValueText("—")
        form.addRow(tr("🩺 PA sistólica:"), self.bp_sys_input)

        # 7. PA diastólica
        self.bp_dia_input = QSpinBox()
        self.bp_dia_input.setRange(0, 200)
        self.bp_dia_input.setSuffix(" mmHg")
        self.bp_dia_input.setSpecialValueText("—")
        form.addRow(tr("🩺 PA diastólica:"), self.bp_dia_input)

        # 8. Peso
        self.weight_input = QDoubleSpinBox()
        self.weight_input.setRange(0, 200)
        self.weight_input.setDecimals(1)
        self.weight_input.setSuffix(" kg")
        self.weight_input.setSpecialValueText("—")
        form.addRow(tr("🏋️ Peso (kg):"), self.weight_input)

        # 9. Grasa corporal %
        self.body_fat_input = QDoubleSpinBox()
        self.body_fat_input.setRange(0, 60)
        self.body_fat_input.setDecimals(1)
        self.body_fat_input.setSuffix(" %")
        self.body_fat_input.setSpecialValueText("—")
        form.addRow(f"📊 {tr('Grasa corporal')} (%):", self.body_fat_input)

        # 10. Grasa subcutánea %
        self.subcut_fat_input = QDoubleSpinBox()
        self.subcut_fat_input.setRange(0, 60)
        self.subcut_fat_input.setDecimals(1)
        self.subcut_fat_input.setSuffix(" %")
        self.subcut_fat_input.setSpecialValueText("—")
        form.addRow(tr("📊 Grasa subcutánea (%):"), self.subcut_fat_input)

        # 11. Notas
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText(tr("Notas opcionales…"))
        form.addRow(tr("📝 Notas:"), self.notes_input)

        card.layout().addLayout(form)

        # Botones
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton(tr("💾  Guardar"))
        self.btn_save.setFixedHeight(42)
        self.btn_save.setMinimumWidth(180)
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)

        self.btn_cancel_edit = QPushButton(tr("✖  Cancelar edición"))
        self.btn_cancel_edit.setFixedHeight(42)
        self.btn_cancel_edit.setProperty("class", "ghost")
        self.btn_cancel_edit.setVisible(False)
        self.btn_cancel_edit.clicked.connect(self._cancel_edit)
        btn_row.addWidget(self.btn_cancel_edit)

        btn_row.addStretch()
        card.layout().addLayout(btn_row)

        parent_lay.addWidget(card)
        self._form_card = card

    # ================================================================
    # Gráficos (pyqtgraph) — Orden: 1.Cardiovascular  2.PA candlestick  3.Composición
    # ================================================================
    def _setup_dual_axis(self, plot_widget: "pg.PlotWidget", right_label: str, right_color: str = None):
        """Crea un segundo eje Y (derecho) con su propio ViewBox vinculado al eje X del plot principal."""
        # Crear ViewBox secundario
        vb2 = pg.ViewBox()
        plot_item = plot_widget.plotItem

        # Configurar eje derecho
        right_axis = plot_item.getAxis('right')
        right_axis.setLabel(right_label)
        if right_color:
            right_axis.setPen(pg.mkPen(right_color))
            right_axis.setTextPen(pg.mkPen(right_color))
        plot_item.showAxis('right')
        plot_item.scene().addItem(vb2)
        right_axis.linkToView(vb2)
        vb2.setXLink(plot_item)
        vb2.setMouseEnabled(x=False, y=False)

        # Mantener geometría sincronizada
        def _update_views():
            vb2.setGeometry(plot_item.vb.sceneBoundingRect())
            vb2.linkedViewChanged(plot_item.vb, vb2.XAxis)

        plot_item.vb.sigResized.connect(_update_views)
        _update_views()

        # Guardar callback para poder forzar sync tras refresh
        vb2._sync_geometry = _update_views

        return vb2

    # ================================================================
    # Selector de periodo
    # ================================================================
    def _build_period_selector(self, parent_lay: QVBoxLayout):
        row = QHBoxLayout()
        row.setSpacing(10)

        lbl = QLabel(tr("📅  Periodo:"))
        lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; font-weight: 600; color: {COLORS['fg']};"
        )
        row.addWidget(lbl)

        self._period_combo = QComboBox()
        self._period_combo.setFixedHeight(34)
        self._period_combo.setMinimumWidth(200)
        self._period_combo.addItems([
            tr("Últimos 30 días"),
            tr("Últimos 60 días"),
            tr("Últimos 90 días"),
            tr("Últimos 6 meses"),
            tr("Últimos 365 días"),
            tr("Todo el histórico"),
            tr("── Rango ──"),
            tr("Rango personalizado"),
        ])
        # Por defecto: Todo el histórico
        self._period_combo.setCurrentIndex(5)
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        row.addWidget(self._period_combo)

        # Etiqueta que muestra el rango personalizado activo
        self._range_label = QLabel("")
        self._range_label.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['primary']}; font-weight: 500;"
        )
        row.addWidget(self._range_label)

        row.addStretch()
        parent_lay.addLayout(row)

    def _on_period_changed(self, _idx: int) -> None:
        text = self._period_combo.currentText()
        # Ignorar separadores
        if text.startswith("──"):
            return
        # Rango personalizado → diálogo con dos calendarios
        if text == tr("Rango personalizado"):
            self._show_custom_range_dialog()
            return
        self._custom_range = None
        self._range_label.setText("")
        self.refresh()

    def _show_custom_range_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Seleccionar rango de fechas"))
        dlg.setMinimumWidth(520)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(12)

        lbl = QLabel(tr("Selecciona el rango de fechas para el análisis:"))
        lbl.setStyleSheet(f"color: {COLORS['fg']}; font-weight: 600;")
        lay.addWidget(lbl)

        cals_row = QHBoxLayout()
        from_lbl = QLabel(tr("Desde:"))
        from_lbl.setStyleSheet(f"color: {COLORS['fg_muted']};")
        to_lbl = QLabel(tr("Hasta:"))
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
            d1 = self._custom_range[0].strftime("%d/%m/%Y")
            d2 = self._custom_range[1].strftime("%d/%m/%Y")
            self._range_label.setText(f"{d1}  →  {d2}")
            self.refresh()
        else:
            # Revertir combo a la opción anterior segura
            self._period_combo.blockSignals(True)
            self._period_combo.setCurrentIndex(5)  # Todo el histórico
            self._period_combo.blockSignals(False)
            self._custom_range = None
            self._range_label.setText("")

    def _get_date_filter(self) -> Optional[Tuple[datetime, datetime]]:
        """Devuelve (desde, hasta) en datetime UTC según la selección del combo.
        None = sin filtro (todo el histórico)."""
        if self._custom_range:
            d_from, d_to = self._custom_range
            return (
                datetime(d_from.year, d_from.month, d_from.day, tzinfo=timezone.utc),
                datetime(d_to.year, d_to.month, d_to.day, 23, 59, 59, tzinfo=timezone.utc),
            )

        text = self._period_combo.currentText()
        _PERIOD_DAYS = {
            tr("Últimos 30 días"): 30,
            tr("Últimos 60 días"): 60,
            tr("Últimos 90 días"): 90,
            tr("Últimos 6 meses"): 180,
            tr("Últimos 365 días"): 365,
        }
        days = _PERIOD_DAYS.get(text)
        if days is None:
            return None  # Todo el histórico
        now = datetime.now(timezone.utc)
        return (now - timedelta(days=days), now)

    # ================================================================
    # Gráficos
    # ================================================================
    def _build_charts(self, parent_lay: QVBoxLayout):
        pg.setConfigOption('background', COLORS['bg_card'])
        pg.setConfigOption('foreground', COLORS['fg'])

        # ── 1. Cardiovascular + Readiness (dual Y) ──
        card1 = _make_card(tr("❤️  Cardiovascular y Readiness"),
                           f"{tr('FC reposo')} ({hr_unit()}), HRV (ms) — {tr('eje izq.')}  |  Readiness (1-10) — {tr('eje der.')}")
        self.chart_cardio = pg.PlotWidget()
        self.chart_cardio.setMinimumHeight(260)
        self.chart_cardio.showGrid(x=True, y=True, alpha=0.15)
        self.chart_cardio.addLegend(offset=(10, 10))
        self.chart_cardio.setMouseEnabled(x=False, y=False)
        self.chart_cardio.setMenuEnabled(False)
        self.chart_cardio.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.chart_cardio.setLabel('left', f'{hr_unit()} / ms')
        # Segundo eje Y para Readiness
        self._vb_cardio_right = self._setup_dual_axis(self.chart_cardio, 'Readiness (1-10)', '#F59E0B')
        card1.layout().addWidget(self.chart_cardio)
        parent_lay.addWidget(card1)

        # ── 2. Presión arterial (candlestick) ──
        card2 = _make_card(tr("🩺  Presión arterial"),
                           tr("Sistólica y diastólica (mmHg) — rango representado como velas"))
        self.chart_bp = pg.PlotWidget()
        self.chart_bp.setMinimumHeight(260)
        self.chart_bp.showGrid(x=True, y=True, alpha=0.15)
        self.chart_bp.setMouseEnabled(x=False, y=False)
        self.chart_bp.setMenuEnabled(False)
        self.chart_bp.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.chart_bp.setLabel('left', 'mmHg')
        card2.layout().addWidget(self.chart_bp)
        parent_lay.addWidget(card2)

        # ── 3. Composición corporal (dual Y) ──
        card3 = _make_card(tr("📊  Composición corporal"),
                           tr("Peso (kg) — eje izq.  |  Grasa corporal y subcutánea (%) — eje der."))
        self.chart_body = pg.PlotWidget()
        self.chart_body.setMinimumHeight(260)
        self.chart_body.showGrid(x=True, y=True, alpha=0.15)
        self.chart_body.addLegend(offset=(10, 10))
        self.chart_body.setMouseEnabled(x=False, y=False)
        self.chart_body.setMenuEnabled(False)
        self.chart_body.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.chart_body.setLabel('left', 'kg')
        # Segundo eje Y para porcentajes
        self._vb_body_right = self._setup_dual_axis(self.chart_body, 'Grasa (%)', '#FF9149')
        card3.layout().addWidget(self.chart_body)
        parent_lay.addWidget(card3)

    # ================================================================
    # Tabla historial  (orden: Fecha, FC rep, HRV, Readiness, PA sist, PA diast, Peso, Grasa %, Grasa sub, Notas)
    # ================================================================
    def _build_history_table(self, parent_lay: QVBoxLayout):
        card = _make_card(f"🕐  {tr('Historial de registros')}",
                          tr("Haz clic en ✏️ para editar o 🗑 para eliminar."))
        self.history_table = QTableWidget()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)

        cols = [
            tr("Fecha"), tr("FC rep."), "HRV", "Readiness",
            tr("PA sist."), tr("PA diast."), tr("Peso"), tr("Grasa %"), tr("Grasa sub."),
            tr("Notas"), "", "",
        ]
        self.history_table.setColumnCount(len(cols))
        self.history_table.setHorizontalHeaderLabels(cols)
        hdr = self.history_table.horizontalHeader()
        for i in range(len(cols) - 2):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(cols) - 3, QHeaderView.ResizeMode.Stretch)  # Notas
        hdr.setSectionResizeMode(len(cols) - 2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.ResizeToContents)

        card.layout().addWidget(self.history_table)
        parent_lay.addWidget(card, stretch=1)

    # ================================================================
    # CSV Importar / Exportar
    # ================================================================
    def _build_csv_buttons(self, parent_lay: QVBoxLayout):
        row = QHBoxLayout()
        row.setSpacing(12)

        btn_import = QPushButton(tr("📥  Importar CSV"))
        btn_import.setFixedHeight(38)
        btn_import.setMinimumWidth(170)
        btn_import.setToolTip(
            tr("Importa métricas de salud desde un archivo .csv\n"
               "(formato Ciclométricas Web o cualquier hoja de cálculo\n"
               " con las mismas columnas separadas por ';')")
        )
        btn_import.clicked.connect(self._on_import_csv)
        row.addWidget(btn_import)

        btn_export = QPushButton(tr("📤  Exportar CSV"))
        btn_export.setFixedHeight(38)
        btn_export.setMinimumWidth(170)
        btn_export.setToolTip(
            tr("Exporta todos los registros de salud a un archivo .csv\n"
               "compatible con Ciclométricas Web y hojas de cálculo")
        )
        btn_export.clicked.connect(self._on_export_csv)
        row.addWidget(btn_export)

        row.addStretch()
        parent_lay.addLayout(row)

    # ── Exportar ──────────────────────────────────────────────────────
    def _on_export_csv(self):
        session = get_session()
        try:
            metrics = (
                session.query(HealthMetric)
                .order_by(HealthMetric.date.asc())
                .all()
            )
            session.expunge_all()
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), f"{tr('Error al leer datos')}: {e}")
            return
        finally:
            session.close()

        if not metrics:
            QMessageBox.information(self, tr("Sin datos"), tr("No hay registros de salud para exportar."))
            return

        default_name = f"salud_ciclometricas_{date.today().isoformat()}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Exportar CSV de salud"), default_name,
            tr("Archivos CSV (*.csv);;Todos los archivos (*)"),
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(_CSV_HEADER + "\n")
                for m in metrics:
                    row_vals = [
                        m.date.strftime("%Y-%m-%d") if m.date else "",
                        f"{m.weight_kg:.1f}" if m.weight_kg is not None else "",
                        str(m.resting_hr) if m.resting_hr is not None else "",
                        f"{m.hrv:.1f}" if m.hrv is not None else "",
                        f"{m.body_fat_pct:.1f}" if m.body_fat_pct is not None else "",
                        f"{m.subcutaneous_fat_pct:.1f}" if m.subcutaneous_fat_pct is not None else "",
                        str(m.bp_systolic) if m.bp_systolic is not None else "",
                        str(m.bp_diastolic) if m.bp_diastolic is not None else "",
                        f"{m.readiness:.1f}" if m.readiness is not None else "",
                        _SOURCE_KEY_TO_LABEL.get(m.readiness_source or "", m.readiness_source or ""),
                        f'"{m.notes.replace(chr(34), chr(34)+chr(34))}"' if m.notes else "",
                    ]
                    f.write(";".join(row_vals) + "\n")

            QMessageBox.information(
                self, tr("Exportado"),
                tr("Se exportaron {} registros a:\n{}").format(len(metrics), path),
            )
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), f"{tr('Error al escribir CSV')}: {e}")

    # ── Importar ──────────────────────────────────────────────────────
    def _on_import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Importar CSV de salud"), "",
            tr("Archivos CSV (*.csv);;Todos los archivos (*)"),
        )
        if not path:
            return

        try:
            # Leer el archivo detectando BOM
            with open(path, "r", encoding="utf-8-sig") as f:
                raw = f.read()
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), f"{tr('No se pudo leer el archivo')}: {e}")
            return

        # Detectar separador: si la primera línea tiene ';' usamos ';', si no ','
        first_line = raw.split("\n", 1)[0]
        sep = ";" if ";" in first_line else ","

        reader = csv.reader(io.StringIO(raw), delimiter=sep)
        rows = list(reader)
        if len(rows) < 2:
            QMessageBox.warning(self, tr("CSV vacío"), tr("El archivo no contiene datos."))
            return

        # Mapear cabeceras a índices (flexible: busca por contenido parcial)
        header = [h.strip().lower() for h in rows[0]]
        col_map = {}
        _KEYWORDS = {
            "fecha": "date", "date": "date",
            "peso": "weight", "weight": "weight",
            "fc reposo": "rhr", "fc rep": "rhr", "resting": "rhr", "resting_hr": "rhr",
            "hrv": "hrv",
            "grasa corporal": "fat", "body fat": "fat", "grasa corp": "fat",
            "grasa subcut": "subfat", "subcutaneous": "subfat", "grasa sub": "subfat",
            "sistólica": "sys", "sistolica": "sys", "systolic": "sys", "pa sist": "sys",
            "diastólica": "dia", "diastolica": "dia", "diastolic": "dia", "pa diast": "dia",
            "readiness": "readiness",
            "fuente": "source", "source": "source",
            "notas": "notes", "notes": "notes",
        }
        for idx, h in enumerate(header):
            for keyword, field in _KEYWORDS.items():
                if keyword in h and field not in col_map:
                    col_map[field] = idx
                    break

        if "date" not in col_map:
            QMessageBox.warning(
                self, tr("Formato inválido"),
                tr("No se encontró una columna de 'Fecha' en el CSV.\n"
                   "La primera fila debe contener las cabeceras."),
            )
            return

        # Procesar filas
        imported = 0
        updated = 0
        skipped = 0
        errors = []

        session = get_session()
        try:
            for row_num, row in enumerate(rows[1:], start=2):
                if not row or all(c.strip() == "" for c in row):
                    continue  # fila vacía

                # Parsear fecha
                date_val = _parse_date(row[col_map["date"]]) if "date" in col_map and col_map["date"] < len(row) else None
                if not date_val:
                    errors.append(f"{tr('Fila')} {row_num}: {tr('fecha inválida')}")
                    skipped += 1
                    continue

                # Extraer campos
                def _get(field: str) -> str:
                    idx = col_map.get(field)
                    if idx is not None and idx < len(row):
                        return row[idx].strip()
                    return ""

                weight = _parse_float(_get("weight"))
                rhr = _parse_int(_get("rhr"))
                hrv = _parse_float(_get("hrv"))
                fat = _parse_float(_get("fat"))
                subfat = _parse_float(_get("subfat"))
                sys_bp = _parse_int(_get("sys"))
                dia_bp = _parse_int(_get("dia"))
                readiness = _parse_float(_get("readiness"))

                # Fuente readiness
                source_raw = _get("source").strip().lower()
                readiness_source = _SOURCE_LABEL_TO_KEY.get(source_raw, source_raw if source_raw else None)
                if readiness is None:
                    readiness_source = None

                notes_raw = _get("notes")
                # Quitar comillas envolventes de CSV
                if notes_raw.startswith('"') and notes_raw.endswith('"'):
                    notes_raw = notes_raw[1:-1].replace('""', '"')
                notes = notes_raw or None

                # Al menos un valor debe existir
                if all(v is None for v in [weight, rhr, hrv, fat, subfat, sys_bp, dia_bp, readiness]):
                    skipped += 1
                    continue

                # Upsert por fecha (inicio y fin del día)
                day_start = date_val.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = date_val.replace(hour=23, minute=59, second=59, microsecond=999999)
                existing = (
                    session.query(HealthMetric)
                    .filter(HealthMetric.date >= day_start, HealthMetric.date <= day_end)
                    .first()
                )

                if existing:
                    # Actualizar campos no nulos (merge: importado rellena lo que falta)
                    if weight is not None: existing.weight_kg = weight
                    if rhr is not None: existing.resting_hr = rhr
                    if hrv is not None: existing.hrv = hrv
                    if fat is not None: existing.body_fat_pct = fat
                    if subfat is not None: existing.subcutaneous_fat_pct = subfat
                    if sys_bp is not None: existing.bp_systolic = sys_bp
                    if dia_bp is not None: existing.bp_diastolic = dia_bp
                    if readiness is not None:
                        existing.readiness = readiness
                        existing.readiness_source = readiness_source
                    if notes is not None: existing.notes = notes
                    updated += 1
                else:
                    metric = HealthMetric(
                        date=day_start,
                        weight_kg=weight,
                        body_fat_pct=fat,
                        subcutaneous_fat_pct=subfat,
                        resting_hr=rhr,
                        hrv=hrv,
                        readiness=readiness,
                        readiness_source=readiness_source,
                        bp_systolic=sys_bp,
                        bp_diastolic=dia_bp,
                        notes=notes,
                    )
                    session.add(metric)
                    imported += 1

            session.commit()
        except Exception as e:
            session.rollback()
            QMessageBox.warning(self, tr("Error"), f"{tr('Error al importar')}: {e}")
            return
        finally:
            session.close()

        # Resumen
        msg_parts = []
        if imported:
            msg_parts.append(tr("{} registros nuevos").format(imported))
        if updated:
            msg_parts.append(tr("{} registros actualizados").format(updated))
        if skipped:
            msg_parts.append(tr("{} filas omitidas").format(skipped))

        summary = "\n".join(msg_parts) if msg_parts else tr("No se importaron datos.")
        if errors:
            summary += "\n\n" + tr("Errores:") + "\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                summary += f"\n... (+{len(errors) - 10} más)"

        QMessageBox.information(self, tr("Importación completada"), summary)
        self.refresh()

    # ================================================================
    # Acciones
    # ================================================================
    def _on_save(self):
        qdate = self.date_input.date()
        dt = datetime(qdate.year(), qdate.month(), qdate.day(), tzinfo=timezone.utc)

        weight = self.weight_input.value() if self.weight_input.value() > 0 else None
        body_fat = self.body_fat_input.value() if self.body_fat_input.value() > 0 else None
        subcut = self.subcut_fat_input.value() if self.subcut_fat_input.value() > 0 else None
        resting_hr = self.resting_hr_input.value() if self.resting_hr_input.value() > 0 else None
        hrv = self.hrv_input.value() if self.hrv_input.value() > 0 else None
        raw_readiness = self.readiness_input.value()
        source_key = self.readiness_source_input.currentData()
        readiness = normalize_readiness(raw_readiness, source_key) if raw_readiness > 0 else None
        readiness_source = source_key if readiness is not None else None
        bp_sys = self.bp_sys_input.value() if self.bp_sys_input.value() > 0 else None
        bp_dia = self.bp_dia_input.value() if self.bp_dia_input.value() > 0 else None
        notes = self.notes_input.text().strip() or None

        # Al menos un campo debe tener valor
        if all(v is None for v in [weight, body_fat, subcut, resting_hr, hrv, readiness, bp_sys]):
            QMessageBox.warning(self, tr("Sin datos"), tr("Introduce al menos un valor."))
            return

        session = get_session()
        try:
            if self._editing_id:
                metric = session.query(HealthMetric).filter_by(id=self._editing_id).first()
                if metric:
                    metric.date = dt
                    metric.weight_kg = weight
                    metric.body_fat_pct = body_fat
                    metric.subcutaneous_fat_pct = subcut
                    metric.resting_hr = resting_hr
                    metric.hrv = hrv
                    metric.readiness = readiness
                    metric.readiness_source = readiness_source
                    metric.bp_systolic = bp_sys
                    metric.bp_diastolic = bp_dia
                    metric.notes = notes
            else:
                metric = HealthMetric(
                    date=dt,
                    weight_kg=weight,
                    body_fat_pct=body_fat,
                    subcutaneous_fat_pct=subcut,
                    resting_hr=resting_hr,
                    hrv=hrv,
                    readiness=readiness,
                    readiness_source=readiness_source,
                    bp_systolic=bp_sys,
                    bp_diastolic=bp_dia,
                    notes=notes,
                )
                session.add(metric)
            session.commit()
        except Exception as e:
            session.rollback()
            QMessageBox.warning(self, tr("Error"), f"{tr('Error al guardar')}: {e}")
            return
        finally:
            session.close()

        self._clear_form()
        self.refresh()

    def _on_edit(self, metric_id: int):
        session = get_session()
        try:
            m = session.query(HealthMetric).filter_by(id=metric_id).first()
            if not m:
                return
            session.expunge(m)
        finally:
            session.close()

        self._editing_id = m.id
        self.btn_save.setText(f"💾  {tr('Actualizar')}")
        self.btn_cancel_edit.setVisible(True)

        self.date_input.setDate(QDate(m.date.year, m.date.month, m.date.day))
        self.resting_hr_input.setValue(m.resting_hr or 0)
        self.hrv_input.setValue(m.hrv or 0)
        self.readiness_input.setValue(m.readiness or 0)
        if m.readiness_source:
            idx = self.readiness_source_input.findData(m.readiness_source)
            if idx >= 0:
                self.readiness_source_input.setCurrentIndex(idx)
        self.bp_sys_input.setValue(m.bp_systolic or 0)
        self.bp_dia_input.setValue(m.bp_diastolic or 0)
        self.weight_input.setValue(m.weight_kg or 0)
        self.body_fat_input.setValue(m.body_fat_pct or 0)
        self.subcut_fat_input.setValue(m.subcutaneous_fat_pct or 0)
        self.notes_input.setText(m.notes or "")

        # Scroll al formulario
        self._form_card.parent().parent().ensureWidgetVisible(self._form_card)

    def _on_delete(self, metric_id: int):
        if not confirmar(self, tr("Confirmar"), tr("¿Eliminar este registro de salud?")):
            return
        session = get_session()
        try:
            m = session.query(HealthMetric).filter_by(id=metric_id).first()
            if m:
                session.delete(m)
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()
        self.refresh()

    def _cancel_edit(self):
        self._editing_id = None
        self.btn_save.setText(tr("💾  Guardar"))
        self.btn_cancel_edit.setVisible(False)
        self._clear_form()

    def _clear_form(self):
        self._editing_id = None
        self.btn_save.setText(tr("💾  Guardar"))
        self.btn_cancel_edit.setVisible(False)
        self.date_input.setDate(QDate.currentDate())
        self.resting_hr_input.setValue(0)
        self.hrv_input.setValue(0)
        self.readiness_input.setValue(0)
        self.readiness_source_input.setCurrentIndex(0)
        self.bp_sys_input.setValue(0)
        self.bp_dia_input.setValue(0)
        self.weight_input.setValue(0)
        self.body_fat_input.setValue(0)
        self.subcut_fat_input.setValue(0)
        self.notes_input.clear()

    # ================================================================
    # Refresh
    # ================================================================
    def refresh(self):
        session = get_session()
        try:
            q = session.query(HealthMetric)
            date_filter = self._get_date_filter()
            if date_filter:
                dt_from, dt_to = date_filter
                q = q.filter(HealthMetric.date >= dt_from, HealthMetric.date <= dt_to)
            metrics = q.order_by(HealthMetric.date.desc()).all()
            session.expunge_all()
        except Exception:
            metrics = []
        finally:
            session.close()

        self._refresh_table(metrics)
        if HAS_PYQTGRAPH:
            self._refresh_charts(metrics)

    # ── Tabla (orden: Fecha, FC rep, HRV, Readiness, PA sist, PA diast, Peso, Grasa %, Grasa sub, Notas) ──
    def _refresh_table(self, metrics: List[HealthMetric]):
        self.history_table.setRowCount(len(metrics))
        for row, m in enumerate(metrics):
            col = 0
            self.history_table.setItem(row, col, QTableWidgetItem(_fmt_date(m.date))); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.resting_hr} {hr_unit()}" if m.resting_hr else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.hrv:.1f} ms" if m.hrv else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.readiness:.1f}/10" if m.readiness else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.bp_systolic}" if m.bp_systolic else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.bp_diastolic}" if m.bp_diastolic else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.weight_kg:.1f} kg" if m.weight_kg else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.body_fat_pct:.1f}%" if m.body_fat_pct else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(
                f"{m.subcutaneous_fat_pct:.1f}%" if m.subcutaneous_fat_pct else "—")); col += 1
            self.history_table.setItem(row, col, QTableWidgetItem(m.notes or "—")); col += 1

            # Botón editar
            btn_edit = QPushButton(tr("✏️"))
            btn_edit.setFixedSize(34, 34)
            btn_edit.setProperty("class", "ghost")
            btn_edit.setToolTip(tr("Editar"))
            btn_edit.clicked.connect(lambda checked=False, mid=m.id: self._on_edit(mid))
            self.history_table.setCellWidget(row, col, btn_edit); col += 1

            # Botón eliminar
            btn_del = QPushButton("🗑")
            btn_del.setFixedSize(34, 34)
            btn_del.setProperty("class", "ghost")
            btn_del.setToolTip(tr("Eliminar"))
            btn_del.clicked.connect(lambda checked=False, mid=m.id: self._on_delete(mid))
            self.history_table.setCellWidget(row, col, btn_del)

    # ================================================================
    # Gráficos refresh
    # ================================================================
    def _refresh_charts(self, metrics: List[HealthMetric]):
        # Ordenar cronológicamente para gráficos
        sorted_m = sorted(metrics, key=lambda m: m.date)

        # Timestamps como float para eje X
        dates = [m.date.timestamp() for m in sorted_m]

        # ── 1. Cardiovascular + Readiness (dual Y) ──
        self.chart_cardio.clear()
        # Limpiar items del ViewBox derecho de forma segura
        for item in list(self._vb_cardio_right.addedItems):
            self._vb_cardio_right.removeItem(item)
        # Re-attach tooltip items tras clear()
        if hasattr(self, '_tooltip_cardio'):
            self._tooltip_cardio.reattach()

        rhr = [(d, m.resting_hr) for d, m in zip(dates, sorted_m) if m.resting_hr]
        hrvs = [(d, m.hrv) for d, m in zip(dates, sorted_m) if m.hrv]
        readiness_pts = [(d, m.readiness) for d, m in zip(dates, sorted_m) if m.readiness]

        # Eje izquierdo: FC reposo + HRV
        if rhr:
            xr, yr = zip(*rhr)
            self.chart_cardio.plot(xr, yr, pen=pg.mkPen('#FF6363', width=2),
                                  symbol='o', symbolSize=6, symbolBrush='#FF6363',
                                  name=f'{tr("FC reposo")} ({hr_unit()})')
        if hrvs:
            xh, yh = zip(*hrvs)
            self.chart_cardio.plot(xh, yh, pen=pg.mkPen('#80D8C3', width=2),
                                  symbol='t', symbolSize=6, symbolBrush='#80D8C3',
                                  name='HRV (ms)')

        # Eje derecho: Readiness (1-10) — plotear en ViewBox secundario
        if readiness_pts:
            xrd, yrd = np.array([p[0] for p in readiness_pts], dtype=float), np.array([p[1] for p in readiness_pts], dtype=float)
            readiness_curve = pg.PlotCurveItem(xrd, yrd, pen=pg.mkPen('#F59E0B', width=2), name='Readiness')
            readiness_scatter = pg.ScatterPlotItem(xrd, yrd, symbol='d', size=7,
                                                    brush=pg.mkBrush('#F59E0B'),
                                                    pen=pg.mkPen('#F59E0B'))
            self._vb_cardio_right.addItem(readiness_curve)
            self._vb_cardio_right.addItem(readiness_scatter)
            # Fijar rango del eje derecho a 0-10
            self._vb_cardio_right.setYRange(0, 10.5, padding=0)

            # Bandas de referencia Readiness en el ViewBox derecho
            bands_readiness = [
                (0, 3, '#FF636330', tr('Baja')),
                (3, 5, '#FF914930', tr('Moderada')),
                (5, 7, '#F59E0B20', tr('Buena')),
                (7, 10.5, '#80D8C320', tr('Óptima')),
            ]
            for y_lo, y_hi, color, _label in bands_readiness:
                region = pg.LinearRegionItem(
                    values=[y_lo, y_hi], orientation='horizontal',
                    brush=pg.mkBrush(color), movable=False,
                )
                region.setZValue(-10)
                self._vb_cardio_right.addItem(region)

            # Etiquetas de bandas en el margen derecho
            if dates:
                x_right = max(dates) + (max(dates) - min(dates)) * 0.02 if len(dates) > 1 else max(dates)
                for y_lo, y_hi, _c, label in bands_readiness:
                    txt = pg.TextItem(label, color=COLORS['fg_muted'], anchor=(1, 0.5))
                    txt.setPos(x_right, (y_lo + y_hi) / 2)
                    txt.setZValue(50)
                    font = QFont()
                    font.setPointSize(7)
                    txt.setFont(font)
                    self._vb_cardio_right.addItem(txt)
        else:
            self._vb_cardio_right.setYRange(0, 10.5, padding=0)

        # Forzar sincronización de geometría del ViewBox derecho
        if hasattr(self._vb_cardio_right, '_sync_geometry'):
            self._vb_cardio_right._sync_geometry()

        # Añadir Readiness a la leyenda del chart principal
        if readiness_pts:
            legend_item = pg.PlotDataItem(pen=pg.mkPen('#F59E0B', width=2),
                                          symbol='d', symbolSize=7, symbolBrush='#F59E0B',
                                          name='Readiness (1-10)')
            self.chart_cardio.addItem(legend_item)
            legend_item.setData([], [])  # invisible, solo para leyenda

        self._setup_date_axis(self.chart_cardio, dates)

        # Tooltip Cardiovascular
        cardio_data = []
        for d, m in zip(dates, sorted_m):
            if m.resting_hr or m.hrv or m.readiness:
                cardio_data.append((d, {
                    "resting_hr": m.resting_hr,
                    "hrv": m.hrv,
                    "readiness": m.readiness,
                }))

        def fmt_cardio(ts, vals):
            dt = datetime.fromtimestamp(ts)
            fg = COLORS['fg']
            html = (f'<div style="padding:4px 6px;">'
                    f'<b style="color:{fg};">{dt.strftime("%d %b %Y")}</b>')
            if vals.get("resting_hr"):
                html += f'<br/><span style="color:#FF6363;">● {tr("FC reposo")}:</span> <span style="color:{fg};">{vals["resting_hr"]} {hr_unit()}</span>'
            if vals.get("hrv"):
                html += f'<br/><span style="color:#80D8C3;">▲ HRV:</span> <span style="color:{fg};">{vals["hrv"]:.1f} ms</span>'
            if vals.get("readiness"):
                html += f'<br/><span style="color:#F59E0B;">◆ Readiness:</span> <span style="color:{fg};">{vals["readiness"]:.1f}/10</span>'
            html += '</div>'
            return html

        if not hasattr(self, '_tooltip_cardio'):
            self._tooltip_cardio = ChartTooltip(self.chart_cardio, fmt_cardio)
        else:
            self._tooltip_cardio.format_fn = fmt_cardio
        self._tooltip_cardio.set_data(cardio_data)

        # ── 2. Presión arterial (candlestick) + etiquetas de banda ──
        self.chart_bp.clear()
        # Re-attach tooltip items tras clear()
        if hasattr(self, '_tooltip_bp'):
            self._tooltip_bp.reattach()
        bp_points = [(d, m) for d, m in zip(dates, sorted_m)
                     if m.bp_systolic and m.bp_diastolic]

        if bp_points:
            # Dibujar velas: rectángulo de diastólica a sistólica para cada punto
            bar_width_sec = 86400 * 0.6  # ~0.6 días de ancho
            if len(bp_points) > 1:
                min_gap = min(bp_points[i+1][0] - bp_points[i][0] for i in range(len(bp_points) - 1))
                bar_width_sec = max(min_gap * 0.5, 3600)  # al menos 1h

            for ts, m in bp_points:
                sys_val = m.bp_systolic
                dia_val = m.bp_diastolic
                band = _classify_bp(sys_val)
                color = QColor(band["color"])

                bar = pg.BarGraphItem(
                    x=[ts], y=[dia_val], height=[sys_val - dia_val],
                    width=bar_width_sec,
                    brush=pg.mkBrush(color.red(), color.green(), color.blue(), 180),
                    pen=pg.mkPen(color, width=1),
                )
                self.chart_bp.addItem(bar)

            # Bandas de referencia PA
            all_sys = [m.bp_systolic for _, m in bp_points]
            all_dia = [m.bp_diastolic for _, m in bp_points]
            y_min = max(30, min(all_dia) - 10)
            y_max = max(all_sys) + 15
            self.chart_bp.setYRange(y_min, y_max)

            for b in _bp_bands():
                s_lo = max(b["s_min"], y_min)
                s_hi = min(b["s_max"], y_max)
                if s_lo < s_hi:
                    region = pg.LinearRegionItem(
                        values=[s_lo, s_hi], orientation='horizontal',
                        brush=pg.mkBrush(QColor(b["color"]).red(), QColor(b["color"]).green(),
                                         QColor(b["color"]).blue(), 15),
                        movable=False,
                    )
                    region.setZValue(-10)
                    self.chart_bp.addItem(region)

            # Etiquetas de clasificación en el margen derecho del gráfico
            bp_dates = [ts for ts, _ in bp_points]
            x_right = max(bp_dates) + (max(bp_dates) - min(bp_dates)) * 0.02 if len(bp_dates) > 1 else max(bp_dates)
            for b in _bp_bands():
                s_lo = max(b["s_min"], y_min)
                s_hi = min(b["s_max"], y_max)
                if s_lo < s_hi:
                    y_mid = (s_lo + s_hi) / 2
                    txt = pg.TextItem(b["label"], color=b["color"], anchor=(1, 0.5))
                    txt.setPos(x_right, y_mid)
                    txt.setZValue(50)
                    font = QFont()
                    font.setPointSize(7)
                    txt.setFont(font)
                    self.chart_bp.addItem(txt)

        self._setup_date_axis(self.chart_bp, dates)

        # Tooltip PA
        bp_data = []
        for d, m in zip(dates, sorted_m):
            if m.bp_systolic and m.bp_diastolic:
                bp_data.append((d, {
                    "systolic": m.bp_systolic,
                    "diastolic": m.bp_diastolic,
                }))

        def fmt_bp(ts, vals):
            dt = datetime.fromtimestamp(ts)
            fg = COLORS['fg']
            sys_v = vals.get("systolic")
            dia_v = vals.get("diastolic")
            band = _classify_bp(sys_v) if sys_v else _bp_bands()[0]
            html = (f'<div style="padding:4px 6px;">'
                    f'<b style="color:{fg};">{dt.strftime("%d %b %Y")}</b>')
            lbl_sys = tr("Sistólica")
            lbl_dia = tr("Diastólica")
            lbl_estado = tr("Estado")
            if sys_v is not None:
                html += f'<br/><span style="color:{band["color"]};">▮ {lbl_sys}:</span> <span style="color:{fg};">{sys_v} mmHg</span>'
            if dia_v is not None:
                html += f'<br/><span style="color:{band["color"]};">▮ {lbl_dia}:</span> <span style="color:{fg};">{dia_v} mmHg</span>'
            html += f'<br/><span style="color:{band["color"]};">{lbl_estado}: {band["label"]}</span>'
            html += '</div>'
            return html

        if not hasattr(self, '_tooltip_bp'):
            self._tooltip_bp = ChartTooltip(self.chart_bp, fmt_bp)
        else:
            self._tooltip_bp.format_fn = fmt_bp
        self._tooltip_bp.set_data(bp_data)

        # ── 3. Composición corporal (dual Y) ──
        self.chart_body.clear()
        # Limpiar items del ViewBox derecho de forma segura
        for item in list(self._vb_body_right.addedItems):
            self._vb_body_right.removeItem(item)
        # Re-attach tooltip items tras clear()
        if hasattr(self, '_tooltip_body'):
            self._tooltip_body.reattach()

        weights = [(d, m.weight_kg) for d, m in zip(dates, sorted_m) if m.weight_kg]
        fats = [(d, m.body_fat_pct) for d, m in zip(dates, sorted_m) if m.body_fat_pct]
        subcuts = [(d, m.subcutaneous_fat_pct) for d, m in zip(dates, sorted_m) if m.subcutaneous_fat_pct]

        # Eje izquierdo: Peso (kg)
        if weights:
            xw, yw = zip(*weights)
            self.chart_body.plot(xw, yw, pen=pg.mkPen('#60B5FF', width=2),
                                symbol='o', symbolSize=6, symbolBrush='#60B5FF',
                                name=tr('Peso (kg)'))

        # Eje derecho: Grasa corp. (%) y Grasa subc. (%)
        if fats:
            xf, yf = np.array([p[0] for p in fats], dtype=float), np.array([p[1] for p in fats], dtype=float)
            fat_curve = pg.PlotCurveItem(xf, yf, pen=pg.mkPen('#FF9149', width=2), name='Grasa corp.')
            fat_scatter = pg.ScatterPlotItem(xf, yf, symbol='s', size=6,
                                              brush=pg.mkBrush('#FF9149'),
                                              pen=pg.mkPen('#FF9149'))
            self._vb_body_right.addItem(fat_curve)
            self._vb_body_right.addItem(fat_scatter)

        if subcuts:
            xs, ys = np.array([p[0] for p in subcuts], dtype=float), np.array([p[1] for p in subcuts], dtype=float)
            sub_curve = pg.PlotCurveItem(xs, ys, pen=pg.mkPen('#EAB308', width=2), name='Grasa subc.')
            sub_scatter = pg.ScatterPlotItem(xs, ys, symbol='t', size=6,
                                              brush=pg.mkBrush('#EAB308'),
                                              pen=pg.mkPen('#EAB308'))
            self._vb_body_right.addItem(sub_curve)
            self._vb_body_right.addItem(sub_scatter)

        # Determinar rango del eje derecho (%)
        all_pcts = [v for _, v in fats] + [v for _, v in subcuts]
        if all_pcts:
            pct_min = max(0, min(all_pcts) - 2)
            pct_max = max(all_pcts) + 2
            self._vb_body_right.setYRange(pct_min, pct_max, padding=0)

            # Bandas de referencia grasa corporal (hombre ciclista referencia)
            body_bands = [
                (3, 8, '#80D8C320', tr('Atlético')),
                (8, 15, '#60B5FF20', tr('Fitness')),
            ]
            for y_lo, y_hi, color, _label in body_bands:
                if y_lo < pct_max and y_hi > pct_min:
                    region = pg.LinearRegionItem(
                        values=[max(y_lo, pct_min), min(y_hi, pct_max)],
                        orientation='horizontal',
                        brush=pg.mkBrush(color), movable=False,
                    )
                    region.setZValue(-10)
                    self._vb_body_right.addItem(region)

            # Etiquetas de bandas
            if dates:
                x_right = max(dates) + (max(dates) - min(dates)) * 0.02 if len(dates) > 1 else max(dates)
                for y_lo, y_hi, _c, label in body_bands:
                    if y_lo < pct_max and y_hi > pct_min:
                        y_mid = (max(y_lo, pct_min) + min(y_hi, pct_max)) / 2
                        txt = pg.TextItem(label, color=COLORS['fg_muted'], anchor=(1, 0.5))
                        txt.setPos(x_right, y_mid)
                        txt.setZValue(50)
                        font = QFont()
                        font.setPointSize(7)
                        txt.setFont(font)
                        self._vb_body_right.addItem(txt)
        else:
            self._vb_body_right.setYRange(0, 20, padding=0)

        # Forzar sincronización de geometría del ViewBox derecho
        if hasattr(self._vb_body_right, '_sync_geometry'):
            self._vb_body_right._sync_geometry()

        # Añadir series de grasa a la leyenda del chart principal
        if fats:
            leg_fat = pg.PlotDataItem(pen=pg.mkPen('#FF9149', width=2),
                                       symbol='s', symbolSize=6, symbolBrush='#FF9149',
                                       name='Grasa corp. (%)')
            self.chart_body.addItem(leg_fat)
            leg_fat.setData([], [])
        if subcuts:
            leg_sub = pg.PlotDataItem(pen=pg.mkPen('#EAB308', width=2),
                                       symbol='t', symbolSize=6, symbolBrush='#EAB308',
                                       name='Grasa subc. (%)')
            self.chart_body.addItem(leg_sub)
            leg_sub.setData([], [])

        self._setup_date_axis(self.chart_body, dates)

        # Tooltip Composición
        comp_data = []
        for d, m in zip(dates, sorted_m):
            if m.weight_kg or m.body_fat_pct or m.subcutaneous_fat_pct:
                comp_data.append((d, {
                    "weight": m.weight_kg,
                    "body_fat": m.body_fat_pct,
                    "subcut_fat": m.subcutaneous_fat_pct,
                }))

        def fmt_comp(ts, vals):
            dt = datetime.fromtimestamp(ts)
            fg = COLORS['fg']
            html = (f'<div style="padding:4px 6px;">'
                    f'<b style="color:{fg};">{dt.strftime("%d %b %Y")}</b>')
            lbl_peso = tr("Peso")
            if vals.get("weight"):
                html += f'<br/><span style="color:#60B5FF;">● {lbl_peso}:</span> <span style="color:{fg};">{vals["weight"]:.1f} kg</span>'
            if vals.get("body_fat"):
                html += f'<br/><span style="color:#FF9149;">■ {tr("Grasa corp.")}:</span> <span style="color:{fg};">{vals["body_fat"]:.1f}%</span>'
            if vals.get("subcut_fat"):
                html += f'<br/><span style="color:#EAB308;">▲ {tr("Grasa subc.")}:</span> <span style="color:{fg};">{vals["subcut_fat"]:.1f}%</span>'
            html += '</div>'
            return html

        if not hasattr(self, '_tooltip_body'):
            self._tooltip_body = ChartTooltip(self.chart_body, fmt_comp)
        else:
            self._tooltip_body.format_fn = fmt_comp
        self._tooltip_body.set_data(comp_data)

    def _setup_date_axis(self, plot_widget, dates):
        """Configura el eje X como fechas legibles."""
        if not dates:
            return
        ax = plot_widget.getAxis('bottom')
        # Seleccionar ~6 ticks
        n = len(dates)
        step = max(1, n // 6)
        ticks = []
        for i in range(0, n, step):
            dt = datetime.fromtimestamp(dates[i])
            ticks.append((dates[i], dt.strftime('%d/%m')))
        ax.setTicks([ticks])
