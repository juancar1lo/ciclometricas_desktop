"""
Tests para los modelos de base de datos y el gestor de perfiles.
"""
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Parchear DATA_DIR antes de importar
_temp_dir = tempfile.mkdtemp()

with patch("db.athlete_manager.DATA_DIR", Path(_temp_dir)), \
     patch("db.athlete_manager.INDEX_FILE", Path(_temp_dir) / "atletas.json"):
    from db.athlete_manager import AthleteManager
    from db.models import Base, Activity, ProfileSnapshot, PowerTestSet, ProcessedFile
    from db.engine import get_session, init_db


class TestAthleteManager:
    def setup_method(self):
        """Crear un manager con directorio temporal."""
        self.tmp = Path(tempfile.mkdtemp())
        with patch("db.athlete_manager.DATA_DIR", self.tmp), \
             patch("db.athlete_manager.INDEX_FILE", self.tmp / "atletas.json"):
            self.manager = AthleteManager()

    def test_create_profile(self):
        with patch("db.athlete_manager.DATA_DIR", self.tmp), \
             patch("db.athlete_manager.INDEX_FILE", self.tmp / "atletas.json"):
            profile = self.manager.create_profile("Carlos", ftp=280, weight_kg=72.0, hr_max=190)

        assert profile.name == "Carlos"
        assert (self.tmp / "Carlos" / "ciclometricas.db").exists()
        assert (self.tmp / "Carlos" / "config.json").exists()

        config = json.loads((self.tmp / "Carlos" / "config.json").read_text())
        assert config["ftp"] == 280
        assert config["weight_kg"] == 72.0

    def test_list_profiles(self):
        with patch("db.athlete_manager.DATA_DIR", self.tmp), \
             patch("db.athlete_manager.INDEX_FILE", self.tmp / "atletas.json"):
            self.manager.create_profile("Ana")
            self.manager.create_profile("Beto")
            profiles = self.manager.list_profiles()

        assert "Ana" in profiles
        assert "Beto" in profiles

    def test_duplicate_name_raises(self):
        with patch("db.athlete_manager.DATA_DIR", self.tmp), \
             patch("db.athlete_manager.INDEX_FILE", self.tmp / "atletas.json"):
            self.manager.create_profile("Carlos")
            with pytest.raises(ValueError, match="Ya existe"):
                self.manager.create_profile("Carlos")

    def test_delete_profile(self):
        with patch("db.athlete_manager.DATA_DIR", self.tmp), \
             patch("db.athlete_manager.INDEX_FILE", self.tmp / "atletas.json"):
            self.manager.create_profile("Temporal")
            assert "Temporal" in self.manager.list_profiles()

            self.manager.delete_profile("Temporal")
            assert "Temporal" not in self.manager.list_profiles()
            assert not (self.tmp / "Temporal").exists()


class TestModels:
    def setup_method(self):
        """Crear DB en memoria para tests."""
        tmp = Path(tempfile.mkdtemp()) / "test.db"
        init_db(tmp)
        self.session = get_session()

    def teardown_method(self):
        self.session.close()

    def test_create_profile_snapshot(self):
        snap = ProfileSnapshot(
            ftp=260,
            weight_kg=70.0,
            hr_max=188,
        )
        self.session.add(snap)
        self.session.commit()

        result = self.session.query(ProfileSnapshot).first()
        assert result is not None
        assert result.ftp == 260
        assert result.weight_kg == 70.0

    def test_create_activity(self):
        act = Activity(
            started_at=datetime(2025, 6, 15, 8, 0, tzinfo=timezone.utc),
            source="fit",
            file_name="morning_ride.fit",
            custom_name="Intervalos Z5",
            duration_sec=3600,
            distance_km=42.5,
        )
        self.session.add(act)
        self.session.commit()

        result = self.session.query(Activity).first()
        assert result is not None
        assert result.display_name == "Intervalos Z5"
        assert result.distance_km == 42.5

    def test_activity_json_fields(self):
        act = Activity(
            started_at=datetime(2025, 6, 15, 8, 0, tzinfo=timezone.utc),
            source="tcx",
            duration_sec=1800,
            distance_km=20.0,
        )
        act.set_zones_power({"z1": 300, "z2": 500, "z3": 400, "z4": 200, "z5": 100, "z6": 50, "z7": 10})
        act.set_mmp({"5": 850, "60": 420, "300": 310})

        self.session.add(act)
        self.session.commit()

        result = self.session.query(Activity).first()
        zones = result.get_zones_power()
        assert zones["z1"] == 300

        mmp = result.get_mmp()
        assert mmp["60"] == 420

    def test_create_power_test(self):
        test = PowerTestSet(
            short_duration=60,
            short_power=480,
            mid_duration=300,
            mid_power=350,
            long_duration=1200,
            long_power=290,
            cp=275.0,
            w_prime=22000.0,
        )
        self.session.add(test)
        self.session.commit()

        result = self.session.query(PowerTestSet).first()
        assert result.cp == 275.0
        assert result.w_prime == 22000.0
