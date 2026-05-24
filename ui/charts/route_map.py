"""Mapa de ruta interactivo para detalle de actividad.

Genera HTML Leaflet embebido (sin CDN) cargado desde file:// temporal.
Esto evita dos bugs del diseño anterior:
  1. URL de tile rota (apuntaba a una imagen de blog en vez de OSM).
  2. Bloqueo de scripts CDN desde file:// por la política CORS de WebEngine.

Solución: Leaflet se descarga una vez en runtime y se cachea en disco,
o se carga desde CDN usando setHtml() + página base https: vacía
(baseUrl trick de Qt WebEngine).
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
    QSizePolicy,
)

from ui.theme import (
    COLORS, FONT_SIZE_SM, FONT_SIZE_XL, FONT_SIZE_XS,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


# Gradiente azul → verde → amarillo → naranja → rojo
_GRADIENT = [
    (0.00, (59, 130, 246)),
    (0.25, (34, 197, 94)),
    (0.50, (234, 179, 8)),
    (0.75, (249, 115, 22)),
    (1.00, (239, 68, 68)),
]


def _interpolate_color(pct: float) -> Tuple[int, int, int]:
    pct = max(0.0, min(1.0, pct))
    for i in range(len(_GRADIENT) - 1):
        p0, c0 = _GRADIENT[i]
        p1, c1 = _GRADIENT[i + 1]
        if pct <= p1:
            t = (pct - p0) / (p1 - p0) if p1 != p0 else 0
            return (
                int(c0[0] + (c1[0] - c0[0]) * t),
                int(c0[1] + (c1[1] - c0[1]) * t),
                int(c0[2] + (c1[2] - c0[2]) * t),
            )
    return (239, 68, 68)


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


# ═══════════════════════════════════════════════════════════════════════════
# Plantilla HTML: Leaflet cargado desde CDN usando setHtml() con baseUrl
# de una URL https real, lo que permite a WebEngine cargar recursos externos.
# ═══════════════════════════════════════════════════════════════════════════
_MAP_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet"
      href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        crossorigin=""></script>
<style>
  html, body { margin:0; padding:0; width:100%%; height:100%%;
               background:#111827; overflow:hidden; }
  #map { width:100%%; height:100%%; }
</style>
</head>
<body>
<div id="map"></div>
<script>
(function(){
  var segments = %s;
  var bounds   = %s;
  var startPt  = %s;
  var endPt    = %s;

  // Esperar a que Leaflet esté disponible (por si el script tarda en cargar)
  function init() {
    if (typeof L === 'undefined') { setTimeout(init, 100); return; }

    var map = L.map('map', {scrollWheelZoom: true, zoomControl: true});

    // ── Tile layer OSM correcto ──────────────────────────────────
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19
    }).addTo(map);

    map.fitBounds(bounds, {padding: [30, 30], maxZoom: 16});

    segments.forEach(function(seg) {
      L.polyline(seg.p, {color: seg.c, weight: 4, opacity: 0.9}).addTo(map);
    });

    L.circleMarker(startPt, {
      radius: 7, fillColor: '#22C55E', color: '#ffffff',
      weight: 2, fillOpacity: 1
    }).addTo(map).bindTooltip('Inicio', {permanent: false});

    L.circleMarker(endPt, {
      radius: 7, fillColor: '#EF4444', color: '#ffffff',
      weight: 2, fillOpacity: 1
    }).addTo(map).bindTooltip('Fin', {permanent: false});
  }

  init();
})();
</script>
</body>
</html>"""

# URL base ficticia https: — Qt WebEngine la usa para resolver recursos
# externos (CDN). No tiene que existir realmente.
_BASE_URL = QUrl("https://ciclometricas.app/map/")


def _build_map_html(
    gps_points: List[dict],
    color_mode: str,
    min_val: float,
    max_val: float,
) -> str:
    """Genera el HTML completo del mapa Leaflet con segmentos coloreados."""
    lats = [p["lat"] for p in gps_points]
    lngs = [p["lng"] for p in gps_points]
    bounds = [[min(lats), min(lngs)], [max(lats), max(lngs)]]
    start = [gps_points[0]["lat"], gps_points[0]["lng"]]
    end   = [gps_points[-1]["lat"], gps_points[-1]["lng"]]

    rng = max_val - min_val
    segments = []
    for i in range(1, len(gps_points)):
        p0 = gps_points[i - 1]
        p1 = gps_points[i]
        if color_mode == "power":
            v = p1.get("p")
        elif color_mode == "hr":
            v = p1.get("hr")
        else:
            v = p1.get("v") or p1.get("s")
        pct = ((float(v) - min_val) / rng) if (v is not None and rng > 0) else 0.5
        color = _rgb_to_hex(_interpolate_color(pct))
        segments.append({
            "p": [[p0["lat"], p0["lng"]], [p1["lat"], p1["lng"]]],
            "c": color,
        })

    return _MAP_HTML % (
        json.dumps(segments),
        json.dumps(bounds),
        json.dumps(start),
        json.dumps(end),
    )


# ═══════════════════════════════════════════════════════════════════════════
class RouteMapWidget(QFrame):
    """Mapa Leaflet con ruta coloreada por potencia / FC / velocidad."""

    def __init__(self, samples: list[dict], parent=None):
        super().__init__(parent)
        self.setProperty("class", "card")

        self._gps_points: List[dict] = [
            s for s in samples
            if s.get("lat") is not None and s.get("lng") is not None
            and math.isfinite(s["lat"]) and math.isfinite(s["lng"])
        ]
        self._has_power = any(p.get("p")  is not None for p in self._gps_points)
        self._has_hr    = any(p.get("hr") is not None for p in self._gps_points)
        self._has_speed = any(
            (p.get("v") is not None or p.get("s") is not None)
            for p in self._gps_points
        )

        # FIX: elegir modo inicial según disponibilidad de datos
        if self._has_power:
            self._color_mode = "power"
        elif self._has_hr:
            self._color_mode = "hr"
        else:
            self._color_mode = "speed"

        self._build_ui()

    @property
    def has_gps(self) -> bool:
        return len(self._gps_points) >= 2

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        if not self.has_gps:
            self.setVisible(False)
            return

        if not HAS_WEBENGINE:
            msg = QLabel(
                "🗺️ Para ver el mapa, instala PySide6-WebEngine:\n"
                "    pip install PySide6-Addons"
            )
            msg.setWordWrap(True)
            msg.setStyleSheet(
                f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; "
                f"padding: 20px; background: {COLORS['bg_secondary']}; border-radius: 8px;"
            )
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(msg)
            return

        # ── Título + toggles ──────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(8)

        title_col = QVBoxLayout()
        title = QLabel("📍 Mapa de la ruta")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_XL}; font-weight: bold; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        title_col.addWidget(title)
        self._desc_label = QLabel(self._mode_desc(self._color_mode))
        self._desc_label.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        title_col.addWidget(self._desc_label)
        header.addLayout(title_col, stretch=1)

        toggles = QHBoxLayout()
        toggles.setSpacing(6)
        self._mode_btns: Dict[str, QPushButton] = {}
        for key, label, available in [
            ("power", "⚡ Potencia", self._has_power),
            ("hr",    "❤️ FC",       self._has_hr),
            ("speed", "💨 Velocidad", self._has_speed),
        ]:
            if not available:
                continue
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, k=key: self._set_mode(k))
            toggles.addWidget(btn)
            self._mode_btns[key] = btn
        header.addLayout(toggles)
        layout.addLayout(header)

        # ── QWebEngineView ────────────────────────────────────────
        self._web_view = QWebEngineView()
        self._web_view.setMinimumHeight(400)
        self._web_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Habilitar JavaScript y acceso a recursos remotos
        settings = self._web_view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

        layout.addWidget(self._web_view)

        # ── Leyenda ───────────────────────────────────────────────
        self._legend_frame = self._build_legend()
        layout.addWidget(self._legend_frame)

        self._style_mode_btns()
        self._render_map()

    # ── Leyenda ──────────────────────────────────────────────────
    def _build_legend(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"background: {COLORS['bg_secondary']}; border-radius: 6px; padding: 8px;"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        self._legend_title = QLabel(self._mode_legend_title(self._color_mode))
        self._legend_title.setStyleSheet(
            f"font-size: {FONT_SIZE_SM}; font-weight: 600; "
            f"color: {COLORS['fg']}; background: transparent;"
        )
        lay.addWidget(self._legend_title)

        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        self._legend_min = QLabel("0")
        self._legend_min.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        bar_row.addWidget(self._legend_min)

        gradient_bar = QLabel()
        gradient_bar.setFixedHeight(12)
        gradient_bar.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #3B82F6, stop:0.25 #22C55E, stop:0.5 #EAB308, "
            "stop:0.75 #F97316, stop:1 #EF4444); border-radius: 6px;"
        )
        bar_row.addWidget(gradient_bar, stretch=1)

        self._legend_max = QLabel("400")
        self._legend_max.setStyleSheet(
            f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_muted']}; background: transparent;"
        )
        bar_row.addWidget(self._legend_max)
        lay.addLayout(bar_row)

        labels_row = QHBoxLayout()
        for text in ("Bajo", "Medio", "Alto"):
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"font-size: {FONT_SIZE_XS}; color: {COLORS['fg_dim']}; background: transparent;"
            )
            alignment = (
                Qt.AlignmentFlag.AlignLeft  if text == "Bajo"
                else Qt.AlignmentFlag.AlignRight if text == "Alto"
                else Qt.AlignmentFlag.AlignCenter
            )
            lbl.setAlignment(alignment)
            labels_row.addWidget(lbl)
        lay.addLayout(labels_row)
        return frame

    # ── Helpers de texto por modo ─────────────────────────────────
    @staticmethod
    def _mode_desc(mode: str) -> str:
        return {
            "power": "Ruta coloreada por potencia (W).",
            "hr":    "Ruta coloreada por frecuencia cardíaca (bpm).",
            "speed": "Ruta coloreada por velocidad (km/h).",
        }.get(mode, "")

    @staticmethod
    def _mode_legend_title(mode: str) -> str:
        return {
            "power": "Potencia (W)",
            "hr":    "FC (bpm)",
            "speed": "Velocidad (km/h)",
        }.get(mode, "")

    # ── Toggles ───────────────────────────────────────────────────
    def _style_mode_btns(self) -> None:
        for key, btn in self._mode_btns.items():
            if key == self._color_mode:
                btn.setStyleSheet(
                    f"QPushButton {{ background: {COLORS['primary']}; color: white; "
                    f"border: none; border-radius: 6px; "
                    f"font-size: {FONT_SIZE_XS}; padding: 4px 12px; font-weight: 600; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; color: {COLORS['fg_muted']}; "
                    f"border: 1px solid {COLORS['border']}; border-radius: 6px; "
                    f"font-size: {FONT_SIZE_XS}; padding: 4px 12px; }}"
                    f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
                )

    def _set_mode(self, mode: str) -> None:
        self._color_mode = mode
        self._style_mode_btns()
        self._desc_label.setText(self._mode_desc(mode))
        self._legend_title.setText(self._mode_legend_title(mode))
        self._render_map()

    def _get_min_max(self) -> Tuple[float, float]:
        vals: List[float] = []
        for p in self._gps_points:
            if self._color_mode == "power":
                v = p.get("p")
            elif self._color_mode == "hr":
                v = p.get("hr")
            else:
                v = p.get("v") or p.get("s")
            if v is not None:
                vals.append(float(v))
        return (min(vals), max(vals)) if vals else (0.0, 100.0)

    # ── Render ────────────────────────────────────────────────────
    def _render_map(self) -> None:
        if not self.has_gps:
            return

        min_val, max_val = self._get_min_max()
        self._legend_min.setText(str(round(min_val)))
        self._legend_max.setText(str(round(max_val)))

        html = _build_map_html(self._gps_points, self._color_mode, min_val, max_val)

        # FIX: usar setHtml() con baseUrl https: para que WebEngine permita
        # cargar recursos externos (CDN de Leaflet).
        # Anteriormente se usaba load(QUrl.fromLocalFile(...)) desde file://,
        # lo que bloqueaba los scripts de CDN por CORS en WebEngine.
        self._web_view.setHtml(html, _BASE_URL)
