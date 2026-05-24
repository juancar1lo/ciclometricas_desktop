"""Tests para calc/wbal.py."""
import pytest
from calc.wbal import compute_wbal, compute_wbal_from_samples


class TestComputeWbal:
    def test_depletion(self):
        """Esfuerzo constante por encima de CP agota W'."""
        cp = 300
        w_prime = 20000
        power = [350.0] * 400  # 50W sobre CP * 400s = 20000J
        result = compute_wbal(power, cp, w_prime)
        assert len(result) == 400
        assert result[0].pct == 100  # primer punto casi lleno
        assert result[-1].pct == 0  # debería estar agotado

    def test_recovery(self):
        """Reposo tras esfuerzo recupera W'."""
        cp = 300
        w_prime = 20000
        power = [400.0] * 100 + [100.0] * 300
        result = compute_wbal(power, cp, w_prime)
        # Al final debería haber recuperado bastante
        assert result[-1].pct > result[100].pct

    def test_empty(self):
        assert compute_wbal([], 300, 20000) == []

    def test_invalid_cp(self):
        assert compute_wbal([200], 0, 20000) == []


class TestComputeWbalFromSamples:
    def test_basic(self):
        samples = [(float(i), 350.0) for i in range(100)]
        result = compute_wbal_from_samples(samples, 300, 20000)
        assert len(result) == 100
        assert result[0].t == 0
        assert result[-1].pct < 100
