"""
Gestión de motor SQLAlchemy y sesiones.
Cada perfil de atleta tiene su propia base de datos SQLite.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

# Referencia global al motor activo (cambia al cambiar de perfil)
_current_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    """Activa WAL y foreign keys para mejor rendimiento concurrente."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(db_path: Path | None = None) -> Engine:
    """Devuelve el motor actual o crea uno nuevo si se pasa db_path."""
    global _current_engine, _SessionFactory

    if db_path is not None:
        if _current_engine is not None:
            _current_engine.dispose()
        _current_engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            pool_pre_ping=True,
        )
        _SessionFactory = sessionmaker(bind=_current_engine)

    if _current_engine is None:
        raise RuntimeError("No se ha inicializado la base de datos. Selecciona un perfil primero.")

    return _current_engine


def dispose_engine() -> None:
    """Cierra y libera el motor actual (necesario en Windows antes de borrar el .db)."""
    global _current_engine, _SessionFactory
    if _current_engine is not None:
        _current_engine.dispose()
        _current_engine = None
        _SessionFactory = None


def get_session() -> Session:
    """Crea una nueva sesión con el motor activo."""
    if _SessionFactory is None:
        raise RuntimeError("No se ha inicializado la base de datos. Selecciona un perfil primero.")
    return _SessionFactory()


def _run_migrations(engine: Engine) -> None:
    """Aplica migraciones incrementales para columnas nuevas en tablas existentes."""
    insp = inspect(engine)
    # Migración: añadir hr_lthr a profile_snapshot si falta
    if insp.has_table("profile_snapshot"):
        cols = {c["name"] for c in insp.get_columns("profile_snapshot")}
        if "hr_lthr" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE profile_snapshot ADD COLUMN hr_lthr INTEGER"
                ))
    # Migración: añadir moving_time_sec y avg_left_balance a activity si faltan
    if insp.has_table("activity"):
        cols = {c["name"] for c in insp.get_columns("activity")}
        if "moving_time_sec" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE activity ADD COLUMN moving_time_sec INTEGER"
                ))
        if "avg_left_balance" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE activity ADD COLUMN avg_left_balance REAL"
                ))
        # Migración: columnas para sesiones manuales
        if "activity_type" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE activity ADD COLUMN activity_type VARCHAR(30)"
                ))
        if "is_manual" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE activity ADD COLUMN is_manual BOOLEAN DEFAULT 0"
                ))
        if "perceived_if" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE activity ADD COLUMN perceived_if REAL"
                ))


def init_db(db_path: Path) -> Engine:
    """
    Inicializa (o abre) la base de datos en db_path.
    Crea todas las tablas si no existen y aplica migraciones.
    """
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _run_migrations(engine)
    return engine
