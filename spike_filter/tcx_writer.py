"""Reescritura de archivos TCX con potencia corregida.

Estrategia: parsear el XML, localizar todos los <Watts> dentro de
Extensions/TPX y reemplazar valores según el mapa de correcciones.
Se mantiene intacto todo lo demás (GPS, HR, cadencia, laps, etc.).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Union
from copy import deepcopy

from lxml import etree

# Namespaces TCX
_NS = {
    "tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
    "ext": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
}
_NS_EXT = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"


def rewrite_tcx(
    source: Union[str, Path, bytes],
    corrections: Dict[int, float],
    output_path: Optional[Union[str, Path]] = None,
) -> bytes:
    """Reescribe un archivo TCX aplicando correcciones de potencia.

    Args:
        source: Ruta, bytes o string del TCX original.
        corrections: Mapa {indice_trackpoint: nuevo_valor_watts}.
        output_path: Si se proporciona, guarda el resultado ahí.

    Returns:
        bytes del TCX corregido.
    """
    # Parsear
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    else:
        raw = source

    # Preservar declaración XML original
    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(raw, parser)

    # Encontrar Activity
    activity = root.find(".//tcx:Activity", _NS)
    if activity is None:
        activity = root.find(".//Activity")
    if activity is None:
        raise ValueError("TCX sin actividad")

    # Recorrer trackpoints en orden y mapear al índice secuencial
    tp_idx = 0
    for lap in activity.findall(".//tcx:Lap", _NS) or activity.findall(".//Lap"):
        tracks = lap.findall("tcx:Track", _NS) or lap.findall("Track")
        for track in tracks:
            tps = track.findall("tcx:Trackpoint", _NS) or track.findall("Trackpoint")
            for tp in tps:
                if tp_idx in corrections:
                    _set_watts(tp, corrections[tp_idx])
                tp_idx += 1

    # Serializar
    result = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True,
    )

    if output_path:
        Path(output_path).write_bytes(result)

    return result


def _set_watts(tp_el: etree._Element, watts: float) -> None:
    """Establece el valor de Watts en un trackpoint TCX."""
    extensions = tp_el.find("tcx:Extensions", _NS)
    if extensions is None:
        extensions = tp_el.find("Extensions")
    if extensions is None:
        return  # Sin extensiones, no hay potencia que cambiar

    # Buscar TPX con namespace
    tpx = extensions.find("ext:TPX", _NS)
    if tpx is None:
        tpx = extensions.find(f"{{{_NS_EXT}}}TPX")
    if tpx is None:
        return

    # Buscar Watts
    watts_el = tpx.find("ext:Watts", _NS)
    if watts_el is None:
        watts_el = tpx.find(f"{{{_NS_EXT}}}Watts")
    if watts_el is None:
        return

    watts_el.text = str(round(watts))
