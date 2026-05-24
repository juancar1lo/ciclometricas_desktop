"""Vista de Durabilidad (DRI — Durability Index).

Formulario para registrar tests empíricos, gráficos de curvas CP
fresca vs fatigada, zonas Coggan comparadas, área entre curvas,
curva de decaimiento exponencial con extrapolación e historial.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator, QDoubleValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from db.engine import get_session
from db.models import DurabilityTest, PowerTestSet, ProfileSnapshot
from calc.durability import (
    calc_durability_index, classify_dri, fit_exponential_decay,
    generate_cp_curve, ExponentialDecayModel, calc_area_between_curves,
)
from calc.cp_model import fit_cp_model, PowerTestPoint
from calc.zones import POWER_ZONES, resolve_zone_ref
from ui.dialogs import confirmar
from ui.theme import COLORS, FONT_SIZE_SM, FONT_SIZE_BASE, FONT_SIZE_TITLE
from ui.charts.chart_utils import (
    make_plot, _qcolor, attach_tooltip, tooltip_html,
    tooltip_header, tooltip_line, add_horizontal_line,
    add_horizontal_band,
)

KJ_PRESETS = [1500, 2000, 2500, 3000]


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
    card.setMinimumHeight(80)
    card.setMaximumHeight(100)
    card.setStyleSheet(
        f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
        f"border-radius: 10px; }}"
    )
    lay = QVBoxLayout(card)
    lay.setContentsMargins(8, 8, 8, 6)
    lay.setSpacing(2)
    lbl = QLabel(label)
    lbl.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_muted']}; text-transform: uppercase; border: none;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    val = QLabel(value)
    val.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {color}; border: none;")
    val.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(val)
    s = QLabel(sub if sub else " ")
    s.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_muted']}; border: none;")
    s.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(s)
    return card


class DurabilityView(QWidget):
    """Vista de tests de durabilidad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tests: List[DurabilityTest] = []
        self._fresh_cp: float = 0
        self._fresh_w: float = 0
        self._zone_ref_label: str = "CP"
        self._zone_ref_value: int = 0
        self._cp_tooltip: Optional[object] = None
        self._zones_tooltip: Optional[object] = None
        self._decay_tooltip: Optional[object] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll, inner, lay = _scrollable()
        root.addWidget(scroll)

        lay.addWidget(_section_title(
            "🧪", "Test de Durabilidad",
            "DRI — Durability Index · Mide la degradación de CP bajo fatiga acumulada"
        ))

        # Summary cards
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(10)
        lay.addLayout(self._cards_row)

        # Form to add new test
        lay.addWidget(self._build_form())

        # CP overlay chart
        lay.addWidget(_section_title("📈", "Curvas CP: Fresca vs Fatigada",
            "Superposición de la curva de potencia fresca y fatigada"))
        self._cp_chart = make_plot(height=300)
        lay.addWidget(self._cp_chart)

        # Zonas Coggan: fresca vs fatigada
        lay.addWidget(_section_title("📊", "Zonas Coggan: Fresca vs Fatigada",
            "Rangos de vatios por zona según referencia fresca y fatigada"))
        self._zones_chart = make_plot(height=320)
        lay.addWidget(self._zones_chart)
        self._zones_table = self._make_zones_table()
        lay.addWidget(self._zones_table)

        # Área entre curvas
        lay.addWidget(_section_title("📐", "Área entre curvas",
            "Capacidad perdida entre 30s y 30min de duración"))
        self._area_cards_row = QHBoxLayout()
        self._area_cards_row.setSpacing(10)
        lay.addLayout(self._area_cards_row)

        # Decay curve chart
        lay.addWidget(_section_title("📉", "Curva de Decaimiento Exponencial",
            "DRI(kJ) = 100 × e^(-λ × kJ) — Modelo de degradación"))
        self._decay_chart = make_plot(height=280)
        lay.addWidget(self._decay_chart)

        # Extrapolation input
        lay.addWidget(self._build_extrapolation())

        # History table
        lay.addWidget(_section_title("📋", "Historial de tests"))
        self._table = self._make_table()
        lay.addWidget(self._table)

        # Explanation
        lay.addWidget(self._make_explanation())
        lay.addStretch()

        self._refresh_data()

    def _build_form(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setSpacing(10)

        title = QLabel("➕  Registrar nuevo test")
        title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        lay.addWidget(title)

        form_grid = QGridLayout()
        form_grid.setSpacing(8)

        # kJ consumed
        form_grid.addWidget(QLabel("kJ acumulados:"), 0, 0)
        self._kj_input = QLineEdit()
        self._kj_input.setPlaceholderText("ej: 2000")
        self._kj_input.setValidator(QIntValidator(100, 10000))
        form_grid.addWidget(self._kj_input, 0, 1)

        # kJ presets
        presets_row = QHBoxLayout()
        for kj in KJ_PRESETS:
            btn = QPushButton(f"{kj} kJ")
            btn.setProperty("class", "ghost")
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, v=kj: self._kj_input.setText(str(v)))
            presets_row.addWidget(btn)
        presets_row.addStretch()
        form_grid.addLayout(presets_row, 0, 2)

        # Power 3 min
        form_grid.addWidget(QLabel("Potencia 3 min (W):"), 1, 0)
        self._p3_input = QLineEdit()
        self._p3_input.setPlaceholderText("ej: 310")
        self._p3_input.setValidator(QIntValidator(50, 2000))
        form_grid.addWidget(self._p3_input, 1, 1)

        # Power 12 min
        form_grid.addWidget(QLabel("Potencia 12 min (W):"), 2, 0)
        self._p12_input = QLineEdit()
        self._p12_input.setPlaceholderText("ej: 260")
        self._p12_input.setValidator(QIntValidator(50, 2000))
        form_grid.addWidget(self._p12_input, 2, 1)

        # Notes
        form_grid.addWidget(QLabel("Notas (opcional):"), 3, 0)
        self._notes_input = QLineEdit()
        self._notes_input.setPlaceholderText("Detalles del test...")
        form_grid.addWidget(self._notes_input, 3, 1, 1, 2)

        lay.addLayout(form_grid)

        # Save button
        btn_save = QPushButton("💾  Guardar test")
        btn_save.clicked.connect(self._save_test)
        lay.addWidget(btn_save)

        return card

    def _make_table(self) -> QTableWidget:
        tbl = QTableWidget()
        tbl.setColumnCount(8)
        tbl.setHorizontalHeaderLabels([
            "Fecha", "kJ", "P3min", "P12min", "CP fat.", "DRI %", "Estado", "",
        ])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        tbl.setColumnWidth(7, 60)
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

    def _make_zones_table(self) -> QTableWidget:
        """Tabla de zonas Coggan fresca vs fatigada."""
        tbl = QTableWidget()
        tbl.setColumnCount(4)
        tbl.setHorizontalHeaderLabels(["Zona", "Fresca (W)", "Fatigada (W)", "Δ W"])
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

    def _build_extrapolation(self) -> QFrame:
        """Input de extrapolación: introduce kJ → ve DRI estimado."""
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 14px; }}"
        )
        lay = QHBoxLayout(card)
        lay.setSpacing(12)

        lbl = QLabel("Extrapolar a kJ:")
        lbl.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; border: none;")
        lay.addWidget(lbl)

        self._extrap_input = QLineEdit()
        self._extrap_input.setPlaceholderText("ej: 3400")
        self._extrap_input.setValidator(QIntValidator(100, 10000))
        self._extrap_input.setFixedWidth(100)
        self._extrap_input.textChanged.connect(self._on_extrapolate)
        lay.addWidget(self._extrap_input)

        self._extrap_result = QLabel("")
        self._extrap_result.setStyleSheet(f"font-size: 14px; color: {COLORS['fg']}; border: none;")
        lay.addWidget(self._extrap_result)

        self._extrap_lambda = QLabel("")
        self._extrap_lambda.setStyleSheet(f"font-size: 10px; color: {COLORS['fg_dim']}; border: none;")
        lay.addWidget(self._extrap_lambda)

        lay.addStretch()
        return card

    def _make_explanation(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 18px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setSpacing(8)

        title = QLabel("¿Cómo funciona?")
        title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {COLORS['fg']}; border: none;")
        lay.addWidget(title)

        texts = [
            ("El <b>Test de Durabilidad</b> mide tu capacidad de mantener la potencia crítica "
             "después de acumular trabajo mecánico (kJ). El protocolo es:"),
            "",
            "1. Acumula un número conocido de kJ sobre la bici (ej: 2500 kJ).",
            '2. Haz un test all-out de <b>3 minutos</b> seguido de uno de <b>12 minutos</b>.',
            "3. Registra los resultados aquí.",
            "",
            ("La app calcula el <b>CP fatigado</b> con el modelo de 2 parámetros y lo compara "
             "con tu CP fresco para obtener el <b>Índice de Durabilidad (DRI)</b>:"),
            "",
            '<span style="font-family:monospace;">DRI = (CP<sub>fatigado</sub> / CP<sub>fresco</sub>) × 100</span>',
            "",
            "<b>Clasificación del DRI:</b>",
            f'• <span style="color:#22c55e"><b>≥ 95%</b></span> — Excelente durabilidad',
            f'• <span style="color:#3b82f6"><b>92 – 94,99%</b></span> — Buena durabilidad',
            f'• <span style="color:#eab308"><b>88 – 91,99%</b></span> — Mejorable',
            f'• <span style="color:#ef4444"><b>&lt; 88%</b></span> — Limitante en recorridos largos',
            "",
            ("Con múltiples tests a distintos kJ, se ajusta un <b>modelo exponencial</b> de decaimiento "
             "que permite <b>extrapolar</b> tu DRI a valores de kJ que no hayas testeado directamente."),
        ]
        for t in texts:
            lbl = QLabel(t)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"font-size: 14px; color: {COLORS['fg_muted']}; border: none; line-height: 1.6;")
            lay.addWidget(lbl)
        return card

    # ── Data ──

    def _get_fresh_model(self):
        """Get latest fresh CP/W' from power tests and zone reference."""
        with get_session() as session:
            test = session.query(PowerTestSet).order_by(
                PowerTestSet.tested_at.desc()
            ).first()
            if test and test.cp and test.w_prime:
                self._fresh_cp = test.cp
                self._fresh_w = test.w_prime
            else:
                # Fallback: use FTP as rough CP estimate
                snap = session.query(ProfileSnapshot).order_by(
                    ProfileSnapshot.effective_at.desc()
                ).first()
                if snap and snap.ftp:
                    self._fresh_cp = snap.ftp
                    self._fresh_w = 20000  # default W'
                else:
                    self._fresh_cp = 0
                    self._fresh_w = 0

        # Determine zone reference label
        self._zone_ref_label = "CP"
        self._zone_ref_value = round(self._fresh_cp) if self._fresh_cp else 0

    def refresh(self) -> None:
        self._refresh_data()

    def _refresh_data(self) -> None:
        self._get_fresh_model()

        with get_session() as session:
            self._tests = (
                session.query(DurabilityTest)
                .order_by(DurabilityTest.tested_at.asc())
                .all()
            )
            session.expunge_all()

        self._update_cards()
        self._draw_cp_chart()
        self._draw_zones_chart()
        self._update_area_cards()
        self._draw_decay_chart()
        self._update_extrapolation_lambda()
        self._fill_table()

    def _save_test(self) -> None:
        try:
            kj = int(self._kj_input.text())
            p3 = int(self._p3_input.text())
            p12 = int(self._p12_input.text())
        except (ValueError, TypeError):
            QMessageBox.warning(self, "Datos inválidos", "Rellena todos los campos numéricos.")
            return

        if self._fresh_cp <= 0:
            QMessageBox.warning(self, "Sin referencia",
                "No hay modelo CP fresco disponible. Registra primero un test de potencia en Configuración.")
            return

        if p3 <= p12:
            QMessageBox.warning(self, "Error", "La potencia de 3 min debe ser mayor que la de 12 min.")
            return

        result = calc_durability_index(p3, p12, self._fresh_cp, self._fresh_w)
        if result is None:
            QMessageBox.warning(self, "Error", "No se pudo calcular el DRI con estos datos.")
            return

        notes = self._notes_input.text().strip() or None

        with get_session() as session:
            test = DurabilityTest(
                kj_consumed=kj,
                power_3min=p3,
                power_12min=p12,
                cp_fatigued=result.cp_fatigued,
                w_prime_fatigued=result.w_prime_fatigued,
                cp_fresh=self._fresh_cp,
                w_prime_fresh=self._fresh_w,
                dri_percent=result.dri_percent,
                classification=result.classification,
                notes=notes,
            )
            session.add(test)
            session.commit()

        # Clear form
        self._kj_input.clear()
        self._p3_input.clear()
        self._p12_input.clear()
        self._notes_input.clear()

        QMessageBox.information(self, "Test guardado",
            f"DRI: {result.dri_percent:.1f}% — {result.label}")
        self._refresh_data()

    def _delete_test(self, test_id: int) -> None:
        if not confirmar(self, "Eliminar test", "¿Eliminar este test de durabilidad?"):
            return
        with get_session() as session:
            test = session.query(DurabilityTest).get(test_id)
            if test:
                session.delete(test)
                session.commit()
        self._refresh_data()

    # ── Cards ──

    def _update_cards(self) -> None:
        while self._cards_row.count():
            item = self._cards_row.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        self._cards_row.addWidget(_stat_card(
            "CP Fresco",
            f"{self._fresh_cp:.0f} W" if self._fresh_cp else "—",
            "#22d3ee",
            "Referencia actual",
        ))

        if self._tests:
            last = self._tests[-1]
            cls, lbl, clr = classify_dri(last.dri_percent)
            self._cards_row.addWidget(_stat_card(
                "Último DRI",
                f"{last.dri_percent:.1f}%",
                clr,
                f"{lbl} ({last.kj_consumed:.0f} kJ)",
            ))
            self._cards_row.addWidget(_stat_card(
                "Tests realizados",
                str(len(self._tests)),
                COLORS["fg"],
            ))
        else:
            self._cards_row.addWidget(_stat_card(
                "Último DRI", "—", COLORS["fg_dim"], "Sin tests aún",
            ))

    # ── CP Overlay Chart ──

    def _draw_cp_chart(self) -> None:
        pw = self._cp_chart
        if self._cp_tooltip is not None:
            self._cp_tooltip.clear()
            self._cp_tooltip = None
        pw.clear()
        if pw.plotItem.legend is not None:
            pw.plotItem.legend.scene().removeItem(pw.plotItem.legend)
            pw.plotItem.legend = None
        pw.viewport().setMouseTracking(True)

        if not self._tests or self._fresh_cp <= 0:
            txt = pg.TextItem("Registra un test para ver la comparación de curvas CP",
                color=QColor(COLORS["fg_muted"]))
            txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(txt)
            txt.setPos(100, 250)
            return

        last = self._tests[-1]

        # Fresh curve
        fresh_pts = generate_cp_curve(self._fresh_cp, self._fresh_w)
        fx = np.array([p[0] for p in fresh_pts], dtype=float)
        fy = np.array([p[1] for p in fresh_pts], dtype=float)
        fresh_line = pg.PlotCurveItem(fx, fy,
            pen=pg.mkPen(color="#22c55e", width=2.5))
        pw.addItem(fresh_line)

        # Fatigued curve
        fat_pts = generate_cp_curve(last.cp_fatigued, last.w_prime_fatigued)
        fax = np.array([p[0] for p in fat_pts], dtype=float)
        fay = np.array([p[1] for p in fat_pts], dtype=float)
        fat_line = pg.PlotCurveItem(fax, fay,
            pen=pg.mkPen(color="#ef4444", width=2.5))
        pw.addItem(fat_line)

        # Fill area between curves
        min_len = min(len(fx), len(fax))
        if min_len > 1:
            fill = pg.FillBetweenItem(fresh_line, fat_line,
                brush=_qcolor("#ef4444", 30))
            pw.addItem(fill)

        # CP reference lines
        add_horizontal_line(pw, self._fresh_cp, "#22c55e", Qt.PenStyle.DashLine)
        add_horizontal_line(pw, last.cp_fatigued, "#ef4444", Qt.PenStyle.DashLine)

        # Cap Y-axis: use t=30s (realistic sprint cap) instead of t=5
        max_power_fresh = self._fresh_cp + self._fresh_w / 30.0
        max_power_fat = last.cp_fatigued + last.w_prime_fatigued / 30.0
        y_max = max(max_power_fresh, max_power_fat) * 1.15
        # Tope absoluto: 2× CP fresco o 1500W, lo que sea mayor
        y_max = min(y_max, max(self._fresh_cp * 2.0, 1500.0))
        y_min = min(self._fresh_cp, last.cp_fatigued) * 0.85
        pw.setYRange(y_min, y_max)

        # Labels junto a las líneas CP
        cp_spread = abs(self._fresh_cp - last.cp_fatigued)
        label_offset = max(8, cp_spread * 0.15)
        for clr, lbl_text, y_base, direction in [
            ("#22c55e", f"CP fresco: {self._fresh_cp:.0f}W",
             self._fresh_cp, 1),
            ("#ef4444", f"CP fatigado: {last.cp_fatigued:.0f}W",
             last.cp_fatigued, -1),
        ]:
            t = pg.TextItem(lbl_text, color=QColor(clr))
            t.setFont(QFont("Segoe UI", 9))
            t.setPos(1800, y_base + direction * label_offset)
            pw.addItem(t, ignoreBounds=True)

        # Legend — usar addLegend nativo de pyqtgraph (esquina superior derecha)
        legend = pw.addLegend(offset=(-10, 10))
        legend.setLabelTextColor(QColor(COLORS["fg_muted"]))
        legend.addItem(fresh_line, "CP Fresco")
        legend.addItem(fat_line, "CP Fatigado")

        pw.setLabel("bottom", "Duración (s)")
        pw.setLabel("left", "Potencia (W)")

        # Tooltip — snap to fresh curve X values
        fresh_cp_val = self._fresh_cp
        fresh_w_val = self._fresh_w
        fat_cp_val = last.cp_fatigued
        fat_w_val = last.w_prime_fatigued
        last_kj = last.kj_consumed

        def _fmt_cp(xv, yv):
            t_sec = max(1, xv)
            p_fresh = fresh_cp_val + fresh_w_val / t_sec
            p_fat = fat_cp_val + fat_w_val / t_sec
            diff = p_fresh - p_fat
            if t_sec >= 3600:
                dur_str = f"{t_sec / 3600:.1f}h"
            elif t_sec >= 60:
                dur_str = f"{t_sec / 60:.0f} min"
            else:
                dur_str = f"{t_sec:.0f} s"
            lines = [
                tooltip_header(f"Duración: {dur_str}"),
                tooltip_line("P. Fresca", f"{p_fresh:.0f} W", "#22c55e"),
                tooltip_line("P. Fatigada", f"{p_fat:.0f} W ({last_kj:.0f} kJ)", "#ef4444"),
                tooltip_line("Diferencia", f"–{diff:.0f} W ({diff / max(p_fresh, 1) * 100:.1f}%)"),
            ]
            return tooltip_html(lines)

        self._cp_tooltip = attach_tooltip(pw, _fmt_cp, snap_xs=fx)

    # ── Zonas Coggan Chart ──

    def _draw_zones_chart(self) -> None:
        pw = self._zones_chart
        if self._zones_tooltip is not None:
            self._zones_tooltip.clear()
            self._zones_tooltip = None
        pw.clear()
        if pw.plotItem.legend is not None:
            pw.plotItem.legend.scene().removeItem(pw.plotItem.legend)
            pw.plotItem.legend = None
        pw.viewport().setMouseTracking(True)

        if not self._tests or self._fresh_cp <= 0:
            txt = pg.TextItem("Registra un test para ver la comparación de zonas",
                color=QColor(COLORS["fg_muted"]))
            txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(txt)
            txt.setPos(1, 200)
            self._zones_table.setRowCount(0)
            return

        last = self._tests[-1]
        fresh_ref = self._zone_ref_value if self._zone_ref_value > 0 else round(self._fresh_cp)
        ratio = last.cp_fatigued / last.cp_fresh if last.cp_fresh > 0 else 1.0
        fat_ref = round(fresh_ref * ratio)

        # Build zone data
        zone_data = []
        for z in POWER_ZONES:
            f_min = round(fresh_ref * z.min_pct / 100)
            f_max = round(fresh_ref * z.max_pct / 100) if z.max_pct != math.inf else round(fresh_ref * 2)
            fa_min = round(fat_ref * z.min_pct / 100)
            fa_max = round(fat_ref * z.max_pct / 100) if z.max_pct != math.inf else round(fat_ref * 2)
            zone_data.append({
                "label": z.label, "short": z.short_label, "color": z.color,
                "f_min": f_min, "f_max": f_max, "fa_min": fa_min, "fa_max": fa_max,
            })

        # Grouped bar chart (horizontal-ish, but we do vertical grouped bars)
        n = len(zone_data)
        x = np.arange(n)
        bar_w = 0.35

        # Fresh bars (stacked: invisible base + visible range)
        fresh_bases = np.array([z["f_min"] for z in zone_data], dtype=float)
        fresh_ranges = np.array([z["f_max"] - z["f_min"] for z in zone_data], dtype=float)
        fat_bases = np.array([z["fa_min"] for z in zone_data], dtype=float)
        fat_ranges = np.array([z["fa_max"] - z["fa_min"] for z in zone_data], dtype=float)

        # Draw fresh bars (cyan)
        for i in range(n):
            bar = pg.BarGraphItem(
                x=[x[i] - bar_w / 2], height=[fresh_ranges[i]], width=bar_w,
                y0=fresh_bases[i],
                brush=_qcolor("#22d3ee", 180), pen=pg.mkPen(None),
            )
            pw.addItem(bar)

        # Draw fatigued bars (orange)
        for i in range(n):
            bar = pg.BarGraphItem(
                x=[x[i] + bar_w / 2], height=[fat_ranges[i]], width=bar_w,
                y0=fat_bases[i],
                brush=_qcolor("#f97316", 180), pen=pg.mkPen(None),
            )
            pw.addItem(bar)

        # X-axis ticks
        ticks = [(i, zone_data[i]["short"]) for i in range(n)]
        pw.getAxis("bottom").setTicks([ticks])
        pw.setLabel("bottom", "")
        pw.setLabel("left", "Vatios")

        # Legend at top-left (Zone 1 area) to avoid overlapping Zone 7 bars
        legend = pw.addLegend(offset=(10, 10))
        legend.setLabelTextColor(QColor(COLORS["fg_muted"]))
        # Añadir items ficticios para la leyenda
        dummy_fresh = pg.PlotCurveItem(pen=pg.mkPen("#22d3ee", width=6))
        dummy_fat = pg.PlotCurveItem(pen=pg.mkPen("#f97316", width=6))
        legend.addItem(dummy_fresh, f"CP Fresca ({fresh_ref}W)")
        legend.addItem(dummy_fat, f"CP Fatigada ({fat_ref}W)")

        # Tooltip de zonas
        _zd = zone_data
        def _fmt_zones(xv, _yv):
            idx = int(round(max(0, min(xv, n - 1))))
            z = _zd[idx]
            lines = [
                tooltip_header(z["label"]),
                tooltip_line("Fresca", f"{z['f_min']}–{z['f_max']} W", "#22d3ee"),
                tooltip_line("Fatigada", f"{z['fa_min']}–{z['fa_max']} W", "#f97316"),
                tooltip_line("Δ mín", f"−{z['f_min'] - z['fa_min']} W", "#ef4444"),
                tooltip_line("Δ máx", f"−{z['f_max'] - z['fa_max']} W", "#ef4444"),
            ]
            return tooltip_html(lines)
        snap = np.arange(n, dtype=float)
        self._zones_tooltip = attach_tooltip(pw, _fmt_zones, snap_xs=snap)

        # Fill zones table
        tbl = self._zones_table
        tbl.setRowCount(n)
        for i, z in enumerate(zone_data):
            tbl.setRowHeight(i, 30)

            # Zone label with color indicator
            zone_item = QTableWidgetItem(f"  {z['label']}")
            zone_item.setForeground(QColor(z["color"]))
            zone_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 0, zone_item)

            # Fresh range
            fresh_item = QTableWidgetItem(f"{z['f_min']}–{z['f_max']}")
            fresh_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            fresh_item.setForeground(QColor("#22d3ee"))
            fresh_item.setFont(QFont("Consolas", 9))
            tbl.setItem(i, 1, fresh_item)

            # Fatigued range
            fat_item = QTableWidgetItem(f"{z['fa_min']}–{z['fa_max']}")
            fat_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            fat_item.setForeground(QColor("#f97316"))
            fat_item.setFont(QFont("Consolas", 9))
            tbl.setItem(i, 2, fat_item)

            # Delta
            delta_min = z["f_min"] - z["fa_min"]
            delta_max = z["f_max"] - z["fa_max"]
            delta_item = QTableWidgetItem(f"−{delta_min}–{delta_max}")
            delta_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            delta_item.setForeground(QColor("#ef4444"))
            tbl.setItem(i, 3, delta_item)

    # ── Área entre curvas ──

    def _update_area_cards(self) -> None:
        while self._area_cards_row.count():
            item = self._area_cards_row.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        if not self._tests or self._fresh_cp <= 0:
            reason = "Sin tests" if not self._tests else f"CP fresco={self._fresh_cp}"
            self._area_cards_row.addWidget(_stat_card(
                "Área total", "—", COLORS["fg_dim"], reason,
            ))
            return

        last = self._tests[-1]
        try:
            area = calc_area_between_curves(
                self._fresh_cp, self._fresh_w,
                last.cp_fatigued, last.w_prime_fatigued,
            )
        except Exception as e:
            self._area_cards_row.addWidget(_stat_card(
                "Error", str(e)[:30], "#ef4444",
            ))
            return

        # Delta ref
        fresh_ref = self._zone_ref_value if self._zone_ref_value > 0 else round(self._fresh_cp)
        ratio = last.cp_fatigued / last.cp_fresh if last.cp_fresh > 0 else 1.0
        fat_ref = round(fresh_ref * ratio)
        delta_ref = fresh_ref - fat_ref

        self._area_cards_row.addWidget(_stat_card(
            "Área total",
            f"{area.area_kj} kJ",
            "#f97316",
            f"{area.area_watt_sec:,} W·s",
        ))
        self._area_cards_row.addWidget(_stat_card(
            "Pérdida media",
            f"{area.avg_power_loss} W",
            COLORS["fg"],
        ))
        self._area_cards_row.addWidget(_stat_card(
            "Pérdida % media",
            f"{area.avg_percent_loss}%",
            COLORS["fg"],
        ))
        self._area_cards_row.addWidget(_stat_card(
            f"Δ {self._zone_ref_label}",
            f"{delta_ref} W",
            "#ef4444",
            f"{fresh_ref}W → {fat_ref}W",
        ))

    # ── Decay Curve Chart ──

    def _draw_decay_chart(self) -> None:
        pw = self._decay_chart
        if self._decay_tooltip is not None:
            self._decay_tooltip.clear()
            self._decay_tooltip = None
        pw.clear()
        if pw.plotItem.legend is not None:
            pw.plotItem.legend.scene().removeItem(pw.plotItem.legend)
            pw.plotItem.legend = None
        pw.viewport().setMouseTracking(True)

        if not self._tests:
            txt = pg.TextItem("Registra tests a diferentes kJ para ver el modelo de decaimiento",
                color=QColor(COLORS["fg_muted"]))
            txt.setFont(QFont("Segoe UI", 10))
            pw.addItem(txt)
            txt.setPos(500, 95)
            return

        # Classification bands
        bands = [
            (95, 105, "#22c55e", 20),  # excellent
            (92, 95, "#3b82f6", 20),   # good
            (88, 92, "#eab308", 20),   # improvable
            (70, 88, "#ef4444", 20),   # limiting
        ]
        for y1, y2, clr, alpha in bands:
            add_horizontal_band(pw, y1, y2, clr, alpha)

        # Reference lines
        for y, clr in [(95, "#22c55e"), (92, "#3b82f6"), (88, "#eab308")]:
            add_horizontal_line(pw, y, clr, Qt.PenStyle.DashDotLine)

        # Scatter test points
        spots = []
        points_for_model = []
        for t in self._tests:
            cls, lbl, clr = classify_dri(t.dri_percent)
            spots.append({
                "pos": (t.kj_consumed, t.dri_percent),
                "brush": QColor(clr),
                "pen": pg.mkPen("#ffffff", width=1.5),
                "size": 10,
            })
            points_for_model.append((t.kj_consumed, t.dri_percent))

        scatter = pg.ScatterPlotItem(spots=spots)
        pw.addItem(scatter)

        # Fit exponential decay
        model = fit_exponential_decay(points_for_model)
        self._decay_model = model  # store for extrapolation
        if model is not None:
            max_kj = max(max(t.kj_consumed for t in self._tests) * 1.3, 7000)
            curve_pts = model.curve(0, max_kj, 80)
            cx = np.array([p[0] for p in curve_pts], dtype=float)
            cy = np.array([p[1] for p in curve_pts], dtype=float)
            curve_line = pg.PlotCurveItem(cx, cy,
                pen=pg.mkPen(color="#8b5cf6", width=2, style=Qt.PenStyle.DashLine))
            pw.addItem(curve_line)

            # Label with lambda
            lam_txt = pg.TextItem(
                f"λ = {model.lam:.6f}  |  R² = {model.r_squared:.3f}",
                color=QColor("#8b5cf6"),
            )
            lam_txt.setFont(QFont("Segoe UI", 9))
            lam_txt.setPos(max_kj * 0.05, 72)
            pw.addItem(lam_txt, ignoreBounds=True)

        pw.setYRange(70, 105)
        pw.setLabel("bottom", "kJ acumulados")
        pw.setLabel("left", "DRI (%)")

        # Tooltip — traverse full model curve, not just test points
        model_ref = model
        tests_ref = self._tests

        def _fmt(xv, yv):
            if not tests_ref:
                return ""
            # Check if near a test point first
            dists = [abs(t.kj_consumed - xv) for t in tests_ref]
            idx = int(np.argmin(dists))
            near_test = dists[idx] < 150

            if near_test:
                t = tests_ref[idx]
                cls, lbl, clr = classify_dri(t.dri_percent)
                lines = [
                    tooltip_header(f"Test @ {t.kj_consumed:.0f} kJ"),
                    tooltip_line("DRI", f"{t.dri_percent:.1f}% — {lbl}", clr),
                    tooltip_line("CP fatigado", f"{t.cp_fatigued:.0f} W"),
                    tooltip_line("P3min / P12min", f"{t.power_3min}W / {t.power_12min}W"),
                ]
                if t.notes:
                    lines.append(f'<span style="color:{COLORS["fg_dim"]}">{t.notes}</span>')
                return tooltip_html(lines)
            elif model_ref is not None:
                # Show model prediction for any kJ
                kj_val = max(0, xv)
                dri_pred = model_ref.predict(kj_val)
                cls, lbl, clr = classify_dri(dri_pred)
                lines = [
                    tooltip_header(f"Modelo @ {kj_val:.0f} kJ"),
                    tooltip_line("DRI estimado", f"{dri_pred:.1f}%", clr),
                    tooltip_line("Estado", lbl),
                ]
                return tooltip_html(lines)
            return ""

        # Don't snap to test points — let tooltip traverse the full curve
        self._decay_tooltip = attach_tooltip(pw, _fmt)

    # ── Extrapolation ──

    def _update_extrapolation_lambda(self) -> None:
        model = getattr(self, '_decay_model', None)
        if model is not None:
            txt = f"λ = {model.lam:.2e}"
            if len(self._tests) >= 2:
                txt += f"  ·  R² = {model.r_squared:.4f}"
            self._extrap_lambda.setText(txt)
        else:
            self._extrap_lambda.setText("")

    def _on_extrapolate(self) -> None:
        model = getattr(self, '_decay_model', None)
        text = self._extrap_input.text().strip()
        if not text or model is None:
            self._extrap_result.setText("")
            return
        try:
            kj = int(text)
        except ValueError:
            self._extrap_result.setText("")
            return
        if kj <= 0:
            self._extrap_result.setText("")
            return

        dri = model.predict(kj)
        cls, lbl, clr = classify_dri(dri)
        self._extrap_result.setText(
            f'DRI estimado a {kj:,} kJ:  '
            f'<span style="color:{clr}; font-weight:700; font-size:18px;">{dri:.1f}%</span>  '
            f'<span style="color:{clr};">({lbl})</span>'
        )
        self._extrap_result.setTextFormat(Qt.TextFormat.RichText)

    # ── Table ──

    def _fill_table(self) -> None:
        tbl = self._table
        rows = list(reversed(self._tests))
        tbl.setRowCount(len(rows))
        for i, t in enumerate(rows):
            tbl.setRowHeight(i, 36)
            d = t.tested_at.date() if isinstance(t.tested_at, datetime) else t.tested_at
            tbl.setItem(i, 0, QTableWidgetItem(f"{d.day:02d}/{d.month:02d}/{d.year}"))

            kj_item = QTableWidgetItem(f"{t.kj_consumed:.0f}")
            kj_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 1, kj_item)

            p3_item = QTableWidgetItem(f"{t.power_3min}W")
            p3_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 2, p3_item)

            p12_item = QTableWidgetItem(f"{t.power_12min}W")
            p12_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 3, p12_item)

            cp_item = QTableWidgetItem(f"{t.cp_fatigued:.0f}W")
            cp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(i, 4, cp_item)

            cls, lbl, clr = classify_dri(t.dri_percent)
            dri_item = QTableWidgetItem(f"{t.dri_percent:.1f}%")
            dri_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dri_item.setForeground(QColor(clr))
            dri_item.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            tbl.setItem(i, 5, dri_item)

            st_item = QTableWidgetItem(lbl)
            st_item.setForeground(QColor(clr))
            tbl.setItem(i, 6, st_item)

            # Delete button
            btn = QPushButton("🗑")
            btn.setProperty("class", "ghost")
            btn.setFixedSize(40, 28)
            btn.clicked.connect(lambda checked, tid=t.id: self._delete_test(tid))
            tbl.setCellWidget(i, 7, btn)
