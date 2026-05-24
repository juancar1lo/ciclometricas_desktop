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

from datetime import datetime, timezone, date
from typing import Optional, List

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
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
READINESS_SOURCES = [
    ("manual", "Manual (1-10)"),
    ("garmin", "Garmin (1-100)"),
    ("whoop", "Whoop (1-100)"),
    ("oura", "Oura (1-100)"),
    ("coros", "COROS (1-100)"),
    ("ehrv", "Elite HRV (1-10)"),
]


def normalize_readiness(raw: float, source: str) -> float:
    """Normaliza un valor de readiness a escala 1-10."""
    if source in ("manual", "ehrv"):
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
BP_BANDS = [
    {"label": "Óptima",  "s_min": 60,  "s_max": 120, "color": "#22C55E"},
    {"label": "Normal",  "s_min": 120, "s_max": 130, "color": "#84CC16"},
    {"label": "Elevada", "s_min": 130, "s_max": 140, "color": "#EAB308"},
    {"label": "Alta",    "s_min": 140, "s_max": 250, "color": "#EF4444"},
]


def _classify_bp(sys: float) -> dict:
    for b in reversed(BP_BANDS):
        if sys >= b["s_min"]:
            return b
    return BP_BANDS[0]


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
        self.label.setPos(mouse_point.x(), mouse_point.y())
        self.label.setVisible(True)


class HealthView(QWidget):
    """Vista completa de métricas de salud."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing_id: Optional[int] = None  # id del registro siendo editado

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 28)
        main_layout.setSpacing(18)

        # Título
        title = QLabel("❤️\u200d🩹  Salud")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; color: {COLORS['fg']};"
        )
        main_layout.addWidget(title)
        desc = QLabel(
            "Registra FC reposo, HRV, Readiness, presión arterial, peso, composición corporal y notas. "
            "Los gráficos se actualizan en tiempo real."
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

        # ── Gráficos ──
        if HAS_PYQTGRAPH:
            self._build_charts(content_lay)
        else:
            lbl = QLabel("⚠️ pyqtgraph no instalado — los gráficos no están disponibles.")
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
        card = _make_card("📝  Nuevo registro", "Introduce las métricas del día. Todos los campos son opcionales.")
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
        form.addRow("📅 Fecha:", self.date_input)

        # 2. FC reposo
        self.resting_hr_input = QSpinBox()
        self.resting_hr_input.setRange(0, 120)
        self.resting_hr_input.setSuffix(" ppm")
        self.resting_hr_input.setSpecialValueText("—")
        form.addRow("❤️ FC reposo (ppm):", self.resting_hr_input)

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
        for key, label in READINESS_SOURCES:
            self.readiness_source_input.addItem(label, key)
        readiness_row.addWidget(self.readiness_source_input)
        # 5. Readiness valor
        self.readiness_input = QDoubleSpinBox()
        self.readiness_input.setRange(0, 100)
        self.readiness_input.setDecimals(1)
        self.readiness_input.setSpecialValueText("—")
        readiness_row.addWidget(self.readiness_input)
        form.addRow("🎯 Readiness:", readiness_row)

        # 6. PA sistólica
        self.bp_sys_input = QSpinBox()
        self.bp_sys_input.setRange(0, 250)
        self.bp_sys_input.setSuffix(" mmHg")
        self.bp_sys_input.setSpecialValueText("—")
        form.addRow("🩺 PA sistólica:", self.bp_sys_input)

        # 7. PA diastólica
        self.bp_dia_input = QSpinBox()
        self.bp_dia_input.setRange(0, 200)
        self.bp_dia_input.setSuffix(" mmHg")
        self.bp_dia_input.setSpecialValueText("—")
        form.addRow("🩺 PA diastólica:", self.bp_dia_input)

        # 8. Peso
        self.weight_input = QDoubleSpinBox()
        self.weight_input.setRange(0, 200)
        self.weight_input.setDecimals(1)
        self.weight_input.setSuffix(" kg")
        self.weight_input.setSpecialValueText("—")
        form.addRow("🏋️ Peso (kg):", self.weight_input)

        # 9. Grasa corporal %
        self.body_fat_input = QDoubleSpinBox()
        self.body_fat_input.setRange(0, 60)
        self.body_fat_input.setDecimals(1)
        self.body_fat_input.setSuffix(" %")
        self.body_fat_input.setSpecialValueText("—")
        form.addRow("📊 Grasa corporal (%):", self.body_fat_input)

        # 10. Grasa subcutánea %
        self.subcut_fat_input = QDoubleSpinBox()
        self.subcut_fat_input.setRange(0, 60)
        self.subcut_fat_input.setDecimals(1)
        self.subcut_fat_input.setSuffix(" %")
        self.subcut_fat_input.setSpecialValueText("—")
        form.addRow("📊 Grasa subcutánea (%):", self.subcut_fat_input)

        # 11. Notas
        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Notas opcionales…")
        form.addRow("📝 Notas:", self.notes_input)

        card.layout().addLayout(form)

        # Botones
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾  Guardar")
        self.btn_save.setFixedHeight(42)
        self.btn_save.setMinimumWidth(180)
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)

        self.btn_cancel_edit = QPushButton("✖  Cancelar edición")
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

    def _build_charts(self, parent_lay: QVBoxLayout):
        pg.setConfigOption('background', COLORS['bg_card'])
        pg.setConfigOption('foreground', COLORS['fg'])

        # ── 1. Cardiovascular + Readiness (dual Y) ──
        card1 = _make_card("❤️  Cardiovascular y Readiness",
                           "FC reposo (ppm), HRV (ms) — eje izq.  |  Readiness (1-10) — eje der.")
        self.chart_cardio = pg.PlotWidget()
        self.chart_cardio.setMinimumHeight(260)
        self.chart_cardio.showGrid(x=True, y=True, alpha=0.15)
        self.chart_cardio.addLegend(offset=(10, 10))
        self.chart_cardio.setMouseEnabled(x=False, y=False)
        self.chart_cardio.setMenuEnabled(False)
        self.chart_cardio.getViewBox().setMouseMode(pg.ViewBox.PanMode)
        self.chart_cardio.setLabel('left', 'ppm / ms')
        # Segundo eje Y para Readiness
        self._vb_cardio_right = self._setup_dual_axis(self.chart_cardio, 'Readiness (1-10)', '#F59E0B')
        card1.layout().addWidget(self.chart_cardio)
        parent_lay.addWidget(card1)

        # ── 2. Presión arterial (candlestick) ──
        card2 = _make_card("🩺  Presión arterial",
                           "Sistólica y diastólica (mmHg) — rango representado como velas")
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
        card3 = _make_card("📊  Composición corporal",
                           "Peso (kg) — eje izq.  |  Grasa corporal y subcutánea (%) — eje der.")
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
        card = _make_card("🕐  Historial de registros",
                          "Haz clic en ✏️ para editar o 🗑 para eliminar.")
        self.history_table = QTableWidget()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)

        cols = [
            "Fecha", "FC rep.", "HRV", "Readiness",
            "PA sist.", "PA diast.", "Peso", "Grasa %", "Grasa sub.",
            "Notas", "", "",
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
            QMessageBox.warning(self, "Sin datos", "Introduce al menos un valor.")
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
            QMessageBox.warning(self, "Error", f"Error al guardar: {e}")
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
        self.btn_save.setText("💾  Actualizar")
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
        if not confirmar(self, "Confirmar", "¿Eliminar este registro de salud?"):
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
        self.btn_save.setText("💾  Guardar")
        self.btn_cancel_edit.setVisible(False)
        self._clear_form()

    def _clear_form(self):
        self._editing_id = None
        self.btn_save.setText("💾  Guardar")
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
            metrics = (
                session.query(HealthMetric)
                .order_by(HealthMetric.date.desc())
                .all()
            )
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
                f"{m.resting_hr} ppm" if m.resting_hr else "—")); col += 1
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
            btn_edit = QPushButton("✏️")
            btn_edit.setFixedSize(34, 34)
            btn_edit.setProperty("class", "ghost")
            btn_edit.setToolTip("Editar")
            btn_edit.clicked.connect(lambda checked=False, mid=m.id: self._on_edit(mid))
            self.history_table.setCellWidget(row, col, btn_edit); col += 1

            # Botón eliminar
            btn_del = QPushButton("🗑")
            btn_del.setFixedSize(34, 34)
            btn_del.setProperty("class", "ghost")
            btn_del.setToolTip("Eliminar")
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
                                  name='FC reposo (ppm)')
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
                (0, 3, '#FF636330', 'Baja'),
                (3, 5, '#FF914930', 'Moderada'),
                (5, 7, '#F59E0B20', 'Buena'),
                (7, 10.5, '#80D8C320', 'Óptima'),
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
                html += f'<br/><span style="color:#FF6363;">● FC reposo:</span> <span style="color:{fg};">{vals["resting_hr"]} ppm</span>'
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

            for b in BP_BANDS:
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
            for b in BP_BANDS:
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
            band = _classify_bp(sys_v) if sys_v else BP_BANDS[0]
            html = (f'<div style="padding:4px 6px;">'
                    f'<b style="color:{fg};">{dt.strftime("%d %b %Y")}</b>')
            if sys_v is not None:
                html += f'<br/><span style="color:{band["color"]};">▮ Sistólica:</span> <span style="color:{fg};">{sys_v} mmHg</span>'
            if dia_v is not None:
                html += f'<br/><span style="color:{band["color"]};">▮ Diastólica:</span> <span style="color:{fg};">{dia_v} mmHg</span>'
            html += f'<br/><span style="color:{band["color"]};">Estado: {band["label"]}</span>'
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
                                name='Peso (kg)')

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
                (3, 8, '#80D8C320', 'Atlético'),
                (8, 15, '#60B5FF20', 'Fitness'),
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
            if vals.get("weight"):
                html += f'<br/><span style="color:#60B5FF;">● Peso:</span> <span style="color:{fg};">{vals["weight"]:.1f} kg</span>'
            if vals.get("body_fat"):
                html += f'<br/><span style="color:#FF9149;">■ Grasa corp.:</span> <span style="color:{fg};">{vals["body_fat"]:.1f}%</span>'
            if vals.get("subcut_fat"):
                html += f'<br/><span style="color:#EAB308;">▲ Grasa subc.:</span> <span style="color:{fg};">{vals["subcut_fat"]:.1f}%</span>'
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
