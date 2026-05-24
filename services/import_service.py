"""Servicio de importación de actividades.

Flujo: archivo → parser → cálculos (NP, TSS, zonas, MMP) → DB.
Equivalente a processAndStoreActivity de la web.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import Activity, ProcessedFile
from parsers import parse_activity_file, sha256_file, ParsedActivity, TrackPoint
from calc.power import calculate_power_metrics
from calc.zones import bucket_series, POWER_ZONES, HR_ZONES
from calc.mmp import compute_mmp, sanitize_power_series
from calc.ftp_estimator import estimate_ftp_from_power


@dataclass
class ImportResult:
    """Resultado de importar un archivo."""
    status: str          # 'created' | 'duplicate' | 'error'
    file_name: str
    message: str
    activity_id: Optional[int] = None


def _downsample_trackpoints(tps: List[TrackPoint], interval: int = 5) -> list[dict]:
    """Reduce trackpoints a samples cada N segundos para almacenar en DB."""
    if not tps:
        return []
    samples = []
    last_t = -interval
    for tp in tps:
        if tp.t - last_t >= interval:
            samples.append({
                "t": round(tp.t, 1),
                "p": round(tp.power) if tp.power is not None else None,
                "hr": round(tp.hr) if tp.hr is not None else None,
                "c": round(tp.cadence) if tp.cadence is not None else None,
                "s": round(tp.speed, 2) if tp.speed is not None else None,
                "alt": round(tp.altitude, 1) if tp.altitude is not None else None,
                "lat": round(tp.lat, 6) if tp.lat is not None else None,
                "lng": round(tp.lng, 6) if tp.lng is not None else None,
            })
            last_t = tp.t
    # Asegurarse de incluir el último punto
    if tps and (not samples or samples[-1]["t"] != round(tps[-1].t, 1)):
        tp = tps[-1]
        samples.append({
            "t": round(tp.t, 1),
            "p": round(tp.power) if tp.power is not None else None,
            "hr": round(tp.hr) if tp.hr is not None else None,
            "c": round(tp.cadence) if tp.cadence is not None else None,
            "s": round(tp.speed, 2) if tp.speed is not None else None,
            "alt": round(tp.altitude, 1) if tp.altitude is not None else None,
            "lat": round(tp.lat, 6) if tp.lat is not None else None,
            "lng": round(tp.lng, 6) if tp.lng is not None else None,
        })
    return samples


def _extract_power_series(tps: List[TrackPoint]) -> List[Optional[float]]:
    """Extrae serie de potencia 1 Hz."""
    if not tps:
        return []
    duration = int(tps[-1].t) + 1
    series: List[Optional[float]] = [None] * duration
    for tp in tps:
        idx = int(tp.t)
        if 0 <= idx < duration:
            series[idx] = tp.power
    # Forward fill
    last = None
    for i in range(duration):
        if series[i] is not None:
            last = series[i]
        elif last is not None:
            series[i] = last
    return series


def _extract_hr_series(tps: List[TrackPoint]) -> List[Optional[float]]:
    """Extrae serie de FC."""
    if not tps:
        return []
    duration = int(tps[-1].t) + 1
    series: List[Optional[float]] = [None] * duration
    for tp in tps:
        idx = int(tp.t)
        if 0 <= idx < duration:
            series[idx] = tp.hr
    last = None
    for i in range(duration):
        if series[i] is not None:
            last = series[i]
        elif last is not None:
            series[i] = last
    return series


def import_activity_file(
    file_path: str | Path,
    ftp: int,
    hr_max: int = 185,
    hr_lthr: int | None = None,
    weight_kg: float = 70.0,
) -> ImportResult:
    """Importa un archivo de actividad: parsea, calcula métricas, guarda en DB.

    Args:
        file_path: Ruta al archivo .fit o .tcx
        ftp: FTP actual del atleta (watts)
        hr_max: FC máxima del atleta (ppm)
        hr_lthr: FC de umbral / FCL (ppm) — referencia para zonas HR Friel
        weight_kg: Peso del atleta en kg

    Returns:
        ImportResult con el estado de la importación.
    """
    file_path = Path(file_path)
    file_name = file_path.name

    try:
        # 1. Verificar duplicado por hash
        file_bytes = file_path.read_bytes()
        file_hash = sha256_file(file_bytes)

        session = get_session()
        try:
            existing = session.query(ProcessedFile).filter_by(file_hash=file_hash).first()
            if existing:
                return ImportResult(
                    status="duplicate",
                    file_name=file_name,
                    message=f"Archivo ya importado: {existing.original_name}",
                )

            # 2. Parsear
            print(f"[IMPORT] Parseando {file_name} ({len(file_bytes)} bytes)...")
            parsed, file_type = parse_activity_file(file_bytes, file_name)
            print(f"[IMPORT] Parseado OK: tipo={file_type}, "
                  f"trackpoints={len(parsed.trackpoints)}, "
                  f"duration={parsed.duration_sec}s, "
                  f"has_power={parsed.has_power}")

            # 2b. Deduplicación por fecha + duración (detecta Strava ↔ local)
            if parsed.started_at and parsed.duration_sec:
                from datetime import timedelta
                t_start = parsed.started_at - timedelta(minutes=5)
                t_end = parsed.started_at + timedelta(minutes=5)
                dur_lo = int(parsed.duration_sec * 0.9)
                dur_hi = int(parsed.duration_sec * 1.1)
                dup = session.query(Activity.id, Activity.file_name).filter(
                    Activity.started_at.between(t_start, t_end),
                    Activity.duration_sec.between(dur_lo, dur_hi),
                ).first()
                if dup:
                    print(f"[IMPORT] Duplicado por fecha+duración: {file_name} ↔ {dup.file_name}")
                    return ImportResult(
                        status="duplicate",
                        file_name=file_name,
                        message=f"Actividad ya existente (coincide fecha y duración): {dup.file_name}",
                    )

            # 3. Extraer series
            power_series = _extract_power_series(parsed.trackpoints)
            hr_series = _extract_hr_series(parsed.trackpoints)

            # 3b. Sanitizado de potencia — protección contra spikes de sensor
            from db.models import PowerTestSet
            last_test = (
                session.query(PowerTestSet)
                .order_by(PowerTestSet.tested_at.desc())
                .first()
            )
            if last_test and last_test.cp and last_test.cp > 0:
                max_valid_power = last_test.cp * 3
            else:
                max_valid_power = max(ftp * 5, 1500)

            sr = sanitize_power_series(power_series, max_valid_power)
            clean_power: list = list(sr.values)
            if sr.outliers > 0:
                print(f"[Sanitize] Descartadas {sr.outliers} muestras "
                      f"de potencia > {max_valid_power} W en {file_name}")

            # 4. Métricas de potencia (sobre serie limpia)
            pm = calculate_power_metrics(clean_power, ftp=ftp, duration_sec=parsed.duration_sec)

            # 5. Zonas (sobre serie limpia)
            zones_power = bucket_series(clean_power, ftp, POWER_ZONES) if parsed.has_power else None
            # Zonas HR: referencia FCL (hr_lthr) si está definida, si no hr_max
            hr_ref = hr_lthr if hr_lthr and hr_lthr > 0 else hr_max
            zones_hr = bucket_series(hr_series, hr_ref, HR_ZONES) if parsed.has_hr else None

            # 6. MMP (con maxValidPower para filtrar outliers)
            mmp_data = compute_mmp(power_series, max_valid_power=max_valid_power) if parsed.has_power else None

            # 7. Estadísticas básicas de FC
            valid_hr = [v for v in hr_series if v is not None and v > 0]
            avg_hr = round(sum(valid_hr) / len(valid_hr)) if valid_hr else None
            max_hr_val = round(max(valid_hr)) if valid_hr else None

            # 8. Estadísticas de velocidad/cadencia
            speeds = [tp.speed for tp in parsed.trackpoints if tp.speed is not None and tp.speed > 0]
            avg_speed_ms = sum(speeds) / len(speeds) if speeds else None
            max_speed_ms = max(speeds) if speeds else None
            cadences = [tp.cadence for tp in parsed.trackpoints if tp.cadence is not None and tp.cadence > 0]
            avg_cad = round(sum(cadences) / len(cadences)) if cadences else None
            max_cad = round(max(cadences)) if cadences else None

            # 9. Potencia máxima
            valid_power = [v for v in power_series if v is not None and v > 0]
            max_power = round(max(valid_power)) if valid_power else None

            # 10. FTP suggestion (sobre serie limpia ya sanitizada)
            ftp_suggestion = None
            ftp_suggestion_duration = None
            if parsed.has_power and len(clean_power) >= 300:
                estimate = estimate_ftp_from_power(clean_power, ftp)
                if estimate:
                    ftp_suggestion = estimate.estimated_ftp
                    ftp_suggestion_duration = estimate.duration_sec

            # 11. Downsample para almacenar
            samples = _downsample_trackpoints(parsed.trackpoints)

            # 12. Calcular elevación (del parser o de trackpoints)
            elev_gain = parsed.elevation_gain_m

            # 13. Moving time
            # FIT: usamos duration_sec del parser (= total_timer_time del dispositivo,
            #       ya descuenta pausas automáticas)
            # TCX y otros: estimamos contando segundos con speed>0.28m/s ó power>0
            if file_type == "fit":
                moving_time = parsed.duration_sec
            else:
                moving_secs = sum(
                    1 for tp in parsed.trackpoints
                    if (tp.speed is not None and tp.speed > 0.28)
                    or (tp.power is not None and tp.power > 0)
                )
                moving_time = moving_secs if moving_secs > 0 else None
            # Fallback: si sigue siendo 0/None, usar duración total
            if not moving_time:
                moving_time = parsed.duration_sec

            # 14. Balance de pedaleo (izq/der) — solo FIT con potencímetro compatible
            avg_left_balance = None
            lb_values = [
                tp.left_balance for tp in parsed.trackpoints
                if tp.left_balance is not None
            ]
            if len(lb_values) >= 10:
                avg_left_balance = round(sum(lb_values) / len(lb_values), 1)
                print(f"[IMPORT] Balance L/R: {avg_left_balance}% izq ({len(lb_values)} muestras)")

            # 15. Crear actividad en DB (incluye avg_left_balance)
            activity = Activity(
                started_at=parsed.started_at,
                sport=parsed.sport,
                source=file_type,
                file_name=file_name,
                duration_sec=parsed.duration_sec,
                moving_time_sec=moving_time,
                distance_km=parsed.distance_km,
                elevation_gain_m=elev_gain,
                calories=parsed.calories,
                avg_speed_kmh=round(avg_speed_ms * 3.6, 1) if avg_speed_ms else None,
                max_speed_kmh=round(max_speed_ms * 3.6, 1) if max_speed_ms else None,
                avg_cadence=avg_cad,
                max_cadence=max_cad,
                avg_hr=avg_hr,
                max_hr=max_hr_val,
                avg_power=pm.avg_power,
                max_power=max_power,
                normalized_power=pm.np,
                intensity_factor=pm.intensity_factor,
                tss=pm.tss,
                work_kj=pm.work_kj,
                ftp_used=ftp,
                ftp_suggestion=ftp_suggestion,
                ftp_suggestion_duration=ftp_suggestion_duration,
                avg_left_balance=avg_left_balance,
            )

            # JSON fields
            if zones_power:
                activity.set_zones_power(zones_power)
            if zones_hr:
                activity.set_zones_hr(zones_hr)
            if samples:
                activity.set_samples(samples)
            if mmp_data:
                activity.set_mmp(mmp_data)

            session.add(activity)
            session.flush()  # para obtener activity.id

            # 15. Registrar archivo procesado
            pf = ProcessedFile(
                file_hash=file_hash,
                original_name=file_name,
                file_size=len(file_bytes),
                file_type=file_type,
                activity_id=activity.id,
            )
            session.add(pf)
            session.commit()

            return ImportResult(
                status="created",
                file_name=file_name,
                message=f"Importado correctamente",
                activity_id=activity.id,
            )

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    except ValueError as e:
        print(f"[IMPORT] ValueError en {file_name}: {e}")
        return ImportResult(status="error", file_name=file_name, message=str(e))
    except Exception as e:
        import traceback
        print(f"[IMPORT] Error inesperado en {file_name}: {e}")
        traceback.print_exc()
        return ImportResult(status="error", file_name=file_name, message=f"Error inesperado: {e}")


def import_multiple_files(
    file_paths: List[str | Path],
    ftp: int,
    hr_max: int = 185,
    hr_lthr: int | None = None,
    weight_kg: float = 70.0,
) -> List[ImportResult]:
    """Importa múltiples archivos secuencialmente."""
    results = []
    for fp in file_paths:
        result = import_activity_file(fp, ftp=ftp, hr_max=hr_max, hr_lthr=hr_lthr, weight_kg=weight_kg)
        results.append(result)
    return results


def reimport_activity_samples(activity_id: int, file_path: str | Path) -> Tuple[bool, str]:
    """Re-parsea un archivo y actualiza SOLO los samples (con GPS) de una actividad existente.

    Útil para actividades importadas antes de incluir lat/lng en el downsampling.
    No modifica métricas, zonas ni MMP — solo el JSON de samples.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return False, f"Archivo no encontrado: {file_path}"

    try:
        file_bytes = file_path.read_bytes()
        parsed, _ = parse_activity_file(file_bytes, file_path.name)
    except Exception as e:
        return False, f"Error al parsear: {e}"

    if not parsed or not parsed.trackpoints:
        return False, "No se encontraron datos en el archivo."

    samples = _downsample_trackpoints(parsed.trackpoints)
    has_gps = any(s.get("lat") is not None for s in samples)
    if not has_gps:
        return False, "El archivo no contiene datos GPS."

    session = get_session()
    try:
        act = session.get(Activity, activity_id)
        if not act:
            return False, f"Actividad {activity_id} no encontrada."
        act.set_samples(samples)
        session.commit()
        n_gps = sum(1 for s in samples if s.get("lat") is not None)
        return True, f"Samples actualizados: {len(samples)} puntos, {n_gps} con GPS."
    except Exception as e:
        session.rollback()
        return False, f"Error al guardar: {e}"
    finally:
        session.close()
