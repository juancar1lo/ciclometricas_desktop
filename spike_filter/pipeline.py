"""Pipeline orquestador: detectar → corregir → exportar.

Provee la API principal del módulo spike_filter.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np

from .detector import (
    DetectionConfig,
    SpikeInfo,
    detect_spikes,
)
from .corrector import (
    CorrectionInfo,
    CorrectionMethod,
    CorrectionResult,
    correct_spikes,
)


@dataclass
class ChannelSnapshot:
    """Datos multi-canal de un instante (para contexto de spike)."""
    t: float              # segundos relativos
    power: float          # W (puede ser NaN)
    hr: Optional[float] = None        # ppm
    cadence: Optional[float] = None   # rpm
    speed_kmh: Optional[float] = None # km/h
    altitude: Optional[float] = None  # m


@dataclass
class MetricsImpact:
    """Impacto de la limpieza en las métricas clave."""
    avg_power_before: float
    avg_power_after: float
    max_power_before: float
    max_power_after: float
    np_before: Optional[float] = None
    np_after: Optional[float] = None

    @property
    def avg_power_delta(self) -> float:
        return self.avg_power_after - self.avg_power_before

    @property
    def max_power_delta(self) -> float:
        return self.max_power_after - self.max_power_before


@dataclass
class SpikeDetail:
    """Un spike con su contexto multi-canal para revisión."""
    spike: SpikeInfo
    correction: CorrectionInfo
    context: List[ChannelSnapshot]   # ±10 s alrededor del spike
    accepted: bool = True            # el usuario puede rechazarlo


@dataclass
class CleanResult:
    """Resultado completo del pipeline de limpieza."""
    file_type: str
    original_path: Optional[str]
    spike_details: List[SpikeDetail]    # picos con contexto
    metrics_impact: MetricsImpact
    corrected_power: np.ndarray
    original_power: np.ndarray
    timestamps: np.ndarray              # serie temporal (s)
    # Canales completos para gráfico multi-canal
    hr: np.ndarray                      # ppm (NaN si no hay)
    cadence: np.ndarray                 # rpm (NaN si no hay)
    speed_kmh: np.ndarray               # km/h (NaN si no hay)
    altitude: np.ndarray                # m (NaN si no hay)
    _source_bytes: bytes = field(repr=False, default=b"")
    _corrections_map: Dict[int, float] = field(repr=False, default_factory=dict)

    # Compat: propiedades que usaba la vista anterior
    @property
    def spikes(self) -> List[SpikeInfo]:
        return [sd.spike for sd in self.spike_details]

    @property
    def corrections(self) -> List[CorrectionInfo]:
        return [sd.correction for sd in self.spike_details]

    @property
    def num_spikes(self) -> int:
        return len(self.spike_details)

    @property
    def num_accepted(self) -> int:
        return sum(1 for sd in self.spike_details if sd.accepted)

    @property
    def summary(self) -> str:
        mi = self.metrics_impact
        lines = [
            f"Archivo: {self.original_path or '(bytes)'}",
            f"Tipo: {self.file_type.upper()}",
            f"Picos detectados: {self.num_spikes} (aceptados: {self.num_accepted})",
            f"Potencia media: {mi.avg_power_before:.1f} → {mi.avg_power_after:.1f} W "
            f"({mi.avg_power_delta:+.1f} W)",
            f"Potencia máxima: {mi.max_power_before:.0f} → {mi.max_power_after:.0f} W "
            f"({mi.max_power_delta:+.0f} W)",
        ]
        if mi.np_before is not None:
            lines.append(f"NP: {mi.np_before:.1f} → {mi.np_after:.1f} W")
        return "\n".join(lines)

    def recalc_with_accepted(self) -> None:
        """Recalcula corrected_power y métricas solo con spikes aceptados."""
        power = self.original_power.copy()
        new_map: Dict[int, float] = {}
        for sd in self.spike_details:
            if sd.accepted:
                power[sd.spike.index] = sd.correction.corrected_watts
                new_map[sd.spike.index] = sd.correction.corrected_watts
        self.corrected_power = power
        self._corrections_map = new_map
        self.metrics_impact = _calc_impact(self.original_power, power)

    def save(self, output_path: Union[str, Path]) -> Path:
        """Guarda el archivo corregido (solo spikes aceptados)."""
        self.recalc_with_accepted()
        out = Path(output_path)
        if self.file_type == "tcx":
            from .tcx_writer import rewrite_tcx
            rewrite_tcx(self._source_bytes, self._corrections_map, out)
        elif self.file_type == "fit":
            from .fit_writer import rewrite_fit
            rewrite_fit(self._source_bytes, self._corrections_map, out)
        else:
            raise ValueError(f"Tipo no soportado: {self.file_type}")
        return out


def clean_file(
    source: Union[str, Path, bytes],
    *,
    file_type: Optional[str] = None,
    max_watts: float = 2500.0,
    ftp: Optional[float] = None,
    weight_kg: Optional[float] = None,
    method: Union[str, CorrectionMethod] = CorrectionMethod.INTERPOLATE,
    cap_value: Optional[float] = None,
    zscore_threshold: float = 4.0,
    max_delta_per_sec: float = 500.0,
    max_wkg: float = 25.0,
    max_ftp_mult: float = 4.0,
    context_secs: int = 10,
) -> CleanResult:
    """Limpia un archivo FIT o TCX de picos aberrantes de potencia."""
    # Detectar tipo
    if file_type is None:
        if isinstance(source, (str, Path)):
            ext = str(source).lower()
            if ext.endswith(".fit"):
                file_type = "fit"
            elif ext.endswith(".tcx"):
                file_type = "tcx"
            else:
                raise ValueError("Extensión no reconocida. Usa file_type='fit'|'tcx'.")
        else:
            raise ValueError("Con bytes, especifica file_type='fit'|'tcx'.")

    # Leer bytes originales
    if isinstance(source, (str, Path)):
        source_bytes = Path(source).read_bytes()
        original_path = str(source)
    else:
        source_bytes = source
        original_path = None

    # Parsear para obtener trackpoints
    trackpoints = _parse_trackpoints(source_bytes, file_type)
    n = len(trackpoints)

    # Extraer series multi-canal
    power = np.array(
        [tp.power if tp.power is not None else float('nan') for tp in trackpoints],
        dtype=float,
    )
    timestamps = np.array([tp.t for tp in trackpoints], dtype=float)
    hr = np.array(
        [tp.hr if tp.hr is not None else float('nan') for tp in trackpoints],
        dtype=float,
    )
    cadence = np.array(
        [tp.cadence if tp.cadence is not None else float('nan') for tp in trackpoints],
        dtype=float,
    )
    speed_ms = np.array(
        [tp.speed if tp.speed is not None else float('nan') for tp in trackpoints],
        dtype=float,
    )
    speed_kmh = speed_ms * 3.6  # m/s -> km/h
    altitude = np.array(
        [tp.altitude if tp.altitude is not None else float('nan') for tp in trackpoints],
        dtype=float,
    )

    # Configurar detección
    config = DetectionConfig(
        max_watts=max_watts,
        ftp=ftp,
        weight_kg=weight_kg,
        max_wkg=max_wkg,
        max_ftp_mult=max_ftp_mult,
        max_delta_per_sec=max_delta_per_sec,
        zscore_threshold=zscore_threshold,
    )

    # Detectar
    spikes = detect_spikes(power, timestamps, config)

    # Corregir
    if isinstance(method, str):
        method = CorrectionMethod(method)

    correction_result = correct_spikes(
        power, spikes, method=method, cap_value=cap_value
    )

    # Construir SpikeDetail con contexto multi-canal
    spike_details: List[SpikeDetail] = []
    for spike, corr in zip(spikes, correction_result.corrections):
        ctx = _build_context(
            spike.index, timestamps, power, hr, cadence, speed_kmh, altitude,
            context_secs,
        )
        spike_details.append(SpikeDetail(
            spike=spike,
            correction=corr,
            context=ctx,
            accepted=True,  # por defecto todos aceptados
        ))

    # Mapa de correcciones
    corrections_map = {
        c.index: c.corrected_watts for c in correction_result.corrections
    }

    metrics = _calc_impact(power, correction_result.corrected_power)

    return CleanResult(
        file_type=file_type,
        original_path=original_path,
        spike_details=spike_details,
        metrics_impact=metrics,
        corrected_power=correction_result.corrected_power,
        original_power=correction_result.original_power,
        timestamps=timestamps,
        hr=hr,
        cadence=cadence,
        speed_kmh=speed_kmh,
        altitude=altitude,
        _source_bytes=source_bytes,
        _corrections_map=corrections_map,
    )


def _build_context(
    idx: int,
    timestamps: np.ndarray,
    power: np.ndarray,
    hr: np.ndarray,
    cadence: np.ndarray,
    speed_kmh: np.ndarray,
    altitude: np.ndarray,
    context_secs: int,
) -> List[ChannelSnapshot]:
    """Construye contexto multi-canal ±context_secs alrededor de idx."""
    n = len(timestamps)
    t_center = timestamps[idx]
    lo = max(0, idx - context_secs)
    hi = min(n, idx + context_secs + 1)
    result = []
    for i in range(lo, hi):
        result.append(ChannelSnapshot(
            t=float(timestamps[i]),
            power=float(power[i]),
            hr=float(hr[i]) if not np.isnan(hr[i]) else None,
            cadence=float(cadence[i]) if not np.isnan(cadence[i]) else None,
            speed_kmh=float(speed_kmh[i]) if not np.isnan(speed_kmh[i]) else None,
            altitude=float(altitude[i]) if not np.isnan(altitude[i]) else None,
        ))
    return result


def _parse_trackpoints(data: bytes, file_type: str):
    """Parsea trackpoints usando los parsers existentes."""
    import sys
    import os

    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from parsers.fit_parser import parse_fit
    from parsers.tcx_parser import parse_tcx

    if file_type == "fit":
        parsed = parse_fit(data)
    elif file_type == "tcx":
        parsed = parse_tcx(data)
    else:
        raise ValueError(f"Tipo no soportado: {file_type}")

    return parsed.trackpoints


def _calc_np(power: np.ndarray) -> Optional[float]:
    """Calcula Normalized Power (rolling 30s, raíz cuarta)."""
    valid = power[~np.isnan(power)]
    if len(valid) < 30:
        return None
    kernel = np.ones(30) / 30
    rolling = np.convolve(valid, kernel, mode='valid')
    np4 = np.mean(rolling ** 4)
    return float(np4 ** 0.25)


def _calc_impact(original: np.ndarray, corrected: np.ndarray) -> MetricsImpact:
    """Calcula el impacto en métricas clave."""
    orig_valid = original[~np.isnan(original)]
    corr_valid = corrected[~np.isnan(corrected)]

    return MetricsImpact(
        avg_power_before=float(np.mean(orig_valid)) if len(orig_valid) > 0 else 0,
        avg_power_after=float(np.mean(corr_valid)) if len(corr_valid) > 0 else 0,
        max_power_before=float(np.max(orig_valid)) if len(orig_valid) > 0 else 0,
        max_power_after=float(np.max(corr_valid)) if len(corr_valid) > 0 else 0,
        np_before=_calc_np(original),
        np_after=_calc_np(corrected),
    )
