"""Durability Index (DRI) — Índice de Durabilidad Ciclista.

Protocolo empírico: acumula X kJ de trabajo + test CP (3+12 min).
DRI = (CP_fatigado / CP_fresco) × 100

Clasificación:
  ≥ 95%      → Excelente durabilidad
  92–94.99%  → Buena durabilidad
  88–91.99%  → Mejorable
  < 88%      → Limitante

Extrapolación: DRI(kJ) = 100 × e^(-λ × kJ)

Port fiel de lib/calc/durability.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .cp_model import fit_cp_model, PowerTestPoint


# ── Clasificación ─────────────────────────────────────

def classify_dri(dri: float) -> Tuple[str, str, str]:
    """Retorna (classification, label, color_hex)."""
    if dri >= 95:
        return ("excellent", "Excelente durabilidad", "#22c55e")
    if dri >= 92:
        return ("good", "Buena durabilidad", "#3b82f6")
    if dri >= 88:
        return ("improvable", "Mejorable", "#eab308")
    return ("limiting", "Limitante en recorridos largos", "#ef4444")


# ── Cálculo del DRI ─────────────────────────────────

@dataclass
class DurabilityResult:
    cp_fatigued: float
    w_prime_fatigued: float  # julios
    dri_percent: float
    classification: str
    label: str
    color: str


def calc_durability_index(
    power_3min: int,
    power_12min: int,
    cp_fresh: float,
    w_prime_fresh: float,
) -> Optional[DurabilityResult]:
    """Calcula DRI a partir de test de 3+12 min fatigado."""
    if power_3min <= 0 or power_12min <= 0 or cp_fresh <= 0:
        return None
    if power_3min <= power_12min:
        return None

    points = [
        PowerTestPoint(duration_sec=180, power=power_3min),
        PowerTestPoint(duration_sec=720, power=power_12min),
    ]
    model = fit_cp_model(points)
    if model is None or model.cp <= 0:
        return None

    dri = (model.cp / cp_fresh) * 100
    cls, label, color = classify_dri(dri)

    return DurabilityResult(
        cp_fatigued=round(model.cp, 1),
        w_prime_fatigued=round(model.w_prime),
        dri_percent=round(dri, 2),
        classification=cls,
        label=label,
        color=color,
    )


# ── Extrapolación exponencial ─────────────────────────

@dataclass
class ExponentialDecayModel:
    lam: float       # λ
    r_squared: float

    def predict(self, kj: float) -> float:
        if kj <= 0:
            return 100.0
        return 100.0 * math.exp(-self.lam * kj)

    def curve(self, kj_min: float, kj_max: float, steps: int = 50):
        result = []
        step = (kj_max - kj_min) / steps
        kj = kj_min
        while kj <= kj_max:
            result.append((round(kj), round(self.predict(kj), 2)))
            kj += step
        return result


def fit_exponential_decay(
    points: List[Tuple[float, float]],  # [(kj, dri%), ...]
) -> Optional[ExponentialDecayModel]:
    """Ajusta modelo DRI(kJ) = 100 × e^(-λ × kJ)."""
    valid = [(kj, dri) for kj, dri in points if kj > 0 and 0 < dri <= 100]
    if not valid:
        return None

    if len(valid) == 1:
        kj, dri = valid[0]
        lam = -math.log(dri / 100.0) / kj
        return ExponentialDecayModel(lam=lam, r_squared=1.0) if math.isfinite(lam) and lam > 0 else None

    xs = [p[0] for p in valid]
    ys = [math.log(p[1] / 100.0) for p in valid]
    n = len(valid)

    sum_xy = sum(xs[i] * ys[i] for i in range(n))
    sum_x2 = sum(x * x for x in xs)
    if sum_x2 == 0:
        return None
    lam = -sum_xy / sum_x2

    mean_y = sum(ys) / n
    ss_res = sum((ys[i] - (-lam * xs[i])) ** 2 for i in range(n))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r_squared = max(0, 1 - ss_res / ss_tot) if ss_tot > 0 else 1.0

    if not math.isfinite(lam) or lam <= 0:
        return None

    return ExponentialDecayModel(lam=lam, r_squared=r_squared)


# ── Área entre curvas ──────────────────────────────────

@dataclass
class AreaBetweenCurvesResult:
    area_watt_sec: int       # W·s integral
    area_kj: float           # kJ
    avg_power_loss: float    # W
    avg_percent_loss: float  # %


def calc_area_between_curves(
    cp_fresh: float,
    w_prime_fresh: float,
    cp_fatigued: float,
    w_prime_fatigued: float,
    min_t: int = 30,
    max_t: int = 1800,
) -> AreaBetweenCurvesResult:
    """Integración trapezoidal del área entre curvas CP fresca y fatigada."""
    area = 0.0
    total_loss = 0.0
    total_pct_loss = 0.0
    n = max_t - min_t  # steps (dt=1s)

    for t in range(min_t, max_t):
        t1 = t
        t2 = t + 1
        pf1 = cp_fresh + w_prime_fresh / t1
        pf2 = cp_fresh + w_prime_fresh / t2
        pfa1 = cp_fatigued + w_prime_fatigued / t1
        pfa2 = cp_fatigued + w_prime_fatigued / t2
        d1 = max(0.0, pf1 - pfa1)
        d2 = max(0.0, pf2 - pfa2)
        area += (d1 + d2) / 2.0  # dt=1
        total_loss += d1
        if pf1 > 0:
            total_pct_loss += (d1 / pf1) * 100.0

    return AreaBetweenCurvesResult(
        area_watt_sec=round(area),
        area_kj=round(area / 1000.0, 2),
        avg_power_loss=round(total_loss / n, 1) if n > 0 else 0.0,
        avg_percent_loss=round(total_pct_loss / n, 2) if n > 0 else 0.0,
    )


# ── Curva CP para superposición ────────────────────────

def generate_cp_curve(
    cp: float,
    w_prime_j: float,
    durations: Optional[List[int]] = None,
) -> List[Tuple[int, int]]:
    """Genera puntos (duration_sec, power) de la curva P(t) = CP + W'/t."""
    if durations is None:
        durations = [
            5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300,
            360, 420, 480, 600, 720, 900, 1200, 1500, 1800, 2400, 2700,
        ]
    result = []
    for t in durations:
        p = cp + w_prime_j / t
        if p > 0:
            result.append((t, round(p)))
    return result
