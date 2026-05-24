"""Estimación continua de FTP a partir de la curva MMP.

Usa un coeficiente logarítmico calibrado con datos empíricos
(Coggan, Cheung, Pinot & Grappe):
  coef(t) = 0.336271 + 0.086562 × ln(t)

Puntos de referencia:
  5 min (300s) → 0.83
  10 min (600s) → 0.89
  20 min (1200s) → 0.95

Port fiel de lib/calc/ftp-estimator.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

COEF_A = 0.336271
COEF_B = 0.086562
MIN_DURATION = 300   # 5 min
MAX_DURATION = 1200  # 20 min
STEP = 15
FTP_SUGGESTION_THRESHOLD = 3  # watts


@dataclass
class FtpEstimate:
    estimated_ftp: int
    duration_sec: int
    power_at_duration: int
    coefficient: float


def ftp_coefficient(t: float) -> float:
    """Coeficiente de corrección para una duración dada."""
    return COEF_A + COEF_B * math.log(t)


def _dense_mmp_in_range(
    power: np.ndarray,
) -> List[dict]:
    """MMP denso cada STEP segundos entre MIN y MAX_DURATION."""
    n = len(power)
    max_dur = min(MAX_DURATION, n)
    if max_dur < MIN_DURATION:
        return []

    results: List[dict] = []
    cs = np.cumsum(power)

    for d in range(MIN_DURATION, max_dur + 1, STEP):
        if n < d:
            break
        sums = cs[d - 1:].copy()
        sums[1:] -= cs[:len(cs) - d]
        max_sum = float(np.max(sums))
        results.append({"dur": d, "power": max_sum / d})

    return results


def estimate_ftp_from_power(
    power_series: List[float],
    current_ftp: float,
) -> Optional[FtpEstimate]:
    """Estima FTP desde serie de potencia 1 Hz."""
    arr = np.array(power_series, dtype=np.float64)
    entries = _dense_mmp_in_range(arr)
    if not entries:
        return None

    best_est = 0.0
    best_dur = 0
    best_power = 0.0
    best_coef = 0.0

    for e in entries:
        coef = ftp_coefficient(e["dur"])
        est = e["power"] * coef
        if est > best_est:
            best_est = est
            best_dur = e["dur"]
            best_power = e["power"]
            best_coef = coef

    rounded_est = round(best_est)
    if rounded_est <= current_ftp + FTP_SUGGESTION_THRESHOLD:
        return None

    return FtpEstimate(
        estimated_ftp=rounded_est,
        duration_sec=best_dur,
        power_at_duration=round(best_power),
        coefficient=best_coef,
    )


def estimate_ftp_from_mmp(
    mmp: Dict[int, int],
    current_ftp: float,
) -> Optional[FtpEstimate]:
    """Estima FTP desde un diccionario MMP ya calculado."""
    entries = [
        {"dur": k, "power": v}
        for k, v in mmp.items()
        if MIN_DURATION <= k <= MAX_DURATION and v > 0
    ]
    if not entries:
        return None

    best_est = 0.0
    best_dur = 0
    best_power = 0.0
    best_coef = 0.0

    for e in entries:
        coef = ftp_coefficient(e["dur"])
        est = e["power"] * coef
        if est > best_est:
            best_est = est
            best_dur = e["dur"]
            best_power = e["power"]
            best_coef = coef

    rounded_est = round(best_est)
    if rounded_est <= current_ftp + FTP_SUGGESTION_THRESHOLD:
        return None

    return FtpEstimate(
        estimated_ftp=rounded_est,
        duration_sec=best_dur,
        power_at_duration=round(best_power),
        coefficient=best_coef,
    )
