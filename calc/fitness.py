"""CTL (Fitness) · ATL (Fatigue) · TSB (Form).

Modelo exponencial de Banister:
  CTL_t = CTL_{t-1} + (TSS_t - CTL_{t-1}) × (1 - e^(-1/42))
  ATL_t = ATL_{t-1} + (TSS_t - ATL_{t-1}) × (1 - e^(-1/7))
  TSB_t = CTL_t - ATL_t

Port fiel de lib/calc/fitness.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence


@dataclass
class DailyTss:
    date: str    # ISO yyyy-mm-dd
    tss: float


@dataclass
class FitnessPoint:
    date: str
    tss: float
    ctl: float
    atl: float
    tsb: float
    forecast: bool = False


def _to_iso_date(d: date) -> str:
    return d.isoformat()


def aggregate_daily_tss(
    activities: Sequence[dict],
) -> Dict[str, float]:
    """Agrega TSS por día. activities: [{started_at: datetime, tss: float}, ...]."""
    result: Dict[str, float] = {}
    for a in (activities or []):
        started = a.get("started_at")
        if started is None:
            continue
        if isinstance(started, datetime):
            d = started.date()
        elif isinstance(started, date):
            d = started
        else:
            continue
        iso = _to_iso_date(d)
        tss = a.get("tss", 0) or 0
        if not isinstance(tss, (int, float)) or not math.isfinite(tss):
            tss = 0
        result[iso] = result.get(iso, 0) + tss
    return result


def build_fitness_series(
    activities: Sequence[dict],
    from_date: date,
    to_date: date,
) -> List[FitnessPoint]:
    """Construye serie CTL/ATL/TSB con pre-warm proporcional."""
    daily_tss = aggregate_daily_tss(activities)

    display_span = (to_date - from_date).days
    warmup_days = max(90, display_span)
    start = from_date - timedelta(days=warmup_days)
    end = to_date
    today = date.today()

    ctl_alpha = 1 - math.exp(-1 / 42)
    atl_alpha = 1 - math.exp(-1 / 7)

    points: List[FitnessPoint] = []
    ctl = 0.0
    atl = 0.0
    cur = start

    while cur <= end:
        iso = _to_iso_date(cur)
        is_forecast = cur > today
        tss = 0.0 if is_forecast else daily_tss.get(iso, 0.0)
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        if cur >= from_date:
            points.append(FitnessPoint(
                date=iso,
                tss=tss,
                ctl=round(ctl, 2),
                atl=round(atl, 2),
                tsb=round(ctl - atl, 2),
                forecast=is_forecast,
            ))
        cur += timedelta(days=1)

    return points


def calc_ramp_rate(points: List[FitnessPoint], days: int = 7) -> Optional[float]:
    """Ramp rate semanal: ΔCTL en `days` días (solo puntos reales)."""
    if not points:
        return None
    last_idx = len(points) - 1
    while last_idx >= 0 and points[last_idx].forecast:
        last_idx -= 1
    if last_idx < days:
        return None
    return round(points[last_idx].ctl - points[last_idx - days].ctl, 2)


def last_real_point(points: List[FitnessPoint]) -> Optional[FitnessPoint]:
    """Último punto real (no proyectado)."""
    for p in reversed(points or []):
        if not p.forecast:
            return p
    return None
