"""Algoritmos de detección de picos aberrantes de potencia.

Combina múltiples estrategias para maximizar la detección sin falsos positivos:
1. Umbral absoluto — techo configurable (ej. 2500 W)
2. Umbral relativo — basado en W/kg o múltiplo de FTP
3. Tasa de cambio — gradiente imposible (ΔP/Δt)
4. Z-score en ventana deslizante — outlier estadístico local
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Set

import numpy as np


@dataclass
class SpikeInfo:
    """Información sobre un pico detectado."""
    index: int                  # Índice en la serie temporal
    time_sec: float             # Segundo relativo al inicio
    original_watts: float       # Valor original
    reason: str                 # Motivo de detección


@dataclass
class DetectionConfig:
    """Configuración de detección de picos."""
    # Umbral absoluto
    max_watts: float = 2500.0

    # Umbral relativo (requiere ftp o peso)
    ftp: Optional[float] = None
    weight_kg: Optional[float] = None
    max_wkg: float = 25.0           # W/kg máximo fisiológico
    max_ftp_mult: float = 4.0       # Múltiplo máximo de FTP

    # Tasa de cambio
    max_delta_per_sec: float = 500.0  # W/s máximo permitido

    # Z-score
    zscore_window: int = 30           # Ventana en segundos (±)
    zscore_threshold: float = 4.0     # Desviaciones estándar
    zscore_min_std: float = 10.0      # Std mínima para evitar falsos en zonas planas


def detect_spikes(
    power: np.ndarray,
    timestamps: Optional[np.ndarray] = None,
    config: Optional[DetectionConfig] = None,
) -> List[SpikeInfo]:
    """Detecta picos aberrantes en una serie de potencia.

    Args:
        power: Array de vatios (puede contener NaN para huecos).
        timestamps: Segundos relativos al inicio. Si None, asume 1 Hz.
        config: Configuración de detección.

    Returns:
        Lista de SpikeInfo con los picos detectados, ordenada por índice.
    """
    if config is None:
        config = DetectionConfig()

    n = len(power)
    if n == 0:
        return []

    if timestamps is None:
        timestamps = np.arange(n, dtype=float)

    spike_indices: Set[int] = set()
    spike_map: dict[int, SpikeInfo] = {}

    def _mark(idx: int, watts: float, reason: str):
        if idx not in spike_map:
            spike_map[idx] = SpikeInfo(
                index=idx,
                time_sec=float(timestamps[idx]),
                original_watts=float(watts),
                reason=reason,
            )
        else:
            # Acumular razones
            spike_map[idx].reason += f" + {reason}"
        spike_indices.add(idx)

    # --- 1. Umbral absoluto ---
    for i in range(n):
        w = power[i]
        if np.isnan(w):
            continue
        if w > config.max_watts:
            _mark(i, w, f"abs>{config.max_watts:.0f}W")

    # --- 2. Umbral relativo ---
    if config.weight_kg and config.weight_kg > 0:
        for i in range(n):
            w = power[i]
            if np.isnan(w) or w <= 0:
                continue
            wkg = w / config.weight_kg
            if wkg > config.max_wkg:
                _mark(i, w, f"W/kg={wkg:.1f}>{config.max_wkg}")

    if config.ftp and config.ftp > 0:
        ftp_ceil = config.ftp * config.max_ftp_mult
        for i in range(n):
            w = power[i]
            if np.isnan(w) or w <= 0:
                continue
            if w > ftp_ceil:
                _mark(i, w, f">{config.max_ftp_mult:.1f}×FTP")

    # --- 3. Tasa de cambio ---
    for i in range(1, n):
        w_curr = power[i]
        w_prev = power[i - 1]
        if np.isnan(w_curr) or np.isnan(w_prev):
            continue
        dt = timestamps[i] - timestamps[i - 1]
        if dt <= 0:
            continue
        delta = abs(w_curr - w_prev) / dt
        if delta > config.max_delta_per_sec and w_curr > 0:
            # Solo si el valor actual es alto (no marcamos caídas a 0)
            if w_curr > (config.ftp or 400) * 1.5:
                _mark(i, w_curr, f"Δ={delta:.0f}W/s")

    # --- 4. Z-score en ventana deslizante ---
    half_win = config.zscore_window
    for i in range(n):
        w = power[i]
        if np.isnan(w) or w <= 0:
            continue
        if i in spike_indices:
            continue  # Ya detectado

        lo = max(0, i - half_win)
        hi = min(n, i + half_win + 1)
        window = power[lo:hi]
        valid = window[~np.isnan(window)]
        if len(valid) < 5:
            continue

        mean = np.mean(valid)
        std = np.std(valid)
        if std < config.zscore_min_std:
            continue  # Zona muy plana, Z-score no es fiable

        z = (w - mean) / std
        if z > config.zscore_threshold:
            _mark(i, w, f"Z={z:.1f}")

    # Ordenar por índice
    return sorted(spike_map.values(), key=lambda s: s.index)


def detect_from_trackpoints(
    trackpoints: list,
    config: Optional[DetectionConfig] = None,
) -> List[SpikeInfo]:
    """Wrapper que acepta lista de TrackPoint del parser existente."""
    power = np.array(
        [tp.power if tp.power is not None else float('nan') for tp in trackpoints],
        dtype=float,
    )
    timestamps = np.array([tp.t for tp in trackpoints], dtype=float)
    return detect_spikes(power, timestamps, config)
