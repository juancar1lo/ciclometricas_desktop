"""
Modelos SQLAlchemy para Ciclométricas Desktop.
Traducción del schema Prisma (PostgreSQL) a SQLite.
Cada perfil de atleta tiene su propia base de datos SQLite independiente.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer, String, Text,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ProfileSnapshot — historial del perfil del ciclista
# ---------------------------------------------------------------------------
class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ftp: Mapped[int] = mapped_column(Integer)                     # watts
    weight_kg: Mapped[float] = mapped_column(Float)
    hr_max: Mapped[int] = mapped_column(Integer)                  # ppm (frecuencia cardíaca máxima)
    hr_lthr: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ppm (FCL / LTHR)
    zone_source: Mapped[str] = mapped_column(String(10), default="ftp")  # 'ftp' | 'cp' | 'mftp'
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_profile_effective", "effective_at"),
    )


# ---------------------------------------------------------------------------
# PowerTestSet — tests de potencia para modelo CP / W'
# ---------------------------------------------------------------------------
class PowerTestSet(Base):
    __tablename__ = "power_test_set"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Tests: corto, medio, largo
    short_duration: Mapped[int] = mapped_column(Integer)     # segundos (60-120)
    short_power: Mapped[int] = mapped_column(Integer)        # watts
    mid_duration: Mapped[int] = mapped_column(Integer)       # segundos (180-300)
    mid_power: Mapped[int] = mapped_column(Integer)          # watts
    long_duration: Mapped[int] = mapped_column(Integer)      # segundos (600-1200)
    long_power: Mapped[int] = mapped_column(Integer)         # watts

    # Sprint máximo (opcional)
    max_power: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Resultados calculados (cacheados)
    cp: Mapped[float | None] = mapped_column(Float, nullable=True)
    w_prime: Mapped[float | None] = mapped_column(Float, nullable=True)       # julios
    p5min: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2max: Mapped[float | None] = mapped_column(Float, nullable=True)
    m_ftp: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_squared: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_test_tested_at", "tested_at"),
    )


# ---------------------------------------------------------------------------
# ProcessedFile — hash de archivos para evitar duplicados
# ---------------------------------------------------------------------------
class ProcessedFile(Base):
    __tablename__ = "processed_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_hash: Mapped[str] = mapped_column(String(64))           # SHA-256
    original_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(Integer)
    file_type: Mapped[str] = mapped_column(String(10))           # "fit" | "tcx"
    activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_file_hash", "file_hash", unique=True),
    )


# ---------------------------------------------------------------------------
# Activity — entrenamiento procesado
# ---------------------------------------------------------------------------
class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Metadatos
    started_at: Mapped[datetime] = mapped_column(DateTime)
    sport: Mapped[str] = mapped_column(String(30), default="cycling")
    source: Mapped[str] = mapped_column(String(10))              # "fit" | "tcx" | "strava"
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    strava_activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)

    # Métricas básicas
    duration_sec: Mapped[int] = mapped_column(Integer)
    moving_time_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_km: Mapped[float] = mapped_column(Float)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Velocidad / cadencia
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_cadence: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_cadence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Frecuencia cardíaca
    avg_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Potencia
    avg_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    normalized_power: Mapped[float | None] = mapped_column(Float, nullable=True)
    intensity_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    tss: Mapped[float | None] = mapped_column(Float, nullable=True)
    work_kj: Mapped[float | None] = mapped_column(Float, nullable=True)

    # FTP usado en el cálculo
    ftp_used: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # JSON fields — almacenados como TEXT en SQLite
    zones_power: Mapped[str | None] = mapped_column(Text, nullable=True)    # JSON {z1: s, ...}
    zones_hr: Mapped[str | None] = mapped_column(Text, nullable=True)       # JSON {z1: s, ...}
    samples: Mapped[str | None] = mapped_column(Text, nullable=True)        # JSON array
    mmp: Mapped[str | None] = mapped_column(Text, nullable=True)            # JSON {"5": 850, ...}
    climbs: Mapped[str | None] = mapped_column(Text, nullable=True)         # JSON array

    # FTP suggestion
    ftp_suggestion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ftp_suggestion_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ftp_suggestion_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Balance de pedaleo
    avg_left_balance: Mapped[float | None] = mapped_column(Float, nullable=True)  # % izq (ej. 48.5)

    # Notas
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    # Sesiones manuales (fuerza, caminar, otro)
    activity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 'cycling'|'strength'|'walk'|'other'
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    perceived_if: Mapped[float | None] = mapped_column(Float, nullable=True)  # IF percibido para TSS manual

    __table_args__ = (
        Index("ix_activity_started", "started_at"),
    )

    # --- Helpers para campos JSON ---
    def get_zones_power(self) -> dict[str, float] | None:
        return json.loads(self.zones_power) if self.zones_power else None

    def set_zones_power(self, data: dict[str, float]) -> None:
        self.zones_power = json.dumps(data)

    def get_zones_hr(self) -> dict[str, float] | None:
        return json.loads(self.zones_hr) if self.zones_hr else None

    def set_zones_hr(self, data: dict[str, float]) -> None:
        self.zones_hr = json.dumps(data)

    def get_samples(self) -> list[dict] | None:
        return json.loads(self.samples) if self.samples else None

    def set_samples(self, data: list[dict]) -> None:
        self.samples = json.dumps(data)

    def get_mmp(self) -> dict[str, int] | None:
        return json.loads(self.mmp) if self.mmp else None

    def set_mmp(self, data: dict[str, int]) -> None:
        self.mmp = json.dumps(data)

    def get_climbs(self) -> list[dict] | None:
        return json.loads(self.climbs) if self.climbs else None

    def set_climbs(self, data: list[dict]) -> None:
        self.climbs = json.dumps(data)

    @property
    def display_name(self) -> str:
        """Nombre para mostrar: custom > fileName > fallback."""
        return (self.custom_name or "").strip() or self.file_name or "Sin nombre"


# ---------------------------------------------------------------------------
# DurabilityTest — tests empíricos de durabilidad (DRI)
# ---------------------------------------------------------------------------
class DurabilityTest(Base):
    __tablename__ = "durability_test"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tested_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    kj_consumed: Mapped[float] = mapped_column(Float)             # kJ acumulados antes del test
    power_3min: Mapped[int] = mapped_column(Integer)              # watts test 3 min
    power_12min: Mapped[int] = mapped_column(Integer)             # watts test 12 min

    cp_fatigued: Mapped[float] = mapped_column(Float)             # CP fatigado calculado
    w_prime_fatigued: Mapped[float] = mapped_column(Float)        # W' fatigado (J)
    cp_fresh: Mapped[float] = mapped_column(Float)                # CP fresco de referencia
    w_prime_fresh: Mapped[float] = mapped_column(Float)           # W' fresco de referencia (J)

    dri_percent: Mapped[float] = mapped_column(Float)             # DRI %
    classification: Mapped[str] = mapped_column(String(20))       # excellent|good|improvable|limiting
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_durability_tested", "tested_at"),
    )


# ---------------------------------------------------------------------------
# HealthMetric — métricas de salud diarias
# ---------------------------------------------------------------------------
class HealthMetric(Base):
    __tablename__ = "health_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(DateTime)              # fecha del registro

    # Composición corporal
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    subcutaneous_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cardiovascular
    resting_hr: Mapped[int | None] = mapped_column(Integer, nullable=True)     # ppm
    hrv: Mapped[float | None] = mapped_column(Float, nullable=True)            # ms (RMSSD)

    # Readiness (normalizado 1-10)
    readiness: Mapped[float | None] = mapped_column(Float, nullable=True)
    readiness_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Fuentes: "manual", "garmin", "whoop", "oura", "coros", "ehrv"

    # Presión arterial
    bp_systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)    # mmHg
    bp_diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)   # mmHg

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_health_date", "date"),
    )