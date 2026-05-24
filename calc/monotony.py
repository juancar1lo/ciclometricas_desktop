"""Training Monotony & Strain (Foster, 1998).

Monotony = Mean(daily TSS 7d) / StdDev(daily TSS 7d)
Strain   = Weekly Load × Monotony

Port fiel de lib/calc/monotony.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class MonotonyWeek:
    week_key: str           # '2026-W18'
    week_label: str
    start_date: str
    end_date: str
    daily_tss: List[float]  # 7 values (Mon..Sun)
    week_load: float
    mean_daily_tss: float
    std_daily_tss: float
    monotony: Optional[float]
    strain: Optional[float]
    active_days: int
    classification: str     # low | moderate | high | very_high | insufficient
    class_label: str
    strain_class: str
    strain_label: str


MIN_ACTIVE_DAYS = 2


def _mean(arr: List[float]) -> float:
    return sum(arr) / len(arr) if arr else 0.0


def _std_dev(arr: List[float], avg: float) -> float:
    if len(arr) < 2:
        return 0.0
    variance = sum((v - avg) ** 2 for v in arr) / len(arr)
    return math.sqrt(variance)


def classify_monotony(m: Optional[float]) -> Tuple[str, str]:
    """Retorna (classification, class_label)."""
    if m is None:
        return ("insufficient", "Sin datos")
    if m > 2.0:
        return ("very_high", "Muy alta")
    if m > 1.5:
        return ("high", "Alta")
    if m > 1.0:
        return ("moderate", "Moderada")
    return ("low", "Buena variabilidad")


def classify_strain(s: Optional[float]) -> Tuple[str, str]:
    """Retorna (strain_class, strain_label)."""
    if s is None:
        return ("insufficient", "Sin datos")
    if s > 6000:
        return ("very_high", "Muy alto")
    if s > 4000:
        return ("high", "Alto")
    if s > 2000:
        return ("moderate", "Moderado")
    return ("low", "Bajo")


@dataclass
class WeekMonotonyResult:
    week_load: float
    mean_daily_tss: float
    std_daily_tss: float
    monotony: Optional[float]
    strain: Optional[float]
    active_days: int


def calc_week_monotony(daily_tss: List[float]) -> WeekMonotonyResult:
    """Calcula monotonía y strain para una ventana de 7 días."""
    week_load = sum(daily_tss)
    active_days = sum(1 for v in daily_tss if v > 0)
    avg = _mean(daily_tss)
    sd = _std_dev(daily_tss, avg)

    if active_days < MIN_ACTIVE_DAYS or sd == 0:
        return WeekMonotonyResult(
            week_load=round(week_load),
            mean_daily_tss=round(avg, 1),
            std_daily_tss=round(sd, 1),
            monotony=None,
            strain=None,
            active_days=active_days,
        )

    monotony = round(avg / sd, 2)
    strain = round(week_load * monotony)

    return WeekMonotonyResult(
        week_load=round(week_load),
        mean_daily_tss=round(avg, 1),
        std_daily_tss=round(sd, 1),
        monotony=monotony,
        strain=strain,
        active_days=active_days,
    )
