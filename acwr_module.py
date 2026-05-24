"""Módulo ACWR — Ratio de Carga Aguda:Crónica (Acute:Chronic Workload Ratio).

Extraído de Ciclométricas Desktop.
Calcula y clasifica el ACWR a partir de datos de fitness (CTL/ATL).

  ACWR = ATL / CTL

  Bandas de clasificación:
  - < 0.80  → Infracarga (bajo riesgo, pero estancamiento)
  - 0.80–1.30 → Óptimo (sweet spot de rendimiento)
  - 1.30–1.50 → Alto (riesgo creciente de lesión)
  - > 1.50  → Peligro (riesgo alto de lesión/sobreentrenamiento)

Dependencias:
  - calc/fitness.py  (build_fitness_series, FitnessPoint)

Autor: Ciclométricas · https://ciclometricas.abacusai.app
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1.  Modelo de fitness (Banister) — CTL / ATL / TSB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class DailyTss:
    date: str    # ISO yyyy-mm-dd
    tss: float


@dataclass
class FitnessPoint:
    """Un punto en la serie temporal de fitness."""
    date: str
    tss: float
    ctl: float     # Chronic Training Load (42d EMA)
    atl: float     # Acute Training Load  (7d EMA)
    tsb: float     # Training Stress Balance = CTL − ATL
    forecast: bool = False


def aggregate_daily_tss(
    activities: Sequence[dict],
) -> Dict[str, float]:
    """Agrega TSS por día.

    activities: lista de dicts con claves 'started_at' (datetime/date) y 'tss' (float).
    """
    result: Dict[str, float] = {}
    for a in (activities or []):
        started = a.get("started_at")
        if started is None:
            continue
        if isinstance(started, datetime):
            d = started.date()
        elif isinstance(started, date):
            d = started
        else:
            continue
        iso = d.isoformat()
        tss = a.get("tss", 0) or 0
        if not isinstance(tss, (int, float)) or not math.isfinite(tss):
            tss = 0
        result[iso] = result.get(iso, 0) + tss
    return result


def build_fitness_series(
    activities: Sequence[dict],
    from_date: date,
    to_date: date,
) -> List[FitnessPoint]:
    """Construye serie CTL/ATL/TSB con pre-warm de 90 días."""
    daily_tss = aggregate_daily_tss(activities)

    start = from_date - timedelta(days=90)
    end = to_date
    today = date.today()

    ctl_alpha = 1 - math.exp(-1 / 42)
    atl_alpha = 1 - math.exp(-1 / 7)

    points: List[FitnessPoint] = []
    ctl = 0.0
    atl = 0.0
    cur = start

    while cur <= end:
        iso = cur.isoformat()
        is_forecast = cur > today
        tss = 0.0 if is_forecast else daily_tss.get(iso, 0.0)
        ctl = ctl + (tss - ctl) * ctl_alpha
        atl = atl + (tss - atl) * atl_alpha
        if cur >= from_date:
            points.append(FitnessPoint(
                date=iso,
                tss=tss,
                ctl=round(ctl, 2),
                atl=round(atl, 2),
                tsb=round(ctl - atl, 2),
                forecast=is_forecast,
            ))
        cur += timedelta(days=1)

    return points


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2.  Cálculo del ACWR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class AcwrPoint:
    """Un punto de la serie ACWR."""
    date: str
    acwr: float
    ctl: float
    atl: float
    classification: str   # "Infracarga", "Óptimo", "Alto", "Peligro"
    color: str            # color hex para la clasificación


def classify_acwr(acwr: float) -> Tuple[str, str]:
    """Clasifica un valor ACWR en banda y devuelve (etiqueta, color_hex).

    Bandas (Gabbett, 2016; Hulin et al., 2014):
      < 0.80  → Infracarga   (azul)
      0.80–1.30 → Óptimo     (verde)
      1.30–1.50 → Alto       (ámbar)
      > 1.50  → Peligro      (rojo)
    """
    if acwr < 0.80:
        return "Infracarga", "#60B5FF"
    if acwr <= 1.30:
        return "Óptimo", "#22c55e"
    if acwr <= 1.50:
        return "Alto", "#f59e0b"
    return "Peligro", "#ef4444"


def compute_acwr_series(
    fitness_points: List[FitnessPoint],
    ctl_min: float = 10.0,
) -> List[AcwrPoint]:
    """Calcula la serie ACWR a partir de puntos de fitness.

    Solo se incluyen días donde CTL >= ctl_min para evitar
    ratios ruidosos con denominador muy pequeño.

    Args:
        fitness_points: lista de FitnessPoint (desde build_fitness_series).
        ctl_min: umbral mínimo de CTL para considerar el punto fiable.

    Returns:
        Lista de AcwrPoint con la serie ACWR válida.
    """
    result: List[AcwrPoint] = []
    for p in fitness_points:
        if p.forecast:
            continue
        if p.ctl < ctl_min:
            continue
        ratio = p.atl / p.ctl
        label, color = classify_acwr(ratio)
        result.append(AcwrPoint(
            date=p.date,
            acwr=round(ratio, 3),
            ctl=p.ctl,
            atl=p.atl,
            classification=label,
            color=color,
        ))
    return result


def current_acwr(
    fitness_points: List[FitnessPoint],
    ctl_min: float = 10.0,
) -> Optional[AcwrPoint]:
    """Devuelve el ACWR más reciente (último punto real con CTL >= ctl_min)."""
    for p in reversed(fitness_points or []):
        if p.forecast:
            continue
        if p.ctl >= ctl_min:
            ratio = p.atl / p.ctl
            label, color = classify_acwr(ratio)
            return AcwrPoint(
                date=p.date,
                acwr=round(ratio, 3),
                ctl=p.ctl,
                atl=p.atl,
                classification=label,
                color=color,
            )
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3.  Ejemplo de uso
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    # Ejemplo: generar datos ficticios y calcular ACWR
    import random

    today = date.today()
    # Simular 120 días de actividades con TSS variable
    activities = []
    for i in range(120):
        d = today - timedelta(days=119 - i)
        # Patrón: 4 días de entreno + 1 descanso
        if i % 5 == 4:
            tss = 0  # día de descanso
        else:
            tss = random.uniform(40, 120)
        activities.append({"started_at": d, "tss": tss})

    # Construir serie de fitness
    pts = build_fitness_series(activities, today - timedelta(days=90), today)
    print(f"Puntos de fitness: {len(pts)}")

    # Calcular ACWR
    acwr_pts = compute_acwr_series(pts)
    print(f"Puntos ACWR válidos: {len(acwr_pts)}")

    # Último valor
    last = current_acwr(pts)
    if last:
        print(f"\nACWR actual: {last.acwr:.2f} → {last.classification}")
        print(f"  CTL: {last.ctl:.1f}  ATL: {last.atl:.1f}")
    else:
        print("No hay datos suficientes para calcular ACWR.")

    # Mostrar últimos 10 puntos
    print("\nÚltimos 10 puntos ACWR:")
    for p in acwr_pts[-10:]:
        print(f"  {p.date}  ACWR={p.acwr:.2f}  [{p.classification}]  "
              f"CTL={p.ctl:.1f}  ATL={p.atl:.1f}")
