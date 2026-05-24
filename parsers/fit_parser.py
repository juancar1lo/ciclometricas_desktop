"""Parser de archivos .fit usando fitdecode.

Port fiel de lib/parsers/fit-parser.ts.
Usa fitdecode en lugar de fit-file-parser (Node.js).
"""
from __future__ import annotations

import io
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import fitdecode

from .types import ParsedActivity, TrackPoint


_SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)


def _num(v: Any) -> Optional[float]:
    """Extrae un número finito o None."""
    if v is None:
        return None
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _coord(v: Any) -> Optional[float]:
    """Convierte coordenada de semicírculos FIT a grados."""
    if v is None:
        return None
    try:
        n = float(v)
        if not math.isfinite(n):
            return None
        # Si el valor es muy grande, es semicírculos (entero ≥ 10^7)
        if abs(n) > 1_000_000:
            return n * _SEMICIRCLE_TO_DEG
        return n
    except (TypeError, ValueError):
        return None


def _safe_datetime(v: Any) -> Optional[datetime]:
    """Convierte a datetime aware (UTC) si es posible."""
    if isinstance(v, datetime):
        return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v
    return None


def parse_fit(source: Union[str, Path, bytes]) -> ParsedActivity:
    """Parsea un archivo .fit y devuelve ParsedActivity.

    Args:
        source: Ruta al archivo .fit o bytes del archivo.
    """
    if isinstance(source, (str, Path)):
        fit_source = str(source)
        print(f"[FIT] Parseando archivo: {source}")
    elif isinstance(source, bytes):
        fit_source = io.BytesIO(source)
        print(f"[FIT] Parseando {len(source)} bytes")
    else:
        raise TypeError(f"source debe ser str, Path o bytes, no {type(source)}")

    # Datos de sesión
    session_start: Optional[datetime] = None
    session_sport: str = "cycling"
    session_duration: float = 0
    session_distance: float = 0
    session_calories: Optional[int] = None
    session_ascent: Optional[float] = None

    # Records raw: guardamos (timestamp, campos) en una sola pasada
    raw_records: list[tuple[datetime, dict]] = []

    try:
        with fitdecode.FitReader(fit_source) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue

                if frame.name == "session":
                    st = frame.get_value("start_time", fallback=None)
                    session_start = _safe_datetime(st)

                    sport_raw = frame.get_value("sport", fallback="cycling")
                    sport_str = str(sport_raw).lower() if sport_raw else "cycling"
                    session_sport = "cycling" if ("cycl" in sport_str or "bik" in sport_str) else sport_str

                    session_duration = _num(frame.get_value("total_timer_time", fallback=None)) or 0
                    if not session_duration:
                        session_duration = _num(frame.get_value("total_elapsed_time", fallback=None)) or 0

                    session_distance = _num(frame.get_value("total_distance", fallback=None)) or 0

                    cal = _num(frame.get_value("total_calories", fallback=None))
                    session_calories = int(cal) if cal else None

                    asc = _num(frame.get_value("total_ascent", fallback=None))
                    session_ascent = asc if asc else None

                elif frame.name == "record":
                    ts = frame.get_value("timestamp", fallback=None)
                    record_time = _safe_datetime(ts)
                    if record_time is None:
                        continue

                    fields: dict = {}
                    for fld_name in ("power", "heart_rate", "cadence", "speed",
                                     "enhanced_speed", "distance", "altitude",
                                     "enhanced_altitude", "position_lat", "position_long",
                                     "left_right_balance"):
                        fields[fld_name] = frame.get_value(fld_name, fallback=None)

                    raw_records.append((record_time, fields))
    except Exception as exc:
        print(f"[FIT] Error al leer FIT: {type(exc).__name__}: {exc}")
        raise

    print(f"[FIT] Leídos {len(raw_records)} records, session_start={session_start}, "
          f"duration={session_duration}s, distance={session_distance}m")

    # Determinar started_at
    first_record_time = raw_records[0][0] if raw_records else None
    started_at = session_start or first_record_time or datetime.now(timezone.utc)

    # Construir trackpoints con tiempos relativos
    trackpoints: list[TrackPoint] = []
    for record_time, fields in raw_records:
        t_sec = (record_time - started_at).total_seconds()
        if t_sec < 0:
            continue

        speed = _num(fields["speed"]) or _num(fields["enhanced_speed"])
        altitude = _num(fields["altitude"]) or _num(fields["enhanced_altitude"])

        # Decodificar left_right_balance del FIT SDK:
        #   - Formato raw: bit 7 = right flag, bits 6:0 = porcentaje × 100
        #   - Algunos dispositivos ya decodifican a un float 0-100
        left_bal: Optional[float] = None
        lrb_raw = fields.get("left_right_balance")
        if lrb_raw is not None:
            lrb_val = _num(lrb_raw)
            if lrb_val is not None and lrb_val > 0:
                if lrb_val > 100:
                    # Formato raw FIT SDK: bit-masked integer
                    lrb_int = int(lrb_val)
                    is_right = bool(lrb_int & 0x80)
                    pct = (lrb_int & 0x7F)
                    if is_right:
                        left_bal = 100.0 - pct
                    else:
                        left_bal = float(pct)
                else:
                    # Ya decodificado como porcentaje izquierdo (0-100)
                    left_bal = lrb_val
                # Validar rango razonable
                if left_bal is not None and not (10 <= left_bal <= 90):
                    left_bal = None

        trackpoints.append(TrackPoint(
            t=t_sec,
            power=_num(fields["power"]),
            hr=_num(fields["heart_rate"]),
            cadence=_num(fields["cadence"]),
            speed=speed,
            distance=_num(fields["distance"]),
            altitude=altitude,
            lat=_coord(fields["position_lat"]),
            lng=_coord(fields["position_long"]),
            left_balance=left_bal,
        ))

    # Duración desde records si no hay sesión
    if not session_duration and trackpoints:
        session_duration = trackpoints[-1].t

    return ParsedActivity(
        started_at=started_at,
        sport=session_sport,
        duration_sec=max(0, round(session_duration)),
        distance_m=session_distance,
        elevation_gain_m=session_ascent,
        calories=session_calories,
        trackpoints=trackpoints,
    )
