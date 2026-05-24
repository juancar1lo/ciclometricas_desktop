"""Tests para calc/zones.py."""
import math
from calc.zones import (
    POWER_ZONES, HR_ZONES,
    bucket_series, resolve_zone_ref,
)


class TestBucketSeries:
    def test_all_z1(self):
        ftp = 250
        values = [100.0] * 100  # 40% FTP = Z1
        result = bucket_series(values, ftp, POWER_ZONES)
        assert result["z1"] == 100

    def test_at_ftp(self):
        ftp = 250
        values = [250.0] * 100  # 100% = Z4
        result = bucket_series(values, ftp, POWER_ZONES)
        assert result["z4"] == 100

    def test_neuromuscular(self):
        ftp = 200
        values = [350.0] * 50  # 175% = Z7
        result = bucket_series(values, ftp, POWER_ZONES)
        assert result["z7"] == 50

    def test_empty(self):
        result = bucket_series([], 200, POWER_ZONES)
        assert all(v == 0 for v in result.values())

    def test_hr_zones_fcl_z4(self):
        """95% FCL → Z4 Subumbral (93-99%)."""
        fcl = 170
        values = [round(fcl * 0.95)] * 50  # 95% = Z4
        result = bucket_series(values, fcl, HR_ZONES)
        assert result["z4"] == 50

    def test_hr_zones_fcl_z1(self):
        """70% FCL → Z1 Rec. activa (<81%)."""
        fcl = 170
        values = [round(fcl * 0.70)] * 30
        result = bucket_series(values, fcl, HR_ZONES)
        assert result["z1"] == 30

    def test_hr_zones_fcl_z2(self):
        """84% FCL → Z2 Resist. aeróbica (81-87%)."""
        fcl = 170
        values = [round(fcl * 0.84)] * 40
        result = bucket_series(values, fcl, HR_ZONES)
        assert result["z2"] == 40

    def test_hr_zones_fcl_z5a(self):
        """100% FCL → Z5a Supraumbral (99-102%)."""
        fcl = 170
        values = [round(fcl * 1.00)] * 20
        result = bucket_series(values, fcl, HR_ZONES)
        assert result["z5a"] == 20

    def test_hr_zones_fcl_z5b(self):
        """103% FCL → Z5b Cap. aeróbica (102-105%)."""
        fcl = 170
        values = [round(fcl * 1.03)] * 15
        result = bucket_series(values, fcl, HR_ZONES)
        assert result["z5b"] == 15

    def test_hr_zones_fcl_z5c(self):
        """110% FCL → Z5c Cap. anaeróbica (>105%)."""
        fcl = 170
        values = [round(fcl * 1.10)] * 10
        result = bucket_series(values, fcl, HR_ZONES)
        assert result["z5c"] == 10


class TestResolveZoneRef:
    def test_ftp_default(self):
        ref = resolve_zone_ref(None, ftp=250)
        assert ref.value == 250
        assert ref.source == "ftp"

    def test_cp(self):
        ref = resolve_zone_ref("cp", ftp=250, cp=280)
        assert ref.value == 280
        assert ref.source == "cp"

    def test_mftp(self):
        ref = resolve_zone_ref("mftp", ftp=250, mftp=270)
        assert ref.value == 270
        assert ref.source == "mftp"

    def test_fallback(self):
        ref = resolve_zone_ref("cp", ftp=250, cp=0)
        assert ref.value == 250
        assert ref.source == "ftp"
