"""Tests para calc/recovery.py."""
import pytest
from calc.recovery import project_recovery, estimate_activity_recovery


class TestProjectRecovery:
    def test_fresh(self):
        r = project_recovery(current_ctl=50, current_atl=40)
        assert r.status == "fresh"  # TSB=10 >= 5
        assert r.hours_to_recovery is None

    def test_fatigued(self):
        r = project_recovery(current_ctl=30, current_atl=60)
        assert r.status == "fatigued"  # TSB=-30
        assert r.hours_to_recovery is not None
        assert r.hours_to_recovery > 0

    def test_recovering(self):
        r = project_recovery(current_ctl=40, current_atl=45)
        assert r.status == "recovering"  # TSB=-5

    def test_projection_length(self):
        r = project_recovery(50, 40)
        assert len(r.projection) == 15  # 0..14


class TestEstimateActivityRecovery:
    def test_low_tss(self):
        hours = estimate_activity_recovery(tss=30, ctl_before=50, atl_before=40)
        assert hours >= 0

    def test_high_tss_needs_more_recovery(self):
        h_low = estimate_activity_recovery(50, 50, 40)
        h_high = estimate_activity_recovery(200, 50, 40)
        assert h_high >= h_low
