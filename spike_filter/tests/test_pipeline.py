"""Tests para el pipeline completo."""
import numpy as np
import pytest
import sys
import os

# Añadir directorio raíz al path para importar parsers
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spike_filter.pipeline import clean_file, CleanResult, _calc_np


# TCX de prueba con pico aberrante
_TCX_WITH_SPIKE = b"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase
  xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
  xmlns:ext="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
  <Activities>
    <Activity Sport="Biking">
      <Id>2024-01-01T10:00:00Z</Id>
      <Lap StartTime="2024-01-01T10:00:00Z">
        <TotalTimeSeconds>5</TotalTimeSeconds>
        <DistanceMeters>100</DistanceMeters>
        <Calories>10</Calories>
        <Track>
          <Trackpoint>
            <Time>2024-01-01T10:00:00Z</Time>
            <Extensions><ext:TPX><ext:Watts>200</ext:Watts></ext:TPX></Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-01-01T10:00:01Z</Time>
            <Extensions><ext:TPX><ext:Watts>210</ext:Watts></ext:TPX></Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-01-01T10:00:02Z</Time>
            <Extensions><ext:TPX><ext:Watts>5000</ext:Watts></ext:TPX></Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-01-01T10:00:03Z</Time>
            <Extensions><ext:TPX><ext:Watts>220</ext:Watts></ext:TPX></Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-01-01T10:00:04Z</Time>
            <Extensions><ext:TPX><ext:Watts>200</ext:Watts></ext:TPX></Extensions>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""


class TestCleanFile:

    def test_detects_and_corrects_tcx_spike(self):
        result = clean_file(
            _TCX_WITH_SPIKE,
            file_type="tcx",
            max_watts=2500,
        )
        assert isinstance(result, CleanResult)
        assert result.file_type == "tcx"
        assert result.num_spikes >= 1
        # El pico de 5000W debe haber sido corregido
        assert result.corrected_power[2] < 2500
        # Max corregido < max original
        assert result.metrics_impact.max_power_after < result.metrics_impact.max_power_before

    def test_no_spikes_clean_file(self):
        clean_tcx = b"""<?xml version="1.0" encoding="UTF-8"?>
        <TrainingCenterDatabase
          xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
          xmlns:ext="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
          <Activities>
            <Activity Sport="Biking">
              <Id>2024-01-01T10:00:00Z</Id>
              <Lap StartTime="2024-01-01T10:00:00Z">
                <TotalTimeSeconds>3</TotalTimeSeconds>
                <DistanceMeters>50</DistanceMeters>
                <Calories>5</Calories>
                <Track>
                  <Trackpoint>
                    <Time>2024-01-01T10:00:00Z</Time>
                    <Extensions><ext:TPX><ext:Watts>200</ext:Watts></ext:TPX></Extensions>
                  </Trackpoint>
                  <Trackpoint>
                    <Time>2024-01-01T10:00:01Z</Time>
                    <Extensions><ext:TPX><ext:Watts>220</ext:Watts></ext:TPX></Extensions>
                  </Trackpoint>
                  <Trackpoint>
                    <Time>2024-01-01T10:00:02Z</Time>
                    <Extensions><ext:TPX><ext:Watts>210</ext:Watts></ext:TPX></Extensions>
                  </Trackpoint>
                </Track>
              </Lap>
            </Activity>
          </Activities>
        </TrainingCenterDatabase>"""
        result = clean_file(clean_tcx, file_type="tcx", max_watts=2500)
        assert result.num_spikes == 0
        assert len(result.corrections) == 0

    def test_summary_string(self):
        result = clean_file(_TCX_WITH_SPIKE, file_type="tcx", max_watts=2500)
        summary = result.summary
        assert "Picos detectados" in summary
        assert "Potencia media" in summary
        assert "Potencia máxima" in summary

    def test_save_tcx(self, tmp_path):
        result = clean_file(_TCX_WITH_SPIKE, file_type="tcx", max_watts=2500)
        out = result.save(tmp_path / "cleaned.tcx")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_with_ftp_and_weight(self):
        result = clean_file(
            _TCX_WITH_SPIKE,
            file_type="tcx",
            max_watts=2500,
            ftp=300,
            weight_kg=75,
        )
        assert result.num_spikes >= 1

    def test_method_cap(self):
        result = clean_file(
            _TCX_WITH_SPIKE,
            file_type="tcx",
            max_watts=2500,
            method="cap",
            cap_value=2000,
        )
        assert result.num_spikes >= 1
        # Corregido al cap
        for c in result.corrections:
            assert c.corrected_watts <= 2000

    def test_auto_detect_type_from_path(self, tmp_path):
        f = tmp_path / "test.tcx"
        f.write_bytes(_TCX_WITH_SPIKE)
        result = clean_file(f, max_watts=2500)
        assert result.file_type == "tcx"
        assert result.num_spikes >= 1

    def test_unknown_extension_raises(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_bytes(b"data")
        with pytest.raises(ValueError, match="Extensión no reconocida"):
            clean_file(f)

    def test_bytes_without_type_raises(self):
        with pytest.raises(ValueError, match="file_type"):
            clean_file(b"data")


class TestCalcNp:

    def test_np_calculation(self):
        # Serie constante de 200W, NP deberia ser ~200
        power = np.full(120, 200.0)
        np_val = _calc_np(power)
        assert np_val is not None
        assert abs(np_val - 200) < 5

    def test_np_too_short(self):
        power = np.full(10, 200.0)
        assert _calc_np(power) is None

    def test_np_with_variability(self):
        # Serie variable: NP > media (por definición)
        power = np.array([100, 400] * 60, dtype=float)  # 120 samples
        np_val = _calc_np(power)
        avg = np.mean(power)
        assert np_val is not None
        assert np_val > avg  # NP siempre >= avg con variabilidad
