"""Estrategias de corrección de picos aberrantes.

Métodos disponibles:
- interpolate: interpolación lineal entre vecinos válidos
- cap: recortar al umbral máximo
- local_mean: reemplazar por media local
- zero: poner a 0 (no recomendado, afecta métricas de tiempo)
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Set

import numpy as np

from .detector import SpikeInfo


class CorrectionMethod(Enum):
    INTERPOLATE = "interpolate"
    CAP = "cap"
    LOCAL_MEAN = "local_mean"
    ZERO = "zero"
    AUTO = "auto"


@dataclass
class CorrectionResult:
    """Resultado de la corrección."""
    corrected_power: np.ndarray      # Serie corregida
    original_power: np.ndarray       # Serie original (copia)
    corrections: List[CorrectionInfo]  # Detalle de cada corrección


@dataclass
class CorrectionInfo:
    """Detalle de una corrección aplicada."""
    index: int
    time_sec: float
    original_watts: float
    corrected_watts: float
    method: str
    reason: str  # Del detector


def correct_spikes(
    power: np.ndarray,
    spikes: List[SpikeInfo],
    method: CorrectionMethod = CorrectionMethod.INTERPOLATE,
    cap_value: Optional[float] = None,
    local_mean_window: int = 15,
) -> CorrectionResult:
    """Aplica corrección a los picos detectados.

    Args:
        power: Array de vatios original.
        spikes: Lista de picos detectados.
        method: Estrategia de corrección.
        cap_value: Valor techo para método CAP. Si None, usa 2500.
        local_mean_window: Ventana (±) para LOCAL_MEAN.

    Returns:
        CorrectionResult con la serie corregida y detalle.
    """
    original = power.copy()
    corrected = power.copy()
    corrections: List[CorrectionInfo] = []

    if not spikes:
        return CorrectionResult(corrected, original, corrections)

    spike_set: Set[int] = {s.index for s in spikes}
    n = len(corrected)

    for spike in spikes:
        idx = spike.index
        if idx < 0 or idx >= n:
            continue

        if method == CorrectionMethod.AUTO:
            new_val, chosen = _auto_correct(
                corrected, idx, spike_set, local_mean_window,
                cap_value if cap_value is not None else 2500.0,
            )
        elif method == CorrectionMethod.INTERPOLATE:
            new_val = _interpolate(corrected, idx, spike_set)
            chosen = "interpolate"
        elif method == CorrectionMethod.CAP:
            ceiling = cap_value if cap_value is not None else 2500.0
            new_val = min(corrected[idx], ceiling)
            chosen = "cap"
        elif method == CorrectionMethod.LOCAL_MEAN:
            new_val = _local_mean(corrected, idx, spike_set, local_mean_window)
            chosen = "local_mean"
        elif method == CorrectionMethod.ZERO:
            new_val = 0.0
            chosen = "zero"
        else:
            new_val = _interpolate(corrected, idx, spike_set)
            chosen = "interpolate"

        corrections.append(CorrectionInfo(
            index=idx,
            time_sec=spike.time_sec,
            original_watts=spike.original_watts,
            corrected_watts=new_val,
            method=chosen if method == CorrectionMethod.AUTO else method.value,
            reason=spike.reason,
        ))
        corrected[idx] = new_val

    return CorrectionResult(corrected, original, corrections)


def _interpolate(arr: np.ndarray, idx: int, skip: Set[int]) -> float:
    """Interpolación lineal entre vecinos válidos (no-spike, no-NaN)."""
    n = len(arr)

    # Buscar vecino izquierdo válido
    left_idx = idx - 1
    left_val = None
    while left_idx >= 0:
        if left_idx not in skip and not np.isnan(arr[left_idx]):
            left_val = arr[left_idx]
            break
        left_idx -= 1

    # Buscar vecino derecho válido
    right_idx = idx + 1
    right_val = None
    while right_idx < n:
        if right_idx not in skip and not np.isnan(arr[right_idx]):
            right_val = arr[right_idx]
            break
        right_idx += 1

    # Interpolar
    if left_val is not None and right_val is not None:
        span = right_idx - left_idx
        frac = (idx - left_idx) / span if span > 0 else 0.5
        return left_val + frac * (right_val - left_val)
    elif left_val is not None:
        return left_val
    elif right_val is not None:
        return right_val
    else:
        return 0.0


def _local_mean(arr: np.ndarray, idx: int, skip: Set[int], window: int) -> float:
    """Media local excluyendo spikes y NaN."""
    n = len(arr)
    lo = max(0, idx - window)
    hi = min(n, idx + window + 1)

    values = []
    for i in range(lo, hi):
        if i != idx and i not in skip and not np.isnan(arr[i]):
            values.append(arr[i])

    return float(np.mean(values)) if values else 0.0


def _auto_correct(
    arr: np.ndarray,
    idx: int,
    skip: Set[int],
    local_window: int,
    cap_ceiling: float,
) -> tuple[float, str]:
    """Elige automáticamente el mejor método según el contexto del spike.

    Lógica:
    1. Calcula interpolación y media local.
    2. Si los vecinos inmediatos son estables (variación <20%), usa interpolación
       (produce la transición más natural).
    3. Si la zona es ruidosa, usa media local (más robusto ante fluctuaciones).
    4. Si ambos métodos devuelven un valor mayor que el techo (cap), recorta.
    5. Fallback: interpolación.

    Returns:
        (valor_corregido, nombre_del_método_elegido)
    """
    interp_val = _interpolate(arr, idx, skip)
    mean_val = _local_mean(arr, idx, skip, local_window)

    # Evaluar estabilidad de la zona: std de vecinos ±5
    n = len(arr)
    lo = max(0, idx - 5)
    hi = min(n, idx + 6)
    neighbors = []
    for i in range(lo, hi):
        if i != idx and i not in skip and not np.isnan(arr[i]):
            neighbors.append(arr[i])

    if len(neighbors) >= 3:
        nb_mean = np.mean(neighbors)
        nb_std = np.std(neighbors)
        cv = nb_std / nb_mean if nb_mean > 0 else 0  # coef. de variación

        if cv < 0.20:
            # Zona estable → interpolación (transición suave)
            val = interp_val
            method = "auto→interp"
        else:
            # Zona ruidosa → media local (más robusto)
            val = mean_val
            method = "auto→media"
    else:
        # Pocos vecinos → interpolación
        val = interp_val
        method = "auto→interp"

    # Si el resultado sigue por encima del techo, recortar
    if val > cap_ceiling:
        val = cap_ceiling
        method = "auto→cap"

    return val, method
