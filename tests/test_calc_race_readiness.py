"""Tests para calc/race_readiness.py."""
import pytest
from calc.race_readiness import RrsInput, calc_race_readiness


class TestRaceReadiness:
    def test_ready(self):
        result = calc_race_readiness(RrsInput(
            tsb=10, ctl=80, ctl_max=100, ramp_rate=2.0, monotony=1.1,
        ))
        assert result.level == "ready"
        assert result.score >= 75

    def test_almost(self):
        result = calc_race_readiness(RrsInput(
            tsb=0, ctl=60, ctl_max=100, ramp_rate=0.0, monotony=1.8,
        ))
        assert result.level in ("almost", "not_ready")
        assert result.score >= 30

    def test_not_ready(self):
        result = calc_race_readiness(RrsInput(
            tsb=-25, ctl=30, ctl_max=100, ramp_rate=-3.0, monotony=2.5,
        ))
        assert result.level == "not_ready"
        assert result.score < 50

    def test_score_bounds(self):
        for tsb in [-30, -10, 0, 10, 25]:
            result = calc_race_readiness(RrsInput(
                tsb=tsb, ctl=50, ctl_max=80, ramp_rate=1.0, monotony=1.5,
            ))
            assert 0 <= result.score <= 100

    def test_advice_present(self):
        result = calc_race_readiness(RrsInput(
            tsb=10, ctl=80, ctl_max=100, ramp_rate=2.0, monotony=1.1,
        ))
        assert len(result.advice) > 10
