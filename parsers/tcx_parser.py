"""Parser de archivos .tcx usando lxml.

Port fiel de lib/parsers/tcx-parser.ts.
Usa lxml en lugar de fast-xml-parser (Node.js).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from lxml import etree

from .types import ParsedActivity, TrackPoint

# Namespace TCX
_NS = {
    "tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
    "ext": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
}


def _num(text: Optional[str]) -> Optional[float]:
    """Convierte texto a float finito o None."""
    if text is None:
        return None
    try:
        n = float(text.strip())
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _text(el: Optional[etree._Element]) -> Optional[str]:
    """Extrae .text de un elemento o None."""
    return el.text.strip() if el is not None and el.text else None


def _find_text(parent: etree._Element, xpath: str) -> Optional[str]:
    """Busca un elemento y devuelve su texto."""
    el = parent.find(xpath, _NS)
    return _text(el)


def _parse_iso_datetime(s: Optional[str]) -> Optional[datetime]:
    """Parsea ISO 8601 datetime string."""
    if not s:
        return None
    try:
        # Python 3.11+ puede parsear directamente, para compat usamos fromisoformat
        # con reemplazo de Z por +00:00
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def parse_tcx(source: Union[str, Path, bytes]) -> ParsedActivity:
    """Parsea un archivo .tcx y devuelve ParsedActivity.

    Args:
        source: Ruta al archivo, bytes del XML, o string XML.
    """
    if isinstance(source, Path):
        # Leer como bytes para evitar bug de lxml con rutas Windows (backslashes)
        raw = source.read_bytes()
        root = etree.fromstring(raw)
    elif isinstance(source, bytes):
        root = etree.fromstring(source)
    elif isinstance(source, str):
        # Podría ser una ruta o contenido XML
        if len(source) < 500 and not source.strip().startswith("<"):
            raw = Path(source).read_bytes()
            root = etree.fromstring(raw)
        else:
            root = etree.fromstring(source.encode("utf-8"))
    else:
        raise TypeError(f"source debe ser str, Path o bytes, no {type(source)}")

    # Encontrar Activity
    activity_el = root.find(".//tcx:Activity", _NS)
    if activity_el is None:
        # Intentar sin namespace (algunos TCX no lo usan)
        activity_el = root.find(".//Activity")
    if activity_el is None:
        raise ValueError("Archivo TCX sin actividades")

    # Sport
    sport_attr = activity_el.get("Sport", "Biking")
    sport = "cycling" if "bik" in sport_attr.lower() else sport_attr.lower()

    # Laps
    laps = activity_el.findall("tcx:Lap", _NS)
    if not laps:
        laps = activity_el.findall("Lap")
    if not laps:
        raise ValueError("Archivo TCX sin laps")

    # Start time
    start_str = laps[0].get("StartTime")
    if not start_str:
        id_el = activity_el.find("tcx:Id", _NS)
        if id_el is None:
            id_el = activity_el.find("Id")
        start_str = _text(id_el)
    started_at = _parse_iso_datetime(start_str) or datetime.now(timezone.utc)

    total_sec = 0.0
    total_dist = 0.0
    total_cal = 0
    elev_gain = 0.0
    prev_alt: Optional[float] = None
    trackpoints: list[TrackPoint] = []

    for lap in laps:
        # Acumular datos del lap
        ts_text = _find_text(lap, "tcx:TotalTimeSeconds")
        total_sec += _num(ts_text) or 0

        dist_text = _find_text(lap, "tcx:DistanceMeters")
        total_dist += _num(dist_text) or 0

        cal_text = _find_text(lap, "tcx:Calories")
        total_cal += int(_num(cal_text) or 0)

        # Recorrer tracks y trackpoints
        for track in lap.findall("tcx:Track", _NS) or lap.findall("Track"):
            for tp in track.findall("tcx:Trackpoint", _NS) or track.findall("Trackpoint"):
                time_text = _find_text(tp, "tcx:Time")
                if not time_text:
                    time_text = _find_text(tp, "Time")
                tp_time = _parse_iso_datetime(time_text)
                if tp_time is None:
                    continue

                t_sec = (tp_time - started_at).total_seconds()

                # HR
                hr = _num(_find_text(tp, "tcx:HeartRateBpm/tcx:Value"))
                # Cadencia
                cadence = _num(_find_text(tp, "tcx:Cadence"))
                # Distancia
                distance = _num(_find_text(tp, "tcx:DistanceMeters"))
                # Altitud
                altitude = _num(_find_text(tp, "tcx:AltitudeMeters"))

                # Extensiones (potencia, velocidad)
                power: Optional[float] = None
                speed: Optional[float] = None
                ext_cadence: Optional[float] = None

                # Buscar en múltiples namespaces de extensiones
                extensions = tp.find("tcx:Extensions", _NS)
                if extensions is not None:
                    tpx = extensions.find("ext:TPX", _NS)
                    if tpx is None:
                        # Algunos archivos usan namespace diferente
                        tpx = extensions.find(
                            "{http://www.garmin.com/xmlschemas/ActivityExtension/v2}TPX"
                        )
                    if tpx is not None:
                        power = _num(_text(tpx.find("ext:Watts", _NS)))
                        if power is None:
                            power = _num(_text(tpx.find(
                                "{http://www.garmin.com/xmlschemas/ActivityExtension/v2}Watts"
                            )))
                        speed = _num(_text(tpx.find("ext:Speed", _NS)))
                        if speed is None:
                            speed = _num(_text(tpx.find(
                                "{http://www.garmin.com/xmlschemas/ActivityExtension/v2}Speed"
                            )))
                        ext_cadence = _num(_text(tpx.find("ext:RunCadence", _NS)))

                # Elevación gain
                if altitude is not None and prev_alt is not None:
                    d = altitude - prev_alt
                    if d > 0:
                        elev_gain += d
                if altitude is not None:
                    prev_alt = altitude

                # GPS
                pos = tp.find("tcx:Position", _NS)
                lat: Optional[float] = None
                lng: Optional[float] = None
                if pos is not None:
                    lat = _num(_find_text(pos, "tcx:LatitudeDegrees"))
                    lng = _num(_find_text(pos, "tcx:LongitudeDegrees"))

                trackpoints.append(TrackPoint(
                    t=t_sec,
                    power=power,
                    hr=hr,
                    cadence=cadence or ext_cadence,
                    speed=speed,
                    distance=distance,
                    altitude=altitude,
                    lat=lat,
                    lng=lng,
                ))

    return ParsedActivity(
        started_at=started_at,
        sport=sport,
        duration_sec=max(0, round(total_sec)),
        distance_m=total_dist,
        elevation_gain_m=elev_gain if elev_gain > 0 else None,
        calories=total_cal if total_cal > 0 else None,
        trackpoints=trackpoints,
    )
