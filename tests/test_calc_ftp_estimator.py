"""Tests para calc/ftp_estimator.py."""
import math
import pytest
from calc.ftp_estimator import (
    ftp_coefficient,
    estimate_ftp_from_power,
    estimate_ftp_from_mmp,
)


class TestFtpCoefficient:
    def test_5min(self):
        coef = ftp_coefficient(300)
        assert abs(coef - 0.83) < 0.02

    def test_20min(self):
        coef = ftp_coefficient(1200)
        assert abs(coef - 0.95) < 0.02


class TestEstimateFtpFromPower:
    def test_detects_improvement(self):
        # 20 min a 300W → FTP ~ 285
        power = [300.0] * 1200 + [100.0] * 600
        result = estimate_ftp_from_power(power, current_ftp=250)
        assert result is not None
        assert result.estimated_ftp > 250

    def test_no_improvement(self):
        power = [200.0] * 1200
        result = estimate_ftp_from_power(power, current_ftp=300)
        assert result is None  # 200W < FTP

    def test_too_short(self):
        power = [400.0] * 100  # < 300s
        result = estimate_ftp_from_power(power, current_ftp=200)
        assert result is None


class TestEstimateFtpFromMmp:
    def test_basic(self):
        mmp = {300: 350, 600: 320, 1200: 290}
        result = estimate_ftp_from_mmp(mmp, current_ftp=250)
        assert result is not None
        assert result.estimated_ftp > 250

    def test_no_relevant_durations(self):
        mmp = {5: 800, 60: 500}  # Solo sprints
        result = estimate_ftp_from_mmp(mmp, current_ftp=300)
        assert result is None
