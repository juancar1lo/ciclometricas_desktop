"""Tests para calc/monotony.py."""
import pytest
from calc.monotony import (
    calc_week_monotony, classify_monotony, classify_strain,
)


class TestCalcWeekMonotony:
    def test_uniform_training(self):
        """Entrenamiento idéntico cada día → monotonía muy alta."""
        daily = [100.0] * 7
        result = calc_week_monotony(daily)
        # stddev = 0 → monotony None
        assert result.monotony is None

    def test_varied_training(self):
        daily = [0, 120, 0, 80, 150, 0, 60]
        result = calc_week_monotony(daily)
        assert result.monotony is not None
        assert result.active_days == 4
        assert result.week_load == pytest.approx(410)

    def test_rest_week(self):
        daily = [0, 50, 0, 0, 0, 0, 0]
        result = calc_week_monotony(daily)
        assert result.monotony is None  # < 2 active days


class TestClassify:
    def test_monotony_levels(self):
        assert classify_monotony(2.5)[0] == "very_high"
        assert classify_monotony(1.7)[0] == "high"
        assert classify_monotony(1.2)[0] == "moderate"
        assert classify_monotony(0.8)[0] == "low"
        assert classify_monotony(None)[0] == "insufficient"

    def test_strain_levels(self):
        assert classify_strain(7000)[0] == "very_high"
        assert classify_strain(5000)[0] == "high"
        assert classify_strain(3000)[0] == "moderate"
        assert classify_strain(1000)[0] == "low"
