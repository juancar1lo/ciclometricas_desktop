"""Recovery Estimation.

Simula días de descanso (TSS=0) hacia adelante desde el CTL/ATL actuales
hasta que TSB cruce un umbral de frescura.

Port fiel de lib/calc/recovery.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional


CTL_ALPHA = 1 - math.exp(-1 / 42)
ATL_ALPHA = 1 - math.exp(-1 / 7)
FRESH_THRESHOLD = 5
MAX_PROJECTION_DAYS = 14


@dataclass
class ProjectionDay:
    day: int
    date: str
    ctl: float
    atl: float
    tsb: float


@dataclass
class RecoveryProjection:
    hours_to_recovery: Optional[int]
    status: str          # fresh | recovering | fatigued
    status_label: str
    status_emoji: str
    current_ctl: float
    current_atl: float
    current_tsb: float
    projection: List[ProjectionDay]
    advice: str


def _status_from_tsb(tsb: float) -> dict:
    if tsb >= FRESH_THRESHOLD:
        return {"status": "fresh", "status_label": "Fresco", "status_emoji": "🟢"}
    if tsb >= -10:
        return {"status": "recovering", "status_label": "Recuperando", "status_emoji": "🟡"}
    return {"status": "fatigued", "status_label": "Fatigado", "status_emoji": "🔴"}


def _advice(status: str, hours: Optional[int]) -> str:
    if status == "fresh":
        return "¡Estás fresco! Puedes entrenar a alta intensidad o competir hoy."
    if status == "recovering":
        if hours is not None and hours <= 24:
            return "Casi recuperado. Puedes hacer una sesión suave de recuperación activa."
        return "En proceso de recuperación. Prioriza el descanso o sesiones de baja intensidad (Z1-Z2)."
    if hours is not None and hours > 72:
        return "Fatiga acumulada significativa. Considera 2-3 días de descanso completo antes de volver a entrenar."
    return "Fatigado. Necesitas descanso completo. Evita entrenamientos de intensidad hasta recuperarte."


def project_recovery(current_ctl: float, current_atl: float) -> RecoveryProjection:
    """Proyecta la recuperación desde el estado actual."""
    current_tsb = current_ctl - current_atl
    st = _status_from_tsb(current_tsb)

    projection: List[ProjectionDay] = []
    ctl = current_ctl
    atl = current_atl
    hours_to_recovery: Optional[int] = None
    today = date.today()

    for day in range(MAX_PROJECTION_DAYS + 1):
        d = today + timedelta(days=day)
        tsb = round(ctl - atl, 2)
        projection.append(ProjectionDay(
            day=day,
            date=d.isoformat(),
            ctl=round(ctl, 2),
            atl=round(atl, 2),
            tsb=tsb,
        ))
        if day > 0 and tsb >= FRESH_THRESHOLD and hours_to_recovery is None:
            prev_tsb = projection[day - 1].tsb
            if prev_tsb < FRESH_THRESHOLD:
                fraction = (FRESH_THRESHOLD - prev_tsb) / (tsb - prev_tsb)
                hours_to_recovery = round(((day - 1) + fraction) * 24)
            else:
                hours_to_recovery = day * 24
        ctl = ctl + (0 - ctl) * CTL_ALPHA
        atl = atl + (0 - atl) * ATL_ALPHA

    if current_tsb >= FRESH_THRESHOLD:
        hours_to_recovery = None

    advice = _advice(st["status"], hours_to_recovery)

    return RecoveryProjection(
        hours_to_recovery=hours_to_recovery,
        status=st["status"],
        status_label=st["status_label"],
        status_emoji=st["status_emoji"],
        current_ctl=round(current_ctl, 2),
        current_atl=round(current_atl, 2),
        current_tsb=round(current_tsb, 2),
        projection=projection,
        advice=advice,
    )


def estimate_activity_recovery(
    tss: float, ctl_before: float, atl_before: float
) -> int:
    """Estima horas de recuperación tras una actividad individual."""
    ctl = ctl_before + (tss - ctl_before) * CTL_ALPHA
    atl = atl_before + (tss - atl_before) * ATL_ALPHA
    tsb = ctl - atl

    if tsb >= FRESH_THRESHOLD:
        return 0

    for day in range(1, MAX_PROJECTION_DAYS + 1):
        prev_tsb = tsb
        ctl = ctl + (0 - ctl) * CTL_ALPHA
        atl = atl + (0 - atl) * ATL_ALPHA
        tsb = ctl - atl
        if tsb >= FRESH_THRESHOLD:
            fraction = (FRESH_THRESHOLD - prev_tsb) / (tsb - prev_tsb)
            return round(((day - 1) + fraction) * 24)

    return MAX_PROJECTION_DAYS * 24
