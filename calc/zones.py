"""Zonas de potencia (Coggan) y zonas cardíacas (Friel basadas en % FCL).

Port fiel de lib/calc/zones.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence


@dataclass
class ZoneDef:
    key: str
    label: str
    short_label: str
    min_pct: float
    max_pct: float     # inf para la última zona
    color: str


# Coggan en % de FTP
POWER_ZONES: List[ZoneDef] = [
    ZoneDef("z1",  "Z1 · Recuperación",   "Z1",  0,    56,        "#94A3B8"),
    ZoneDef("z2",  "Z2 · Resistencia",    "Z2",  56,   76,        "#60B5FF"),
    ZoneDef("z3",  "Z3 · Tempo",          "Z3",  76,   88,        "#80D8C3"),
    ZoneDef("z3p", "Z3+ · Sweet Spot",    "SS",  88,   95,        "#A19AD3"),
    ZoneDef("z4",  "Z4 · Umbral",         "Z4",  95,   105,       "#FF9149"),
    ZoneDef("z5",  "Z5 · VO2max",         "Z5",  105,  120,       "#FF9898"),
    ZoneDef("z6",  "Z6 · Anaeróbico",     "Z6",  120,  150,       "#FF6363"),
    ZoneDef("z7",  "Z7 · Neuromuscular",  "Z7",  150,  math.inf,  "#D946EF"),
]

# Friel basado en % de FCL (Frecuencia Cardíaca de Umbral / LTHR)
HR_ZONES: List[ZoneDef] = [
    ZoneDef("z1", "Z1 · Rec. activa",       "Z1",   0,    81,        "#94A3B8"),
    ZoneDef("z2", "Z2 · Resist. aeróbica",  "Z2",  81,    87,        "#60B5FF"),
    ZoneDef("z3", "Z3 · Tempo",             "Z3",  87,    93,        "#80D8C3"),
    ZoneDef("z4", "Z4 · Subumbral",         "Z4",  93,    99,        "#FF9149"),
    ZoneDef("z5a","Z5a · Supraumbral",      "Z5a", 99,   102,        "#FF9898"),
    ZoneDef("z5b","Z5b · Cap. aeróbica",    "Z5b",102,   105,        "#FF6363"),
    ZoneDef("z5c","Z5c · Cap. anaeróbica",  "Z5c",105,   math.inf,   "#D946EF"),
]

ZoneSource = str  # 'ftp' | 'cp' | 'mftp'


def bucket_series(
    series: Sequence[Optional[float]],
    reference: float,
    zones: List[ZoneDef],
) -> Dict[str, int]:
    """Clasifica cada muestra en su zona (reference = FTP o FCL). Devuelve segundos por zona."""
    result: Dict[str, int] = {z.key: 0 for z in zones}
    if not reference or reference <= 0:
        return result
    for v in series:
        if v is None or not math.isfinite(v) or v <= 0:
            continue
        pct = (v / reference) * 100
        for z in zones:
            if z.min_pct <= pct < z.max_pct:
                result[z.key] += 1
                break
    return result


@dataclass
class ZoneRef:
    value: int
    label: str
    source: ZoneSource


def resolve_zone_ref(
    source: Optional[ZoneSource],
    ftp: Optional[float] = None,
    cp: Optional[float] = None,
    mftp: Optional[float] = None,
) -> ZoneRef:
    """Resuelve valor de referencia según elección del usuario."""
    _ftp = ftp or 0
    _cp = cp or 0
    _mftp = mftp or 0
    if source == "cp" and _cp > 0:
        return ZoneRef(value=round(_cp), label="CP", source="cp")
    if source == "mftp" and _mftp > 0:
        return ZoneRef(value=round(_mftp), label="mFTP", source="mftp")
    return ZoneRef(value=round(_ftp), label="FTP", source="ftp")
