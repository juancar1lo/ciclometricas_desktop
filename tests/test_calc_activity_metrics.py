"""Tests para calc/activity_metrics.py."""
import pytest
from calc.activity_metrics import (
    calc_tiss, calc_ef, calc_vf, calc_pw_hr_decoupling,
)


class TestTiss:
    def test_below_cp(self):
        """Todo aeróbico si P < CP."""
        samples = [(float(i), 200.0) for i in range(3600)]  # 1h a 200W
        result = calc_tiss(samples, cp=300, w_prime_j=20000)
        assert result is not None
        assert result.pct_aero > 99
        assert result.tiss_anaero < 0.1

    def test_above_cp(self):
        samples = [(float(i), 350.0) for i in range(300)]  # 5min a 350W
        result = calc_tiss(samples, cp=300, w_prime_j=20000)
        assert result is not None
        assert result.tiss_anaero > 0

    def test_empty(self):
        assert calc_tiss([], 300, 20000) is None


class TestEF:
    def test_basic(self):
        assert calc_ef(250, 150) == pytest.approx(250 / 150)

    def test_none(self):
        assert calc_ef(None, 150) is None
        assert calc_ef(250, 0) is None


class TestVF:
    def test_steady(self):
        assert calc_vf(200, 200) == pytest.approx(1.0)

    def test_variable(self):
        vf = calc_vf(220, 200)
        assert vf is not None
        assert vf > 1.0


class TestPwHrDecoupling:
    def test_no_drift(self):
        """Sin drift → decoupling ~ 0."""
        samples = [(float(i), 200.0, 140.0) for i in range(200)]
        result = calc_pw_hr_decoupling(samples)
        assert result is not None
        assert abs(result.decoupling) < 1.0

    def test_positive_drift(self):
        """FC sube en 2ª mitad → decoupling positivo."""
        first = [(float(i), 200.0, 140.0) for i in range(100)]
        second = [(float(100 + i), 200.0, 160.0) for i in range(100)]
        result = calc_pw_hr_decoupling(first + second)
        assert result is not None
        assert result.decoupling > 0

    def test_too_short(self):
        samples = [(float(i), 200.0, 140.0) for i in range(30)]
        assert calc_pw_hr_decoupling(samples) is None
