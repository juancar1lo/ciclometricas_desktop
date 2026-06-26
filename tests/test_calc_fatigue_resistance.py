"""Tests para calc/fatigue_resistance.py."""
import pytest
from calc.fatigue_resistance import calc_fatigue_resistance, classify_fr


class TestFatigueResistance:
    def test_excellent(self):
        """Potencia constante → FR ~ 1.0."""
        power = [250.0] * 600
        result = calc_fatigue_resistance(power)
        assert result.fr_index is not None
        assert result.fr_index >= 0.95
        assert result.classification == "excellent"

    def test_fade(self):
        """Potencia cae en 2ª mitad."""
        power = [300.0] * 300 + [200.0] * 300
        result = calc_fatigue_resistance(power)
        assert result.fr_index is not None
        assert result.fr_index < 0.85

    def test_too_short(self):
        power = [200.0] * 50
        result = calc_fatigue_resistance(power)
        assert result.classification == "insufficient"


class TestClassifyFr:
    def test_levels(self):
        assert classify_fr(0.98)[0] == "excellent"
        assert classify_fr(0.92)[0] == "good"
        assert classify_fr(0.87)[0] == "normal"
        assert classify_fr(0.82)[0] == "moderate_fade"
        assert classify_fr(0.70)[0] == "significant_fade"
        assert classify_fr(None)[0] == "insufficient"
