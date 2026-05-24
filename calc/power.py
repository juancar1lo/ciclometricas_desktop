"""Cálculos de potencia: Normalized Power (NP), IF, TSS, Work (kJ).

Port fiel de lib/calc/power.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Union

import numpy as np


def _safe_array(values: Sequence[Optional[float]], floor: float = 0.0) -> np.ndarray:
    """Convierte serie con posibles None/NaN a ndarray limpio."""
    out = np.empty(len(values), dtype=np.float64)
    for i, v in enumerate(values):
        if v is not None and math.isfinite(v) and v > floor:
            out[i] = v
        else:
            out[i] = 0.0
    return out


def calc_normalized_power(values: Sequence[Optional[float]]) -> Optional[float]:
    """Normalized Power (Coggan):
    1) Media móvil 30 s
    2) Elevar a la 4ª potencia
    3) Media
    4) Raíz 4ª
    """
    safe = _safe_array(values, floor=0.0)
    if len(safe) < 30:
        return None
    window = 30
    # Rolling mean con cumsum (O(n))
    cs = np.cumsum(safe)
    rolling = (cs[window - 1:] - np.concatenate(([0.0], cs[:-window]))) / window
    if len(rolling) == 0:
        return None
    fourth = np.mean(rolling ** 4)
    return float(fourth ** 0.25)


def calc_average_power(values: Sequence[Optional[float]]) -> Optional[float]:
    arr = [v for v in values if v is not None and math.isfinite(v) and v >= 0]
    if not arr:
        return None
    return sum(arr) / len(arr)


def calc_work_kj(values: Sequence[Optional[float]]) -> Optional[float]:
    """Trabajo en kJ asumiendo 1 muestra/segundo."""
    safe = _safe_array(values, floor=0.0)
    if len(safe) == 0:
        return None
    return float(np.sum(safe) / 1000.0)


def calc_intensity_factor(
    np_watts: Optional[float], ftp: Optional[float]
) -> Optional[float]:
    if not np_watts or not ftp or ftp <= 0:
        return None
    return np_watts / ftp


def calc_tss(
    duration_sec: float,
    np_watts: Optional[float],
    ftp: Optional[float],
) -> Optional[float]:
    """TSS = (s × NP × IF) / (FTP × 3600) × 100."""
    if not duration_sec or not np_watts or not ftp or ftp <= 0:
        return None
    intensity = np_watts / ftp
    return (duration_sec * np_watts * intensity) / (ftp * 3600) * 100


@dataclass
class PowerMetrics:
    np: Optional[float]
    avg_power: Optional[float]
    work_kj: Optional[float]
    intensity_factor: Optional[float]
    tss: Optional[float]


def calculate_power_metrics(
    values: Sequence[Optional[float]],
    ftp: Optional[float] = None,
    duration_sec: Optional[float] = None,
) -> PowerMetrics:
    """Calcula todas las métricas de potencia de una vez."""
    np_val = calc_normalized_power(values)
    avg = calc_average_power(values)
    work = calc_work_kj(values)
    if_val = calc_intensity_factor(np_val, ftp) if ftp else None
    dur = duration_sec if duration_sec else float(len(values))
    tss_val = calc_tss(dur, np_val, ftp) if ftp else None
    return PowerMetrics(
        np=round(np_val, 1) if np_val is not None else None,
        avg_power=round(avg, 1) if avg is not None else None,
        work_kj=round(work, 1) if work is not None else None,
        intensity_factor=round(if_val, 3) if if_val is not None else None,
        tss=round(tss_val, 1) if tss_val is not None else None,
    )
