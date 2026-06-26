"""Métricas avanzadas por actividad:
  - TISS aeróbico y anaeróbico
  - EF  (Efficiency Factor = NP / FC media)
  - VF  (Variability Factor = NP / potencia media)
  - Pw:Hr (desacople potencia-FC entre mitades)

Port fiel de lib/calc/activity-metrics.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


# ── TISS ──────────────────────────────────────────────────────────

@dataclass
class TissResult:
    tiss_aero: float
    tiss_anaero: float
    tiss_total: float
    pct_aero: float     # 0-100
    pct_anaero: float   # 0-100


def calc_tiss(
    samples: List[Tuple[float, Optional[float]]],
    cp: float,
    w_prime_j: float,
) -> Optional[TissResult]:
    """Calcula TISS aeróbico y anaeróbico.
    samples: lista de (t_sec, power).
    """
    if not samples or cp <= 0 or w_prime_j <= 0:
        return None

    work_aero_j = 0.0
    work_anaero_j = 0.0

    for i, (t, p_raw) in enumerate(samples):
        p = p_raw if p_raw else 0.0
        if p <= 0:
            continue
        dt = max(1.0, t - samples[i - 1][0]) if i > 0 else 1.0

        if p <= cp:
            work_aero_j += p * dt
        else:
            work_aero_j += cp * dt
            work_anaero_j += (p - cp) * dt

    tiss_aero = (work_aero_j / (cp * 3600)) * 100
    tiss_anaero = (work_anaero_j / w_prime_j) * 100
    tiss_total = tiss_aero + tiss_anaero
    pct_aero = (tiss_aero / tiss_total) * 100 if tiss_total > 0 else 0
    pct_anaero = (tiss_anaero / tiss_total) * 100 if tiss_total > 0 else 0

    return TissResult(
        tiss_aero=tiss_aero,
        tiss_anaero=tiss_anaero,
        tiss_total=tiss_total,
        pct_aero=pct_aero,
        pct_anaero=pct_anaero,
    )


# ── EF ───────────────────────────────────────────────────────────

def calc_ef(np_watts: Optional[float], avg_hr: Optional[float]) -> Optional[float]:
    """Efficiency Factor = NP / FC media."""
    if not np_watts or np_watts <= 0 or not avg_hr or avg_hr <= 0:
        return None
    return np_watts / avg_hr


# ── VF ───────────────────────────────────────────────────────────

def calc_vf(np_watts: Optional[float], avg_power: Optional[float]) -> Optional[float]:
    """Variability Factor = NP / potencia media."""
    if not np_watts or np_watts <= 0 or not avg_power or avg_power <= 0:
        return None
    return np_watts / avg_power


# ── Pw:Hr Decoupling ──────────────────────────────────────────

@dataclass
class PwHrResult:
    decoupling: float   # % (positivo = FC subió)
    ef_first: float
    ef_second: float


def _calc_np_from_values(values: List[float], sample_interval_sec: float = 1.0) -> Optional[float]:
    """Normalized Power sobre un array de potencia.
    Media móvil de 30s → 4ª potencia → media → raíz 4ª.
    """
    if not values:
        return None
    window_size = max(1, round(30 / sample_interval_sec))
    if len(values) < window_size:
        return None
    rolling = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window_size:
            s -= values[i - window_size]
        if i >= window_size - 1:
            rolling.append(s / window_size)
    if not rolling:
        return None
    fourth = sum(v ** 4 for v in rolling) / len(rolling)
    return fourth ** 0.25


def calc_pw_hr_decoupling(
    samples: List[Tuple[float, Optional[float], Optional[float]]],
) -> Optional[PwHrResult]:
    """Desacople aeróbico (Pw:Hr) entre 1ª y 2ª mitad de la sesión.

    Método (Friel/Coggan/WKO5/TrainingPeaks):
    1. Divide por TIEMPO (punto medio temporal), no por nº de muestras.
    2. Calcula EF = NP / Avg(FC) en cada mitad.
    3. Desacople (%) = ((EF1 - EF2) / EF1) × 100.

    samples: lista de (t, power, hr).
    """
    valid = [
        (t, p, hr)
        for t, p, hr in samples
        if p is not None and p > 0 and hr is not None and hr > 0
    ]
    if len(valid) < 20:
        return None

    # Split por TIEMPO: punto medio temporal de la actividad
    t_start = valid[0][0]
    t_end = valid[-1][0]
    t_mid = (t_start + t_end) / 2

    first = [(t, p, hr) for t, p, hr in valid if t < t_mid]
    second = [(t, p, hr) for t, p, hr in valid if t >= t_mid]

    if len(first) < 6 or len(second) < 6:
        return None

    # Estimar intervalo de muestreo
    sample_interval = 1.0
    if len(valid) >= 2:
        total_time = t_end - t_start
        sample_interval = max(1.0, round(total_time / (len(valid) - 1)))

    # NP de cada mitad (método TrainingPeaks/WKO5)
    np1 = _calc_np_from_values([p for _, p, _ in first], sample_interval)
    np2 = _calc_np_from_values([p for _, p, _ in second], sample_interval)
    avg_hr1 = sum(hr for _, _, hr in first) / len(first)
    avg_hr2 = sum(hr for _, _, hr in second) / len(second)

    if not np1 or not np2 or avg_hr1 <= 0 or avg_hr2 <= 0:
        return None

    ef_first = np1 / avg_hr1
    ef_second = np2 / avg_hr2
    if ef_first <= 0:
        return None

    decoupling = ((ef_first - ef_second) / ef_first) * 100

    return PwHrResult(
        decoupling=decoupling,
        ef_first=ef_first,
        ef_second=ef_second,
    )
