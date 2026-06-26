"""spike_filter — Detección y corrección de picos aberrantes de potencia.

Módulo independiente para limpiar archivos FIT y TCX de artefactos
de potencia (reconexiones de potenciómetro, picos eléctricos, etc.).

Uso rápido:
    from spike_filter import clean_file
    result = clean_file("activity.fit", max_watts=2500)
    result.save("activity_clean.fit")
"""
from .pipeline import clean_file, CleanResult, SpikeDetail, ChannelSnapshot  # noqa: F401

__version__ = "1.0.0"
