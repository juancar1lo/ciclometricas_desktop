"""Tests para calc/fitness.py."""
import pytest
from datetime import date, datetime, timedelta
from calc.fitness import (
    build_fitness_series,
    calc_ramp_rate,
    last_real_point,
    aggregate_daily_tss,
)


class TestAggregateDailyTss:
    def test_basic(self):
        activities = [
            {"started_at": datetime(2026, 1, 1, 10, 0), "tss": 100},
            {"started_at": datetime(2026, 1, 1, 16, 0), "tss": 50},
            {"started_at": datetime(2026, 1, 2, 8, 0), "tss": 80},
        ]
        result = aggregate_daily_tss(activities)
        assert result["2026-01-01"] == 150
        assert result["2026-01-02"] == 80


class TestBuildFitnessSeries:
    def test_empty_activities(self):
        today = date.today()
        points = build_fitness_series(
            [], today - timedelta(days=7), today
        )
        assert len(points) == 8  # 7 días + hoy
        assert all(p.ctl == 0.0 for p in points)

    def test_with_activity(self):
        today = date.today()
        activities = [
            {"started_at": datetime.combine(today - timedelta(days=3), datetime.min.time()), "tss": 200},
        ]
        points = build_fitness_series(
            activities, today - timedelta(days=7), today
        )
        assert len(points) > 0
        # CTL debería ser > 0 en los últimos días
        assert points[-1].ctl > 0


class TestRampRate:
    def test_flat(self):
        from calc.fitness import FitnessPoint
        points = [
            FitnessPoint(date=f"2026-01-{i:02d}", tss=0, ctl=50, atl=30, tsb=20)
            for i in range(1, 15)
        ]
        rr = calc_ramp_rate(points, 7)
        assert rr == 0.0


class TestLastRealPoint:
    def test_mixed(self):
        from calc.fitness import FitnessPoint
        points = [
            FitnessPoint("2026-01-01", 100, 50, 30, 20, forecast=False),
            FitnessPoint("2026-01-02", 0, 49, 28, 21, forecast=True),
        ]
        p = last_real_point(points)
        assert p is not None
        assert p.date == "2026-01-01"
