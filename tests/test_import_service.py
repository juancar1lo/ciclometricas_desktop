"""Tests para el servicio de importación de actividades."""
import os
import tempfile
from pathlib import Path

import pytest

from db.engine import init_db, dispose_engine, get_session
from db.models import Activity, ProcessedFile
from services.import_service import (
    ImportResult,
    import_activity_file,
    import_multiple_files,
    _downsample_trackpoints,
    _extract_power_series,
)
from parsers.types import TrackPoint


@pytest.fixture()
def tmp_db(tmp_path):
    """Crea una DB temporal para tests."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path
    dispose_engine()


# -- Fixtures de archivos TCX mínimos --

MINI_TCX = """\
<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
<Activities>
<Activity Sport="Biking">
<Id>2024-06-15T10:00:00Z</Id>
<Lap StartTime="2024-06-15T10:00:00Z">
<TotalTimeSeconds>120</TotalTimeSeconds>
<DistanceMeters>1000</DistanceMeters>
<Calories>50</Calories>
<Track>
<Trackpoint>
<Time>2024-06-15T10:00:00Z</Time>
<DistanceMeters>0</DistanceMeters>
<HeartRateBpm><Value>130</Value></HeartRateBpm>
<Cadence>85</Cadence>
<Extensions>
<ns3:TPX xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
<ns3:Watts>200</ns3:Watts>
<ns3:Speed>5.0</ns3:Speed>
</ns3:TPX>
</Extensions>
</Trackpoint>
<Trackpoint>
<Time>2024-06-15T10:01:00Z</Time>
<DistanceMeters>500</DistanceMeters>
<HeartRateBpm><Value>145</Value></HeartRateBpm>
<Cadence>90</Cadence>
<Extensions>
<ns3:TPX xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
<ns3:Watts>250</ns3:Watts>
<ns3:Speed>6.0</ns3:Speed>
</ns3:TPX>
</Extensions>
</Trackpoint>
<Trackpoint>
<Time>2024-06-15T10:02:00Z</Time>
<DistanceMeters>1000</DistanceMeters>
<HeartRateBpm><Value>155</Value></HeartRateBpm>
<Cadence>88</Cadence>
<Extensions>
<ns3:TPX xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
<ns3:Watts>230</ns3:Watts>
<ns3:Speed>5.5</ns3:Speed>
</ns3:TPX>
</Extensions>
</Trackpoint>
</Track>
</Lap>
</Activity>
</Activities>
</TrainingCenterDatabase>
"""


def _write_tcx(tmp_path: Path, name: str = "test.tcx", content: str = MINI_TCX) -> Path:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


# --- Tests de utilidades internas ---

class TestDownsample:
    def test_basic(self):
        tps = [
            TrackPoint(t=0, power=200, hr=130),
            TrackPoint(t=3, power=210, hr=135),
            TrackPoint(t=5, power=220, hr=140),
            TrackPoint(t=10, power=230, hr=145),
            TrackPoint(t=15, power=240, hr=150),
        ]
        samples = _downsample_trackpoints(tps, interval=5)
        assert len(samples) >= 3  # 0, 5, 10 + último
        assert samples[0]["t"] == 0
        assert samples[0]["p"] == 200

    def test_empty(self):
        assert _downsample_trackpoints([]) == []


class TestExtractPowerSeries:
    def test_basic(self):
        tps = [
            TrackPoint(t=0, power=100),
            TrackPoint(t=2, power=200),
            TrackPoint(t=4, power=300),
        ]
        series = _extract_power_series(tps)
        assert len(series) == 5  # 0..4
        assert series[0] == 100
        assert series[1] == 100  # forward fill
        assert series[2] == 200
        assert series[4] == 300

    def test_empty(self):
        assert _extract_power_series([]) == []


# --- Tests de importación ---

class TestImportService:
    def test_import_tcx(self, tmp_path, tmp_db):
        tcx_file = _write_tcx(tmp_path)
        result = import_activity_file(tcx_file, ftp=200, hr_max=185)

        assert result.status == "created"
        assert result.activity_id is not None
        assert "test.tcx" in result.file_name

        # Verificar en DB
        session = get_session()
        try:
            act = session.query(Activity).filter_by(id=result.activity_id).first()
            assert act is not None
            assert act.sport == "cycling"
            assert act.source == "tcx"
            assert act.distance_km > 0
            assert act.duration_sec == 120
        finally:
            session.close()

    def test_duplicate_detection(self, tmp_path, tmp_db):
        tcx_file = _write_tcx(tmp_path)
        r1 = import_activity_file(tcx_file, ftp=200)
        assert r1.status == "created"

        r2 = import_activity_file(tcx_file, ftp=200)
        assert r2.status == "duplicate"

    def test_processed_file_record(self, tmp_path, tmp_db):
        tcx_file = _write_tcx(tmp_path)
        import_activity_file(tcx_file, ftp=200)

        session = get_session()
        try:
            pf = session.query(ProcessedFile).first()
            assert pf is not None
            assert pf.file_type == "tcx"
            assert len(pf.file_hash) == 64  # SHA-256
        finally:
            session.close()

    def test_import_multiple(self, tmp_path, tmp_db):
        f1 = _write_tcx(tmp_path, "a.tcx")
        # Crear un segundo archivo con contenido ligeramente diferente
        alt_tcx = MINI_TCX.replace("2024-06-15T10:00:00Z", "2024-06-20T10:00:00Z")
        f2 = _write_tcx(tmp_path, "b.tcx", content=alt_tcx)

        results = import_multiple_files([f1, f2], ftp=200)
        assert len(results) == 2
        assert results[0].status == "created"
        assert results[1].status == "created"

    def test_invalid_file(self, tmp_path, tmp_db):
        bad = tmp_path / "bad.tcx"
        bad.write_text("not xml at all", encoding="utf-8")
        result = import_activity_file(bad, ftp=200)
        assert result.status == "error"

    def test_unsupported_format(self, tmp_path, tmp_db):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c", encoding="utf-8")
        result = import_activity_file(f, ftp=200)
        assert result.status == "error"

    def test_power_metrics_calculated(self, tmp_path, tmp_db):
        """Verifica que se calculan NP, TSS, zonas al importar."""
        tcx_file = _write_tcx(tmp_path)
        result = import_activity_file(tcx_file, ftp=200)

        session = get_session()
        try:
            act = session.query(Activity).filter_by(id=result.activity_id).first()
            # Con solo 3 trackpoints no hay NP (necesita 30s) pero avg_power sí
            assert act.avg_power is not None
            assert act.avg_power > 0
            # Zonas deberían estar calculadas
            zones = act.get_zones_power()
            assert zones is not None
        finally:
            session.close()

    def test_hr_data_extracted(self, tmp_path, tmp_db):
        tcx_file = _write_tcx(tmp_path)
        result = import_activity_file(tcx_file, ftp=200, hr_max=185)

        session = get_session()
        try:
            act = session.query(Activity).filter_by(id=result.activity_id).first()
            assert act.avg_hr is not None
            assert act.max_hr is not None
            zones_hr = act.get_zones_hr()
            assert zones_hr is not None
        finally:
            session.close()

    def test_samples_stored(self, tmp_path, tmp_db):
        tcx_file = _write_tcx(tmp_path)
        result = import_activity_file(tcx_file, ftp=200)

        session = get_session()
        try:
            act = session.query(Activity).filter_by(id=result.activity_id).first()
            samples = act.get_samples()
            assert samples is not None
            assert len(samples) > 0
            assert "t" in samples[0]
            assert "p" in samples[0]
        finally:
            session.close()
