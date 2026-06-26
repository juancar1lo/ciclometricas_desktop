"""Vista híbrida de edición de picos de potencia.

Flujo: Abrir → Auto-detectar → Revisar spike a spike (contexto multi-canal)
       → Aceptar/Rechazar individual → Exportar solo los aceptados.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
from i18n import tr

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)

from ui.theme import (
    COLORS, FONT_SIZE_TITLE, FONT_SIZE_LG, FONT_SIZE_BASE,
    FONT_SIZE_SM, FONT_SIZE_XS,
)


class SpikeEditorView(QWidget):
    """Editor híbrido de picos de potencia."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_path: Optional[str] = None
        self._result = None  # CleanResult
        self._ftp: float = 200.0
        self._weight: float = 70.0
        self._build_ui()

    def load_from_profile(self, ftp: float, weight: float):
        self._ftp = ftp
        self._weight = weight
        self._spin_ftp.setValue(ftp)
        self._spin_weight.setValue(weight)

    # ---- Construcción de la UI ----

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background: {COLORS['bg']};")
        root.addWidget(scroll)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        scroll.setWidget(container)

        # Título
        title = QLabel(tr("✂️ Editor de picos de potencia"))
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_TITLE}; font-weight: bold; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        layout.addWidget(title)

        subtitle = QLabel(tr("Detecta automáticamente → revisa con contexto → acepta/rechaza → exporta"))
        subtitle.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        layout.addWidget(subtitle)

        # ---- Fila: Abrir archivo + info ----
        file_row = QHBoxLayout()
        self._btn_open = QPushButton(tr("📂 Abrir archivo FIT / TCX"))
        self._btn_open.setStyleSheet(self._button_style("#3b82f6"))
        self._btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_open.clicked.connect(self._open_file)
        file_row.addWidget(self._btn_open)

        self._lbl_file = QLabel(tr("Ningún archivo seleccionado"))
        self._lbl_file.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        file_row.addWidget(self._lbl_file, 1)
        layout.addLayout(file_row)

        # ---- Parámetros de detección ----
        params_group = QGroupBox(tr("⚙️ Parámetros de detección"))
        params_group.setStyleSheet(self._group_style())
        pg = QHBoxLayout(params_group)
        pg.setSpacing(16)

        # Umbral absoluto
        pg.addWidget(self._make_label(tr("Umbral absoluto (W)")))
        self._spin_max_watts = QSpinBox()
        self._spin_max_watts.setRange(500, 5000)
        self._spin_max_watts.setValue(2500)
        self._spin_max_watts.setSingleStep(100)
        self._spin_max_watts.setStyleSheet(self._spin_style())
        pg.addWidget(self._spin_max_watts)

        # FTP
        pg.addWidget(self._make_label("FTP (W)"))
        self._spin_ftp = QSpinBox()
        self._spin_ftp.setRange(50, 500)
        self._spin_ftp.setValue(int(self._ftp))
        self._spin_ftp.setStyleSheet(self._spin_style())
        pg.addWidget(self._spin_ftp)

        # Peso
        pg.addWidget(self._make_label(tr("Peso (kg)")))
        self._spin_weight = QDoubleSpinBox()
        self._spin_weight.setRange(30, 150)
        self._spin_weight.setValue(self._weight)
        self._spin_weight.setDecimals(1)
        self._spin_weight.setStyleSheet(self._spin_style())
        pg.addWidget(self._spin_weight)

        # Z-score
        pg.addWidget(self._make_label(tr("Sensibilidad Z-score")))
        self._spin_zscore = QDoubleSpinBox()
        self._spin_zscore.setRange(1.5, 10.0)
        self._spin_zscore.setValue(4.0)
        self._spin_zscore.setSingleStep(0.5)
        self._spin_zscore.setDecimals(1)
        self._spin_zscore.setStyleSheet(self._spin_style())
        pg.addWidget(self._spin_zscore)

        # Método
        pg.addWidget(self._make_label(tr("Método de corrección")))
        self._combo_method = QComboBox()
        self._combo_method.addItems([
            tr("Interpolación lineal"),
            tr("Media local"),
            tr("Recortar al umbral"),
            tr("Auto"),
        ])
        self._combo_method.setStyleSheet(self._combo_style())
        pg.addWidget(self._combo_method)

        pg.addStretch()
        layout.addWidget(params_group)

        # ---- Botones de acción ----
        btn_row = QHBoxLayout()

        self._btn_analyze = QPushButton(tr("🔍 Analizar picos"))
        self._btn_analyze.setStyleSheet(self._button_style("#8b5cf6"))
        self._btn_analyze.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.clicked.connect(self._analyze)
        btn_row.addWidget(self._btn_analyze)

        self._btn_export = QPushButton(tr("💾 Exportar archivo limpio"))
        self._btn_export.setStyleSheet(self._button_style("#22c55e"))
        self._btn_export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self._export)
        btn_row.addWidget(self._btn_export)

        # Toggle líneas FTP
        self._chk_ftp_lines = QCheckBox(tr("Líneas % FTP"))
        self._chk_ftp_lines.setChecked(True)
        self._chk_ftp_lines.setStyleSheet(f"color: {COLORS['fg']}; font-size: {FONT_SIZE_SM};")
        self._chk_ftp_lines.toggled.connect(self._on_ftp_lines_toggle)
        btn_row.addWidget(self._chk_ftp_lines)

        # Aceptar/Rechazar todos
        self._btn_accept_all = QPushButton(tr("✅ Aceptar todos"))
        self._btn_accept_all.setStyleSheet(self._button_style_small("#22c55e"))
        self._btn_accept_all.setEnabled(False)
        self._btn_accept_all.clicked.connect(lambda: self._set_all_accepted(True))
        btn_row.addWidget(self._btn_accept_all)

        self._btn_reject_all = QPushButton(tr("❌ Rechazar todos"))
        self._btn_reject_all.setStyleSheet(self._button_style_small("#ef4444"))
        self._btn_reject_all.setEnabled(False)
        self._btn_reject_all.clicked.connect(lambda: self._set_all_accepted(False))
        btn_row.addWidget(self._btn_reject_all)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ---- Gráfico ----
        self._chart_container = QWidget()
        chart_layout = QVBoxLayout(self._chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)

        try:
            from ui.charts.spike_chart import SpikeChart
            self._chart = SpikeChart()
            chart_layout.addWidget(self._chart.widget)
            self._chart.widget.setMinimumHeight(300)
        except ImportError:
            self._chart = None
            no_chart = QLabel(tr("⚠️ pyqtgraph no instalado — los gráficos no están disponibles."))
            no_chart.setStyleSheet(f"color: {COLORS['fg_muted']}; font-size: {FONT_SIZE_BASE};")
            chart_layout.addWidget(no_chart)

        layout.addWidget(self._chart_container)

        # ---- Resumen de impacto ----
        self._impact_card = QFrame()
        self._impact_card.setStyleSheet(
            f"background: {COLORS['bg_card']}; border-radius: 10px; padding: 16px;"
        )
        self._impact_card.setVisible(False)
        impact_layout = QVBoxLayout(self._impact_card)

        impact_title = QLabel(tr("📊 Resumen de impacto"))
        impact_title.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']}; background: transparent;"
        )
        impact_layout.addWidget(impact_title)

        self._impact_label = QLabel()
        self._impact_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg']}; background: transparent;"
        )
        impact_layout.addWidget(self._impact_label)
        layout.addWidget(self._impact_card)

        # ---- Tabla de picos con contexto ----
        spikes_title = QLabel(tr("📝 Picos detectados — revisa y acepta/rechaza"))
        spikes_title.setStyleSheet(
            f"font-size: {FONT_SIZE_LG}; font-weight: bold; color: {COLORS['fg']};"
            f" background: transparent; margin-top: 8px;"
        )
        self._spikes_title = spikes_title
        spikes_title.setVisible(False)
        layout.addWidget(spikes_title)

        # Contenedor de tarjetas de spike
        self._spike_cards_container = QWidget()
        self._spike_cards_layout = QVBoxLayout(self._spike_cards_container)
        self._spike_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._spike_cards_layout.setSpacing(12)
        self._spike_cards_container.setVisible(False)
        layout.addWidget(self._spike_cards_container)

        self._no_spikes_label = QLabel()
        self._no_spikes_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; color: {COLORS['accent']}; background: transparent;"
        )
        self._no_spikes_label.setVisible(False)
        layout.addWidget(self._no_spikes_label)

        layout.addStretch()

    # ---- Acciones ----

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Abrir archivo de actividad"), "",
            "FIT / TCX (*.fit *.tcx);;Todos (*)"
        )
        if not path:
            return

        self._file_path = path
        name = os.path.basename(path)
        self._lbl_file.setText(f"📄 {name}")
        self._lbl_file.setStyleSheet(
            f"font-size: {FONT_SIZE_BASE}; color: {COLORS['accent']}; background: transparent;"
        )
        self._btn_analyze.setEnabled(True)
        self._btn_export.setEnabled(False)
        self._result = None
        self._hide_results()

        # Previsualizar la serie original
        try:
            from spike_filter.pipeline import _parse_trackpoints
            ext = path.lower()
            ft = "fit" if ext.endswith(".fit") else "tcx" if ext.endswith(".tcx") else None
            if ft:
                tps = _parse_trackpoints(open(path, 'rb').read(), ft)
                power = np.array([tp.power or 0 for tp in tps], dtype=float)
                time_min = np.array([tp.t / 60 for tp in tps], dtype=float)
                if self._chart:
                    self._chart.plot_original(time_min, power)
        except Exception:
            pass

    def _analyze(self):
        if not self._file_path:
            return

        try:
            from spike_filter import clean_file

            max_watts = self._spin_max_watts.value()
            ftp = self._spin_ftp.value()
            weight = self._spin_weight.value()
            zscore = self._spin_zscore.value()
            method_map = {0: "interpolate", 1: "local_mean", 2: "cap", 3: "auto"}
            method = method_map.get(self._combo_method.currentIndex(), "interpolate")

            self._result = clean_file(
                self._file_path,
                max_watts=max_watts,
                ftp=ftp,
                weight_kg=weight,
                zscore_threshold=zscore,
                method=method,
                cap_value=float(max_watts) if method == "cap" else None,
            )

            self._update_chart()
            self._update_impact()
            self._build_spike_cards()

            self._btn_export.setEnabled(self._result.num_spikes > 0)
            self._btn_accept_all.setEnabled(self._result.num_spikes > 0)
            self._btn_reject_all.setEnabled(self._result.num_spikes > 0)

            if self._result.num_spikes == 0:
                self._no_spikes_label.setText(
                    tr("No se detectaron picos aberrantes con los parámetros actuales.")
                )
                self._no_spikes_label.setVisible(True)

        except Exception as e:
            QMessageBox.warning(self, tr("Error"), f"{tr('Error al analizar')}:\n{e}")

    def _export(self):
        if not self._result or self._result.num_accepted == 0:
            QMessageBox.information(
                self, tr("Info"),
                tr("No hay picos aceptados para exportar.")
            )
            return

        base = os.path.splitext(self._file_path)[0]
        ext = os.path.splitext(self._file_path)[1]
        suggested = f"{base}_clean{ext}"

        path, _ = QFileDialog.getSaveFileName(
            self, tr("Guardar archivo limpio"), suggested,
            f"*{ext}"
        )
        if not path:
            return

        try:
            self._result.save(path)
            QMessageBox.information(
                self, tr("✅ Exportado"),
                f"{tr('✅ Archivo limpio')}:\n{os.path.basename(path)}\n\n"
                f"{tr('Picos corregidos')}: {self._result.num_accepted} / {self._result.num_spikes}",
            )
        except Exception as e:
            QMessageBox.warning(self, tr("Error"), f"{tr('Error al exportar')}:\n{e}")

    # ---- UI update helpers ----

    def _hide_results(self):
        self._impact_card.setVisible(False)
        self._spikes_title.setVisible(False)
        self._spike_cards_container.setVisible(False)
        self._no_spikes_label.setVisible(False)

    def _update_chart(self):
        if not self._chart or not self._result:
            return
        r = self._result
        time_min = r.timestamps / 60.0
        spike_indices = [sd.spike.index for sd in r.spike_details]
        accepted_mask = [sd.accepted for sd in r.spike_details]

        self._chart.plot_analysis(
            time_min=time_min,
            original=r.original_power,
            corrected=r.corrected_power,
            spike_indices=spike_indices,
            accepted_mask=accepted_mask,
            cadence=r.cadence,
            ftp=self._spin_ftp.value(),
            show_ftp_lines=self._chk_ftp_lines.isChecked(),
            spike_details=r.spike_details,
        )

    def _update_impact(self):
        if not self._result:
            return
        r = self._result
        mi = r.metrics_impact
        lines = []
        lines.append(f"{tr('Picos detectados')}: {r.num_spikes}  |  "
                     f"{tr('Aceptados')}: {r.num_accepted}")
        lines.append(f"{tr('Potencia media')}: {mi.avg_power_before:.1f} → {mi.avg_power_after:.1f} W "
                     f"({mi.avg_power_delta:+.1f} W)")
        lines.append(f"{tr('Potencia máxima')}: {mi.max_power_before:.0f} → {mi.max_power_after:.0f} W "
                     f"({mi.max_power_delta:+.0f} W)")
        if mi.np_before is not None:
            lines.append(f"NP: {mi.np_before:.1f} → {mi.np_after:.1f} W")

        self._impact_label.setText("\n".join(lines))
        self._impact_card.setVisible(True)

    def _build_spike_cards(self):
        """Construye una tarjeta por cada spike detectado con contexto multi-canal."""
        # Limpiar tarjetas anteriores
        while self._spike_cards_layout.count():
            item = self._spike_cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._result or self._result.num_spikes == 0:
            self._spikes_title.setVisible(False)
            self._spike_cards_container.setVisible(False)
            return

        self._spikes_title.setVisible(True)
        self._spike_cards_container.setVisible(True)
        self._no_spikes_label.setVisible(False)

        for i, sd in enumerate(self._result.spike_details):
            card = self._make_spike_card(i, sd)
            self._spike_cards_layout.addWidget(card)

    def _make_spike_card(self, idx: int, sd) -> QFrame:
        """Crea una tarjeta para un spike con checkbox + contexto multi-canal."""
        from spike_filter.pipeline import SpikeDetail

        card = QFrame()
        card.setObjectName(f"spikeCard_{idx}")
        card.setStyleSheet(
            f"QFrame#spikeCard_{idx} {{ background: {COLORS['bg_card']}; border-radius: 8px; "
            f"border: 1px solid {COLORS['border']}; padding: 12px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setSpacing(8)

        # Fila cabecera: checkbox + info del spike
        header = QHBoxLayout()

        chk = QCheckBox()
        chk.setChecked(sd.accepted)
        chk.setStyleSheet("QCheckBox::indicator { width: 18px; height: 18px; }")
        chk.toggled.connect(lambda checked, i=idx: self._on_spike_toggle(i, checked))
        header.addWidget(chk)

        time_str = self._format_time(sd.spike.time_sec)
        info = QLabel(
            f"<b>Spike #{idx + 1}</b> — {time_str} — "
            f"<span style='color:#f87171'>{sd.spike.original_watts:.0f} W</span> → "
            f"<span style='color:#4ade80'>{sd.correction.corrected_watts:.0f} W</span> — "
            f"<span style='color:{COLORS['fg_muted']}'>{sd.spike.reason}</span>"
            f" — <span style='color:{COLORS['accent']}'>[{sd.correction.method}]</span>"
        )
        info.setStyleSheet(f"font-size: {FONT_SIZE_BASE}; color: {COLORS['fg']}; background: transparent;")
        header.addWidget(info, 1)

        # Etiqueta de estado
        status = QLabel(tr("✅ Aceptado") if sd.accepted else tr("❌ Rechazado"))
        status.setObjectName(f"status_{idx}")
        status.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; font-weight: bold; background: transparent; "
            f"color: {'#22c55e' if sd.accepted else '#ef4444'};"
        )
        header.addWidget(status)
        layout.addLayout(header)

        # Tabla de contexto multi-canal (±10 s) — una sola QLabel con tabla HTML
        ctx = sd.context
        if ctx:
            accent = COLORS['accent']
            bg_sec = COLORS['bg_secondary']
            fg = COLORS['fg']
            bg_c = COLORS['bg_card']
            brd = COLORS['border']

            html = (
                f'<table width="100%" cellspacing="0" cellpadding="6" '
                f'style="border-collapse:collapse; border:1px solid {brd};">' 
                f'<tr style="background-color:{bg_sec};">' 
            )
            col_names = [
                tr("Tiempo"), tr("Potencia (W)"), "FC (ppm)",
                tr("Cadencia"), tr("Vel. (km/h)"), tr("Altitud (m)"),
            ]
            for name in col_names:
                html += (
                    f'<th style="color:{accent}; font-size:11px; font-weight:bold; '
                    f'text-align:center; padding:6px 4px; '
                    f'border-bottom:2px solid {accent}; '
                    f'border-right:1px solid {brd};">{name}</th>'
                )
            html += '</tr>'

            spike_t = sd.spike.time_sec

            for row_i, snap in enumerate(ctx):
                is_spike = abs(snap.t - spike_t) < 0.5
                if is_spike:
                    row_bg = "#2a1015"
                else:
                    row_bg = bg_c if row_i % 2 == 0 else bg_sec

                items = [
                    self._format_time(snap.t),
                    f"{snap.power:.0f}" if not np.isnan(snap.power) else "—",
                    f"{snap.hr:.0f}" if snap.hr is not None else "—",
                    f"{snap.cadence:.0f}" if snap.cadence is not None else "—",
                    f"{snap.speed_kmh:.1f}" if snap.speed_kmh is not None else "—",
                    f"{snap.altitude:.0f}" if snap.altitude is not None else "—",
                ]

                html += f'<tr style="background-color:{row_bg};">'
                for col_i, text in enumerate(items):
                    cell_bg = "#3b1419" if (is_spike and col_i == 1) else row_bg
                    html += (
                        f'<td style="color:{fg}; font-size:12px; '
                        f'text-align:center; padding:4px; '
                        f'background-color:{cell_bg}; '
                        f'border-bottom:1px solid {brd}; '
                        f'border-right:1px solid {brd};">{text}</td>'
                    )
                html += '</tr>'

            html += '</table>'

            browser = QTextBrowser()
            browser.setOpenLinks(False)
            browser.setHtml(html)
            browser.setStyleSheet(
                f"QTextBrowser {{ background: transparent; border: none; "
                f"padding: 0; color: {COLORS['fg']}; }}"
            )
            # Calcular altura necesaria: ~28px por fila + 32px header + 16 margen
            num_rows = len(ctx)
            needed_h = 32 + 28 * num_rows + 16
            browser.setFixedHeight(needed_h)
            browser.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            layout.addWidget(browser)

        return card

    def _on_spike_toggle(self, idx: int, accepted: bool):
        """Cuando el usuario acepta/rechaza un spike individual."""
        if not self._result:
            return
        self._result.spike_details[idx].accepted = accepted
        self._result.recalc_with_accepted()
        self._update_impact()
        self._update_chart()

        # Actualizar etiqueta de estado en la tarjeta
        card = self._spike_cards_layout.itemAt(idx)
        if card and card.widget():
            status = card.widget().findChild(QLabel, f"status_{idx}")
            if status:
                if accepted:
                    status.setText(tr("✅ Aceptado"))
                    status.setStyleSheet(
                        f"font-size: {FONT_SIZE_SM}; font-weight: bold; "
                        f"background: transparent; color: #22c55e;"
                    )
                else:
                    status.setText(tr("❌ Rechazado"))
                    status.setStyleSheet(
                        f"font-size: {FONT_SIZE_SM}; font-weight: bold; "
                        f"background: transparent; color: #ef4444;"
                    )

    def _set_all_accepted(self, accepted: bool):
        if not self._result:
            return
        for i, sd in enumerate(self._result.spike_details):
            sd.accepted = accepted
        self._result.recalc_with_accepted()
        self._update_impact()
        self._update_chart()
        self._build_spike_cards()

    def _on_ftp_lines_toggle(self, checked: bool):
        self._update_chart()

    # ---- Formateo ----

    @staticmethod
    def _format_time(t_sec: float) -> str:
        m, s = divmod(int(t_sec), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ---- Estilos ----

    @staticmethod
    def _button_style(color: str) -> str:
        return (
            f"QPushButton {{ background: {color}; color: white; border: none; "
            f"border-radius: 8px; padding: 10px 20px; font-size: 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {color}dd; }}"
            f"QPushButton:disabled {{ background: {COLORS['bg_card']}; color: {COLORS['fg_muted']}; }}"
        )

    @staticmethod
    def _button_style_small(color: str) -> str:
        return (
            f"QPushButton {{ background: {color}30; color: {color}; border: 1px solid {color}60; "
            f"border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {color}50; }}"
            f"QPushButton:disabled {{ background: transparent; color: {COLORS['fg_muted']}; border-color: {COLORS['border']}; }}"
        )

    @staticmethod
    def _group_style() -> str:
        return (
            f"QGroupBox {{ background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; "
            f"border-radius: 10px; padding: 16px; padding-top: 28px; "
            f"font-size: 13px; font-weight: bold; color: {COLORS['fg']}; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; "
            f"color: {COLORS['fg']}; }}"
        )

    @staticmethod
    def _spin_style() -> str:
        return (
            f"QSpinBox, QDoubleSpinBox {{ background: {COLORS['bg']}; color: {COLORS['fg']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"padding: 4px 8px; font-size: 13px; }}"
        )

    @staticmethod
    def _combo_style() -> str:
        return (
            f"QComboBox {{ background: {COLORS['bg']}; color: {COLORS['fg']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
            f"padding: 4px 8px; font-size: 13px; }}"
            f"QComboBox QAbstractItemView {{ background: {COLORS['bg_card']}; color: {COLORS['fg']}; "
            f"selection-background-color: {COLORS['accent']}; }}"
        )

    @staticmethod
    def _table_style() -> str:
        return (
            f"QTableWidget {{ background: {COLORS['bg_card']}; color: {COLORS['fg']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 0px; "
            f"gridline-color: {COLORS['border']}; font-size: 12px; }} "
            f"QTableWidget QHeaderView {{ background: {COLORS['bg_secondary']}; }} "
            f"QTableWidget QHeaderView::section {{ "
            f"background-color: {COLORS['bg_secondary']}; color: {COLORS['fg']}; "
            f"border: none; border-bottom: 2px solid {COLORS['accent']}; "
            f"border-right: 1px solid {COLORS['border']}; "
            f"padding: 4px 2px; font-size: 11px; font-weight: bold; "
            f"min-height: 22px; }} "
            f"QTableWidget QHeaderView::section:last {{ border-right: none; }}"
        )

    def _make_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        return lbl


def pg_color(hex_color: str):
    """Convierte color hex a QColor para usar en QTableWidgetItem.setBackground."""
    from PySide6.QtGui import QColor, QBrush
    c = QColor(hex_color)
    return QBrush(c)
