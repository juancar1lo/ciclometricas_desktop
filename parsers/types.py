"""Tipos compartidos para los parsers de actividad.

Port fiel de lib/parsers/types.ts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class TrackPoint:
    """Un punto del track con datos de sensores."""
    t: float                        # segundos relativos al inicio
    power: Optional[float] = None   # watts
    hr: Optional[float] = None      # bpm
    cadence: Optional[float] = None # rpm
    speed: Optional[float] = None   # m/s
    distance: Optional[float] = None # metros acumulados
    altitude: Optional[float] = None # metros
    lat: Optional[float] = None     # latitud (grados decimales)
    lng: Optional[float] = None     # longitud (grados decimales)
    left_balance: Optional[float] = None  # % pierna izquierda (ej. 48.5)


@dataclass
class ParsedActivity:
    """Resultado de parsear un archivo FIT o TCX."""
    started_at: datetime
    sport: str                          # "cycling" | "running" ...
    duration_sec: int
    distance_m: float
    trackpoints: List[TrackPoint] = field(default_factory=list)
    elevation_gain_m: Optional[float] = None
    calories: Optional[int] = None

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000.0

    @property
    def has_power(self) -> bool:
        return any(tp.power is not None and tp.power > 0 for tp in self.trackpoints)

    @property
    def has_hr(self) -> bool:
        return any(tp.hr is not None and tp.hr > 0 for tp in self.trackpoints)

    @property
    def has_gps(self) -> bool:
        return any(tp.lat is not None and tp.lng is not None for tp in self.trackpoints)
