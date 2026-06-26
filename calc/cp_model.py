"""Modelo de Critical Power de 2 parámetros (Monod-Scherrer).

Ajuste por regresión lineal del TRABAJO frente al TIEMPO:
  y = W (julios), x = t (segundos)
  y = b·x + a  →  pendiente b = CP, ordenada a = W'

Port fiel de lib/calc/cp-model.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class PowerTestPoint:
    duration_sec: float
    power: float


@dataclass
class CpModelResult:
    cp: float           # watts
    w_prime: float      # joules
    w_prime_kj: float   # kJ
    r_squared: float    # R² (0..1)

    def predict_power(self, duration_sec: float) -> float:
        """P(t) = CP + W'/t."""
        if duration_sec <= 0:
            return self.cp
        return self.cp + self.w_prime / duration_sec


def fit_cp_model(points: List[PowerTestPoint]) -> Optional[CpModelResult]:
    """Ajusta el modelo CP de 2 parámetros por regresión lineal W vs t."""
    pts = [
        p for p in (points or [])
        if p.duration_sec > 0
        and p.power > 0
        and math.isfinite(p.duration_sec)
        and math.isfinite(p.power)
    ]
    if len(pts) < 2:
        return None

    n = len(pts)
    xs = [p.duration_sec for p in pts]
    ys = [p.power * p.duration_sec for p in pts]  # trabajo en julios
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return None

    cp = num / den
    w_prime = mean_y - cp * mean_x
    if not math.isfinite(cp) or not math.isfinite(w_prime) or cp <= 0 or w_prime <= 0:
        return None

    # R²
    ss_res = sum((ys[i] - (cp * xs[i] + w_prime)) ** 2 for i in range(n))
    ss_tot = sum((ys[i] - mean_y) ** 2 for i in range(n))
    r_squared = 1.0 if ss_tot == 0 else max(0.0, min(1.0, 1 - ss_res / ss_tot))

    return CpModelResult(
        cp=cp,
        w_prime=w_prime,
        w_prime_kj=w_prime / 1000,
        r_squared=r_squared,
    )


def estimate_vo2max(p5min: float, weight_kg: float) -> Optional[float]:
    """VO2max (Storer-style): 16.6 + 8.87 × (P5min / peso)."""
    if not p5min or not weight_kg or weight_kg <= 0:
        return None
    return 16.6 + 8.87 * (p5min / weight_kg)


def estimate_mftp(model: CpModelResult) -> float:
    """mFTP = 0.96 × CP."""
    return 0.96 * model.cp


def estimate_p_vo2max(
    vo2max: Optional[float], weight_kg: Optional[float]
) -> Optional[float]:
    """Potencia equivalente al VO₂max invirtiendo la fórmula."""
    if not vo2max or not weight_kg or weight_kg <= 0 or vo2max <= 16.6:
        return None
    p = ((vo2max - 16.6) * weight_kg) / 8.87
    return p if math.isfinite(p) and p > 0 else None


def calc_mftp_vo2max_percentage(
    mftp: Optional[float],
    vo2max: Optional[float],
    weight_kg: Optional[float],
) -> Optional[float]:
    """mFTP como % de PVO₂max."""
    if not mftp or mftp <= 0:
        return None
    p_vo2 = estimate_p_vo2max(vo2max, weight_kg)
    if not p_vo2:
        return None
    pct = (mftp / p_vo2) * 100
    return pct if math.isfinite(pct) and pct > 0 else None


# ── TTE ──────────────────────────────────────────────────────────

@dataclass
class TteResult:
    seconds: Optional[float]   # None si sostenible
    label: str
    sustainable: bool


def _format_seconds(sec: float) -> str:
    if not math.isfinite(sec) or sec <= 0:
        return "—"
    total = round(sec)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}:{s:02d} min"
    return f"{s} s"


def calc_tte(power: float, cp: float, w_prime_j: float) -> TteResult:
    """Time-To-Exhaustion: TTE = W' / (P - CP)."""
    if not math.isfinite(power) or power <= 0:
        return TteResult(seconds=None, label="—", sustainable=False)
    if not math.isfinite(cp) or cp <= 0 or not math.isfinite(w_prime_j) or w_prime_j <= 0:
        return TteResult(seconds=None, label="—", sustainable=False)
    if power <= cp:
        ratio = power / cp
        if ratio >= 0.95:
            label = "Sostenible — ~1-2 h (zona umbral)"
        elif ratio >= 0.85:
            label = "Sostenible — ~2-4 h (zona tempo alta)"
        elif ratio >= 0.75:
            label = "Sostenible — ~3-5 h (zona tempo)"
        elif ratio >= 0.55:
            label = "Sostenible — >5 h (zona resistencia)"
        else:
            label = "Sostenible — muchas horas (zona baja)"
        return TteResult(seconds=None, label=label, sustainable=True)
    sec = w_prime_j / (power - cp)
    return TteResult(seconds=sec, label=_format_seconds(sec), sustainable=False)


# ── Fiabilidad R² ────────────────────────────────────────────────

@dataclass
class ReliabilityLabel:
    level: str   # 'high' | 'ok' | 'low' | 'na'
    text: str
    emoji: str


def reliability_from_r2(r2: Optional[float]) -> ReliabilityLabel:
    if r2 is None or not math.isfinite(r2):
        return ReliabilityLabel(level="na", text="Sin datos suficientes", emoji="—")
    if r2 >= 0.99:
        return ReliabilityLabel(level="high", text="Tests muy fiables", emoji="✅")
    if r2 >= 0.97:
        return ReliabilityLabel(level="ok", text="Fiabilidad aceptable", emoji="⚠️")
    return ReliabilityLabel(level="low", text="Tests poco fiables", emoji="❌")
