"""Tests para el escritor TCX."""
from lxml import etree
import pytest

from spike_filter.tcx_writer import rewrite_tcx


# TCX mínimo con extensiones de potencia
_SAMPLE_TCX = b"""<?xml version="1.0" encoding="UTF-8"?>
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
            <HeartRateBpm><Value>120</Value></HeartRateBpm>
            <Extensions>
              <ext:TPX>
                <ext:Watts>200</ext:Watts>
              </ext:TPX>
            </Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-01-01T10:00:01Z</Time>
            <HeartRateBpm><Value>122</Value></HeartRateBpm>
            <Extensions>
              <ext:TPX>
                <ext:Watts>5000</ext:Watts>
              </ext:TPX>
            </Extensions>
          </Trackpoint>
          <Trackpoint>
            <Time>2024-01-01T10:00:02Z</Time>
            <HeartRateBpm><Value>121</Value></HeartRateBpm>
            <Extensions>
              <ext:TPX>
                <ext:Watts>250</ext:Watts>
              </ext:TPX>
            </Extensions>
          </Trackpoint>
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""

_NS = {
    "tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
    "ext": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
}


class TestTcxWriter:

    def test_rewrite_single_trackpoint(self):
        corrections = {1: 225.0}  # Trackpoint 1: 5000 -> 225
        result = rewrite_tcx(_SAMPLE_TCX, corrections)
        root = etree.fromstring(result)
        watts_els = root.findall(".//ext:Watts", _NS)
        assert len(watts_els) == 3
        assert watts_els[0].text == "200"   # Sin cambio
        assert watts_els[1].text == "225"   # Corregido
        assert watts_els[2].text == "250"   # Sin cambio

    def test_rewrite_multiple_trackpoints(self):
        corrections = {0: 150, 2: 180}
        result = rewrite_tcx(_SAMPLE_TCX, corrections)
        root = etree.fromstring(result)
        watts_els = root.findall(".//ext:Watts", _NS)
        assert watts_els[0].text == "150"
        assert watts_els[1].text == "5000"  # Sin cambio
        assert watts_els[2].text == "180"

    def test_no_corrections_preserves_data(self):
        result = rewrite_tcx(_SAMPLE_TCX, {})
        root = etree.fromstring(result)
        watts_els = root.findall(".//ext:Watts", _NS)
        assert watts_els[1].text == "5000"

    def test_hr_preserved(self):
        corrections = {1: 225}
        result = rewrite_tcx(_SAMPLE_TCX, corrections)
        root = etree.fromstring(result)
        hr_els = root.findall(".//tcx:HeartRateBpm/tcx:Value", _NS)
        assert [el.text for el in hr_els] == ["120", "122", "121"]

    def test_output_is_valid_xml(self):
        corrections = {1: 225}
        result = rewrite_tcx(_SAMPLE_TCX, corrections)
        # Should parse without error
        root = etree.fromstring(result)
        assert root is not None

    def test_output_to_file(self, tmp_path):
        out = tmp_path / "cleaned.tcx"
        rewrite_tcx(_SAMPLE_TCX, {1: 225}, output_path=out)
        assert out.exists()
        root = etree.fromstring(out.read_bytes())
        watts_els = root.findall(".//ext:Watts", _NS)
        assert watts_els[1].text == "225"
