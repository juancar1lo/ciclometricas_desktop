"""
Gestor de perfiles de atleta.
Cada atleta tiene su propia carpeta con:
  - ciclometricas.db   (SQLite)
  - config.json        (FTP, peso, hrMax, Strava tokens)

Estructura en disco:
  ~/.ciclometricas/
  ├── atletas.json       <- {"last_open": "Carlos", "profiles": ["Carlos", "María"]}
  ├── Carlos/
  │   ├── ciclometricas.db
  │   └── config.json
  └── María/
      ├── ciclometricas.db
      └── config.json
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .engine import init_db

# Directorio raíz de datos
DATA_DIR = Path.home() / ".ciclometricas"
INDEX_FILE = DATA_DIR / "atletas.json"
DB_NAME = "ciclometricas.db"
CONFIG_NAME = "config.json"

DEFAULT_CONFIG = {
    "ftp": 200,
    "weight_kg": 70.0,
    "hr_max": 185,
    "hr_lthr": 165,
    "zone_source": "ftp",
    "strava": None,
}


@dataclass
class AthleteProfile:
    """Representación de un perfil de atleta."""
    name: str
    path: Path
    config: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.path / DB_NAME

    @property
    def config_path(self) -> Path:
        return self.path / CONFIG_NAME


class AthleteManager:
    """Gestiona la creación, listado y selección de perfiles de atleta."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()
        self._active: AthleteProfile | None = None

    # --- Índice ---

    def _load_index(self) -> dict:
        if INDEX_FILE.exists():
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"last_open": None, "profiles": []}

    def _save_index(self) -> None:
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2, ensure_ascii=False)

    # --- Listado ---

    def list_profiles(self) -> list[str]:
        """Devuelve los nombres de todos los perfiles existentes."""
        return list(self._index.get("profiles", []))

    @property
    def last_open(self) -> str | None:
        return self._index.get("last_open")

    @property
    def active(self) -> AthleteProfile | None:
        return self._active

    # --- CRUD ---

    def create_profile(
        self,
        name: str,
        ftp: int = 200,
        weight_kg: float = 70.0,
        hr_max: int = 185,
        hr_lthr: int = 165,
    ) -> AthleteProfile:
        """Crea un nuevo perfil de atleta."""
        name = name.strip()
        if not name:
            raise ValueError("El nombre no puede estar vacío.")

        if name in self._index["profiles"]:
            raise ValueError(f"Ya existe un perfil con el nombre '{name}'.")

        profile_dir = DATA_DIR / name
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Config inicial
        config = {
            **DEFAULT_CONFIG,
            "ftp": ftp,
            "weight_kg": weight_kg,
            "hr_max": hr_max,
            "hr_lthr": hr_lthr,
        }
        config_path = profile_dir / CONFIG_NAME
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Crear DB vacía con tablas
        init_db(profile_dir / DB_NAME)

        # Registrar en índice
        self._index["profiles"].append(name)
        self._index["profiles"].sort()
        self._save_index()

        profile = AthleteProfile(name=name, path=profile_dir, config=config)
        return profile

    def open_profile(self, name: str) -> AthleteProfile:
        """Abre un perfil existente e inicializa su DB."""
        if name not in self._index["profiles"]:
            raise ValueError(f"No existe el perfil '{name}'.")

        profile_dir = DATA_DIR / name
        config_path = profile_dir / CONFIG_NAME

        config = DEFAULT_CONFIG.copy()
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config.update(json.load(f))

        # Inicializar motor de DB
        init_db(profile_dir / DB_NAME)

        # Actualizar índice
        self._index["last_open"] = name
        self._save_index()

        self._active = AthleteProfile(name=name, path=profile_dir, config=config)
        return self._active

    def rename_profile(self, old_name: str, new_name: str) -> None:
        """Renombra un perfil."""
        new_name = new_name.strip()
        if not new_name:
            raise ValueError("El nombre no puede estar vacío.")
        if old_name not in self._index["profiles"]:
            raise ValueError(f"No existe el perfil '{old_name}'.")
        if new_name in self._index["profiles"]:
            raise ValueError(f"Ya existe un perfil '{new_name}'.")

        old_dir = DATA_DIR / old_name
        new_dir = DATA_DIR / new_name
        old_dir.rename(new_dir)

        idx = self._index["profiles"].index(old_name)
        self._index["profiles"][idx] = new_name
        self._index["profiles"].sort()
        if self._index["last_open"] == old_name:
            self._index["last_open"] = new_name
        self._save_index()

        if self._active and self._active.name == old_name:
            self._active.name = new_name
            self._active.path = new_dir

    def delete_profile(self, name: str) -> None:
        """Elimina un perfil y todos sus datos."""
        if name not in self._index["profiles"]:
            raise ValueError(f"No existe el perfil '{name}'.")

        # Cerrar conexión SQLite antes de borrar (necesario en Windows,
        # donde los archivos .db quedan bloqueados si el motor sigue abierto)
        from .engine import dispose_engine
        dispose_engine()

        profile_dir = DATA_DIR / name
        if profile_dir.exists():
            shutil.rmtree(profile_dir)

        self._index["profiles"].remove(name)
        if self._index["last_open"] == name:
            self._index["last_open"] = (
                self._index["profiles"][0] if self._index["profiles"] else None
            )
        self._save_index()

        if self._active and self._active.name == name:
            self._active = None

    def save_config(self, profile: AthleteProfile | None = None) -> None:
        """Guarda la configuración del perfil activo (o el indicado) a disco."""
        p = profile or self._active
        if p is None:
            raise RuntimeError("No hay perfil activo.")
        with open(p.config_path, "w", encoding="utf-8") as f:
            json.dump(p.config, f, indent=2, ensure_ascii=False)
