"""Tests para el módulo de corrección de picos."""
import numpy as np
import pytest

from spike_filter.detector import SpikeInfo
from spike_filter.corrector import (
    CorrectionMethod,
    correct_spikes,
)


def _spike(idx: int, watts: float = 5000.0) -> SpikeInfo:
    return SpikeInfo(index=idx, time_sec=float(idx), original_watts=watts, reason="test")


class TestInterpolation:
    """Corrección por interpolación lineal."""

    def test_simple_interpolation(self):
        power = np.array([100, 5000, 300], dtype=float)
        spikes = [_spike(1)]
        result = correct_spikes(power, spikes, CorrectionMethod.INTERPOLATE)
        # Interpolación entre 100 y 300 = 200
        assert result.corrected_power[1] == pytest.approx(200.0)
        assert result.original_power[1] == 5000.0

    def test_interpolation_consecutive_spikes(self):
        power = np.array([100, 5000, 6000, 400], dtype=float)
        spikes = [_spike(1), _spike(2, 6000)]
        result = correct_spikes(power, spikes, CorrectionMethod.INTERPOLATE)
        # Ambos son spikes, interpolar entre 100 y 400
        # idx 1: 100 + 1/3*(400-100) = 200
        # idx 2: 100 + 2/3*(400-100) = 300
        assert result.corrected_power[1] == pytest.approx(200.0)
        assert result.corrected_power[2] == pytest.approx(300.0)

    def test_spike_at_start(self):
        power = np.array([5000, 200, 250], dtype=float)
        spikes = [_spike(0)]
        result = correct_spikes(power, spikes, CorrectionMethod.INTERPOLATE)
        # Sin vecino izquierdo, usa el derecho
        assert result.corrected_power[0] == 200.0

    def test_spike_at_end(self):
        power = np.array([200, 250, 5000], dtype=float)
        spikes = [_spike(2)]
        result = correct_spikes(power, spikes, CorrectionMethod.INTERPOLATE)
        # Sin vecino derecho, usa el izquierdo
        assert result.corrected_power[2] == 250.0

    def test_spike_near_nan(self):
        power = np.array([100, float('nan'), 5000, float('nan'), 300], dtype=float)
        spikes = [_spike(2)]
        result = correct_spikes(power, spikes, CorrectionMethod.INTERPOLATE)
        # Salta NaN, interpola entre 100 (idx 0) y 300 (idx 4)
        assert result.corrected_power[2] == pytest.approx(200.0)


class TestCap:
    """Corrección por capping."""

    def test_cap_at_default(self):
        power = np.array([200, 5000, 300], dtype=float)
        spikes = [_spike(1)]
        result = correct_spikes(power, spikes, CorrectionMethod.CAP)
        assert result.corrected_power[1] == 2500.0

    def test_cap_custom_value(self):
        power = np.array([200, 5000, 300], dtype=float)
        spikes = [_spike(1)]
        result = correct_spikes(power, spikes, CorrectionMethod.CAP, cap_value=1500)
        assert result.corrected_power[1] == 1500.0

    def test_cap_preserves_lower(self):
        """Si el spike está por debajo del cap, mantiene original."""
        power = np.array([200, 3000, 300], dtype=float)
        spikes = [_spike(1, 3000)]
        result = correct_spikes(power, spikes, CorrectionMethod.CAP, cap_value=3500)
        assert result.corrected_power[1] == 3000.0


class TestLocalMean:
    """Corrección por media local."""

    def test_local_mean(self):
        power = np.array([200, 220, 5000, 180, 200], dtype=float)
        spikes = [_spike(2)]
        result = correct_spikes(power, spikes, CorrectionMethod.LOCAL_MEAN)
        # Media de [200, 220, 180, 200] = 200
        assert result.corrected_power[2] == pytest.approx(200.0)


class TestZero:
    """Corrección a cero."""

    def test_zero(self):
        power = np.array([200, 5000, 300], dtype=float)
        spikes = [_spike(1)]
        result = correct_spikes(power, spikes, CorrectionMethod.ZERO)
        assert result.corrected_power[1] == 0.0


class TestCorrectionInfo:
    """Información de corrección."""

    def test_corrections_returned(self):
        power = np.array([200, 5000, 300], dtype=float)
        spikes = [_spike(1)]
        result = correct_spikes(power, spikes, CorrectionMethod.INTERPOLATE)
        assert len(result.corrections) == 1
        c = result.corrections[0]
        assert c.index == 1
        assert c.original_watts == 5000
        assert c.corrected_watts == pytest.approx(250.0)
        assert c.method == "interpolate"
        assert c.reason == "test"

    def test_no_spikes_no_corrections(self):
        power = np.array([200, 250, 300], dtype=float)
        result = correct_spikes(power, [], CorrectionMethod.INTERPOLATE)
        assert len(result.corrections) == 0
        assert np.array_equal(result.corrected_power, result.original_power)
