"""Tests para los parsers FIT y TCX."""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parsers import (
    parse_activity_file,
    parse_tcx,
    sha256_file,
    ParsedActivity,
    TrackPoint,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestTcxParser:
    def test_parse_sample(self):
        """Parsea el TCX de prueba correctamente."""
        act = parse_tcx(FIXTURES / "sample.tcx")
        assert act.sport == "cycling"
        assert act.duration_sec == 600
        assert act.distance_m == pytest.approx(5000)
        assert act.calories == 120
        assert act.elevation_gain_m is not None
        assert act.elevation_gain_m == pytest.approx(30.0)  # 680 - 650
        assert act.started_at.year == 2026
        assert act.started_at.month == 1
        assert act.started_at.day == 15

    def test_trackpoints(self):
        act = parse_tcx(FIXTURES / "sample.tcx")
        assert len(act.trackpoints) == 5
        # Primer punto
        tp0 = act.trackpoints[0]
        assert tp0.t == pytest.approx(0.0)
        assert tp0.power == 200
        assert tp0.hr == 120
        assert tp0.cadence == 85
        assert tp0.speed == pytest.approx(8.3)
        assert tp0.altitude == 650
        assert tp0.lat == pytest.approx(40.4168)
        assert tp0.lng == pytest.approx(-3.7038)

    def test_last_trackpoint(self):
        act = parse_tcx(FIXTURES / "sample.tcx")
        tp_last = act.trackpoints[-1]
        assert tp_last.t == pytest.approx(600.0)  # 10 min
        assert tp_last.power == 320
        assert tp_last.hr == 160
        assert tp_last.distance == 5000

    def test_has_properties(self):
        act = parse_tcx(FIXTURES / "sample.tcx")
        assert act.has_power
        assert act.has_hr
        assert act.has_gps
        assert act.distance_km == pytest.approx(5.0)

    def test_from_string(self):
        """Parsea desde string XML."""
        xml = (FIXTURES / "sample.tcx").read_text(encoding="utf-8")
        act = parse_tcx(xml)
        assert act.sport == "cycling"
        assert len(act.trackpoints) == 5

    def test_from_bytes(self):
        """Parsea desde bytes."""
        data = (FIXTURES / "sample.tcx").read_bytes()
        act = parse_tcx(data)
        assert act.sport == "cycling"
        assert len(act.trackpoints) == 5

    def test_invalid_tcx(self):
        with pytest.raises(ValueError, match="sin actividades"):
            parse_tcx("<root></root>")


class TestParseActivityFile:
    def test_dispatch_tcx(self):
        act, ft = parse_activity_file(FIXTURES / "sample.tcx")
        assert ft == "tcx"
        assert act.sport == "cycling"

    def test_dispatch_by_name(self):
        data = (FIXTURES / "sample.tcx").read_bytes()
        act, ft = parse_activity_file(data, file_name="ride.tcx")
        assert ft == "tcx"

    def test_sniff_tcx(self):
        data = (FIXTURES / "sample.tcx").read_bytes()
        act, ft = parse_activity_file(data)  # sin nombre
        assert ft == "tcx"

    def test_unsupported_format(self):
        with pytest.raises(ValueError, match="Formato no soportado"):
            parse_activity_file(b"random bytes", file_name="data.csv")


class TestSha256:
    def test_bytes(self):
        data = b"hello cycling"
        expected = hashlib.sha256(data).hexdigest()
        assert sha256_file(data) == expected

    def test_file(self):
        path = FIXTURES / "sample.tcx"
        data = path.read_bytes()
        assert sha256_file(path) == hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────
# Tests de FIT parser
# ─────────────────────────────────────────────────────────────
# No podemos generar un .fit válido fácilmente sin una librería de escritura,
# pero sí podemos verificar que el parser maneja errores correctamente.

class TestFitParser:
    def test_invalid_fit_raises(self):
        """Bytes inválidos deben lanzar excepción."""
        with pytest.raises(Exception):
            from parsers.fit_parser import parse_fit
            parse_fit(b"this is not a fit file")

    def test_type_error(self):
        """Tipo incorrecto debe lanzar TypeError."""
        from parsers.fit_parser import parse_fit
        with pytest.raises(TypeError):
            parse_fit(12345)  # type: ignore
