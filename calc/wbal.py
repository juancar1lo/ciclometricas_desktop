"""W' Balance (modelo diferencial de Skiba et al., 2012).

Calcula segundo a segundo cuánta W' queda disponible:
  - Si P(t) > CP → gasto:        W'bal -= (P(t) - CP)
  - Si P(t) ≤ CP → recuperación:  W'bal += (W' - W'bal) × (1 - e^(-(CP-P(t))·dt / τ))
    con τ = 546 · e^(-0.01 · (CP - P(t))) + 316

Port fiel de lib/calc/wbal.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple


@dataclass
class WbalPoint:
    t: float        # segundos desde inicio
    wbal: int       # W' restante en julios
    pct: int        # % restante (0..100)


def compute_wbal(
    power: Sequence[float],
    cp: float,
    w_prime_j: float,
    dt: float = 1.0,
) -> List[WbalPoint]:
    """W' balance segundo a segundo (serie 1 Hz)."""
    if not power or cp <= 0 or w_prime_j <= 0:
        return []

    result: List[WbalPoint] = []
    wbal = w_prime_j

    for i, p_raw in enumerate(power):
        p = p_raw if p_raw else 0.0
        if p > cp:
            wbal -= (p - cp) * dt
        else:
            diff = cp - p
            tau = 546.0 * math.exp(-0.01 * diff) + 316.0
            wbal += (w_prime_j - wbal) * (1.0 - math.exp(-(diff * dt) / tau))
        wbal = max(0.0, min(w_prime_j, wbal))
        result.append(WbalPoint(
            t=i * dt,
            wbal=round(wbal),
            pct=round((wbal / w_prime_j) * 100),
        ))

    return result


def compute_wbal_from_samples(
    samples: List[Tuple[float, Optional[float]]],
    cp: float,
    w_prime_j: float,
) -> List[WbalPoint]:
    """Versión ligera para samples downsampled (t, p)."""
    if not samples or cp <= 0 or w_prime_j <= 0:
        return []

    result: List[WbalPoint] = []
    wbal = w_prime_j

    for i, (t, p_raw) in enumerate(samples):
        p = p_raw if p_raw else 0.0
        dt = max(1.0, t - samples[i - 1][0]) if i > 0 else 1.0

        if p > cp:
            wbal -= (p - cp) * dt
        else:
            diff = cp - p
            tau = 546.0 * math.exp(-0.01 * diff) + 316.0
            wbal += (w_prime_j - wbal) * (1.0 - math.exp(-(diff * dt) / tau))
        wbal = max(0.0, min(w_prime_j, wbal))
        result.append(WbalPoint(
            t=t,
            wbal=round(wbal),
            pct=round((wbal / w_prime_j) * 100),
        ))

    return result
