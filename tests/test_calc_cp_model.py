"""Tests para calc/cp_model.py."""
import pytest
from calc.cp_model import (
    PowerTestPoint,
    fit_cp_model,
    estimate_vo2max,
    estimate_mftp,
    estimate_p_vo2max,
    calc_mftp_vo2max_percentage,
    calc_tte,
    reliability_from_r2,
)


class TestFitCpModel:
    def test_known_values(self):
        """CP~316, W'~3.5kJ con tests clásicos."""
        points = [
            PowerTestPoint(duration_sec=180, power=380),   # 3 min
            PowerTestPoint(duration_sec=720, power=330),   # 12 min
        ]
        model = fit_cp_model(points)
        assert model is not None
        assert 300 < model.cp < 340
        assert 1000 < model.w_prime < 30000
        assert model.r_squared >= 0.0

    def test_three_points(self):
        points = [
            PowerTestPoint(duration_sec=120, power=420),
            PowerTestPoint(duration_sec=300, power=350),
            PowerTestPoint(duration_sec=720, power=320),
        ]
        model = fit_cp_model(points)
        assert model is not None
        assert model.r_squared > 0.90

    def test_predict_power(self):
        points = [
            PowerTestPoint(duration_sec=180, power=380),
            PowerTestPoint(duration_sec=720, power=330),
        ]
        model = fit_cp_model(points)
        assert model is not None
        p5min = model.predict_power(300)
        assert p5min > model.cp  # siempre > CP para duración finita

    def test_insufficient_points(self):
        assert fit_cp_model([PowerTestPoint(180, 380)]) is None
        assert fit_cp_model([]) is None


class TestEstimateVo2max:
    def test_known_value(self):
        """P5min=328, peso=67 → ~60."""
        vo2 = estimate_vo2max(328, 67)
        assert vo2 is not None
        assert abs(vo2 - 60.0) < 2.0

    def test_invalid(self):
        assert estimate_vo2max(0, 70) is None
        assert estimate_vo2max(300, 0) is None


class TestEstimateMftp:
    def test_basic(self):
        points = [
            PowerTestPoint(duration_sec=180, power=380),
            PowerTestPoint(duration_sec=720, power=330),
        ]
        model = fit_cp_model(points)
        assert model is not None
        mftp = estimate_mftp(model)
        assert abs(mftp - 0.96 * model.cp) < 0.01


class TestTte:
    def test_above_cp(self):
        result = calc_tte(350, 300, 20000)
        assert not result.sustainable
        assert result.seconds is not None
        assert abs(result.seconds - 400) < 1  # 20000 / 50 = 400

    def test_at_cp(self):
        result = calc_tte(300, 300, 20000)
        assert result.sustainable
        assert result.seconds is None

    def test_below_cp(self):
        result = calc_tte(250, 300, 20000)
        assert result.sustainable


class TestReliability:
    def test_high(self):
        r = reliability_from_r2(0.995)
        assert r.level == "high"

    def test_ok(self):
        r = reliability_from_r2(0.98)
        assert r.level == "ok"

    def test_low(self):
        r = reliability_from_r2(0.90)
        assert r.level == "low"

    def test_none(self):
        r = reliability_from_r2(None)
        assert r.level == "na"
