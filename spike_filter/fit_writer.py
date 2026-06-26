"""Reescritura de archivos FIT con potencia corregida.

Estrategia principal: parcheo binario in-place con fitdecode.
Lee el FIT original, localiza los campos power en los Record messages,
parchea los bytes uint16 LE directamente, y recalcula el CRC.

Esta técnica preserva TODOS los mensajes originales (lap, session,
event, device_info, etc.) sin necesidad de reconstruir el archivo.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


def rewrite_fit(
    source: Union[str, Path, bytes],
    corrections: Dict[int, float],
    output_path: Optional[Union[str, Path]] = None,
) -> bytes:
    """Reescribe un archivo FIT aplicando correcciones de potencia.

    Args:
        source: Ruta o bytes del FIT original.
        corrections: Mapa {indice_record: nuevo_valor_watts}.
        output_path: Si se proporciona, guarda el resultado ahí.

    Returns:
        bytes del FIT corregido.
    """
    raw = _read_source(source)

    if not corrections:
        if output_path:
            Path(output_path).write_bytes(raw)
        return raw

    result = _binary_patch_fit(raw, corrections)

    if output_path:
        Path(output_path).write_bytes(result)
    return result


def _read_source(source: Union[str, Path, bytes]) -> bytes:
    if isinstance(source, bytes):
        return source
    return Path(source).read_bytes()


# ---- Parcheo binario con fitdecode (método principal) --------------------

def _binary_patch_fit(
    raw: bytes,
    corrections: Dict[int, float],
) -> bytes:
    """Parchea los campos power directamente en el binario FIT.

    1. Parsea con fitdecode para localizar cada record message y su
       campo power (field def_num = 7, tipo uint16).
    2. Calcula el offset exacto del campo en el archivo raw.
    3. Escribe el nuevo valor uint16 LE en esa posición.
    4. Recalcula el CRC del data section.
    """
    import fitdecode

    data = bytearray(raw)

    # --- Paso 1: encontrar las posiciones a parchear ---
    patches: List[Tuple[int, int]] = []  # (byte_offset, new_uint16_value)

    # Rastrear las definiciones activas por local_mesg_num
    # Cada definición nos dice qué campos hay y en qué orden (para calcular offset)
    active_defs: Dict[int, List[Tuple[int, int, int]]] = {}  # local_num -> [(def_num, size, offset_in_payload)]

    record_idx = 0

    with fitdecode.FitReader(raw, keep_raw_chunks=True) as reader:
        for frame in reader:
            if isinstance(frame, fitdecode.records.FitDefinitionMessage):
                # Guardar layout de campos para este local_mesg_num
                fields_layout: List[Tuple[int, int, int]] = []
                payload_offset = 0
                for fdef in frame.field_defs:
                    fields_layout.append((fdef.def_num, fdef.size, payload_offset))
                    payload_offset += fdef.size
                # Dev fields van después
                for ddef in (getattr(frame, 'dev_field_defs', None) or []):
                    payload_offset += ddef.size
                active_defs[frame.local_mesg_num] = fields_layout

            elif isinstance(frame, fitdecode.records.FitDataMessage):
                mesg_num = frame.mesg_type.mesg_num if frame.mesg_type else (frame.global_mesg_num or -1)
                if mesg_num == 20:  # Record message
                    if record_idx in corrections:
                        # Buscar campo power (def_num=7) en el layout activo
                        local_num = frame.local_mesg_num
                        layout = active_defs.get(local_num, [])

                        for def_num, fsize, foffset in layout:
                            if def_num == 7 and fsize == 2:  # power = uint16
                                # chunk.index = inicio del record en el stream
                                # El header del record es 1 byte
                                # Luego van los campos en orden del layout
                                byte_pos = frame.chunk.offset + 1 + foffset
                                new_val = max(0, min(65534, round(corrections[record_idx])))
                                patches.append((byte_pos, new_val))
                                break
                    record_idx += 1

    if not patches:
        return bytes(data)

    # --- Paso 2: aplicar los parches ---
    for byte_pos, new_val in patches:
        struct.pack_into('<H', data, byte_pos, new_val)

    # --- Paso 3: recalcular CRC ---
    _fix_fit_crc(data)

    return bytes(data)


def _fix_fit_crc(data: bytearray) -> None:
    """Recalcula el CRC de un archivo FIT in-place.

    Estructura FIT:
      - Header (12 o 14 bytes)
        - byte 0: header_size
        - bytes 4-7: data_size (uint32 LE)
        - Si header_size == 14: bytes 12-13 = header CRC
      - Data (data_size bytes)
      - Footer: 2 bytes CRC del data section
    """
    if len(data) < 14:
        return

    header_size = data[0]
    data_size = struct.unpack_from('<I', data, 4)[0]

    # CRC del header (solo existe si header es de 14 bytes)
    if header_size == 14 and len(data) >= 14:
        header_crc = _crc16(data[:12])
        struct.pack_into('<H', data, 12, header_crc)

    # CRC del data section (2 bytes al final del archivo)
    data_start = header_size
    data_end = data_start + data_size
    if data_end + 2 <= len(data):
        # El CRC cubre desde header (inclusive) hasta final de data
        data_crc = _crc16(data[:data_end])
        struct.pack_into('<H', data, data_end, data_crc)


def _crc16(data: Union[bytes, bytearray]) -> int:
    """Calcula CRC-16 según la especificación FIT (CRC-CCITT)."""
    crc_table = [
        0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400,
    ]
    crc = 0
    for byte in data:
        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[byte & 0xF]

        tmp = crc_table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ crc_table[(byte >> 4) & 0xF]
    return crc
