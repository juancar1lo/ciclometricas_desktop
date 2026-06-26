"""Tests para services/data_queries.py"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock
from typing import List

import pytest

from ciclometricas_desktop.services.data_queries import (
    _parse_date,
    _parse_args,
    _fmt_dur,
    buscar_actividades,
    mejor_mmp,
    resumen_periodo,
    fitness_en_fecha,
    tendencia_semanal,
    zonas_periodo,
    buscar_por_nombre,
    historial_salud,
    actividad_mas_larga,
    actividad_mayor_tss,
    get_tools_description,
    parse_and_execute_queries,
    QUERY_FUNCTIONS,
    QUERY_PATTERN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2026-05-15") == date(2026, 5, 15)

    def test_european_format(self):
        assert _parse_date("15/05/2026") == date(2026, 5, 15)

    def test_dash_european(self):
        assert _parse_date("15-05-2026") == date(2026, 5, 15)

    def test_with_quotes(self):
        assert _parse_date('"2026-05-15"') == date(2026, 5, 15)

    def test_invalid(self):
        with pytest.raises(ValueError):
            _parse_date("not-a-date")


class TestParseArgs:
    def test_empty(self):
        assert _parse_args("") == []

    def test_simple(self):
        assert _parse_args("300, 2026-01-01, 2026-06-01") == [
            "300", "2026-01-01", "2026-06-01"
        ]

    def test_quoted(self):
        assert _parse_args('"puerto", "2026-01-01"') == [
            "puerto", "2026-01-01"
        ]

    def test_single_quoted(self):
        assert _parse_args("'ruta montaña'") == ["ruta montaña"]

    def test_mixed(self):
        result = _parse_args('300, "2026-05-01", "2026-05-31"')
        assert result == ["300", "2026-05-01", "2026-05-31"]


class TestFmtDur:
    def test_hours(self):
        assert _fmt_dur(7200) == "2h00m"

    def test_minutes(self):
        assert _fmt_dur(125) == "2min"


# ---------------------------------------------------------------------------
# Query pattern regex
# ---------------------------------------------------------------------------
class TestQueryPattern:
    def test_basic_match(self):
        text = '[QUERY: mejor_mmp(300, "2026-05-01", "2026-05-31")]'
        m = QUERY_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "mejor_mmp"
        assert '300' in m.group(2)

    def test_no_args(self):
        text = "[QUERY: tendencia_semanal()]"
        m = QUERY_PATTERN.search(text)
        assert m is not None
        assert m.group(1) == "tendencia_semanal"
        assert m.group(2).strip() == ""

    def test_multiple_matches(self):
        text = (
            'Veamos los datos...\n'
            '[QUERY: mejor_mmp(300)]\n'
            'Y también:\n'
            '[QUERY: resumen_periodo("2026-05-01", "2026-05-31")]'
        )
        matches = list(QUERY_PATTERN.finditer(text))
        assert len(matches) == 2

    def test_no_match(self):
        text = "No hay ninguna query aquí"
        assert QUERY_PATTERN.search(text) is None

    def test_case_insensitive(self):
        text = '[query: Mejor_MMP(300)]'
        m = QUERY_PATTERN.search(text)
        assert m is not None


# ---------------------------------------------------------------------------
# Tools description
# ---------------------------------------------------------------------------
class TestToolsDescription:
    def test_contains_all_functions(self):
        desc = get_tools_description()
        for name in QUERY_FUNCTIONS:
            assert name in desc

    def test_contains_instructions(self):
        desc = get_tools_description()
        assert "[QUERY:" in desc
        assert "YYYY-MM-DD" in desc


# ---------------------------------------------------------------------------
# parse_and_execute_queries (with mocked DB)
# ---------------------------------------------------------------------------
def _make_mock_activity(**kwargs):
    act = MagicMock()
    act.started_at = kwargs.get("started_at", datetime(2026, 5, 10, 8, 0))
    act.display_name = kwargs.get("name", "Ruta test")
    act.duration_sec = kwargs.get("duration_sec", 3600)
    act.distance_km = kwargs.get("distance_km", 30.0)
    act.tss = kwargs.get("tss", 80.0)
    act.normalized_power = kwargs.get("np", 220)
    act.avg_hr = kwargs.get("hr", 145)
    act.elevation_gain_m = kwargs.get("elev", 500)
    act.work_kj = kwargs.get("kj", 800)
    act.avg_power = kwargs.get("avg_power", 180)
    act.intensity_factor = kwargs.get("if_", 0.88)
    act.activity_type = kwargs.get("activity_type", "cycling")
    act.custom_name = kwargs.get("custom_name", None)
    act.file_name = kwargs.get("file_name", "test.fit")
    act.mmp = None
    act.zones_power = None
    act.zones_hr = None
    act.is_manual = False

    def get_mmp():
        mmp_data = kwargs.get("mmp_data", None)
        return mmp_data
    act.get_mmp = get_mmp

    def get_zones_power():
        return kwargs.get("zones_power_data", None)
    act.get_zones_power = get_zones_power

    def get_zones_hr():
        return kwargs.get("zones_hr_data", None)
    act.get_zones_hr = get_zones_hr

    return act


def _mock_session_with_activities(activities: List):
    """Creates a mock session that returns activities for all query patterns."""
    mock_session = MagicMock()

    def mock_query(*models):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.limit.return_value = q
        q.all.return_value = activities
        q.first.return_value = activities[0] if activities else None
        return q

    mock_session.query = MagicMock(side_effect=mock_query)
    mock_session.close = MagicMock()
    return mock_session


class TestParseAndExecute:
    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_buscar_actividades(self, mock_gs):
        acts = [_make_mock_activity(name="Puerto del León")]
        mock_gs.return_value = _mock_session_with_activities(acts)

        text = '[QUERY: buscar_actividades("2026-05-01", "2026-05-31")]'
        results = parse_and_execute_queries(text)

        assert len(results) == 1
        _, fname, output = results[0]
        assert fname == "buscar_actividades"
        assert "Puerto del León" in output

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_mejor_mmp(self, mock_gs):
        act = _make_mock_activity(
            name="Test MMP",
            mmp_data={"300": 310, "60": 400},
        )
        mock_gs.return_value = _mock_session_with_activities([act])

        text = '[QUERY: mejor_mmp(300)]'
        results = parse_and_execute_queries(text)

        assert len(results) == 1
        _, fname, output = results[0]
        assert fname == "mejor_mmp"
        assert "310 W" in output

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_resumen_periodo(self, mock_gs):
        acts = [
            _make_mock_activity(tss=80, duration_sec=3600, distance_km=30),
            _make_mock_activity(tss=120, duration_sec=5400, distance_km=50),
        ]
        mock_gs.return_value = _mock_session_with_activities(acts)

        text = '[QUERY: resumen_periodo("2026-05-01", "2026-05-31")]'
        results = parse_and_execute_queries(text)

        _, _, output = results[0]
        assert "2 sesiones" in output.lower() or "Sesiones: 2" in output

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_buscar_por_nombre(self, mock_gs):
        acts = [_make_mock_activity(name="Sierra Nevada")]
        mock_gs.return_value = _mock_session_with_activities(acts)

        text = '[QUERY: buscar_por_nombre("sierra")]'
        results = parse_and_execute_queries(text)

        _, _, output = results[0]
        assert "Sierra Nevada" in output

    def test_unknown_function(self):
        text = '[QUERY: funcion_inexistente("test")]'
        results = parse_and_execute_queries(text)
        assert len(results) == 1
        _, _, output = results[0]
        assert "Error" in output
        assert "no existe" in output

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_no_results(self, mock_gs):
        mock_gs.return_value = _mock_session_with_activities([])

        text = '[QUERY: buscar_actividades("2020-01-01", "2020-01-31")]'
        results = parse_and_execute_queries(text)

        _, _, output = results[0]
        assert "No se encontraron" in output

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_multiple_queries(self, mock_gs):
        acts = [_make_mock_activity()]
        mock_gs.return_value = _mock_session_with_activities(acts)

        text = (
            '[QUERY: resumen_periodo("2026-05-01", "2026-05-31")]\n'
            '[QUERY: tendencia_semanal(4)]'
        )
        results = parse_and_execute_queries(text)
        assert len(results) == 2

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_actividad_mas_larga(self, mock_gs):
        act = _make_mock_activity(duration_sec=14400, name="Gran fondo")
        mock_gs.return_value = _mock_session_with_activities([act])

        text = '[QUERY: actividad_mas_larga()]'
        results = parse_and_execute_queries(text)

        _, _, output = results[0]
        assert "Gran fondo" in output

    @patch("ciclometricas_desktop.services.data_queries.get_session")
    def test_actividad_mayor_tss(self, mock_gs):
        act = _make_mock_activity(tss=280, name="Etapa reina")
        mock_gs.return_value = _mock_session_with_activities([act])

        text = '[QUERY: actividad_mayor_tss()]'
        results = parse_and_execute_queries(text)

        _, _, output = results[0]
        assert "Etapa reina" in output


# ---------------------------------------------------------------------------
# Integration: system prompt includes tools
# ---------------------------------------------------------------------------
class TestSystemPromptTools:
    @patch("ciclometricas_desktop.services.ai_coach.get_session")
    def test_tools_in_prompt(self, mock_gs):
        mock_gs.side_effect = RuntimeError("no session")

        from ciclometricas_desktop.services.ai_coach import AiCoachService
        coach = AiCoachService()
        coach.refresh_context()
        prompt = coach._system_prompt

        assert "Herramientas de consulta" in prompt
        assert "buscar_actividades" in prompt
        assert "mejor_mmp" in prompt
        assert "[QUERY:" in prompt
