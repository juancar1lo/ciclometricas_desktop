"""PDC after Fatigue — Curvas de potencia-duración bajo fatiga.

Calcula MMP para diferentes niveles de fatiga medidos en kJ de trabajo
acumulado (similar a WKO5).

Port fiel de lib/calc/pdc-fatigue.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .mmp import merge_mmp_max, sanitize_power_series

# Umbrales de fatiga en kJ
FATIGUE_THRESHOLDS: List[int] = [0, 500, 1000, 1500, 2000, 3000, 4000]

# Duraciones a evaluar (segundos)
PDC_DURATIONS: List[int] = [
    1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120,
    180, 240, 300, 360, 420, 480, 600, 720, 900,
    1200, 1500, 1800, 2400, 3000, 3600, 5400, 7200, 10800,
]


@dataclass
class PdcFatigueCurve:
    kj_threshold: int
    mmp: Dict[int, int]


@dataclass
class PdcFatigueResult:
    curves: List[PdcFatigueCurve]
    activities_used: int


def _rebuild_power_series(
    samples: List[Tuple[float, Optional[float]]],
    duration_sec: float,
) -> np.ndarray:
    """Reconstruye serie ~1 Hz con forward-fill."""
    dur = max(1, round(duration_sec))
    arr = np.zeros(dur, dtype=np.float64)
    if not samples:
        return arr
    pts = sorted(samples, key=lambda s: s[0])
    last = 0.0
    pi = 0
    for t in range(dur):
        while pi < len(pts) and pts[pi][0] <= t:
            v = pts[pi][1]
            if v is not None and v > 0:
                last = v
            pi += 1
        arr[t] = last
    return arr


def _find_kj_threshold_indices(
    power: np.ndarray,
    thresholds: List[int],
) -> Dict[int, int]:
    result: Dict[int, int] = {0: 0}
    sorted_t = sorted(t for t in thresholds if t > 0)
    next_idx = 0
    cum_kj = 0.0
    for i in range(len(power)):
        cum_kj += power[i] / 1000.0
        while next_idx < len(sorted_t) and cum_kj >= sorted_t[next_idx]:
            result[sorted_t[next_idx]] = i + 1
            next_idx += 1
        if next_idx >= len(sorted_t):
            break
    return result


def _compute_mmp_from_slice(
    power: np.ndarray,
    start_idx: int,
    durations: List[int],
) -> Dict[int, int]:
    n = len(power) - start_idx
    if n < 1:
        return {}
    result: Dict[int, int] = {}
    for d in durations:
        if d <= 0 or n < d:
            continue
        cs = np.cumsum(power[start_idx:])
        sums = cs[d - 1:].copy()
        sums[1:] -= cs[:len(cs) - d]
        max_sum = float(np.max(sums))
        avg = max_sum / d
        if avg > 0:
            result[d] = round(avg)
    return result


def calc_pdc_fatigue(
    activities: List[dict],
    max_valid_power: Optional[float] = None,
    thresholds: Optional[List[int]] = None,
) -> PdcFatigueResult:
    """Calcula curvas PDC bajo fatiga.
    activities: [{samples: [(t, p), ...], duration_sec: float}, ...]
    """
    if thresholds is None:
        thresholds = FATIGUE_THRESHOLDS

    accumulated: Dict[int, Dict[int, int]] = {t: {} for t in thresholds}
    activities_used = 0

    for act in activities:
        samps = act.get("samples", [])
        dur = act.get("duration_sec", 0)
        if not samps or len(samps) < 30:
            continue

        power = _rebuild_power_series(samps, dur)

        if max_valid_power:
            sr = sanitize_power_series(list(power), max_valid_power)
            power = sr.values

        kj_indices = _find_kj_threshold_indices(power, thresholds)

        contributed = False
        for threshold in thresholds:
            start_idx = kj_indices.get(threshold)
            if start_idx is None:
                continue
            if len(power) - start_idx < 5:
                continue
            mmp = _compute_mmp_from_slice(power, start_idx, PDC_DURATIONS)
            if mmp:
                accumulated[threshold] = merge_mmp_max(accumulated[threshold], mmp)
                contributed = True

        if contributed:
            activities_used += 1

    curves = [
        PdcFatigueCurve(kj_threshold=t, mmp=accumulated[t])
        for t in thresholds
        if len(accumulated[t]) >= 3
    ]
    return PdcFatigueResult(curves=curves, activities_used=activities_used)
