"""Tests para TimeSeriesChart y RouteMapWidget."""
import pytest
from unittest.mock import patch, MagicMock


def test_time_series_chart_import():
    """TimeSeriesChart se puede importar correctamente."""
    from ui.charts.time_series_chart import TimeSeriesChart, SERIES_COLORS, _fmt_hms
    assert TimeSeriesChart is not None
    assert "power" in SERIES_COLORS
    assert "hr" in SERIES_COLORS
    assert "wbal" in SERIES_COLORS
    assert "altitude" in SERIES_COLORS


def test_fmt_hms():
    from ui.charts.time_series_chart import _fmt_hms
    assert _fmt_hms(0) == "00:00:00"
    assert _fmt_hms(65) == "00:01:05"
    assert _fmt_hms(3661) == "01:01:01"
    assert _fmt_hms(7200) == "02:00:00"


def test_route_map_import():
    """RouteMapWidget se puede importar correctamente."""
    from ui.charts.route_map import RouteMapWidget, _interpolate_color
    assert RouteMapWidget is not None


def test_interpolate_color():
    from ui.charts.route_map import _interpolate_color, _rgb_to_hex
    # Extremos — ahora devuelve (r, g, b)
    c0 = _interpolate_color(0.0)
    assert isinstance(c0, tuple) and len(c0) == 3
    assert _rgb_to_hex(c0).startswith("#")

    c1 = _interpolate_color(1.0)
    assert c1 == (239, 68, 68)  # rojo

    # Medio
    c_mid = _interpolate_color(0.5)
    assert isinstance(c_mid, tuple) and len(c_mid) == 3

    # Fuera de rango clamped
    assert _interpolate_color(-0.5) == _interpolate_color(0.0)
    assert _interpolate_color(1.5) == (239, 68, 68)
