"""Vista de detalle completo de una actividad.

Muestra métricas, análisis avanzado, zonas, intervalos, subidas y MMP,
replicando la experiencia de la app web.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal, QThread
from i18n import tr
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QScrollArea, QPushButton, QVBoxLayout,
    QWidget, QInputDialog, QTextEdit,
)

from db.engine import get_session
from db.models import Activity, PowerTestSet, ProfileSnapshot
from ui.theme import (
    COLORS, FONT_SIZE_BASE, FONT_SIZE_SM, FONT_SIZE_LG, FONT_SIZE_TITLE,
    FONT_SIZE_XS, FONT_SIZE_XL, FONT_SIZE_MD, FONT_SIZE_HERO,
    ICON_MD, ICON_LG, ICON_SM, RADIUS, RADIUS_LG,
)
from ui.widgets.stat_card import StatCard
from ui.charts.time_series_chart import TimeSeriesChart
from ui.charts.route_map import RouteMapWidget

# Lazy imports for calc modules
from calc.activity_metrics import calc_tiss, calc_ef, calc_vf, calc_pw_hr_decoupling
from calc.zones import POWER_ZONES, HR_ZONES, bucket_series
from calc.intervals import detect_intervals, SampleRow as IntervalSampleRow, DetectIntervalsOptions
from calc.climbs import detect_climbs, SampleRow as ClimbSampleRow, ClimbDetectionOptions
from calc.mmp import PR_DURATIONS
from calc.quadrant_analysis import calc_quadrant_analysis, QuadrantSample, QuadrantResult
from calc.torque import compute_torque_series, compute_torque_stats


def _fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "\u2014"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def _fmt_hms(seconds: int | float | None) -> str:
    if not seconds:
        return "00:00:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_float(val: float | None, decimals: int = 1) -> str:
    if val is None:
        return "\u2014"
    return f"{val:.{decimals}f}"


def _fmt_int(val: int | float | None) -> str:
    if val is None:
        return "\u2014"
    return str(round(val))


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return "\u2014"
    day = dt.strftime("%d").lstrip("0")
    months = [tr("ene"), tr("feb"), tr("mar"), tr("abr"), tr("may"), tr("jun"),
              tr("jul"), tr("ago"), "sep", tr("oct"), tr("nov"), tr("dic")]
    month = months[dt.month - 1]
    return f"{day} {month} {dt.year}, {dt.strftime('%H:%M')}"


def _dur_label(sec: int) -> str:
    """Label corto para duración MMP: 5S, 15S, 30S, 1MIN, 5MIN, etc."""
    if sec < 60:
        return f"{sec}S"
    elif sec < 3600:
        return f"{sec // 60}MIN"
    else:
        return f"{sec // 3600}H"


class ActivityDetailView(QWidget):
    """Vista de detalle completa de una actividad."""

    go_back = Signal()
    request_rename = Signal(int)  # activity_id

    def __init__(self, activity_id: int, parent=None):
        super().__init__(parent)
        self._activity_id = activity_id

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(32, 24, 32, 32)
        self._content_layout.setSpacing(20)
        
        scroll.setWidget(content)
        self._scroll_area = scroll
        main_layout.addWidget(scroll)

        self._load_and_build()

    def _load_and_build(self):
        session = get_session()
        try:
            act = session.query(Activity).get(self._activity_id)
            if not act:
                self._add_error(tr("Actividad no encontrada."))
                return
            session.expunge(act)

            # Load latest profile for FTP/weight reference
            profile = (
                session.query(ProfileSnapshot)
                .order_by(ProfileSnapshot.effective_at.desc())
                .first()
            )
            ftp = profile.ftp if profile else 250
            weight_kg = profile.weight_kg if profile else 72
            session.expunge_all()
        finally:
            session.close()

        lay = self._content_layout

        # === Header: back button + title ===
        self._build_header(lay, act)

        # === Stats cards row ===
        self._build_stats_cards(lay, act, ftp)

        # === Potencia / FC / Cadencia ===
        self._build_metric_groups(lay, act, ftp)

        # === Análisis avanzado ===
        self._build_advanced_analysis(lay, act, ftp, weight_kg)

        # === Series temporales (gráfico interactivo) ===
        self._build_time_series(lay, act, ftp)

        # === Mapa de la ruta ===
        self._build_route_map(lay, act)

        # === Notas ===
        self._build_notes(lay, act)

        # === Analizar con IA ===
        self._build_ai_analysis(lay, act, ftp, weight_kg, profile)

        # === Mejor potencia por duración (MMP) ===
        self._build_mmp_peaks(lay, act)

        # === Análisis por cuadrantes de pedaleo ===
        self._build_quadrant_analysis(lay, act, ftp)

        # === Análisis de torque (AET) ===
        self._build_torque_analysis(lay, act)

        # === Balance de pedaleo izquierda / derecha ===
        self._build_pedal_balance(lay, act)

        # === Zonas de potencia y FC ===
        self._build_zones(lay, act, ftp, profile)

        # === Subidas detectadas ===
        self._build_climbs(lay, act, weight_kg)

        # === Intervalos detectados ===
        self._build_intervals(lay, act, ftp)

        lay.addStretch()

    def _add_error(self, msg: str):
        lbl = QLabel(msg)
        lbl.setStyleSheet(f"font-size: {FONT_SIZE_LG}; color: {COLORS['destructive']};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_layout.addWidget(lbl)

    # ─── Header ───────────────────────────────────────────────────
    def _build_header(self, lay: QVBoxLayout, act: Activity):
        header = QHBoxLayout()
        header.setSpacing(14)

        back_btn = QPushButton(tr("← Volver"))
        back_btn.setProperty("class", "ghost")
        back_btn.setFixedHeight(34)
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.go_back.emit)
        header.addWidget(back_btn)
        header.addStretch()
        
        # Rename button
        rename_btn = QPushButton(tr("✏️  Renombrar"))
        rename_btn.setProperty("class", "ghost")
        rename_btn.setFixedHeight(34)
        rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rename_btn.clicked.connect(lambda: self.request_rename.emit(self._activity_id))
        header.addWidget(rename_btn)

        lay.addLayout(header)

        # Title
        title = QLabel(act.display_name)
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_HERO}; font-weight: bold; color: {COLORS['fg']};"
        )
        title.setWordWrap(True)
        lay.addWidget(title)

        # Subtitle: date, sport, source
        sub_parts = []
        sub_parts.append(_fmt_date(act.started_at))
        if act.sport:
            sub_parts.append(act.sport)
        if act.source:
            sub_parts.append(act.source.upper())
        sub = QLabel("  ·  ".join(sub_parts))
        sub.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        lay.addWidget(sub)
        lay.addSpacing(6)

    # ─── Stats Cards ──────────────────────────────────────────────
    def _build_stats_cards(self, lay: QVBoxLayout, act: Activity, ftp: int):
        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)

        moving_time = act.moving_time_sec or act.duration_sec
        calories = act.calories
        if not calories and act.work_kj:
            calories = round(act.work_kj / 0.8658)

        # Hint: mostrar duración total si hay diferencia con moving time
        dur_hint = ""
        if act.moving_time_sec and act.moving_time_sec < act.duration_sec:
            dur_hint = f"{tr('Total')}: {_fmt_hms(act.duration_sec)}"

        cards_data = [
            ("⏱", tr("T. en movimiento"), _fmt_duration(moving_time), "", dur_hint),
            ("📍", tr("Distancia"), _fmt_float(act.distance_km), "km", ""),
            ("⛰️", tr("Desnivel +"), _fmt_int(act.elevation_gain_m), "m", ""),
            ("🔥", tr("Calorías"), f"~{_fmt_int(calories)}" if calories else "\u2014", "kcal",
             tr("Estimado: kJ / 0,8658") if act.work_kj else ""),
            ("🏋", tr("TSS"), _fmt_int(act.tss), "",
             f"IF {_fmt_float(act.intensity_factor, 2)}" if act.intensity_factor else ""),
            ("💨", tr("Vel. media"), _fmt_float(act.avg_speed_kmh), "km/h",
             f"{tr('Máx')} {_fmt_float(act.max_speed_kmh)} km/h" if act.max_speed_kmh else ""),
        ]

        for i, (icon, label, value, unit, hint) in enumerate(cards_data):
            card = StatCard(icon=icon, label=label, value=value, unit=unit, hint=hint)
            cards_layout.addWidget(card, 0, i)

        lay.addLayout(cards_layout)

    # ─── Potencia / FC / Cadencia ─────────────────────────────────
    def _build_metric_groups(self, lay: QVBoxLayout, act: Activity, ftp: int):
        groups_layout = QGridLayout()
        groups_layout.setSpacing(14)

        # Potencia
        power_card = self._metric_card(tr("⚡ Potencia"), [
            (tr("Promedio"), f"{_fmt_int(act.avg_power)} W"),
            (tr("Máxima"), f"{_fmt_int(act.max_power)} W"),
            (tr("NP"), f"{_fmt_int(act.normalized_power)} W"),
            (tr("Trabajo"), f"{_fmt_int(act.work_kj)} kJ"),
            (tr("FTP usado"), f"{_fmt_int(act.ftp_used)} W" if act.ftp_used else "\u2014"),
        ])
        groups_layout.addWidget(power_card, 0, 0)

        # FC
        hr_card = self._metric_card(tr("❤️ Frecuencia cardíaca"), [
            (tr("Promedio"), f"{_fmt_int(act.avg_hr)} bpm"),
            (tr("Máxima"), f"{_fmt_int(act.max_hr)} bpm"),
        ])
        groups_layout.addWidget(hr_card, 0, 1)

        # Cadencia
        cad_card = self._metric_card(tr("🦿 Cadencia"), [
            (tr("Promedio"), f"{_fmt_int(act.avg_cadence)} rpm"),
            (tr("Máxima"), f"{_fmt_int(act.max_cadence)} rpm"),
        ])
        groups_layout.addWidget(cad_card, 0, 2)

        lay.addLayout(groups_layout)

    def _metric_card(self, title: str, rows: list) -> QFrame:
        card = QFrame()
        card.setProperty("class", "card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(18, 16, 18, 16)
        card_lay.setSpacing(10)

        t = QLabel(title)
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        card_lay.addWidget(t)

        for label, value in rows:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']}; background: transparent;"
            )
            row.addWidget(lbl)
            row.addStretch()
            val = QLabel(value)
            val.setStyleSheet(
                f"font-size: {FONT_SIZE_BASE}; font-weight: 600; "
                f"color: {COLORS['fg']}; background: transparent;"
            )
            row.addWidget(val)
            wrapper = QWidget()
            wrapper.setLayout(row)
            wrapper.setStyleSheet("background: transparent;")
            card_lay.addWidget(wrapper)

        return card

    # ─── Análisis avanzado ────────────────────────────────────────
    def _build_advanced_analysis(self, lay: QVBoxLayout, act: Activity, ftp: int, weight_kg: float):
        samples_data = act.get_samples()
        if not samples_data:
            return

        # Use CP = ftp as approximation, W' = 20000 J as default
        cp = ftp
        w_prime_j = 20000

        # Prepare samples for TISS
        tiss_samples = [(s.get("t", 0), s.get("p")) for s in samples_data]
        tiss = calc_tiss(tiss_samples, cp, w_prime_j)

        ef = calc_ef(act.normalized_power, act.avg_hr)
        vf = calc_vf(act.normalized_power, act.avg_power)

        pw_hr_samples = [(s.get("t", 0), s.get("p"), s.get("hr")) for s in samples_data]
        pw_hr = calc_pw_hr_decoupling(pw_hr_samples)

        # Section card
        section = QFrame()
        section.setProperty("class", "card")
        section_lay = QVBoxLayout(section)
        section_lay.setContentsMargins(20, 18, 20, 18)
        section_lay.setSpacing(12)

        title = QLabel(tr("📊 Análisis avanzado"))
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        section_lay.addWidget(title)
        desc = QLabel(tr("Métricas de eficiencia, variabilidad y distribución del estrés de la sesión."))
        desc.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;")
        section_lay.addWidget(desc)

        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(12)

        # TISS con barra Aero/Anaero
        tiss_val = f"{round(tiss.tiss_aero)} / {round(tiss.tiss_anaero)}" if tiss else "\u2014"
        tiss_hint = f"Aero {round(tiss.pct_aero)}% · Anaero {round(tiss.pct_anaero)}%" if tiss else ""
        tiss_pct_aero = tiss.pct_aero if tiss else None
        metrics_grid.addWidget(
            self._analysis_cell(tr("TISS"), tiss_val, tiss_hint, COLORS['accent'],
                                progress_pct=tiss_pct_aero),
            0, 0,
        )

        # EF
        ef_val = _fmt_float(ef, 2) if ef else "\u2014"
        metrics_grid.addWidget(self._analysis_cell(tr("EF"), ef_val, "NP / FC media", COLORS['success']), 0, 1)

        # VF
        vf_val = _fmt_float(vf, 2) if vf else "\u2014"
        metrics_grid.addWidget(self._analysis_cell(tr("VF"), vf_val, tr("NP / potencia media"), COLORS['warning']), 0, 2)

        # PW:HR
        if pw_hr:
            pw_val = f"{pw_hr.decoupling:+.1f}%"
            pw_hint = tr("Deriva cardíaca positiva") if pw_hr.decoupling > 0 else tr("Deriva cardíaca negativa")
            pw_color = COLORS['destructive'] if pw_hr.decoupling > 5 else COLORS['success']
        else:
            pw_val = "\u2014"
            pw_hint = ""
            pw_color = COLORS['fg_muted']
        metrics_grid.addWidget(self._analysis_cell("PW:HR", pw_val, pw_hint, pw_color), 0, 3)

        section_lay.addLayout(metrics_grid)
        lay.addWidget(section)

    def _analysis_cell(self, label: str, value: str, hint: str, color: str,
                       progress_pct: float | None = None) -> QFrame:
        """Celda de análisis avanzado. Si progress_pct se pasa (0-100), dibuja
        una barra de progreso Aero (verde) / Anaero (rojo) debajo del hint."""
        cell = QFrame()
        cell.setProperty("class", "card")
        cell_lay = QVBoxLayout(cell)
        cell_lay.setContentsMargins(14, 12, 14, 12)
        cell_lay.setSpacing(4)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
            f"font-weight: 600; text-transform: uppercase; background: transparent;"
        )
        cell_lay.addWidget(lbl)

        val = QLabel(value)
        val.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: 700; color: {color}; background: transparent;"
        )
        cell_lay.addWidget(val)

        if hint:
            h = QLabel(hint)
            h.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; background: transparent;"
            )
            cell_lay.addWidget(h)

        # Barra de progreso Aero/Anaero
        if progress_pct is not None:
            pct = max(0.0, min(100.0, progress_pct))
            bar_container = QFrame()
            bar_container.setFixedHeight(8)
            bar_container.setStyleSheet(
                f"background: #ef4444; border-radius: 4px; border: none;"
            )
            # La parte aero (verde) se superpone como hijo con ancho proporcional
            bar_aero = QFrame(bar_container)
            bar_aero.setStyleSheet(
                f"background: #22c55e; border-radius: 4px; border: none;"
            )
            bar_aero.setFixedHeight(8)
            # Se posiciona en el layout update
            bar_container._aero_pct = pct  # type: ignore[attr-defined]
            bar_container._aero_bar = bar_aero  # type: ignore[attr-defined]
            bar_container.resizeEvent = lambda ev, bc=bar_container: self._resize_aero_bar(ev, bc)
            cell_lay.addWidget(bar_container)

        return cell

    @staticmethod
    def _resize_aero_bar(event, bar_container):
        """Ajusta el ancho de la barra aero según el porcentaje."""
        pct = getattr(bar_container, '_aero_pct', 0)
        bar_aero = getattr(bar_container, '_aero_bar', None)
        if bar_aero:
            total_w = event.size().width()
            aero_w = max(0, int(total_w * pct / 100.0))
            bar_aero.setGeometry(0, 0, aero_w, event.size().height())

    # ─── Series temporales ──────────────────────────────────────────
    def _build_time_series(self, lay: QVBoxLayout, act: Activity, ftp: int):
        samples_data = act.get_samples()
        if not samples_data:
            return
        # CP/W' para W'bal — usar ftp como approximación de CP
        cp = ftp
        w_prime_j = 20000  # Default W'
        chart = TimeSeriesChart(
            samples=samples_data,
            duration_sec=act.duration_sec or 0,
            cp=cp,
            w_prime_j=w_prime_j,
        )
        lay.addWidget(chart)

    # ─── Mapa de la ruta ─────────────────────────────────────────
    def _build_route_map(self, lay: QVBoxLayout, act: Activity):
        samples_data = act.get_samples()
        has_gps = samples_data and any(
            s.get("lat") is not None and s.get("lng") is not None
            for s in samples_data
        )

        if has_gps:
            map_widget = RouteMapWidget(samples=samples_data)
            if map_widget.has_gps:
                lay.addWidget(map_widget)
            return

        # Sin GPS → mostrar tarjeta con botón de reimportación
        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(10)

        title = QLabel(f"📍 {tr('Mapa de la ruta')}")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: bold; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        sec_lay.addWidget(title)

        msg = QLabel(
            "Esta actividad no tiene datos GPS en sus samples.\n"
            "Selecciona el archivo original (.fit / .tcx) para "
            "actualizar los datos y ver el mapa."
        )
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; "
            f"background: transparent; padding: 8px 0;"
        )
        sec_lay.addWidget(msg)

        reimport_btn = QPushButton(f"📂  {tr('Reimportar archivo para obtener GPS')}")
        reimport_btn.setFixedHeight(36)
        reimport_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reimport_btn.setStyleSheet(
            f"QPushButton {{ background: {COLORS['primary']}; color: white; "
            f"border: none; border-radius: 6px; font-size: {FONT_SIZE_SM}; "
            f"padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {COLORS['primary_hover']}; }}"
        )
        reimport_btn.clicked.connect(
            lambda: self._reimport_for_gps(act.id)
        )
        sec_lay.addWidget(reimport_btn)

        lay.addWidget(section)

    def _reimport_for_gps(self, activity_id: int):
        """Abre file picker, re-parsea el archivo y actualiza samples con GPS."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecciona el archivo original de la actividad",
            "",
            tr("Archivos de actividad (*.fit *.tcx *.xml);;Todos (*)"),
        )
        if not file_path:
            return

        from services.import_service import reimport_activity_samples
        ok, msg = reimport_activity_samples(activity_id, file_path)

        if ok:
            QMessageBox.information(
                self, tr("GPS actualizado"),
                f"✅ {msg}\n\n{tr('La vista se recargará para mostrar el mapa.')}",
            )
            # Recargar la vista completa
            self._reload_view()
        else:
            QMessageBox.warning(self, tr("Error"), f"❌ {msg}")

    def _reload_view(self):
        """Recarga la vista de detalle completa recreando el contenido."""
        # Crear nuevo widget de contenido
        new_content = QWidget()
        self._content_layout = QVBoxLayout(new_content)
        self._content_layout.setContentsMargins(32, 24, 32, 32)
        self._content_layout.setSpacing(20)

        # setWidget elimina el widget anterior automáticamente
        self._scroll_area.setWidget(new_content)
        self._load_and_build()

    # ─── Notas ────────────────────────────────────────────────────
    # ─── Analizar con IA ──────────────────────────────────────────
    def _build_ai_analysis(self, lay: QVBoxLayout, act: Activity, ftp: int,
                           weight_kg: float, profile: Optional[ProfileSnapshot]):
        """Card con botón para analizar la actividad con IA via Ollama."""
        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(10)

        # Header
        header = QHBoxLayout()
        t = QLabel(tr("🧠 Análisis IA"))
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        header.addWidget(t)
        header.addStretch()
        sec_lay.addLayout(header)

        desc = QLabel(tr("Envía todas las métricas de esta actividad al Consejero IA para un análisis contextual."))
        desc.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        desc.setWordWrap(True)
        sec_lay.addWidget(desc)

        # Button — discreto, integrado con el tema
        btn = QPushButton(tr("🧠 Analizar con IA"))
        btn.setFixedHeight(36)
        btn.setMinimumWidth(200)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLORS['bg_secondary']};
                color: {COLORS['fg']};
                font-size: {FONT_SIZE_SM};
                border-radius: {RADIUS};
                border: 1px solid {COLORS['border']};
                padding: 4px 16px;
            }}
            QPushButton:hover {{ background: {COLORS['bg_hover']}; border-color: {COLORS['primary']}; }}
            QPushButton:disabled {{ color: {COLORS['fg_muted']}; border-color: {COLORS['border']}; }}
        """)
        self._ai_btn = btn
        sec_lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Output area (hidden initially)
        output = QTextEdit()
        output.setReadOnly(True)
        output.setVisible(False)
        output.setMinimumHeight(200)
        output.setStyleSheet(f"""
            QTextEdit {{
                background: {COLORS['bg']};
                color: {COLORS['fg']};
                border: 1px solid {COLORS['border']};
                border-radius: {RADIUS};
                font-size: {FONT_SIZE_BASE};
                padding: 12px;
            }}
        """)
        self._ai_output = output
        sec_lay.addWidget(output)

        # Status label
        status = QLabel("")
        status.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        status.setVisible(False)
        self._ai_status = status
        sec_lay.addWidget(status)

        # Connect
        btn.clicked.connect(lambda: self._run_ai_analysis(act, ftp, weight_kg, profile))

        lay.addWidget(section)

    def _run_ai_analysis(self, act: Activity, ftp: int, weight_kg: float,
                         profile: Optional[ProfileSnapshot]):
        """Launches AI analysis in a background thread."""
        self._ai_btn.setEnabled(False)
        self._ai_btn.setText(tr("Analizando..."))
        self._ai_output.setVisible(True)
        self._ai_output.clear()
        self._ai_status.setVisible(True)
        self._ai_status.setText(tr("⏳ Conectando con Ollama..."))

        prompt = self._build_analysis_prompt(act, ftp, weight_kg, profile)

        self._ai_worker = _AiAnalysisWorker(prompt)
        self._ai_worker.token_received.connect(self._on_ai_token)
        self._ai_worker.finished_signal.connect(self._on_ai_finished)
        self._ai_worker.error_signal.connect(self._on_ai_error)
        self._ai_worker.status_signal.connect(lambda msg: self._ai_status.setText(msg))
        self._ai_worker.start()

    def _on_ai_token(self, token: str):
        self._ai_status.setText(tr("✍️ Generando análisis..."))
        cursor = self._ai_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(token)
        self._ai_output.setTextCursor(cursor)
        self._ai_output.ensureCursorVisible()

    def _on_ai_finished(self):
        self._ai_btn.setEnabled(True)
        self._ai_btn.setText(tr("🔄 Repetir análisis"))
        self._ai_status.setText(tr("✅ Análisis completado"))

    def _on_ai_error(self, error_msg: str):
        self._ai_btn.setEnabled(True)
        self._ai_btn.setText(tr("🧠 Analizar con IA"))
        self._ai_status.setText(f"❌ {error_msg}")
        self._ai_status.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['destructive']}; background: transparent;"
        )

    def _build_analysis_prompt(self, act: Activity, ftp: int, weight_kg: float,
                               profile: Optional[ProfileSnapshot]) -> str:
        """Build a comprehensive prompt with all activity metrics."""
        lines: List[str] = []
        lines.append("Analiza en profundidad esta sesión de ciclismo. Aquí tienes todos los datos:")
        lines.append("")

        # Basic info
        lines.append("## DATOS DE LA SESIÓN")
        lines.append(f"- Nombre: {act.display_name}")
        if act.started_at:
            lines.append(f"- Fecha: {act.started_at.strftime('%A %d %B %Y, %H:%M')}")
        if act.is_manual:
            atype = {"strength": "Gimnasio", "walk": "Caminata", "other": "Otro"}.get(act.activity_type or "", "Manual")
            lines.append(f"- Tipo: Sesión manual ({atype})")
        else:
            lines.append(f"- Tipo: {act.sport or 'Ciclismo'}")
        if act.source:
            lines.append(f"- Fuente: {act.source}")

        # Duration / Distance
        lines.append("")
        lines.append("## TIEMPO Y DISTANCIA")
        if act.duration_sec:
            lines.append(f"- Duración total: {_fmt_duration(act.duration_sec)}")
        if act.moving_time_sec and act.duration_sec and act.moving_time_sec < act.duration_sec:
            lines.append(f"- Tiempo en movimiento: {_fmt_duration(act.moving_time_sec)}")
            pct = round((act.duration_sec - act.moving_time_sec) / act.duration_sec * 100, 1)
            lines.append(f"- Tiempo parado: {pct}%")
        if act.distance_km:
            lines.append(f"- Distancia: {round(act.distance_km, 1)} km")
        if act.elevation_gain_m:
            lines.append(f"- Desnivel positivo: {round(act.elevation_gain_m)} m")
        if act.avg_speed_kmh:
            lines.append(f"- Velocidad media: {round(act.avg_speed_kmh, 1)} km/h")
        if act.max_speed_kmh:
            lines.append(f"- Velocidad máxima: {round(act.max_speed_kmh, 1)} km/h")

        # Power
        if not act.is_manual and (act.avg_power or act.normalized_power):
            lines.append("")
            lines.append("## POTENCIA")
            if act.avg_power:
                lines.append(f"- Potencia media: {round(act.avg_power)} W")
            if act.max_power:
                lines.append(f"- Potencia máxima: {act.max_power} W")
            if act.normalized_power:
                lines.append(f"- NP (Potencia Normalizada): {round(act.normalized_power)} W")
            if act.intensity_factor:
                lines.append(f"- IF (Factor de Intensidad): {round(act.intensity_factor, 2)}")
            if act.tss:
                lines.append(f"- TSS: {round(act.tss)}")
            if act.work_kj:
                lines.append(f"- Trabajo: {round(act.work_kj)} kJ")
            if act.ftp_used:
                lines.append(f"- FTP usado: {act.ftp_used} W")
            # VF / EF
            if act.normalized_power and act.avg_power and act.avg_power > 0:
                vf = act.normalized_power / act.avg_power
                lines.append(f"- VF (Factor de Variabilidad): {round(vf, 2)}")
            if act.normalized_power and act.avg_hr and act.avg_hr > 0:
                ef = act.normalized_power / act.avg_hr
                lines.append(f"- EF (Factor de Eficiencia): {round(ef, 2)}")

        # Heart rate
        if act.avg_hr or act.max_hr:
            lines.append("")
            lines.append("## FRECUENCIA CARDÍACA")
            if act.avg_hr:
                lines.append(f"- FC media: {act.avg_hr} ppm")
            if act.max_hr:
                lines.append(f"- FC máxima: {act.max_hr} ppm")

        # Cadence
        if act.avg_cadence:
            lines.append("")
            lines.append("## CADENCIA")
            lines.append(f"- Cadencia media: {round(act.avg_cadence)} rpm")
            if act.max_cadence:
                lines.append(f"- Cadencia máxima: {round(act.max_cadence)} rpm")

        # Pedal balance
        if act.avg_left_balance is not None:
            lines.append("")
            lines.append("## BALANCE DE PEDALEO")
            lb = round(act.avg_left_balance, 1)
            lines.append(f"- Izquierda: {lb}% / Derecha: {round(100 - lb, 1)}%")

        # Zones
        zones_p = act.get_zones_power()
        if zones_p:
            total_z = sum(zones_p.values()) or 1
            z_lines = []
            for z in POWER_ZONES:
                sec = zones_p.get(z.key, 0)
                if sec > 0:
                    pct = round(sec / total_z * 100, 1)
                    z_lines.append(f"- {z.label}: {_fmt_duration(sec)} ({pct}%)")
            if z_lines:
                lines.append("")
                lines.append("## ZONAS DE POTENCIA (Coggan)")
                lines.extend(z_lines)

        zones_hr = act.get_zones_hr()
        if zones_hr:
            total_z = sum(zones_hr.values()) or 1
            z_lines = []
            for z in HR_ZONES:
                sec = zones_hr.get(z.key, 0)
                if sec > 0:
                    pct = round(sec / total_z * 100, 1)
                    z_lines.append(f"- {z.label}: {_fmt_duration(sec)} ({pct}%)")
            if z_lines:
                lines.append("")
                lines.append("## ZONAS DE FC (Friel)")
                lines.extend(z_lines)

        # MMP
        mmp_data = act.get_mmp()
        if mmp_data:
            key_durs = [(5, "5s"), (15, "15s"), (30, "30s"), (60, "1min"),
                        (300, "5min"), (600, "10min"), (1200, "20min"),
                        (1800, "30min"), (3600, "60min")]
            mmp_parts = [f"{lbl}: {round(mmp_data[str(s)])} W"
                         for s, lbl in key_durs
                         if mmp_data.get(str(s))]
            if mmp_parts:
                lines.append("")
                lines.append("## PICOS DE POTENCIA (MMP)")
                lines.append(" · ".join(mmp_parts))

        # Climbs
        climbs = act.get_climbs()
        if climbs:
            lines.append("")
            lines.append(f"## SUBIDAS DETECTADAS ({len(climbs)})")
            for cl in sorted(climbs, key=lambda c: c.get("elev_gain_m", 0), reverse=True)[:5]:
                parts = []
                if cl.get("distance_m"):
                    parts.append(f"{round(cl['distance_m'])} m")
                if cl.get("elev_gain_m"):
                    parts.append(f"+{round(cl['elev_gain_m'])} m")
                if cl.get("avg_gradient"):
                    parts.append(f"{round(cl['avg_gradient'], 1)}% pend.")
                if cl.get("avg_power"):
                    parts.append(f"{cl['avg_power']} W")
                lines.append(f"- Subida: {', '.join(parts)}")

        # Manual session
        if act.is_manual:
            lines.append("")
            lines.append("## SESIÓN MANUAL")
            lines.append(f"- Tipo: {act.activity_type}")
            if act.perceived_if:
                lines.append(f"- IF percibido: {round(act.perceived_if, 2)}")
            if act.tss:
                lines.append(f"- TSS estimado: {round(act.tss)}")

        # Athlete context
        lines.append("")
        lines.append("## CONTEXTO DEL ATLETA")
        if profile:
            lines.append(f"- FTP: {profile.ftp} W")
            lines.append(f"- Peso: {profile.weight_kg} kg")
            lines.append(f"- W/kg FTP: {round(profile.ftp / profile.weight_kg, 2)} W/kg")
            lines.append(f"- FC máx: {profile.hr_max} ppm")
            if profile.hr_lthr:
                lines.append(f"- FCL (umbral): {profile.hr_lthr} ppm")
        else:
            lines.append("- Sin perfil configurado")

        # Notes
        if act.notes:
            lines.append("")
            lines.append("## NOTAS DEL ATLETA")
            lines.append(act.notes)

        # ── Historical context ──
        hist = self._build_historical_context(act)
        if hist:
            lines.append("")
            lines.append(hist)

        return "\n".join(lines)

    def _build_historical_context(self, current_act: Activity) -> str:
        """Enriquece el análisis con contexto histórico del atleta.

        Incluye:
        - Estado de forma actual (CTL/ATL/TSB)
        - Actividades similares recientes para comparación
        - Último modelo CP/W'
        - Evolución de métricas clave
        """
        from datetime import date, timedelta
        from sqlalchemy import desc

        lines: List[str] = []

        try:
            session = get_session()
        except RuntimeError:
            return ""

        today = date.today()

        # ── 1. Estado de forma (CTL / ATL / TSB) ──
        try:
            from calc.fitness import build_fitness_series
            act_rows = (
                session.query(Activity.started_at, Activity.tss)
                .filter(
                    Activity.started_at <= datetime.combine(today, datetime.max.time()),
                    Activity.tss.isnot(None),
                )
                .all()
            )
            if act_rows:
                act_dicts = [{"started_at": a.started_at, "tss": a.tss} for a in act_rows]
                lookback = today - timedelta(days=90)
                series = build_fitness_series(act_dicts, lookback, today)
                if series:
                    last = series[-1]
                    lines.append("## ESTADO DE FORMA ACTUAL")
                    lines.append(f"- CTL (Fitness crónico): {round(last.ctl, 1)}")
                    lines.append(f"- ATL (Fatiga aguda): {round(last.atl, 1)}")
                    lines.append(f"- TSB (Forma): {round(last.tsb, 1)}")
                    # Estado descriptivo
                    if last.tsb > 15:
                        lines.append("- Estado: Fresco / Transición")
                    elif last.tsb > 5:
                        lines.append("- Estado: Fresco")
                    elif last.tsb > -10:
                        lines.append("- Estado: Óptimo para rendir")
                    elif last.tsb > -30:
                        lines.append("- Estado: Carga productiva")
                    else:
                        lines.append("- Estado: ⚠️ Alto riesgo de sobreentrenamiento")
                    # Ramp rate semanal
                    if len(series) >= 8:
                        ramp = series[-1].ctl - series[-8].ctl
                        lines.append(f"- Ramp rate (7d): {round(ramp, 1)} pts/sem")
                    lines.append("")
        except Exception:
            pass

        # ── 2. Último modelo CP / W' ──
        try:
            cp_test = (
                session.query(PowerTestSet)
                .order_by(desc(PowerTestSet.tested_at))
                .first()
            )
            if cp_test and cp_test.cp:
                lines.append("## MODELO CP ACTUAL")
                lines.append(f"- CP: {round(cp_test.cp)} W")
                if cp_test.w_prime:
                    lines.append(f"- W': {round(cp_test.w_prime / 1000, 1)} kJ")
                if cp_test.m_ftp:
                    lines.append(f"- mFTP: {round(cp_test.m_ftp)} W")
                if cp_test.vo2max:
                    lines.append(f"- VO2max estimado: {round(cp_test.vo2max, 1)} ml/kg/min")
                lines.append("")
        except Exception:
            pass

        # ── 3. Actividades similares recientes (comparación) ──
        try:
            cutoff = today - timedelta(days=60)
            recent: List[Activity] = (
                session.query(Activity)
                .filter(
                    Activity.started_at >= datetime.combine(cutoff, datetime.min.time()),
                    Activity.id != current_act.id,
                    Activity.is_manual == False,
                )
                .order_by(desc(Activity.started_at))
                .limit(50)
                .all()
            )

            if recent:
                # Buscar actividades de duración similar (±30%)
                cur_dur = current_act.duration_sec or 0
                similar = []
                if cur_dur > 0:
                    lo, hi = cur_dur * 0.7, cur_dur * 1.3
                    similar = [a for a in recent if a.duration_sec and lo <= a.duration_sec <= hi]

                if similar:
                    lines.append(f"## ACTIVIDADES SIMILARES RECIENTES ({len(similar[:5])} encontradas, ±30% duración)")
                    lines.append("Compara estas métricas con las de la sesión actual para detectar tendencias:")
                    for a in similar[:5]:
                        d_str = a.started_at.strftime("%d/%m") if a.started_at else "?"
                        parts = [f"{d_str} · {a.display_name}"]
                        if a.duration_sec:
                            parts.append(f"{_fmt_duration(a.duration_sec)}")
                        if a.normalized_power:
                            parts.append(f"NP={round(a.normalized_power)}W")
                        if a.avg_power:
                            parts.append(f"Avg={round(a.avg_power)}W")
                        if a.intensity_factor:
                            parts.append(f"IF={round(a.intensity_factor, 2)}")
                        if a.tss:
                            parts.append(f"TSS={round(a.tss)}")
                        if a.avg_hr:
                            parts.append(f"FC={a.avg_hr}")
                        # EF
                        if a.normalized_power and a.avg_hr and a.avg_hr > 0:
                            ef = round(a.normalized_power / a.avg_hr, 2)
                            parts.append(f"EF={ef}")
                        lines.append(f"- {' · '.join(parts)}")
                    lines.append("")

                # Resumen de las últimas 2 semanas
                cutoff_2w = today - timedelta(days=14)
                recent_2w = [a for a in recent
                             if a.started_at and a.started_at.date() >= cutoff_2w]
                if recent_2w:
                    total_tss = sum(a.tss or 0 for a in recent_2w)
                    total_hrs = sum((a.duration_sec or 0) for a in recent_2w) / 3600
                    avg_if = [a.intensity_factor for a in recent_2w if a.intensity_factor]
                    lines.append("## RESUMEN ÚLTIMAS 2 SEMANAS")
                    lines.append(f"- Sesiones: {len(recent_2w)}")
                    lines.append(f"- Horas totales: {round(total_hrs, 1)}h")
                    lines.append(f"- TSS acumulado: {round(total_tss)}")
                    if avg_if:
                        lines.append(f"- IF medio: {round(sum(avg_if) / len(avg_if), 2)}")
                    lines.append("")
        except Exception:
            pass

        if lines:
            header = ("## ═══ CONTEXTO HISTÓRICO ═══\n"
                      "Usa esta información para comparar, detectar tendencias "
                      "y personalizar las recomendaciones.\n")
            return header + "\n".join(lines)
        return ""

    def _build_notes(self, lay: QVBoxLayout, act: Activity):
        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(8)

        header = QHBoxLayout()
        t = QLabel(tr("📝 Notas"))
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        header.addWidget(t)
        header.addStretch()

        edit_btn = QPushButton(tr("✏️ Editar"))
        edit_btn.setProperty("class", "ghost")
        edit_btn.setFixedHeight(30)
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.clicked.connect(lambda: self._edit_notes(act.id))
        header.addWidget(edit_btn)
        sec_lay.addLayout(header)

        notes_text = act.notes or tr("Sin notas.")
        notes_lbl = QLabel(notes_text)
        notes_lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        notes_lbl.setWordWrap(True)
        sec_lay.addWidget(notes_lbl)
        self._notes_label = notes_lbl
        self._notes_act_id = act.id

        lay.addWidget(section)

    def _edit_notes(self, activity_id: int):
        session = get_session()
        try:
            act = session.query(Activity).get(activity_id)
            if not act:
                return
            text, ok = QInputDialog.getMultiLineText(
                self, tr("Editar notas"), tr("Notas:"), act.notes or ""
            )
            if ok:
                act.notes = text.strip() or None
                session.commit()
                self._notes_label.setText(act.notes or tr("Sin notas."))
        finally:
            session.close()

    # ─── MMP Peaks ────────────────────────────────────────────────
    def _build_mmp_peaks(self, lay: QVBoxLayout, act: Activity):
        mmp_data = act.get_mmp()
        if not mmp_data:
            return

        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(12)

        t = QLabel(tr("⚡ Mejor potencia por duración (de esta actividad)"))
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        sec_lay.addWidget(t)
        desc = QLabel(tr("Picos máximos sostenidos durante este entrenamiento."))
        desc.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;")
        sec_lay.addWidget(desc)

        grid = QGridLayout()
        grid.setSpacing(10)

        durations = [5, 15, 30, 60, 300, 600, 1200, 1800, 3600]
        col = 0
        for d in durations:
            val = mmp_data.get(str(d))
            if val is None:
                continue
            cell = QFrame()
            cell.setProperty("class", "card")
            cell.setMinimumWidth(90)
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(12, 10, 12, 10)
            cell_lay.setSpacing(3)
            cell_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

            dur_lbl = QLabel(_dur_label(d))
            dur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dur_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                f"font-weight: 600; text-transform: uppercase; background: transparent;"
            )
            cell_lay.addWidget(dur_lbl)

            val_lbl = QLabel(str(round(val)))
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XL}; font-weight: 700; "
                f"color: {COLORS['accent']}; background: transparent;"
            )
            cell_lay.addWidget(val_lbl)

            unit_lbl = QLabel(tr("W"))
            unit_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unit_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; background: transparent;"
            )
            cell_lay.addWidget(unit_lbl)

            grid.addWidget(cell, 0, col)
            col += 1

        sec_lay.addLayout(grid)
        lay.addWidget(section)

    # ─── Análisis por cuadrantes ─────────────────────────────────
    _CRANK_OPTIONS = [165.0, 167.5, 170.0, 172.5, 175.0, 177.5, 180.0]
    _CRANK_DEFAULT = 175.0

    def _build_quadrant_analysis(self, lay: QVBoxLayout, act: Activity, ftp: int):
        """Análisis de pedaleo por cuadrantes (Coggan).

        - Cadencia de referencia dinámica: usa la cadencia media real del
          entrenamiento (act.avg_cadence); fallback 90 rpm si no hay dato.
        - Selector de longitud de biela interactivo (165–180 mm, default 175).
        - Nota explicativa sobre la invariancia de los % respecto a la biela.
        """
        samples_data = act.get_samples()
        if not samples_data:
            return

        # Construir QuadrantSample list
        q_samples = [
            QuadrantSample(p=s.get("p"), c=s.get("c"))
            for s in samples_data
        ]

        ref_power = float(ftp)

        # Cadencia de referencia: media real del entreno (fallback 90 rpm)
        avg_cad = act.avg_cadence
        if avg_cad is not None and avg_cad > 0:
            ref_cadence = round(avg_cad)
        else:
            ref_cadence = 90.0

        # Estado mutable para la biela seleccionada
        state = {"crank_mm": self._CRANK_DEFAULT}

        # Cálculo inicial
        result = calc_quadrant_analysis(q_samples, ref_power, ref_cadence, state["crank_mm"])
        if not result:
            return

        # ── Construir sección visual ──────────────────────────────
        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(12)

        # Título + selector biela en la misma fila
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        t = QLabel(tr("🔄 Análisis por cuadrantes de pedaleo"))
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        header_row.addWidget(t, 1)

        biela_lbl = QLabel(tr("Biela:"))
        biela_lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; "
            f"background: transparent;"
        )
        header_row.addWidget(biela_lbl)

        combo = QComboBox()
        for v in self._CRANK_OPTIONS:
            combo.addItem(f"{v:g} mm", v)
        combo.setCurrentIndex(self._CRANK_OPTIONS.index(self._CRANK_DEFAULT))
        combo.setFixedWidth(100)
        combo.setStyleSheet(
            f"QComboBox {{ font-size: {FONT_SIZE_SM}; color: {COLORS['fg']}; "
            f"background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 6px; padding: 4px 8px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background: {COLORS['bg_card']}; "
            f"color: {COLORS['fg']}; selection-background-color: {COLORS['primary']}; }}"
        )
        header_row.addWidget(combo)
        sec_lay.addLayout(header_row)

        # Descripción (referencia + muestras)
        desc = QLabel()
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; "
            f"background: transparent;"
        )
        sec_lay.addWidget(desc)

        # Nota de cadencia
        if avg_cad is not None and avg_cad > 0:
            cad_note_text = f"{tr('Cad. media del entreno')}: {round(avg_cad)} rpm"
        else:
            cad_note_text = tr("Cad. ref.: 90 rpm (sin datos de cadencia)")
        cad_note = QLabel(cad_note_text)
        cad_note.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; "
            f"background: transparent;"
        )
        sec_lay.addWidget(cad_note)

        # Nota explicativa sobre invariancia
        inv_note = QLabel(
            tr("Nota: los % de cada cuadrante son invariantes a la longitud de biela ") +
            tr("(CL se cancela en la comparación AEPF/CPV). Cambiar la biela actualiza ") +
            tr("los valores absolutos de referencia (N y m/s), útiles para análisis biomecánico.")
        )
        inv_note.setWordWrap(True)
        inv_note.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; "
            f"font-style: italic; background: transparent;"
        )
        sec_lay.addWidget(inv_note)

        # Grid de cuadrantes
        grid_container = QWidget()
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(12)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        sec_lay.addWidget(grid_container)

        # Info de cuadrantes: (id, label, key, color, hint)
        _Q_INFO = [
            ("Q1", tr("Neuromuscular"), "q1_pct", "#22d3ee", tr("Alta fuerza + Alta velocidad")),
            ("Q2", "Fuerza Resistencia", "q2_pct", "#ff6b35", tr("Alta fuerza + Baja velocidad")),
            ("Q3", tr("Recuperación / Técnica"), "q3_pct", "#6b7d99", tr("Baja fuerza + Baja velocidad")),
            ("Q4", tr("Eficiencia Cardiovascular"), "q4_pct", "#22c55e", tr("Baja fuerza + Alta velocidad")),
        ]

        # Almacén de widgets de porcentaje para actualización
        pct_labels: list[QLabel] = []

        def _populate_grid(res: QuadrantResult):
            """Llena o actualiza la descripción y las celdas de cuadrantes."""
            desc.setText(
                f"AEPF/CPV (Coggan) · Ref: {round(res.ref_power)} W · "
                f"{round(res.ref_cadence)} rpm → {res.ref_aepf} N · "
                f"{res.ref_cpv} m/s · Biela {res.crank_length_mm:g} mm · " +
                f"{res.total_samples} {tr('muestras válidas')}"
            )
            if pct_labels:
                # Actualizar porcentajes existentes
                for lbl, (_, _, key, _, _) in zip(pct_labels, _Q_INFO):
                    lbl.setText(f"{getattr(res, key):.1f}%")
                return

            # Primera vez: crear celdas
            for i, (qid, label, key, color, hint) in enumerate(_Q_INFO):
                cell = QFrame()
                cell.setProperty("class", "card")
                cell_lay = QVBoxLayout(cell)
                cell_lay.setContentsMargins(14, 12, 14, 12)
                cell_lay.setSpacing(4)

                id_lbl = QLabel(qid)
                id_lbl.setStyleSheet(
                    f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                    f"font-weight: 600; text-transform: uppercase; background: transparent;"
                )
                cell_lay.addWidget(id_lbl)

                pct_lbl = QLabel(f"{getattr(res, key):.1f}%")
                pct_lbl.setStyleSheet(
                    f"font-size: {FONT_SIZE_XL}; font-weight: 700; "
                    f"color: {color}; background: transparent;"
                )
                cell_lay.addWidget(pct_lbl)
                pct_labels.append(pct_lbl)

                name_lbl = QLabel(label)
                name_lbl.setStyleSheet(
                    f"font-size: {FONT_SIZE_SM}; font-weight: 600; "
                    f"color: {COLORS['fg']}; background: transparent;"
                )
                cell_lay.addWidget(name_lbl)

                hint_lbl = QLabel(hint)
                hint_lbl.setStyleSheet(
                    f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; "
                    f"background: transparent;"
                )
                cell_lay.addWidget(hint_lbl)

                grid_layout.addWidget(cell, 0, i)

        _populate_grid(result)

        # Callback del selector de biela
        def _on_crank_changed(index: int):
            new_mm = combo.itemData(index)
            if new_mm == state["crank_mm"]:
                return
            state["crank_mm"] = new_mm
            new_result = calc_quadrant_analysis(q_samples, ref_power, ref_cadence, new_mm)
            if new_result:
                _populate_grid(new_result)

        combo.currentIndexChanged.connect(_on_crank_changed)

        lay.addWidget(section)

    # ─── Balance de pedaleo ──────────────────────────────────────
    def _build_torque_analysis(self, lay: QVBoxLayout, act: Activity):
        """Sección de análisis de torque efectivo medio (AET)."""
        samples_data = act.get_samples()
        if not samples_data:
            return

        pts = compute_torque_series(samples_data)
        stats = compute_torque_stats(pts)
        if stats is None or stats.count < 5:
            return

        section = QFrame()
        section.setProperty("class", "card")
        section_lay = QVBoxLayout(section)
        section_lay.setContentsMargins(20, 18, 20, 18)
        section_lay.setSpacing(12)

        title = QLabel(tr("⚡ Par efectivo medio (AET)"))
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: bold; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        section_lay.addWidget(title)

        desc = QLabel(
            tr("AET = Potencia / (Cadencia × 0.10472). ") +
            tr("Mide la fuerza de pedaleo en Newton-metros (Nm).")
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        section_lay.addWidget(desc)

        # Grid de stats
        grid = QGridLayout()
        grid.setSpacing(12)

        stat_items = [
            ("Media",   f"{stats.avg:.1f} Nm",  COLORS['accent']),
            (tr("Máximo"),  f"{stats.max_val:.1f} Nm", COLORS['warning']),
            (tr("Mediana"), f"{stats.median:.1f} Nm", COLORS['success']),
            ("P25–P75", f"{stats.p25:.1f} – {stats.p75:.1f} Nm", COLORS['primary']),
        ]

        for i, (label, value, color) in enumerate(stat_items):
            cell = QFrame()
            cell.setStyleSheet(
                f"background-color: {COLORS['bg_secondary']}; "
                f"border-radius: {RADIUS_LG}; padding: 14px;"
            )
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(14, 12, 14, 12)
            cell_lay.setSpacing(4)

            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
            )
            cell_lay.addWidget(lbl)

            val = QLabel(value)
            val.setStyleSheet(
                f"font-size: {FONT_SIZE_LG}; font-weight: bold; "
                f"color: {color}; background: transparent;"
            )
            cell_lay.addWidget(val)

            grid.addWidget(cell, 0, i)

        section_lay.addLayout(grid)

        # Hint sobre el toggle en el gráfico
        hint = QLabel(
            f"💡 {tr('Muestras válidas')}: {stats.count}. " +
            tr("Activa 'Par (Nm)' en el gráfico de series temporales para verlo superpuesto.")
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; "
            f"background: transparent; padding-top: 4px;"
        )
        section_lay.addWidget(hint)

        lay.addWidget(section)

    def _build_pedal_balance(self, lay: QVBoxLayout, act: Activity):
        """Muestra distribución izquierda / derecha (si hay datos)."""
        left_pct = getattr(act, "avg_left_balance", None)
        if left_pct is None:
            return

        right_pct = round(100.0 - left_pct, 1)
        diff = abs(left_pct - right_pct)

        # Color según desequilibrio
        if diff <= 2:
            status_label = tr("Equilibrado")
            color_left = "#34D399"   # emerald-400
            color_right = "#10B981"  # emerald-500
            status_color = "#34D399"
        elif diff <= 4:
            status_label = tr("Leve asimetría")
            color_left = "#FBBF24"   # amber-400
            color_right = "#F59E0B"  # amber-500
            status_color = "#FBBF24"
        else:
            status_label = tr("Asimetría notable")
            color_left = "#F87171"   # red-400
            color_right = "#EF4444"  # red-500
            status_color = "#F87171"

        section = QFrame()
        section.setObjectName("card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(16, 14, 16, 16)
        sec_lay.setSpacing(10)

        # Título
        title = QLabel(f"🦶  {tr('Balance de pedaleo')}")
        title.setStyleSheet(f"font-size: {FONT_SIZE_LG}; font-weight: 700; color: {COLORS['fg']};")
        sec_lay.addWidget(title)

        # Subtítulo con estado
        desc = QLabel(
            tr("Distribución izquierda / derecha · ") +
            f"<span style='color:{status_color};'>{status_label}</span>"
        )
        desc.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        desc.setTextFormat(Qt.TextFormat.RichText)
        sec_lay.addWidget(desc)

        sec_lay.addSpacing(4)

        # Barra de balance horizontal
        bar_container = QWidget()
        bar_container.setFixedHeight(32)
        bar_container.setStyleSheet(
            f"background: {COLORS['bg_secondary']}; border-radius: {RADIUS};"
        )

        bar_layout = QHBoxLayout(bar_container)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(0)

        # Barra izquierda
        left_bar = QLabel(f"  {left_pct:.1f}%")
        left_bar.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left_bar.setStyleSheet(
            f"background: {color_left}; color: #000000; font-size: {FONT_SIZE_SM}; "
            f"font-weight: 700; padding-right: 6px; "
            f"border-top-left-radius: {RADIUS}; border-bottom-left-radius: {RADIUS};"
        )

        # Barra derecha
        right_bar = QLabel(f"{right_pct:.1f}%  ")
        right_bar.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right_bar.setStyleSheet(
            f"background: {color_right}; opacity: 0.85; color: #000000; "
            f"font-size: {FONT_SIZE_SM}; font-weight: 700; padding-left: 6px; "
            f"border-top-right-radius: {RADIUS}; border-bottom-right-radius: {RADIUS};"
        )

        # Proporción de stretch para simular el %
        left_stretch = max(1, int(left_pct * 10))
        right_stretch = max(1, int(right_pct * 10))
        bar_layout.addWidget(left_bar, left_stretch)
        bar_layout.addWidget(right_bar, right_stretch)

        sec_lay.addWidget(bar_container)

        # Etiquetas debajo
        labels_row = QHBoxLayout()
        lbl_left = QLabel(
            f"🦵 {tr('Izquierda')}: <span style='color:{COLORS['fg']}; font-weight:600;'>"
            f"{left_pct:.1f}%</span>"
        )
        lbl_left.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        lbl_left.setTextFormat(Qt.TextFormat.RichText)

        lbl_right = QLabel(
            f"{tr('Derecha')}: <span style='color:{COLORS['fg']}; font-weight:600;'>"
            f"{right_pct:.1f}%</span> 🦵"
        )
        lbl_right.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']};")
        lbl_right.setTextFormat(Qt.TextFormat.RichText)
        lbl_right.setAlignment(Qt.AlignmentFlag.AlignRight)

        labels_row.addWidget(lbl_left)
        labels_row.addStretch()
        labels_row.addWidget(lbl_right)
        sec_lay.addLayout(labels_row)

        # Nota de pierna dominante
        if diff > 0.5:
            dominant = tr("izquierda") if left_pct > right_pct else tr("derecha")
            note = QLabel(
                f"{tr('Diferencia')}: {diff:.1f}% — {tr('pierna')} {dominant} {tr('dominante')}"
            )
            note.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']};"
            )
            note.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sec_lay.addWidget(note)

        lay.addWidget(section)

    # ─── Zonas ────────────────────────────────────────────────────
    def _build_zones(self, lay: QVBoxLayout, act: Activity, ftp: int, profile):
        zones_power = act.get_zones_power()
        zones_hr = act.get_zones_hr()
        if not zones_power and not zones_hr:
            return

        zones_layout = QGridLayout()
        zones_layout.setSpacing(14)

        if zones_power:
            total_sec = sum(zones_power.values())
            power_card = self._zone_card(
                tr("Tiempo en zonas de potencia"),
                f"{tr('Reparto de tiempo por zona')} ({_fmt_hms(total_sec)} {tr('total')}).",
                POWER_ZONES, zones_power, total_sec,
            )
            zones_layout.addWidget(power_card, 0, 0)

        if zones_hr:
            total_sec = sum(zones_hr.values())
            hr_card = self._zone_card(
                tr("Tiempo en zonas de FC"),
                f"{tr('Reparto de tiempo por zona')} ({_fmt_hms(total_sec)} {tr('total')}).",
                HR_ZONES, zones_hr, total_sec,
            )
            zones_layout.addWidget(hr_card, 0, 1)

        lay.addLayout(zones_layout)

    def _zone_card(self, title: str, desc: str, zone_defs, zone_data: dict, total_sec: int) -> QFrame:
        card = QFrame()
        card.setProperty("class", "card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 16, 20, 16)
        card_lay.setSpacing(8)

        t = QLabel(title)
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        card_lay.addWidget(t)

        d = QLabel(desc)
        d.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;")
        card_lay.addWidget(d)

        card_lay.addSpacing(4)

        for z in zone_defs:
            secs = zone_data.get(z.key, 0)
            pct = (secs / total_sec * 100) if total_sec > 0 else 0
            pct_int = max(0, min(100, round(pct)))

            row = QHBoxLayout()
            row.setSpacing(8)

            # Color dot
            dot = QLabel("●")
            dot.setStyleSheet(f"font-size: {ICON_SM}; color: {z.color}; background: transparent;")
            dot.setFixedWidth(16)
            row.addWidget(dot)

            # Zone label
            name = QLabel(tr(z.label))
            name.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg']}; background: transparent;"
            )
            name.setFixedWidth(150)
            row.addWidget(name)

            # Progress bar estilizada con color de la zona
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct_int)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setMinimumWidth(80)
            bar.setStyleSheet(
                f"QProgressBar {{ background-color: {COLORS['bg_secondary']}; "
                f"border: none; border-radius: 4px; }}"
                f"QProgressBar::chunk {{ background-color: {z.color}; "
                f"border-radius: 4px; }}"
            )
            row.addWidget(bar, stretch=1)

            # Time + pct
            time_lbl = QLabel(f"{_fmt_hms(secs)}  {pct:.0f}%")
            time_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {z.color}; font-weight: 600; background: transparent;"
            )
            time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            time_lbl.setMinimumWidth(110)
            row.addWidget(time_lbl)

            card_lay.addLayout(row)

        return card

    # ─── Subidas ──────────────────────────────────────────────────
    def _build_climbs(self, lay: QVBoxLayout, act: Activity, weight_kg: float):
        climbs_data = act.get_climbs()
        if not climbs_data:
            # Try to detect from samples
            samples_data = act.get_samples()
            if not samples_data:
                return
            climb_samples = []
            cum_dist = 0.0
            for s in samples_data:
                spd = s.get("v", 0) or 0  # speed km/h
                dt_s = 1
                if len(climb_samples) > 0:
                    dt_s = max(1, s.get("t", 0) - climb_samples[-1].t)
                cum_dist += (spd / 3.6) * dt_s
                climb_samples.append(ClimbSampleRow(
                    t=s.get("t", 0),
                    p=s.get("p"),
                    hr=s.get("hr"),
                    c=s.get("c"),
                    alt=s.get("alt"),
                    dist=cum_dist,
                ))
            opts = ClimbDetectionOptions(weight_kg=weight_kg)
            detected = detect_climbs(climb_samples, opts)
            if not detected:
                return
            climbs_data = [
                {
                    "num": c.num,
                    "duration_sec": c.duration_sec,
                    "distance_m": c.distance_m,
                    "elev_gain_m": c.elev_gain_m,
                    "avg_gradient": c.avg_gradient,
                    "max_gradient": c.max_gradient,
                    "vam": c.vam,
                    "avg_power": c.avg_power,
                    "w_kg": c.w_kg,
                    "avg_hr": c.avg_hr,
                    "avg_cadence": c.avg_cadence,
                }
                for c in detected
            ]

        if not climbs_data:
            return

        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(12)

        t = QLabel(tr("⛰️ Subidas detectadas"))
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        sec_lay.addWidget(t)
        desc_text = f"{len(climbs_data)} subidas con gradiente ≥ 3% y desnivel ≥ 30m."
        desc = QLabel(desc_text)
        desc.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;")
        sec_lay.addWidget(desc)

        # Table header
        cols = ["#", tr("Duración"), tr("Distancia"), tr("Desnivel"), "Grad. medio", tr("Grad. máx"),
                tr("VAM"), tr("Potencia"), "W/kg", tr("FC"), tr("Cadencia")]
        header_row = QHBoxLayout()
        header_row.setSpacing(4)
        for col in cols:
            lbl = QLabel(col)
            lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                f"font-weight: 600; text-transform: uppercase; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumWidth(70)
            header_row.addWidget(lbl)
        hw = QWidget()
        hw.setLayout(header_row)
        hw.setStyleSheet("background: transparent;")
        sec_lay.addWidget(hw)

        for c in climbs_data:
            row = QHBoxLayout()
            row.setSpacing(4)
            vals = [
                str(c.get("num", "")),
                _fmt_hms(c.get("duration_sec", 0)),
                f"{_fmt_float(c.get('distance_m', 0) / 1000 if c.get('distance_m') else 0, 2)} km",
                f"{_fmt_int(c.get('elev_gain_m'))} m",
                f"{_fmt_float(c.get('avg_gradient'), 1)}%",
                f"{_fmt_float(c.get('max_gradient'), 1)}%",
                f"{_fmt_int(c.get('vam'))} m/h",
                f"{_fmt_int(c.get('avg_power'))} W",
                f"{_fmt_float(c.get('w_kg'), 2)}",
                f"{_fmt_int(c.get('avg_hr'))} bpm",
                f"{_fmt_int(c.get('avg_cadence'))} rpm",
            ]
            colors = [
                COLORS['primary'],    # #
                COLORS['fg'],         # duration
                COLORS['fg'],         # distance
                COLORS['fg'],         # desnivel
                COLORS['warning'],    # grad medio
                COLORS['fg_muted'],   # grad max
                COLORS['fg'],         # VAM
                COLORS['fg'],         # power
                COLORS['fg'],         # w/kg
                COLORS['fg'],         # hr
                COLORS['fg'],         # cadence
            ]
            for val, clr in zip(vals, colors):
                lbl = QLabel(val)
                lbl.setStyleSheet(
                    f"font-size: {FONT_SIZE_SM}; color: {clr}; "
                    f"font-weight: 500; background: transparent;"
                )
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setMinimumWidth(70)
                row.addWidget(lbl)
            wrapper = QWidget()
            wrapper.setLayout(row)
            wrapper.setStyleSheet("background: transparent;")
            sec_lay.addWidget(wrapper)

        lay.addWidget(section)

    # ─── Intervalos ───────────────────────────────────────────────
    def _build_intervals(self, lay: QVBoxLayout, act: Activity, ftp: int):
        samples_data = act.get_samples()
        if not samples_data:
            return

        i_samples = [
            IntervalSampleRow(
                t=s.get("t", 0),
                p=s.get("p"),
                hr=s.get("hr"),
                c=s.get("c"),
            )
            for s in samples_data
        ]

        opts = DetectIntervalsOptions()
        intervals = detect_intervals(i_samples, float(ftp), opts)
        if not intervals:
            return

        # Compute stats
        powers = [iv.avg_power for iv in intervals if iv.avg_power]
        hrs = [iv.avg_hr for iv in intervals if iv.avg_hr]
        cads = [iv.avg_cadence for iv in intervals if iv.avg_cadence]
        avg_p = round(sum(powers) / len(powers)) if powers else 0
        avg_hr_val = round(sum(hrs) / len(hrs)) if hrs else 0
        avg_cad = round(sum(cads) / len(cads)) if cads else 0

        # Power drift
        if len(intervals) >= 2 and intervals[0].avg_power and intervals[-1].avg_power:
            p_drift = ((intervals[-1].avg_power - intervals[0].avg_power) / intervals[0].avg_power) * 100
        else:
            p_drift = None

        # HR drift
        if len(intervals) >= 2 and intervals[0].avg_hr and intervals[-1].avg_hr:
            hr_drift = ((intervals[-1].avg_hr - intervals[0].avg_hr) / intervals[0].avg_hr) * 100
        else:
            hr_drift = None

        # Consistency (CV)
        if len(powers) >= 2:
            import statistics
            cv = (statistics.stdev(powers) / (sum(powers)/len(powers))) * 100
            if cv < 3:
                consistency_label = tr("Excelente")
                consistency_color = COLORS['success']
            elif cv < 6:
                consistency_label = tr("Buena")
                consistency_color = COLORS['accent']
            else:
                consistency_label = tr("Variable")
                consistency_color = COLORS['warning']
        else:
            cv = None
            consistency_label = "\u2014"
            consistency_color = COLORS['fg_muted']

        section = QFrame()
        section.setProperty("class", "card")
        sec_lay = QVBoxLayout(section)
        sec_lay.setContentsMargins(20, 16, 20, 16)
        sec_lay.setSpacing(12)

        t = QLabel(f"🎯 Intervalos detectados")
        t.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        sec_lay.addWidget(t)
        desc = QLabel(f"{tr('Series de trabajo detectadas automáticamente')} ({len(intervals)} {tr('intervalos')}). " +
                      tr("Umbral: potencia sostenida por encima de Z3."))
        desc.setStyleSheet(f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;")
        desc.setWordWrap(True)
        sec_lay.addWidget(desc)

        # Summary metrics row
        summary_grid = QGridLayout()
        summary_grid.setSpacing(10)

        consistency_text = f"{consistency_label}  CV {cv:.1f}%" if cv is not None else "\u2014"
        summary_grid.addWidget(
            self._analysis_cell(tr("Consistencia"), consistency_text, "", consistency_color), 0, 0
        )

        drift_p_text = f"{p_drift:+.1f}%" if p_drift is not None else "\u2014"
        drift_p_hint = tr("1ª → última serie") if p_drift is not None else ""
        drift_p_color = COLORS['success'] if p_drift is not None and abs(p_drift) < 3 else COLORS['warning']
        summary_grid.addWidget(
            self._analysis_cell(tr("Deriva potencia"), drift_p_text, drift_p_hint, drift_p_color), 0, 1
        )

        drift_hr_text = f"{hr_drift:+.1f}%" if hr_drift is not None else "\u2014"
        drift_hr_hint = tr("Fatiga cardíaca acumulada") if hr_drift is not None else ""
        drift_hr_color = COLORS['destructive'] if hr_drift is not None and hr_drift > 3 else COLORS['success']
        summary_grid.addWidget(
            self._analysis_cell(tr("Deriva FC"), drift_hr_text, drift_hr_hint, drift_hr_color), 0, 2
        )

        media_text = f"{avg_p} W  {avg_hr_val} bpm  {avg_cad} rpm"
        summary_grid.addWidget(
            self._analysis_cell(tr("Media intervalos"), media_text, "", COLORS['fg']), 0, 3
        )
        sec_lay.addLayout(summary_grid)

        # Máx potencia para barras proporcionales
        max_power = max((iv.avg_power for iv in intervals), default=1)

        # Intervals table con separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']}; background: transparent;")
        sec_lay.addWidget(sep)

        # Header
        cols_def = [
            ("#", 40), (tr("Inicio"), 80), (tr("Duración"), 70),
            (tr("P media"), 200), (tr("P máx"), 70), (tr("FC media"), 80),
            (tr("Cad."), 60), (tr("Descanso"), 80),
        ]
        header_row = QHBoxLayout()
        header_row.setSpacing(6)
        for col, w in cols_def:
            lbl = QLabel(col)
            lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; "
                f"font-weight: 600; text-transform: uppercase; background: transparent;"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setMinimumWidth(w)
            if col == tr("P media"):
                header_row.addWidget(lbl, stretch=2)
            else:
                header_row.addWidget(lbl)
        hw = QWidget()
        hw.setLayout(header_row)
        hw.setStyleSheet("background: transparent;")
        sec_lay.addWidget(hw)

        for iv in intervals:
            row = QHBoxLayout()
            row.setSpacing(6)

            # #
            n_lbl = QLabel(str(iv.num))
            n_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['primary']}; "
                f"font-weight: 700; background: transparent;"
            )
            n_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n_lbl.setMinimumWidth(40)
            row.addWidget(n_lbl)

            # Inicio
            start_lbl = QLabel(_fmt_hms(iv.start_sec))
            start_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg']}; "
                f"font-weight: 600; background: transparent;"
            )
            start_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            start_lbl.setMinimumWidth(80)
            row.addWidget(start_lbl)

            # Duración
            dur_lbl = QLabel(_fmt_duration(iv.duration_sec))
            dur_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg']}; "
                f"font-weight: 600; background: transparent;"
            )
            dur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dur_lbl.setMinimumWidth(70)
            row.addWidget(dur_lbl)

            # P media — barra proporcional + valor (como en la web)
            bar_pct = (iv.avg_power / max_power * 100) if max_power > 0 else 0
            bar_container = QWidget()
            bar_container.setMinimumWidth(200)
            bar_container.setStyleSheet("background: transparent;")
            bar_lay = QHBoxLayout(bar_container)
            bar_lay.setContentsMargins(4, 2, 4, 2)
            bar_lay.setSpacing(6)

            # Barra visual
            bar_bg = QFrame()
            bar_bg.setFixedHeight(16)
            bar_bg.setStyleSheet(
                f"background: {COLORS['bg_secondary']}; border-radius: 3px;"
            )
            bar_bg_lay = QHBoxLayout(bar_bg)
            bar_bg_lay.setContentsMargins(0, 0, 0, 0)
            bar_bg_lay.setSpacing(0)
            bar_fill = QFrame()
            bar_fill.setFixedHeight(16)
            bar_fill.setStyleSheet(
                f"background: {COLORS['primary']}; border-radius: 3px; opacity: 0.7;"
            )
            # Usar stretch para proporciones
            bar_bg_lay.addWidget(bar_fill, stretch=max(1, round(bar_pct)))
            if bar_pct < 100:
                spacer_w = QWidget()
                spacer_w.setStyleSheet("background: transparent;")
                bar_bg_lay.addWidget(spacer_w, stretch=max(1, round(100 - bar_pct)))

            bar_lay.addWidget(bar_bg, stretch=1)

            # Valor numérico
            p_val = QLabel(f"{iv.avg_power} W")
            p_val.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['primary']}; "
                f"font-weight: 700; background: transparent;"
            )
            p_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            p_val.setMinimumWidth(50)
            bar_lay.addWidget(p_val)

            row.addWidget(bar_container, stretch=2)

            # P max
            pm_lbl = QLabel(f"{iv.max_power} W")
            pm_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
            )
            pm_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm_lbl.setMinimumWidth(70)
            row.addWidget(pm_lbl)

            # FC media
            hr_lbl = QLabel(f"{iv.avg_hr} bpm" if iv.avg_hr else "—")
            hr_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['success']}; "
                f"font-weight: 500; background: transparent;"
            )
            hr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hr_lbl.setMinimumWidth(80)
            row.addWidget(hr_lbl)

            # Cadencia
            cad_lbl = QLabel(f"{iv.avg_cadence}" if iv.avg_cadence else "—")
            cad_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['accent']}; "
                f"font-weight: 500; background: transparent;"
            )
            cad_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cad_lbl.setMinimumWidth(60)
            row.addWidget(cad_lbl)

            # Descanso
            rec_text = _fmt_duration(iv.recovery_sec) if iv.recovery_sec else "—"
            rec_lbl = QLabel(rec_text)
            rec_lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
            )
            rec_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rec_lbl.setMinimumWidth(80)
            row.addWidget(rec_lbl)

            # Row separator
            wrapper = QWidget()
            wrapper.setLayout(row)
            wrapper.setStyleSheet(
                f"background: transparent; "
                f"border-bottom: 1px solid {COLORS['border']};"
            )
            sec_lay.addWidget(wrapper)

        lay.addWidget(section)

# ─── Worker thread for AI analysis ─────────────────────────────────────────
class _AiAnalysisWorker(QThread):
    """Runs Ollama chat completion in a background thread."""
    token_received = Signal(str)
    finished_signal = Signal()
    error_signal = Signal(str)
    status_signal = Signal(str)  # feedback de progreso

    SYSTEM_PROMPT = (
        "Eres un entrenador de ciclismo experto con nivel de certificación TrainingPeaks "
        "y formación avanzada en fisiología del ejercicio. Analizas datos de entrenamientos "
        "de ciclismo y proporcionas feedback accionable.\n\n"
        "Reglas:\n"
        "- Responde SIEMPRE en español.\n"
        "- Sé conciso pero profundo. Usa un tono técnico-amigable.\n"
        "- Estructura tu análisis con encabezados claros usando ##.\n"
        "- Incluye interpretaciones fisiológicas cuando los datos lo permitan.\n"
        "- Si detectas valores inusuales o métricas excepcionales, destácalos.\n"
        "- Si faltan datos para un análisis completo, indícalo brevemente.\n"
        "- Usa emojis estratégicos (máx 1 por sección) para mejorar la lectura.\n"
        "- No repitas los datos crudos; interprétalos.\n"
        "- IMPORTANTE: Si se incluye CONTEXTO HISTÓRICO, úsalo activamente para:\n"
        "  · Comparar la sesión actual con actividades similares anteriores.\n"
        "  · Detectar tendencias de mejora o empeoramiento (NP, EF, IF, FC).\n"
        "  · Contextualizar el esfuerzo dentro del estado de forma (CTL/TSB).\n"
        "  · Relacionar con el modelo CP/W' si está disponible.\n"
        "  · Personalizar las recomendaciones según la carga reciente.\n"
        "- Ofrece 2-3 sugerencias concretas de mejora al final."
    )

    def __init__(self, user_prompt: str, parent=None):
        super().__init__(parent)
        self._user_prompt = user_prompt

    def run(self):
        import requests as _requests
        import json as _json
        try:
            from services.ai_coach import DEFAULT_OLLAMA_URL, DEFAULT_MODEL, get_ai_coach
        except ImportError:
            DEFAULT_OLLAMA_URL = "http://localhost:11434"
            DEFAULT_MODEL = "qwen3:8b"
            get_ai_coach = None

        # Get configured URL/model
        try:
            if get_ai_coach:
                coach = get_ai_coach()
                base_url = coach._base_url
                model = coach._model
            else:
                base_url = DEFAULT_OLLAMA_URL
                model = DEFAULT_MODEL
        except Exception:
            base_url = DEFAULT_OLLAMA_URL
            model = DEFAULT_MODEL

        # 1) Verificar que Ollama responde
        self.status_signal.emit("Verificando conexión con Ollama...")
        try:
            ping = _requests.get(f"{base_url}/api/tags", timeout=5)
            ping.raise_for_status()
        except Exception:
            self.error_signal.emit(
                f"No se puede conectar con Ollama en {base_url}. "
                "Verifica que Ollama está ejecutándose."
            )
            return

        # 2) Enviar petición
        self.status_signal.emit(f"Enviando al modelo {model}...")
        try:
            r = _requests.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": self._user_prompt},
                    ],
                    "stream": True,
                },
                stream=True,
                timeout=(30, 600),  # 30s connect (modelo puede tardar en cargar), 10min read
            )
            r.raise_for_status()
        except _requests.ConnectionError:
            self.error_signal.emit(
                f"No se puede conectar con Ollama en {base_url}."
            )
            return
        except _requests.Timeout:
            self.error_signal.emit(
                "Tiempo de espera agotado. El modelo puede estar cargándose. "
                "Inténtalo de nuevo en unos segundos."
            )
            return
        except Exception as exc:
            self.error_signal.emit(f"Error al conectar: {exc}")
            return

        # 3) Leer streaming — filtrar <think>...</think> (usado por varios modelos: Qwen3, DeepSeek-R1, QwQ, etc.)
        in_think = False
        got_any_visible = False
        self.status_signal.emit("Modelo razonando...")
        try:
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                token = chunk.get("message", {}).get("content", "")
                if token:
                    i = 0
                    while i < len(token):
                        if in_think:
                            end_idx = token.find("</think>", i)
                            if end_idx != -1:
                                in_think = False
                                i = end_idx + len("</think>")
                                if not got_any_visible:
                                    self.status_signal.emit("Generando respuesta...")
                            else:
                                break  # aún pensando
                        else:
                            start_idx = token.find("<think>", i)
                            if start_idx != -1:
                                if start_idx > i:
                                    got_any_visible = True
                                    self.token_received.emit(token[i:start_idx])
                                in_think = True
                                i = start_idx + len("<think>")
                            else:
                                got_any_visible = True
                                self.token_received.emit(token[i:])
                                break
                if chunk.get("done", False):
                    break
        except _requests.Timeout:
            self.error_signal.emit("Tiempo de espera agotado durante la generación.")
            return
        except Exception as exc:
            self.error_signal.emit(f"Error durante la generación: {exc}")
            return

        self.finished_signal.emit()