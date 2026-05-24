"""Detección automática de intervalos de trabajo.

Algoritmo:
  1. Suavizado de potencia con media móvil de 10 s
  2. Serie de trabajo cuando P_suavizada > umbral durante >= minWorkSec
  3. Fin cuando P_suavizada < umbral durante >= gapTolerance
  4. El descanso entre series se registra como recovery

Port fiel de lib/calc/intervals.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np


@dataclass
class WorkInterval:
    num: int
    start_sec: float
    end_sec: float
    duration_sec: float
    avg_power: int
    max_power: int
    avg_hr: Optional[int]
    avg_cadence: Optional[int]
    recovery_sec: Optional[float]


@dataclass
class SampleRow:
    t: float
    p: Optional[float]
    hr: Optional[float] = None
    c: Optional[float] = None


@dataclass
class DetectIntervalsOptions:
    threshold: Optional[int] = None
    min_work_sec: int = 20
    gap_tolerance_sec: int = 8
    smooth_window_sec: int = 10


def _smooth(values: List[Optional[float]], window: int) -> np.ndarray:
    """Media móvil centrada."""
    n = len(values)
    out = np.zeros(n, dtype=np.float64)
    half = window // 2
    for i in range(n):
        s = 0.0
        cnt = 0
        for j in range(max(0, i - half), min(n, i + half + 1)):
            v = values[j]
            if v is not None and v > 0:
                s += v
                cnt += 1
        out[i] = s / cnt if cnt > 0 else 0.0
    return out


def detect_intervals(
    samples: List[SampleRow],
    reference_watts: float,
    opts: Optional[DetectIntervalsOptions] = None,
) -> List[WorkInterval]:
    """Detecta intervalos de trabajo en la serie de potencia."""
    if opts is None:
        opts = DetectIntervalsOptions()

    threshold = opts.threshold if opts.threshold is not None else round(reference_watts * 0.75)
    min_work = opts.min_work_sec
    gap_tol = opts.gap_tolerance_sec
    smooth_win = opts.smooth_window_sec

    if not samples or threshold <= 0:
        return []

    smoothed = _smooth([s.p for s in samples], smooth_win)

    # Detectar segmentos above threshold
    raw_segments: List[Dict[str, int]] = []
    seg_start: Optional[int] = None

    for i in range(len(smoothed)):
        if smoothed[i] >= threshold:
            if seg_start is None:
                seg_start = i
        else:
            if seg_start is not None:
                raw_segments.append({"start": seg_start, "end": i - 1})
                seg_start = None
    if seg_start is not None:
        raw_segments.append({"start": seg_start, "end": len(smoothed) - 1})

    # Fusionar segmentos con gap < gap_tolerance
    merged: List[Dict[str, int]] = []
    for seg in raw_segments:
        if merged:
            last = merged[-1]
            gap_sec = samples[seg["start"]].t - samples[last["end"]].t
            if gap_sec <= gap_tol:
                last["end"] = seg["end"]
                continue
        merged.append(dict(seg))

    # Filtrar por duración mínima y construir WorkIntervals
    intervals: List[WorkInterval] = []
    num = 0

    for m_idx, seg in enumerate(merged):
        start_sec = samples[seg["start"]].t
        end_sec = samples[seg["end"]].t
        dur = end_sec - start_sec
        if dur < min_work:
            continue

        num += 1
        sum_p = 0.0
        max_p = 0.0
        sum_hr = 0.0
        cnt_hr = 0
        sum_c = 0.0
        cnt_c = 0
        cnt = 0

        for i in range(seg["start"], seg["end"] + 1):
            s = samples[i]
            if s.p is not None and s.p > 0:
                sum_p += s.p
                cnt += 1
                if s.p > max_p:
                    max_p = s.p
            if s.hr is not None and s.hr > 0:
                sum_hr += s.hr
                cnt_hr += 1
            if s.c is not None and s.c > 0:
                sum_c += s.c
                cnt_c += 1

        recovery: Optional[float] = None
        if m_idx < len(merged) - 1:
            next_start = samples[merged[m_idx + 1]["start"]].t
            recovery = next_start - end_sec

        intervals.append(WorkInterval(
            num=num,
            start_sec=start_sec,
            end_sec=end_sec,
            duration_sec=dur,
            avg_power=round(sum_p / cnt) if cnt > 0 else 0,
            max_power=round(max_p),
            avg_hr=round(sum_hr / cnt_hr) if cnt_hr > 0 else None,
            avg_cadence=round(sum_c / cnt_c) if cnt_c > 0 else None,
            recovery_sec=recovery,
        ))

    return intervals
