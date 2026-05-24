"""Parsers de archivos de actividad ciclista (.fit, .tcx).

Port fiel de lib/parsers/index.ts.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Tuple, Union

from .fit_parser import parse_fit
from .tcx_parser import parse_tcx
from .types import ParsedActivity, TrackPoint


def parse_activity_file(
    source: Union[str, Path, bytes],
    file_name: str = "",
) -> Tuple[ParsedActivity, str]:
    """Parsea un archivo de actividad y devuelve (ParsedActivity, file_type).

    Args:
        source: Ruta al archivo, bytes, o string XML.
        file_name: Nombre del archivo para detectar tipo por extensión.

    Returns:
        Tupla (ParsedActivity, 'fit' | 'tcx').
    """
    lower = file_name.lower() if file_name else ""

    # Si es una ruta, usar el nombre del archivo si no se proporcionó
    if isinstance(source, (str, Path)) and not lower:
        lower = str(source).lower()

    if lower.endswith(".tcx") or lower.endswith(".xml"):
        return parse_tcx(source), "tcx"

    if lower.endswith(".fit"):
        return parse_fit(source), "fit"

    # Sniff por contenido
    if isinstance(source, bytes):
        header = source[:500].decode("utf-8", errors="ignore")
    elif isinstance(source, str) and source.strip().startswith("<"):
        header = source[:500]
    elif isinstance(source, (str, Path)):
        with open(str(source), "rb") as f:
            header = f.read(500).decode("utf-8", errors="ignore")
    else:
        header = ""

    if "TrainingCenterDatabase" in header:
        return parse_tcx(source), "tcx"

    raise ValueError("Formato no soportado: usa .fit o .tcx")


def sha256_file(source: Union[str, Path, bytes]) -> str:
    """Calcula SHA-256 de un archivo o bytes."""
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    with open(str(source), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


__all__ = [
    "parse_activity_file",
    "parse_fit",
    "parse_tcx",
    "sha256_file",
    "ParsedActivity",
    "TrackPoint",
]
