"""Tests para services/report_generator.py"""
from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.report_generator import (
    ReportData,
    collect_report_data,
    generate_report,
    _chart_fitness,
    _chart_zones_bar,
    _chart_mmp,
    _chart_weekly_tss,
    _fmt_duration,
)
from calc.fitness import FitnessPoint
from calc.zones import POWER_ZONES, HR_ZONES
from db.models import ProfileSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class TestFmtDuration:
    def test_hours(self):
        assert _fmt_duration(3720) == "1h02m"

    def test_minutes(self):
        assert _fmt_duration(125) == "2m05s"

    def test_zero(self):
        assert _fmt_duration(0) == "0m00s"


# ---------------------------------------------------------------------------
# ReportData defaults
# ---------------------------------------------------------------------------
class TestReportData:
    def test_defaults(self):
        rd = ReportData()
        assert rd.ftp is None
        assert rd.fitness_series == []
        assert rd.zones_power == {}
        assert rd.weekly_summary == []

    def test_populated(self):
        rd = ReportData(ftp=250, weight_kg=72, cp=265)
        assert rd.ftp == 250
        assert rd.cp == 265


# ---------------------------------------------------------------------------
# Chart functions (no DB needed, just matplotlib)
# ---------------------------------------------------------------------------
class TestCharts:
    def test_chart_fitness_empty(self):
        assert _chart_fitness([]) is None

    def test_chart_fitness_short(self):
        pts = [FitnessPoint(date=date.today(), tss=0, ctl=50, atl=40, tsb=10)]
        assert _chart_fitness(pts) is None  # <7 points

    def test_chart_fitness_ok(self):
        base = date.today() - timedelta(days=30)
        pts = [
            FitnessPoint(date=base + timedelta(days=i), tss=80,
                         ctl=50 + i * 0.5, atl=40 + i * 0.3, tsb=10 + i * 0.2)
            for i in range(30)
        ]
        fig = _chart_fitness(pts)
        assert fig is not None
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_chart_zones_bar_empty(self):
        assert _chart_zones_bar({}, POWER_ZONES, "test") is None

    def test_chart_zones_bar_ok(self):
        zones = {"z1": 600, "z2": 3600, "z3": 1800, "z4": 900}
        fig = _chart_zones_bar(zones, POWER_ZONES, "Potencia")
        assert fig is not None
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_chart_mmp_empty(self):
        assert _chart_mmp({}) is None

    def test_chart_mmp_ok(self):
        mmp = {5: 900, 30: 500, 60: 400, 300: 300, 1200: 250}
        fig = _chart_mmp(mmp, cp=240)
        assert fig is not None
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_chart_weekly_tss_empty(self):
        assert _chart_weekly_tss([]) is None

    def test_chart_weekly_tss_ok(self):
        data = [("W01", 400, 8.5), ("W02", 350, 7.2), ("W03", 500, 10.1)]
        fig = _chart_weekly_tss(data)
        assert fig is not None
        import matplotlib.pyplot as plt
        plt.close(fig)


# ---------------------------------------------------------------------------
# PDF generation (with mock data, no DB)
# ---------------------------------------------------------------------------
class TestGenerateReport:
    def test_empty_report_generates_pdf(self, tmp_path):
        """Even with empty data, a PDF should be generated."""
        out = str(tmp_path / "empty_report.pdf")
        result = generate_report(out, data=ReportData())
        assert result == out
        assert Path(out).exists()
        assert Path(out).stat().st_size > 500  # not trivially empty

    def test_full_report_generates_pdf(self, tmp_path):
        """A report with all sections populated should generate a multi-page PDF."""
        base = date.today() - timedelta(days=30)
        fitness = [
            FitnessPoint(date=base + timedelta(days=i), tss=80,
                         ctl=50 + i, atl=40 + i * 0.8, tsb=10 + i * 0.2)
            for i in range(30)
        ]

        rd = ReportData(
            ftp=250,
            weight_kg=72,
            hr_max=185,
            hr_lthr=172,
            cp=265,
            w_prime_kj=18.5,
            vo2max=55.2,
            m_ftp=255,
            r_squared=0.992,
            ctl=78,
            atl=65,
            tsb=13,
            fitness_series=fitness,
            zones_power={"z1": 600, "z2": 7200, "z3": 3600, "z4": 1800,
                         "z5": 900, "z6": 300, "z7": 60},
            zones_hr={"z1": 1200, "z2": 5400, "z3": 3000, "z4": 2100,
                      "z5a": 600, "z5b": 300, "z5c": 60},
            mmp_best={5: 950, 10: 750, 30: 520, 60: 420, 300: 310,
                      600: 280, 1200: 265, 3600: 240},
            weekly_summary=[
                ("2026-W20", 380, 7.5),
                ("2026-W21", 420, 8.2),
                ("2026-W22", 350, 6.8),
                ("2026-W23", 450, 9.1),
            ],
            monotony=1.45,
            monotony_class="óptimo",
            strain=650,
            strain_class="moderado",
            rrs_score=72,
            rrs_advice="Buena forma. Podrías competir con garantías.",
            health_weight=71.5,
            health_rhr=48,
            health_hrv=52.3,
            health_readiness=7.5,
            recent_sessions=5,
            recent_hours=8.2,
            recent_tss=420,
            recent_distance_km=215,
        )

        out = str(tmp_path / "full_report.pdf")
        result = generate_report(out, data=rd)
        assert result == out
        assert Path(out).exists()
        # Full report should be substantially larger
        assert Path(out).stat().st_size > 5000

    def test_partial_report_no_cp(self, tmp_path):
        """Report without CP model should still work."""
        rd = ReportData(ftp=220, weight_kg=68)
        out = str(tmp_path / "partial.pdf")
        generate_report(out, data=rd)
        assert Path(out).exists()

    def test_report_with_only_fitness(self, tmp_path):
        """Report with just fitness data."""
        base = date.today() - timedelta(days=10)
        fitness = [
            FitnessPoint(date=base + timedelta(days=i), tss=60,
                         ctl=40 + i, atl=35 + i * 0.5, tsb=5 + i * 0.5)
            for i in range(10)
        ]
        rd = ReportData(
            ctl=49, atl=39.5, tsb=9.5,
            fitness_series=fitness,
        )
        out = str(tmp_path / "fitness_only.pdf")
        generate_report(out, data=rd)
        assert Path(out).exists()


# ---------------------------------------------------------------------------
# collect_report_data (mocked DB)
# ---------------------------------------------------------------------------
class TestCollectData:
    @patch("services.report_generator.get_session")
    def test_no_session(self, mock_get_session):
        mock_get_session.side_effect = RuntimeError("No session")
        rd = collect_report_data()
        assert rd.ftp is None
        assert rd.fitness_series == []

    @patch("services.report_generator.get_session")
    def test_with_profile(self, mock_get_session):
        mock_session = MagicMock()

        # Profile
        profile = MagicMock()
        profile.ftp = 250
        profile.weight_kg = 72
        profile.hr_max = 185
        profile.hr_lthr = 172

        # Mock all query chains
        def mock_query(*models):
            q = MagicMock()
            # Make all chain methods return q
            q.order_by.return_value = q
            q.filter.return_value = q
            q.limit.return_value = q
            q.first.return_value = None
            q.all.return_value = []
            return q

        mock_session.query = MagicMock(side_effect=mock_query)

        # Override just the profile query
        profile_query = MagicMock()
        profile_query.order_by.return_value = profile_query
        profile_query.first.return_value = profile

        original_query = mock_session.query.side_effect

        def smart_query(*models):
            if models and models[0] is ProfileSnapshot:
                return profile_query
            return original_query(*models)

        mock_session.query = MagicMock(side_effect=smart_query)
        mock_get_session.return_value = mock_session

        rd = collect_report_data()
        assert rd.ftp == 250
        assert rd.weight_kg == 72
