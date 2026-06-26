"""Tests para calc/mmp.py."""
import pytest
from calc.mmp import (
    sanitize_power_series,
    compute_mmp,
    power_from_samples,
    merge_mmp_max,
)


class TestSanitizePowerSeries:
    def test_basic(self):
        sr = sanitize_power_series([100, None, -5, 200, float('inf')])
        assert list(sr.values) == [100, 0, 0, 200, 0]
        assert sr.outliers == 0

    def test_with_cap(self):
        sr = sanitize_power_series([100, 2000, 300], max_valid_power=500)
        assert sr.outliers == 1
        assert sr.values[1] == 0


class TestComputeMmp:
    def test_constant_power(self):
        power = [300.0] * 600
        mmp = compute_mmp(power, durations=[5, 60, 300, 600])
        assert mmp[5] == 300
        assert mmp[60] == 300
        assert mmp[300] == 300
        assert mmp[600] == 300

    def test_duration_longer_than_series(self):
        power = [200.0] * 50
        mmp = compute_mmp(power, durations=[60])
        assert 60 not in mmp

    def test_finds_peak(self):
        power = [100.0] * 100 + [400.0] * 30 + [100.0] * 100
        mmp = compute_mmp(power, durations=[30])
        assert mmp[30] == 400

    def test_with_outlier_filter(self):
        power = [200.0] * 100
        power[50] = 5000  # outlier
        mmp_no_filter = compute_mmp(power, durations=[1])
        mmp_filtered = compute_mmp(power, durations=[1], max_valid_power=1000)
        assert mmp_no_filter[1] == 5000
        assert mmp_filtered[1] == 200


class TestPowerFromSamples:
    def test_forward_fill(self):
        samples = [(0.0, 100.0), (5.0, 200.0)]
        arr = power_from_samples(samples, 10)
        assert arr[0] == 100.0
        assert arr[4] == 100.0  # forward-filled
        assert arr[5] == 200.0


class TestMergeMmpMax:
    def test_basic(self):
        a = {5: 800, 60: 400}
        b = {5: 750, 60: 420, 300: 350}
        merged = merge_mmp_max(a, b)
        assert merged[5] == 800
        assert merged[60] == 420
        assert merged[300] == 350
