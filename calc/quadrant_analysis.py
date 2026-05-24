"""Análisis por cuadrantes de pedaleo (Quadrant Analysis — Coggan).

Implementación correcta usando AEPF y CPV:
 - AEPF (Average Effective Pedal Force, N) = (P × 60) / (C × 2π × CL)
 - CPV  (Circumferential Pedal Velocity, m/s) = C × CL × 2π / 60

Cada muestra (potencia, cadencia) se convierte a (AEPF, CPV) y se clasifica
respecto al punto de referencia (CP/FTP a cadencia objetivo), también en AEPF/CPV.

Q1 — Alta fuerza / Alta velocidad  → Potencia Neuromuscular
Q2 — Alta fuerza / Baja velocidad  → Fuerza Resistencia
Q3 — Baja fuerza / Baja velocidad  → Recuperación / Técnica
Q4 — Baja fuerza / Alta velocidad  → Eficiencia Cardiovascular

Port fiel de lib/calc/quadrant-analysis.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

TWO_PI = 2 * math.pi


@dataclass
class QuadrantResult:
    q1_pct: float   # Potencia Neuromuscular
    q2_pct: float   # Fuerza Resistencia
    q3_pct: float   # Recuperación / Técnica
    q4_pct: float   # Eficiencia Cardiovascular
    total_samples: int
    ref_power: float
    ref_cadence: float
    ref_aepf: float       # AEPF del punto de referencia (N)
    ref_cpv: float        # CPV del punto de referencia (m/s)
    crank_length_mm: float  # Longitud de biela usada (mm)


@dataclass
class QuadrantSample:
    p: Optional[float]  # power (W)
    c: Optional[float]  # cadence (rpm)


def _to_aepf(power_w: float, cadence_rpm: float, crank_length_m: float) -> float:
    """AEPF = (P × 60) / (C × 2π × CL)  en Newtons."""
    return (power_w * 60) / (cadence_rpm * TWO_PI * crank_length_m)


def _to_cpv(cadence_rpm: float, crank_length_m: float) -> float:
    """CPV = C × CL × 2π / 60  en m/s."""
    return (cadence_rpm * crank_length_m * TWO_PI) / 60


def calc_quadrant_analysis(
    samples: Sequence[QuadrantSample],
    ref_power: float,
    ref_cadence: float = 90.0,
    crank_length_mm: float = 175.0,
) -> Optional[QuadrantResult]:
    """Calcula la distribución porcentual en los 4 cuadrantes de pedaleo
    usando el espacio AEPF/CPV (método Coggan correcto).

    Args:
        samples: Secuencia de muestras con potencia (p) y cadencia (c).
        ref_power: Potencia de referencia (CP, FTP o mFTP).
        ref_cadence: Cadencia de referencia (por defecto 90 rpm — estándar Coggan).
        crank_length_mm: Longitud de biela en mm (por defecto 175).

    Returns:
        QuadrantResult con porcentajes por cuadrante, o None si no hay datos.
    """
    if not samples or ref_power <= 0 or ref_cadence <= 0 or crank_length_mm <= 0:
        return None

    crank_length_m = crank_length_mm / 1000.0

    # Punto de referencia en espacio AEPF/CPV
    ref_aepf = _to_aepf(ref_power, ref_cadence, crank_length_m)
    ref_cpv = _to_cpv(ref_cadence, crank_length_m)

    q1 = q2 = q3 = q4 = 0
    total = 0

    for s in samples:
        p = s.p
        c = s.c
        # Solo muestras con datos válidos de potencia y cadencia > 0
        if p is None or c is None or p <= 0 or c <= 0:
            continue
        if not math.isfinite(p) or not math.isfinite(c):
            continue

        total += 1
        aepf = _to_aepf(p, c, crank_length_m)
        cpv = _to_cpv(c, crank_length_m)

        high_force = aepf >= ref_aepf
        high_velocity = cpv >= ref_cpv

        if high_force and high_velocity:
            q1 += 1       # Alta fuerza + Alta velocidad
        elif high_force and not high_velocity:
            q2 += 1       # Alta fuerza + Baja velocidad
        elif not high_force and not high_velocity:
            q3 += 1       # Baja fuerza + Baja velocidad
        else:
            q4 += 1       # Baja fuerza + Alta velocidad

    if total == 0:
        return None

    return QuadrantResult(
        q1_pct=round(q1 / total * 100, 1),
        q2_pct=round(q2 / total * 100, 1),
        q3_pct=round(q3 / total * 100, 1),
        q4_pct=round(q4 / total * 100, 1),
        total_samples=total,
        ref_power=ref_power,
        ref_cadence=ref_cadence,
        ref_aepf=round(ref_aepf, 1),
        ref_cpv=round(ref_cpv, 2),
        crank_length_mm=crank_length_mm,
    )
