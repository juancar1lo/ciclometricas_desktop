"""Tests para el módulo de detección de picos."""
import numpy as np
import pytest

from spike_filter.detector import (
    DetectionConfig,
    SpikeInfo,
    detect_spikes,
)


class TestAbsoluteThreshold:
    """Detección por umbral absoluto."""

    def test_no_spikes_below_threshold(self):
        power = np.array([200, 250, 300, 280, 260], dtype=float)
        result = detect_spikes(power, config=DetectionConfig(max_watts=2500))
        assert len(result) == 0

    def test_detects_spike_above_threshold(self):
        power = np.array([200, 250, 5000, 280, 260], dtype=float)
        result = detect_spikes(power, config=DetectionConfig(max_watts=2500))
        assert len(result) == 1
        assert result[0].index == 2
        assert result[0].original_watts == 5000
        assert "abs>2500W" in result[0].reason

    def test_multiple_spikes(self):
        power = np.array([200, 3000, 250, 4000, 200], dtype=float)
        result = detect_spikes(power, config=DetectionConfig(max_watts=2500))
        assert len(result) == 2
        assert result[0].index == 1
        assert result[1].index == 3

    def test_custom_threshold(self):
        power = np.array([200, 800, 250], dtype=float)
        result = detect_spikes(power, config=DetectionConfig(max_watts=700))
        assert len(result) == 1
        assert result[0].index == 1

    def test_boundary_value_not_detected(self):
        """Valor exacto al umbral no se detecta por absoluto (pero puede por delta)."""
        power = np.array([200, 2500, 250], dtype=float)
        config = DetectionConfig(max_watts=2500, max_delta_per_sec=99999)  # Desactivar delta
        result = detect_spikes(power, config=config)
        assert len(result) == 0  # 2500 no es > 2500


class TestRelativeThreshold:
    """Detección por umbral relativo (W/kg, FTP)."""

    def test_wkg_detection(self):
        # 75kg rider, 25 W/kg = 1875W, anything above is sus
        power = np.array([200, 2000, 250], dtype=float)
        config = DetectionConfig(max_watts=5000, weight_kg=75, max_wkg=25)
        result = detect_spikes(power, config=config)
        assert len(result) == 1
        assert result[0].index == 1
        assert "W/kg" in result[0].reason

    def test_ftp_multiple_detection(self):
        # FTP=300, max 4x = 1200
        power = np.array([200, 1500, 250], dtype=float)
        config = DetectionConfig(max_watts=5000, ftp=300, max_ftp_mult=4)
        result = detect_spikes(power, config=config)
        assert len(result) == 1
        assert "FTP" in result[0].reason

    def test_no_relative_without_data(self):
        """Sin peso ni FTP, no aplica umbral relativo."""
        power = np.array([200, 1500, 250], dtype=float)
        config = DetectionConfig(max_watts=5000, max_delta_per_sec=99999)  # Desactivar delta
        result = detect_spikes(power, config=config)
        assert len(result) == 0  # Solo absoluto, y 1500 < 5000


class TestDeltaDetection:
    """Detección por tasa de cambio."""

    def test_impossible_gradient(self):
        # Salto de 100 a 1800 en 1 segundo = 1700 W/s
        power = np.array([100, 1800, 200], dtype=float)
        config = DetectionConfig(
            max_watts=5000, max_delta_per_sec=500, ftp=250
        )
        result = detect_spikes(power, config=config)
        # Debe detectar el índice 1 (si 1800 > 1.5*FTP = 375)
        spike_indices = {s.index for s in result}
        assert 1 in spike_indices

    def test_normal_sprint_not_flagged(self):
        # Sprint normal: 200 -> 600 = 400 W/s (< 500)
        power = np.array([200, 600, 580, 550, 200], dtype=float)
        config = DetectionConfig(
            max_watts=5000, max_delta_per_sec=500, ftp=300
        )
        result = detect_spikes(power, config=config)
        assert len(result) == 0


class TestZScore:
    """Detección por Z-score en ventana deslizante."""

    def test_zscore_outlier(self):
        # Serie estable ~200W con un pico de 800W
        power = np.full(100, 200.0)
        power[50] = 800  # Outlier claro
        config = DetectionConfig(
            max_watts=5000,
            zscore_threshold=3.0,
            zscore_min_std=5.0,
        )
        result = detect_spikes(power, config=config)
        spike_indices = {s.index for s in result}
        assert 50 in spike_indices

    def test_no_false_positives_in_flat_zone(self):
        """No debe marcar picos en zona plana (baja std)."""
        power = np.full(100, 200.0)
        power[50] = 210  # Ligeramente más alto, no es spike
        config = DetectionConfig(
            max_watts=5000,
            zscore_threshold=4.0,
            zscore_min_std=10.0,  # Std < 10 se ignora
        )
        result = detect_spikes(power, config=config)
        assert len(result) == 0


class TestNanHandling:
    """Manejo de huecos (NaN) en la serie."""

    def test_nan_not_flagged(self):
        power = np.array([200, float('nan'), 300, 250], dtype=float)
        result = detect_spikes(power, config=DetectionConfig(max_watts=2500))
        assert len(result) == 0

    def test_empty_array(self):
        result = detect_spikes(np.array([], dtype=float))
        assert len(result) == 0

    def test_spike_near_nan(self):
        power = np.array([200, float('nan'), 5000, float('nan'), 200], dtype=float)
        result = detect_spikes(power, config=DetectionConfig(max_watts=2500))
        assert len(result) == 1
        assert result[0].index == 2


class TestCombined:
    """Detección combinada con múltiples razones."""

    def test_spike_caught_by_multiple_detectors(self):
        power = np.array([200, 200, 200, 5000, 200, 200, 200], dtype=float)
        config = DetectionConfig(
            max_watts=2500,
            weight_kg=75,
            max_wkg=25,
            ftp=300,
            max_ftp_mult=4,
        )
        result = detect_spikes(power, config=config)
        assert len(result) == 1
        # Debe tener múltiples razones
        assert "+" in result[0].reason

    def test_timestamps_respected(self):
        """Timestamps custom deben reflejarse en time_sec."""
        power = np.array([200, 5000, 200], dtype=float)
        timestamps = np.array([10.0, 15.0, 20.0])
        result = detect_spikes(power, timestamps, DetectionConfig(max_watts=2500))
        assert result[0].time_sec == 15.0
