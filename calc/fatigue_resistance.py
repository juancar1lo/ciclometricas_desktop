"""Fatigue Resistance Index.

Compara NP de la 1ª vs 2ª mitad de una actividad:
  FR = NP_second / NP_first

Port fiel de lib/calc/fatigue-resistance.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

MIN_SAMPLES = 60


def _calc_np(values: List[float]) -> Optional[int]:
    """NP simplificado (inline, evita deps circulares)."""
    if len(values) < 30:
        return None
    window = 30
    arr = np.array(values, dtype=np.float64)
    cs = np.cumsum(arr)
    rolling = (cs[window - 1:] - np.concatenate(([0.0], cs[:-window]))) / window
    if len(rolling) == 0:
        return None
    fourth = float(np.mean(rolling ** 4))
    return round(fourth ** 0.25)


@dataclass
class FatigueResistanceResult:
    fr_index: Optional[float]
    np_first: Optional[int]
    np_second: Optional[int]
    classification: str  # excellent|good|normal|moderate_fade|significant_fade|insufficient
    class_label: str


def calc_fatigue_resistance(power: List[float]) -> FatigueResistanceResult:
    clean = [v for v in power if isinstance(v, (int, float)) and math.isfinite(v) and v >= 0]

    if len(clean) < MIN_SAMPLES * 2:
        return FatigueResistanceResult(
            fr_index=None, np_first=None, np_second=None,
            classification="insufficient", class_label="Sin datos",
        )

    mid = len(clean) // 2
    np_first = _calc_np(clean[:mid])
    np_second = _calc_np(clean[mid:])

    if np_first is None or np_second is None or np_first == 0:
        return FatigueResistanceResult(
            fr_index=None, np_first=np_first, np_second=np_second,
            classification="insufficient", class_label="Sin datos",
        )

    fr_index = round(np_second / np_first, 3)

    classification, class_label = classify_fr(fr_index)

    return FatigueResistanceResult(
        fr_index=fr_index,
        np_first=np_first,
        np_second=np_second,
        classification=classification,
        class_label=class_label,
    )


def classify_fr(fr: Optional[float]) -> Tuple[str, str]:
    if fr is None:
        return ("insufficient", "Sin datos")
    if fr >= 0.95:
        return ("excellent", "Excelente")
    if fr >= 0.90:
        return ("good", "Buena")
    if fr >= 0.85:
        return ("normal", "Normal")
    if fr >= 0.80:
        return ("moderate_fade", "Fade moderado")
    return ("significant_fade", "Fade significativo")
