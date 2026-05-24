"""Tests básicos para las vistas de UI (importación unitaria sin GUI).

Verifica que los módulos se importan correctamente y las clases existen.
Los tests de integración con Qt requieren QApplication (se ejecutan por separado).
"""
import pytest


class TestImports:
    """Verifica que todos los módulos de vistas se importan sin errores."""

    def test_import_widgets(self):
        from ui.widgets import StatCard, AlertBanner
        assert StatCard is not None
        assert AlertBanner is not None

    def test_import_import_view(self):
        from ui.views.import_view import ImportView
        assert ImportView is not None

    def test_import_settings_view(self):
        from ui.views.settings_view import SettingsView
        assert SettingsView is not None

    def test_import_activities_view(self):
        from ui.views.activities_view import ActivitiesView
        assert ActivitiesView is not None

    def test_import_activity_detail_view(self):
        from ui.views.activity_detail_view import ActivityDetailView
        assert ActivityDetailView is not None

    def test_import_service(self):
        from services.import_service import import_activity_file, import_multiple_files, ImportResult
        assert import_activity_file is not None
        assert import_multiple_files is not None
        assert ImportResult is not None


class TestImportResult:
    def test_created(self):
        from services.import_service import ImportResult
        r = ImportResult(status="created", file_name="test.fit", message="OK", activity_id=1)
        assert r.status == "created"
        assert r.activity_id == 1

    def test_duplicate(self):
        from services.import_service import ImportResult
        r = ImportResult(status="duplicate", file_name="test.fit", message="Ya existe")
        assert r.status == "duplicate"
        assert r.activity_id is None


class TestFormatHelpers:
    def test_fmt_duration(self):
        from ui.views.activities_view import _fmt_duration
        assert _fmt_duration(3661) == "1h 01m"
        assert _fmt_duration(125) == "2m 05s"
        assert _fmt_duration(None) == "—"

    def test_fmt_float(self):
        from ui.views.activities_view import _fmt_float
        assert _fmt_float(3.456, 1) == "3.5"
        assert _fmt_float(None) == "—"

    def test_fmt_int(self):
        from ui.views.activities_view import _fmt_int
        assert _fmt_int(250) == "250"
        assert _fmt_int(None) == "—"

    def test_fmt_date_short(self):
        from ui.views.activities_view import _fmt_date_short
        from datetime import datetime
        dt = datetime(2026, 5, 5, 10, 28)
        result = _fmt_date_short(dt)
        assert "5 may" in result
        assert "2026" in result

    def test_period_options(self):
        from ui.views.activities_view import PERIOD_OPTIONS
        assert len(PERIOD_OPTIONS) >= 5
        labels = [p[0] for p in PERIOD_OPTIONS]
        assert "Todo" in labels


class TestDetailFormatHelpers:
    def test_fmt_hms(self):
        from ui.views.activity_detail_view import _fmt_hms
        assert _fmt_hms(3661) == "01:01:01"
        assert _fmt_hms(0) == "00:00:00"
        assert _fmt_hms(None) == "00:00:00"

    def test_dur_label(self):
        from ui.views.activity_detail_view import _dur_label
        assert _dur_label(5) == "5S"
        assert _dur_label(60) == "1MIN"
        assert _dur_label(300) == "5MIN"
        assert _dur_label(3600) == "1H"

    def test_fmt_date(self):
        from ui.views.activity_detail_view import _fmt_date
        from datetime import datetime
        dt = datetime(2026, 5, 5, 12, 58)
        result = _fmt_date(dt)
        assert "5 may 2026" in result
        assert "12:58" in result
