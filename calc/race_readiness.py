"""Race Readiness Score (RRS).

Puntuación compuesta 0–100 combinando:
  - Forma (TSB): 40%
  - Fitness (CTL + tendencia): 35%
  - Variabilidad (monotonía inversa): 25%

Port fiel de lib/calc/race-readiness.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RrsInput:
    tsb: float
    ctl: float
    ctl_max: float
    ramp_rate: Optional[float]
    monotony: Optional[float]


@dataclass
class RrsResult:
    score: int           # 0–100
    form_score: int
    fitness_score: int
    variability_score: int
    level: str           # ready | almost | not_ready | insufficient
    label: str
    emoji: str
    advice: str


def _score_form(tsb: float) -> float:
    if 5 <= tsb <= 15:
        return 95
    if 15 < tsb <= 25:
        return 85 - (tsb - 15) * 2
    if tsb > 25:
        return max(40, 65 - (tsb - 25) * 3)
    if 0 <= tsb < 5:
        return 70 + tsb * 4
    if -10 <= tsb < 0:
        return 70 + tsb * 3
    if -20 <= tsb < -10:
        return 40 + (tsb + 10) * 2
    return max(0, 20 + (tsb + 20) * 1)


def _score_fitness(ctl: float, ctl_max: float, ramp_rate: Optional[float]) -> float:
    if ctl_max <= 0:
        return 50
    pct = min(ctl / ctl_max, 1.0)
    base = pct * 85
    if ramp_rate is not None:
        if ramp_rate > 0:
            base += min(ramp_rate * 3, 15)
        else:
            base += max(ramp_rate * 2, -10)
    return max(0, min(100, base))


def _score_variability(monotony: Optional[float]) -> float:
    if monotony is None:
        return 50
    if monotony < 1.0:
        return 100
    if monotony < 1.2:
        return 90
    if monotony < 1.5:
        return 75
    if monotony < 2.0:
        return 50
    if monotony < 2.5:
        return 25
    return 10


def _generate_advice(
    level: str, form: int, fitness: int, variability: int
) -> str:
    weakest = min(form, fitness, variability)
    parts: List[str] = []

    if weakest == form and form < 60:
        parts.append("Tu forma (TSB) es baja — necesitas descansar más antes de competir.")
    elif form > 85 and fitness < 50:
        parts.append("Estás descansado pero has perdido fitness. Considera unas sesiones de intensidad.")

    if weakest == fitness and fitness < 60:
        parts.append("Tu CTL está bajo respecto a tu histórico. Aumenta gradualmente la carga.")

    if weakest == variability and variability < 60:
        parts.append("La monotonía es alta — varía la intensidad entre días.")

    if level == "ready" and not parts:
        parts.append("Todos los indicadores están en verde. Buen momento para dar el máximo.")

    if not parts:
        parts.append("Sigue entrenando de forma consistente y variada.")

    return " ".join(parts)


def calc_race_readiness(input_data: RrsInput) -> RrsResult:
    form_score = round(_score_form(input_data.tsb))
    fitness_score = round(_score_fitness(
        input_data.ctl, input_data.ctl_max, input_data.ramp_rate
    ))
    variability_score = round(_score_variability(input_data.monotony))

    score = round(
        form_score * 0.40
        + fitness_score * 0.35
        + variability_score * 0.25
    )

    if score >= 75:
        level, label, emoji = "ready", "Listo para competir", "🟢"
    elif score >= 50:
        level, label, emoji = "almost", "Casi listo", "🟡"
    else:
        level, label, emoji = "not_ready", "No es el momento", "🔴"

    advice = _generate_advice(level, form_score, fitness_score, variability_score)

    return RrsResult(
        score=score,
        form_score=form_score,
        fitness_score=fitness_score,
        variability_score=variability_score,
        level=level,
        label=label,
        emoji=emoji,
        advice=advice,
    )
