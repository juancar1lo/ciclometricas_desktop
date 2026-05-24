"""Detección automática de subidas a partir de datos de altitud y distancia.

Identifica segmentos con gradiente sostenido >3% y calcula métricas.

Port fiel de lib/calc/climbs.ts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class DetectedClimb:
    num: int
    start_idx: int
    end_idx: int
    start_sec: float
    end_sec: float
    duration_sec: float
    distance_m: float
    elev_gain_m: float
    avg_gradient: float     # %
    max_gradient: float     # %
    avg_power: Optional[int]
    avg_hr: Optional[int]
    avg_cadence: Optional[int]
    vam: int                # m/h
    w_kg: Optional[float]


@dataclass
class SampleRow:
    t: float
    p: Optional[float] = None
    hr: Optional[float] = None
    c: Optional[float] = None
    alt: Optional[float] = None
    dist: Optional[float] = None


@dataclass
class ClimbDetectionOptions:
    min_gradient: float = 3.0
    min_elev_gain: float = 30.0
    min_distance_m: float = 300.0
    smooth_window: int = 5
    weight_kg: Optional[float] = None


def _smooth_array(arr: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return arr.copy()
    half = window // 2
    n = len(arr)
    out = np.zeros(n, dtype=np.float64)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = np.mean(arr[lo:hi])
    return out


def detect_climbs(
    samples: List[SampleRow],
    opts: Optional[ClimbDetectionOptions] = None,
) -> List[DetectedClimb]:
    if opts is None:
        opts = ClimbDetectionOptions()

    valid = [s for s in samples if s.alt is not None and s.dist is not None]
    if len(valid) < 10:
        return []

    # Calcular gradientes punto a punto
    n = len(valid)
    gradients = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        d_dist = valid[i].dist - valid[i - 1].dist  # type: ignore
        d_alt = valid[i].alt - valid[i - 1].alt      # type: ignore
        if d_dist > 1:
            gradients[i] = (d_alt / d_dist) * 100

    smooth_grad = _smooth_array(gradients, opts.smooth_window)

    # Identificar segmentos >= min_gradient
    segments: List[dict] = []
    in_climb = False
    climb_start = 0

    for i in range(n):
        if smooth_grad[i] >= opts.min_gradient:
            if not in_climb:
                climb_start = i
                in_climb = True
        else:
            if in_climb:
                segments.append({"start": climb_start, "end": i - 1})
                in_climb = False
    if in_climb:
        segments.append({"start": climb_start, "end": n - 1})

    # Fusionar segmentos cercanos (gap < 200 m)
    merged: List[dict] = []
    for seg in segments:
        if merged:
            gap_dist = valid[seg["start"]].dist - valid[merged[-1]["end"]].dist  # type: ignore
            if gap_dist < 200:
                merged[-1]["end"] = seg["end"]
                continue
        merged.append(dict(seg))

    # Filtrar y calcular métricas
    climbs: List[DetectedClimb] = []
    num = 0

    for seg in merged:
        start_pt = valid[seg["start"]]
        end_pt = valid[seg["end"]]
        dist_m = end_pt.dist - start_pt.dist  # type: ignore
        elev_gain = end_pt.alt - start_pt.alt  # type: ignore

        if dist_m < opts.min_distance_m or elev_gain < opts.min_elev_gain:
            continue

        num += 1
        duration_sec = end_pt.t - start_pt.t
        avg_gradient = (elev_gain / dist_m) * 100 if dist_m > 0 else 0
        max_grad = float(np.max(smooth_grad[seg["start"]:seg["end"] + 1]))

        seg_samples = valid[seg["start"]:seg["end"] + 1]
        powers = [s.p for s in seg_samples if s.p is not None]
        hrs = [s.hr for s in seg_samples if s.hr is not None]
        cads = [s.c for s in seg_samples if s.c is not None and s.c > 0]

        avg_power = round(sum(powers) / len(powers)) if powers else None
        avg_hr = round(sum(hrs) / len(hrs)) if hrs else None
        avg_cadence = round(sum(cads) / len(cads)) if cads else None
        vam = round((elev_gain * 3600) / duration_sec) if duration_sec > 0 else 0
        w_kg = (
            round(avg_power / opts.weight_kg, 2)
            if avg_power is not None and opts.weight_kg and opts.weight_kg > 0
            else None
        )

        climbs.append(DetectedClimb(
            num=num,
            start_idx=seg["start"],
            end_idx=seg["end"],
            start_sec=round(start_pt.t),
            end_sec=round(end_pt.t),
            duration_sec=round(duration_sec),
            distance_m=round(dist_m),
            elev_gain_m=round(elev_gain),
            avg_gradient=round(avg_gradient, 1),
            max_gradient=round(max_grad, 1),
            avg_power=avg_power,
            avg_hr=avg_hr,
            avg_cadence=avg_cadence,
            vam=vam,
            w_kg=w_kg,
        ))

    return climbs
