"""Mean Maximal Power (MMP / curva de potencia máxima media).

Para cada duración d, devuelve la potencia media máxima sostenida
durante d segundos consecutivos. Algoritmo: ventana deslizante O(n).

Port fiel de lib/calc/mmp.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

# Duraciones estándar (segundos) — hasta 6h para cubrir recorridos largos
MMP_DURATIONS: List[int] = [
    1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300,
    420, 600, 900, 1200, 1800, 2400, 3000, 3600, 5400,
    7200, 10800, 14400, 18000, 21600,
]

# Duraciones "famosas" para Personal Records
PR_DURATIONS: List[int] = [5, 15, 30, 60, 300, 600, 1200, 1800, 3600]


@dataclass
class SanitizeResult:
    values: np.ndarray
    outliers: int


def sanitize_power_series(
    power: Sequence[Optional[float]],
    max_valid_power: Optional[float] = None,
) -> SanitizeResult:
    """Sanea una serie de potencia:
    - None/NaN/<=0 → 0
    - Si max_valid_power, muestras > umbral → 0
    """
    cap = (
        max_valid_power
        if max_valid_power is not None
        and math.isfinite(max_valid_power)
        and max_valid_power > 0
        else math.inf
    )
    n = len(power)
    values = np.zeros(n, dtype=np.float64)
    outliers = 0
    for i, v in enumerate(power):
        if v is None or not math.isfinite(v) or v <= 0:
            continue
        if v > cap:
            outliers += 1
            continue
        values[i] = v
    return SanitizeResult(values=values, outliers=outliers)


def compute_mmp(
    power: Sequence[Optional[float]],
    durations: Optional[List[int]] = None,
    max_valid_power: Optional[float] = None,
) -> Dict[int, int]:
    """Calcula MMP con ventana deslizante O(n) por duración."""
    if durations is None:
        durations = MMP_DURATIONS
    sr = sanitize_power_series(power, max_valid_power)
    arr = sr.values
    n = len(arr)
    result: Dict[int, int] = {}
    cs = np.cumsum(arr)
    for d in durations:
        if d <= 0 or n < d:
            continue
        # Ventana deslizante vía cumsum
        sums = cs[d - 1:].copy()
        sums[1:] -= cs[: n - d]
        max_sum = float(np.max(sums))
        avg = max_sum / d
        if avg > 0:
            result[d] = round(avg)
    return result


def power_from_samples(
    samples: List[Tuple[float, Optional[float]]],
    duration_sec: float,
) -> List[Optional[float]]:
    """Reconstruye serie 1 Hz a partir de samples downsampled (t, p).
    Forward-fill para rellenar huecos.
    """
    dur = max(1, round(duration_sec))
    arr: List[Optional[float]] = [None] * dur
    if not samples:
        return arr
    pts = sorted(samples, key=lambda s: s[0])
    last: Optional[float] = None
    pi = 0
    for t in range(dur):
        while pi < len(pts) and pts[pi][0] <= t:
            if pts[pi][1] is not None:
                last = pts[pi][1]
            pi += 1
        arr[t] = last
    return arr


def merge_mmp_max(
    a: Dict[int, int], b: Dict[int, int]
) -> Dict[int, int]:
    """Combina dos diccionarios MMP tomando el máximo por duración."""
    out = dict(a)
    for k, vb in b.items():
        va = out.get(k, 0)
        if vb > va:
            out[k] = vb
    return out
