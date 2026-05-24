"""Tests para calc/power.py."""
import pytest
from calc.power import (
    calc_normalized_power,
    calc_average_power,
    calc_work_kj,
    calc_intensity_factor,
    calc_tss,
    calculate_power_metrics,
)


class TestNormalizedPower:
    def test_constant_power(self):
        """NP de potencia constante = esa potencia."""
        values = [200.0] * 300
        np_val = calc_normalized_power(values)
        assert np_val is not None
        assert abs(np_val - 200.0) < 1.0

    def test_too_short(self):
        assert calc_normalized_power([200.0] * 29) is None

    def test_with_nulls(self):
        values = [None] * 10 + [250.0] * 100
        np_val = calc_normalized_power(values)
        assert np_val is not None
        assert np_val > 0

    def test_variable_power_higher_than_average(self):
        """NP siempre >= avg para series variables."""
        values = [100.0, 300.0] * 200
        np_val = calc_normalized_power(values)
        avg = calc_average_power(values)
        assert np_val is not None and avg is not None
        assert np_val >= avg


class TestAveragePower:
    def test_basic(self):
        assert calc_average_power([100, 200, 300]) == pytest.approx(200.0)

    def test_with_nulls(self):
        assert calc_average_power([None, 200, None, 400]) == pytest.approx(300.0)

    def test_empty(self):
        assert calc_average_power([]) is None


class TestWorkKj:
    def test_one_hour_200w(self):
        """200W * 3600s = 720 kJ."""
        values = [200.0] * 3600
        assert calc_work_kj(values) == pytest.approx(720.0, abs=0.1)


class TestIntensityFactor:
    def test_basic(self):
        assert calc_intensity_factor(200, 250) == pytest.approx(0.8)

    def test_none(self):
        assert calc_intensity_factor(None, 250) is None
        assert calc_intensity_factor(200, 0) is None


class TestTSS:
    def test_one_hour_at_ftp(self):
        """1h a FTP = 100 TSS."""
        tss = calc_tss(3600, 250.0, 250.0)
        assert tss is not None
        assert abs(tss - 100.0) < 0.1

    def test_none_inputs(self):
        assert calc_tss(0, 200, 250) is None
        assert calc_tss(3600, None, 250) is None


class TestCalculatePowerMetrics:
    def test_all_metrics(self):
        values = [250.0] * 3600
        m = calculate_power_metrics(values, ftp=250.0)
        assert m.np is not None and abs(m.np - 250.0) < 1.0
        assert m.avg_power is not None and abs(m.avg_power - 250.0) < 1.0
        assert m.work_kj is not None and abs(m.work_kj - 900.0) < 1.0
        assert m.intensity_factor is not None and abs(m.intensity_factor - 1.0) < 0.01
        assert m.tss is not None and abs(m.tss - 100.0) < 1.0
