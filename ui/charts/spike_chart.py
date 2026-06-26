"""Gráfico interactivo de potencia para el editor de picos.

Muestra la serie original (rojo semitransparente) y la corregida (verde),
con marcadores en los picos detectados y líneas de referencia % FTP.
"""
from __future__ import annotations
from typing import Optional

import numpy as np
from i18n import tr

try:
    import pyqtgraph as pg
    HAS_PG = True
except ImportError:
    HAS_PG = False

from ui.theme import COLORS


class SpikeChart:
    """Widget pyqtgraph para visualizar potencia original vs corregida."""

    def __init__(self):
        if not HAS_PG:
            raise ImportError("pyqtgraph requerido")

        pg.setConfigOptions(antialias=True)
        self.widget = pg.PlotWidget()
        self.widget.setBackground(COLORS["bg"])
        self.widget.showGrid(x=True, y=True, alpha=0.15)
        self.widget.setLabel("left", tr("Potencia (W)"))
        self.widget.setLabel("bottom", tr("Tiempo (min)"))

        # Curvas
        self._original_curve = None
        self._corrected_curve = None
        self._spike_scatter = None
        self._ftp_lines: list = []
        self._cadence_curve = None

        # Datos de spikes para tooltip
        self._spike_data: list[dict] = []  # [{x, y, label}, ...]

        # Eje derecho para cadencia
        self._vb_right = pg.ViewBox()
        self.widget.scene().addItem(self._vb_right)
        self.widget.getAxis('right').linkToView(self._vb_right)
        self._vb_right.setXLink(self.widget)
        self.widget.showAxis('right')
        self.widget.getAxis('right').setLabel(tr('Cadencia (rpm)'),
                                               color=COLORS['fg_muted'])
        self.widget.getAxis('right').setPen(pg.mkPen(COLORS['fg_muted'], width=1))
        self._update_views()
        self.widget.getPlotItem().vb.sigResized.connect(self._update_views)

        # Tooltip flotante para spikes
        self._tooltip = pg.TextItem(
            text='', color=COLORS['fg'], anchor=(0, 1),
            fill=pg.mkBrush(COLORS['bg_card'] + 'E0'),
            border=pg.mkPen(COLORS['accent'], width=1),
        )
        self._tooltip.setFont(pg.QtGui.QFont('Segoe UI', 10))
        self._tooltip.setZValue(100)
        self._tooltip.hide()
        self.widget.addItem(self._tooltip, ignoreBounds=True)

        # Leyenda
        self._legend = self.widget.addLegend(
            offset=(60, 10),
            brush=pg.mkBrush(COLORS["bg"] + "CC"),
            pen=pg.mkPen(COLORS["border"]),
        )

    def _update_views(self):
        self._vb_right.setGeometry(self.widget.getPlotItem().vb.sceneBoundingRect())
        self._vb_right.linkedViewChanged(self.widget.getPlotItem().vb, self._vb_right.XAxis)

    def plot_original(self, time_min: np.ndarray, power: np.ndarray):
        """Dibuja solo la serie original (antes de analizar)."""
        self.widget.clear()
        self._legend.clear()
        self._clear_ftp_lines()
        self._vb_right.clear()
        self._spike_data.clear()
        self._tooltip.hide()
        self.widget.addItem(self._tooltip, ignoreBounds=True)

        self._original_curve = self.widget.plot(
            time_min, power,
            pen=pg.mkPen("#f87171", width=1.5),
            name=tr("Original"),
        )

    def plot_analysis(
        self,
        time_min: np.ndarray,
        original: np.ndarray,
        corrected: np.ndarray,
        spike_indices: list[int],
        accepted_mask: list[bool],
        cadence: Optional[np.ndarray] = None,
        ftp: Optional[float] = None,
        show_ftp_lines: bool = True,
        spike_details: Optional[list] = None,
    ):
        """Dibuja el análisis completo: original + corregida + marcadores."""
        self.widget.clear()
        self._legend.clear()
        self._clear_ftp_lines()
        self._vb_right.clear()
        self._tooltip.hide()
        self.widget.addItem(self._tooltip, ignoreBounds=True)

        # Original (rojo semitransparente)
        self._original_curve = self.widget.plot(
            time_min, original,
            pen=pg.mkPen("#f8717180", width=1.2),
            name=tr("Original"),
        )

        # Corregida (verde)
        self._corrected_curve = self.widget.plot(
            time_min, corrected,
            pen=pg.mkPen("#4ade80", width=1.8),
            name=tr("Corregida"),
        )

        # Marcadores de picos: verde=aceptado, rojo=rechazado
        self._spike_data.clear()
        if spike_indices:
            acc_x = [time_min[i] for i, a in zip(spike_indices, accepted_mask) if a]
            acc_y = [original[i] for i, a in zip(spike_indices, accepted_mask) if a]
            rej_x = [time_min[i] for i, a in zip(spike_indices, accepted_mask) if not a]
            rej_y = [original[i] for i, a in zip(spike_indices, accepted_mask) if not a]

            # Construir datos para tooltip
            for idx_pos, (si, acc) in enumerate(zip(spike_indices, accepted_mask)):
                tx = float(time_min[si])
                ty = float(original[si])
                corr_val = float(corrected[si])
                label = f"Spike #{idx_pos + 1}: {ty:.0f}W → {corr_val:.0f}W"
                if spike_details and idx_pos < len(spike_details):
                    sd = spike_details[idx_pos]
                    reason = getattr(sd.spike, 'reason', '') if hasattr(sd, 'spike') else ''
                    if reason:
                        label += f"\n{reason}"
                estado = tr("Aceptado") if acc else tr("Rechazado")
                label += f"  [{estado}]"
                self._spike_data.append({'x': tx, 'y': ty, 'label': label})

            if acc_x:
                acc_scatter = pg.ScatterPlotItem(
                    acc_x, acc_y,
                    symbol='o', size=10,
                    brush='#22c55e', pen='w',
                    hoverable=True, tip=None,
                )
                acc_scatter.sigHovered.connect(self._on_spike_hovered)
                self.widget.addItem(acc_scatter)
                # Add to legend manually
                self._legend.addItem(acc_scatter, tr('Spike aceptado'))
            if rej_x:
                rej_scatter = pg.ScatterPlotItem(
                    rej_x, rej_y,
                    symbol='x', size=10,
                    brush='#ef4444', pen='#ef4444',
                    hoverable=True, tip=None,
                )
                rej_scatter.sigHovered.connect(self._on_spike_hovered)
                self.widget.addItem(rej_scatter)
                self._legend.addItem(rej_scatter, tr('Spike rechazado'))

        # Líneas FTP
        if ftp and show_ftp_lines:
            self._draw_ftp_lines(ftp)

        # Cadencia en eje derecho
        if cadence is not None and not np.all(np.isnan(cadence)):
            cad_curve = pg.PlotCurveItem(
                time_min, cadence,
                pen=pg.mkPen('#a78bfa50', width=1),
            )
            self._vb_right.addItem(cad_curve)
            self._cadence_curve = cad_curve
            self._vb_right.setYRange(0, float(np.nanmax(cadence)) * 1.3)

    def _draw_ftp_lines(self, ftp: float):
        self._clear_ftp_lines()
        levels = [
            (2.0, "200% FTP", "#fbbf2480"),
            (3.0, "300% FTP", "#f9731680"),
            (4.0, "400% FTP", "#ef444480"),
        ]
        for mult, label, color in levels:
            val = ftp * mult
            line = pg.InfiniteLine(
                pos=val, angle=0,
                pen=pg.mkPen(color, width=1.5, style=pg.QtCore.Qt.PenStyle.DashLine),
                label=label,
                labelOpts={'position': 0.95, 'color': color[:7], 'movable': False},
            )
            self.widget.addItem(line)
            self._ftp_lines.append(line)

    def _clear_ftp_lines(self):
        for line in self._ftp_lines:
            self.widget.removeItem(line)
        self._ftp_lines.clear()

    def _on_spike_hovered(self, scatter_item, points, ev):
        """Muestra tooltip cuando el ratón pasa por encima de un marcador de spike."""
        if not points:
            self._tooltip.hide()
            return

        pt = points[0]
        px, py = pt.pos().x(), pt.pos().y()

        # Buscar en spike_data el más cercano
        best_label = f"{py:.0f}W"
        best_dist = float('inf')
        for sd in self._spike_data:
            dist = abs(sd['x'] - px) + abs(sd['y'] - py)
            if dist < best_dist:
                best_dist = dist
                best_label = sd['label']

        self._tooltip.setText(best_label)
        self._tooltip.setPos(px, py)
        self._tooltip.show()
