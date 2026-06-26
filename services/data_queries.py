"""Funciones de consulta a la BD invocables por el AI Coach.

Cada función acepta parámetros simples (str/int/float) y devuelve un str
con el resultado formateado para inyectar en el contexto del LLM.

El LLM las invoca indirectamente escribiendo:
  [QUERY: nombre_funcion(arg1, arg2, ...)]
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import desc, func

from db.engine import get_session
from db.models import (
    Activity, DurabilityTest, HealthMetric, PowerTestSet, ProfileSnapshot,
)
from calc.fitness import build_fitness_series

log = logging.getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────────────────
def _parse_date(s: str) -> date:
    """Acepta YYYY-MM-DD o DD/MM/YYYY."""
    s = s.strip().strip('"').strip("'")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {s}")


def _fmt_dur(secs: float) -> str:
    h, rem = divmod(int(secs), 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}min"


def _activity_line(a: Activity) -> str:
    d = a.started_at.strftime("%d/%m/%Y") if a.started_at else "?"
    name = a.display_name
    dur = _fmt_dur(a.duration_sec) if a.duration_sec else "?"
    parts = [f"{d} · {name} · {dur}"]
    if a.distance_km:
        parts.append(f"{round(a.distance_km, 1)}km")
    if a.tss:
        parts.append(f"TSS={round(a.tss)}")
    if a.normalized_power:
        parts.append(f"NP={round(a.normalized_power)}W")
    if a.avg_hr:
        parts.append(f"FC={a.avg_hr}ppm")
    if a.elevation_gain_m:
        parts.append(f"+{round(a.elevation_gain_m)}m")
    return " · ".join(parts)


# ── funciones de consulta ─────────────────────────────────────────────────

def buscar_actividades(desde: str, hasta: str, tipo: str = "") -> str:
    """Busca actividades entre dos fechas.

    Args:
        desde: Fecha inicio (YYYY-MM-DD).
        hasta: Fecha fin (YYYY-MM-DD).
        tipo: Filtro opcional: 'cycling', 'strength', 'walk', 'all'. Por defecto todas.
    """
    try:
        d_from = _parse_date(desde)
        d_to = _parse_date(hasta)
    except ValueError as e:
        return f"Error: {e}"

    session = get_session()
    q = session.query(Activity).filter(
        Activity.started_at >= datetime.combine(d_from, datetime.min.time()),
        Activity.started_at <= datetime.combine(d_to, datetime.max.time()),
    )
    tipo = tipo.strip().strip('"').strip("'").lower()
    if tipo and tipo != "all" and tipo != "todas":
        q = q.filter(Activity.activity_type == tipo)

    acts = q.order_by(desc(Activity.started_at)).limit(30).all()
    session.close()

    if not acts:
        return f"No se encontraron actividades entre {d_from} y {d_to}."

    lines = [f"Actividades encontradas ({len(acts)}):"]
    for a in acts:
        lines.append(f"- {_activity_line(a)}")

    # Resumen
    total_tss = sum(a.tss or 0 for a in acts)
    total_hrs = sum((a.duration_sec or 0) for a in acts) / 3600
    total_km = sum(a.distance_km or 0 for a in acts)
    lines.append(f"\nResumen: {len(acts)} sesiones, {round(total_hrs, 1)}h, "
                 f"TSS total={round(total_tss)}, {round(total_km)}km")
    return "\n".join(lines)


def mejor_mmp(duracion_seg: str, desde: str = "", hasta: str = "") -> str:
    """Busca la mejor potencia máxima para una duración específica.

    Args:
        duracion_seg: Duración en segundos (ej: 300 para 5 min).
        desde: Fecha inicio (opcional, YYYY-MM-DD). Por defecto últimos 365 días.
        hasta: Fecha fin (opcional, YYYY-MM-DD). Por defecto hoy.
    """
    try:
        dur = int(str(duracion_seg).strip().strip('"').strip("'"))
    except (ValueError, TypeError):
        return f"Error: duración no válida: {duracion_seg}"

    today = date.today()
    try:
        d_from = _parse_date(desde) if desde.strip() else today - timedelta(days=365)
        d_to = _parse_date(hasta) if hasta.strip() else today
    except ValueError as e:
        return f"Error: {e}"

    session = get_session()
    acts = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(d_from, datetime.min.time()),
            Activity.started_at <= datetime.combine(d_to, datetime.max.time()),
            Activity.mmp.isnot(None),
        )
        .all()
    )
    session.close()

    best_watts = 0
    best_act = None
    for a in acts:
        mmp = a.get_mmp()
        if mmp:
            val = mmp.get(str(dur), 0)
            if val > best_watts:
                best_watts = val
                best_act = a

    dur_label = _fmt_dur(dur)
    if best_watts == 0:
        return f"No se encontró MMP a {dur_label} entre {d_from} y {d_to}."

    d_str = best_act.started_at.strftime("%d/%m/%Y") if best_act and best_act.started_at else "?"
    name = best_act.display_name if best_act else "?"
    result = f"Mejor potencia a {dur_label}: {best_watts} W (el {d_str}, en '{name}')"

    # Intentar añadir W/kg
    session = get_session()
    profile = session.query(ProfileSnapshot).order_by(desc(ProfileSnapshot.effective_at)).first()
    session.close()
    if profile and profile.weight_kg:
        wkg = round(best_watts / profile.weight_kg, 2)
        result += f" = {wkg} W/kg"

    return result


def resumen_periodo(desde: str, hasta: str) -> str:
    """Resumen estadístico de un periodo.

    Args:
        desde: Fecha inicio (YYYY-MM-DD).
        hasta: Fecha fin (YYYY-MM-DD).
    """
    try:
        d_from = _parse_date(desde)
        d_to = _parse_date(hasta)
    except ValueError as e:
        return f"Error: {e}"

    session = get_session()
    acts = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(d_from, datetime.min.time()),
            Activity.started_at <= datetime.combine(d_to, datetime.max.time()),
        )
        .all()
    )
    session.close()

    if not acts:
        return f"Sin actividades entre {d_from} y {d_to}."

    total_sessions = len(acts)
    total_hrs = sum((a.duration_sec or 0) for a in acts) / 3600
    total_tss = sum(a.tss or 0 for a in acts)
    total_km = sum(a.distance_km or 0 for a in acts)
    total_elev = sum(a.elevation_gain_m or 0 for a in acts)
    total_kj = sum(a.work_kj or 0 for a in acts)

    avg_tss = total_tss / total_sessions if total_sessions else 0
    avg_hrs = total_hrs / total_sessions if total_sessions else 0

    # NP medio ponderado
    np_pairs = [(a.duration_sec or 0, a.normalized_power or 0) for a in acts if a.normalized_power]
    avg_np = 0
    if np_pairs:
        total_dur = sum(d for d, _ in np_pairs)
        if total_dur:
            avg_np = sum(d * n for d, n in np_pairs) / total_dur

    lines = [
        f"Resumen del {d_from.strftime('%d/%m/%Y')} al {d_to.strftime('%d/%m/%Y')}:",
        f"- Sesiones: {total_sessions}",
        f"- Horas totales: {round(total_hrs, 1)}h (media {round(avg_hrs, 1)}h/sesión)",
        f"- TSS total: {round(total_tss)} (media {round(avg_tss)}/sesión)",
        f"- Distancia: {round(total_km)}km",
    ]
    if total_elev:
        lines.append(f"- Desnivel: +{round(total_elev)}m")
    if total_kj:
        lines.append(f"- Trabajo: {round(total_kj)} kJ")
    if avg_np:
        lines.append(f"- NP medio: {round(avg_np)} W")

    return "\n".join(lines)


def fitness_en_fecha(fecha: str) -> str:
    """Calcula CTL/ATL/TSB para una fecha específica.

    Args:
        fecha: Fecha a consultar (YYYY-MM-DD).
    """
    try:
        target = _parse_date(fecha)
    except ValueError as e:
        return f"Error: {e}"

    lookback = target - timedelta(days=90)
    session = get_session()
    activities = (
        session.query(Activity.started_at, Activity.tss)
        .filter(
            Activity.started_at >= datetime.combine(lookback, datetime.min.time()),
            Activity.started_at <= datetime.combine(target, datetime.max.time()),
            Activity.tss.isnot(None),
        )
        .all()
    )
    session.close()

    if not activities:
        return f"Sin datos de TSS para calcular fitness a fecha {target}."

    act_dicts = [{"started_at": a.started_at, "tss": a.tss} for a in activities]
    series = build_fitness_series(act_dicts, lookback, target)
    if not series:
        return f"No se pudo calcular fitness para {target}."

    last = series[-1]
    # Estado textual
    if last.tsb > 15:
        estado = "Fresco / Transición"
    elif last.tsb > 5:
        estado = "Fresco"
    elif last.tsb > -10:
        estado = "Óptimo para rendir"
    elif last.tsb > -30:
        estado = "Carga productiva"
    else:
        estado = "Alto riesgo sobreentrenamiento"

    return (
        f"Fitness a fecha {target.strftime('%d/%m/%Y')}:\n"
        f"- CTL (Fitness): {round(last.ctl, 1)}\n"
        f"- ATL (Fatiga): {round(last.atl, 1)}\n"
        f"- TSB (Forma): {round(last.tsb, 1)}\n"
        f"- Estado: {estado}"
    )


def tendencia_semanal(semanas: str = "4") -> str:
    """TSS/horas/km por semana de las últimas N semanas.

    Args:
        semanas: Número de semanas hacia atrás (por defecto 4).
    """
    try:
        n = int(str(semanas).strip().strip('"').strip("'"))
    except (ValueError, TypeError):
        n = 4
    n = max(1, min(n, 52))

    today = date.today()
    lookback = today - timedelta(days=n * 7)

    session = get_session()
    acts = (
        session.query(Activity)
        .filter(Activity.started_at >= datetime.combine(lookback, datetime.min.time()))
        .order_by(Activity.started_at)
        .all()
    )
    session.close()

    if not acts:
        return f"Sin actividades en las últimas {n} semanas."

    weekly: Dict[str, List[Activity]] = {}
    for a in acts:
        if a.started_at:
            iso = a.started_at.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
            weekly.setdefault(wk, []).append(a)

    lines = [f"Tendencia semanal (últimas {n} semanas):"]
    for wk_key in sorted(weekly.keys()):
        w_acts = weekly[wk_key]
        n_sess = len(w_acts)
        hrs = sum((a.duration_sec or 0) for a in w_acts) / 3600
        tss = sum(a.tss or 0 for a in w_acts)
        km = sum(a.distance_km or 0 for a in w_acts)
        lines.append(f"- {wk_key}: {n_sess} sesiones, {round(hrs, 1)}h, "
                     f"TSS={round(tss)}, {round(km)}km")

    return "\n".join(lines)


def zonas_periodo(desde: str, hasta: str) -> str:
    """Distribución de zonas de potencia y FC en un periodo.

    Args:
        desde: Fecha inicio (YYYY-MM-DD).
        hasta: Fecha fin (YYYY-MM-DD).
    """
    try:
        d_from = _parse_date(desde)
        d_to = _parse_date(hasta)
    except ValueError as e:
        return f"Error: {e}"

    session = get_session()
    acts = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(d_from, datetime.min.time()),
            Activity.started_at <= datetime.combine(d_to, datetime.max.time()),
        )
        .all()
    )
    session.close()

    if not acts:
        return f"Sin actividades entre {d_from} y {d_to}."

    from calc.zones import POWER_ZONES, HR_ZONES

    agg_pz: Dict[str, float] = {}
    agg_hz: Dict[str, float] = {}
    for a in acts:
        pz = a.get_zones_power()
        if pz:
            for k, v in pz.items():
                agg_pz[k] = agg_pz.get(k, 0) + (v or 0)
        hz = a.get_zones_hr()
        if hz:
            for k, v in hz.items():
                agg_hz[k] = agg_hz.get(k, 0) + (v or 0)

    lines = [f"Zonas del {d_from.strftime('%d/%m/%Y')} al {d_to.strftime('%d/%m/%Y')}:"]

    if agg_pz:
        pz_labels = {z.key: z.label for z in POWER_ZONES}
        total = sum(agg_pz.values()) or 1
        lines.append("\nZonas de potencia:")
        for k in sorted(agg_pz.keys()):
            pct = round(agg_pz[k] / total * 100, 1)
            lbl = pz_labels.get(k, k)
            h, m = divmod(int(agg_pz[k]), 3600)
            m = m // 60
            lines.append(f"- {k.upper()} ({lbl}): {h}h{m:02d}m ({pct}%)")

    if agg_hz:
        hz_labels = {z.key: z.label for z in HR_ZONES}
        total = sum(agg_hz.values()) or 1
        lines.append("\nZonas de FC:")
        for k in sorted(agg_hz.keys()):
            pct = round(agg_hz[k] / total * 100, 1)
            lbl = hz_labels.get(k, k)
            h, m = divmod(int(agg_hz[k]), 3600)
            m = m // 60
            lines.append(f"- {k.upper()} ({lbl}): {h}h{m:02d}m ({pct}%)")

    return "\n".join(lines)


def buscar_por_nombre(texto: str) -> str:
    """Busca actividades cuyo nombre contenga el texto dado.

    Args:
        texto: Texto a buscar en el nombre de la actividad.
    """
    texto = texto.strip().strip('"').strip("'")
    if not texto:
        return "Error: Texto de búsqueda vacío."

    session = get_session()
    acts = (
        session.query(Activity)
        .filter(
            (Activity.custom_name.ilike(f"%{texto}%")) |
            (Activity.file_name.ilike(f"%{texto}%"))
        )
        .order_by(desc(Activity.started_at))
        .limit(20)
        .all()
    )
    session.close()

    if not acts:
        return f"No se encontraron actividades con '{texto}' en el nombre."

    lines = [f"Actividades que contienen '{texto}' ({len(acts)}):"]
    for a in acts:
        lines.append(f"- {_activity_line(a)}")
    return "\n".join(lines)


def historial_salud(dias: str = "30") -> str:
    """Historial de métricas de salud.

    Args:
        dias: Número de días hacia atrás (por defecto 30).
    """
    try:
        n = int(str(dias).strip().strip('"').strip("'"))
    except (ValueError, TypeError):
        n = 30
    n = max(1, min(n, 365))

    today = date.today()
    lookback = today - timedelta(days=n)

    session = get_session()
    metrics = (
        session.query(HealthMetric)
        .filter(HealthMetric.date >= datetime.combine(lookback, datetime.min.time()))
        .order_by(HealthMetric.date)
        .all()
    )
    session.close()

    if not metrics:
        return f"Sin registros de salud en los últimos {n} días."

    lines = [f"Historial de salud (últimos {n} días, {len(metrics)} registros):"]
    for m in metrics:
        d = m.date.strftime("%d/%m") if m.date else "?"
        parts = [d]
        if m.weight_kg:
            parts.append(f"Peso={m.weight_kg}kg")
        if m.resting_hr:
            parts.append(f"FCrep={m.resting_hr}ppm")
        if m.hrv:
            parts.append(f"HRV={m.hrv}ms")
        if m.readiness:
            parts.append(f"Ready={m.readiness}/10")
        lines.append(f"- {' · '.join(parts)}")

    # Tendencias
    weights = [m.weight_kg for m in metrics if m.weight_kg]
    rhrs = [m.resting_hr for m in metrics if m.resting_hr]
    hrvs = [m.hrv for m in metrics if m.hrv]
    if len(weights) >= 2:
        lines.append(f"\nPeso: {weights[0]}kg → {weights[-1]}kg ("
                     f"{'+'if weights[-1]-weights[0]>0 else ''}{round(weights[-1]-weights[0], 1)}kg)")
    if len(rhrs) >= 2:
        lines.append(f"FC reposo: {rhrs[0]} → {rhrs[-1]}ppm")
    if len(hrvs) >= 2:
        lines.append(f"HRV: {hrvs[0]} → {hrvs[-1]}ms")

    return "\n".join(lines)


def actividad_mas_larga(desde: str = "", hasta: str = "") -> str:
    """Encuentra la actividad más larga (por duración) en un periodo.

    Args:
        desde: Fecha inicio (opcional, YYYY-MM-DD). Por defecto últimos 365 días.
        hasta: Fecha fin (opcional, YYYY-MM-DD). Por defecto hoy.
    """
    today = date.today()
    try:
        d_from = _parse_date(desde) if desde.strip() else today - timedelta(days=365)
        d_to = _parse_date(hasta) if hasta.strip() else today
    except ValueError as e:
        return f"Error: {e}"

    session = get_session()
    act = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(d_from, datetime.min.time()),
            Activity.started_at <= datetime.combine(d_to, datetime.max.time()),
        )
        .order_by(desc(Activity.duration_sec))
        .first()
    )
    session.close()

    if not act:
        return f"Sin actividades entre {d_from} y {d_to}."

    return f"Actividad más larga:\n- {_activity_line(act)}"


def actividad_mayor_tss(desde: str = "", hasta: str = "") -> str:
    """Encuentra la actividad con mayor TSS en un periodo.

    Args:
        desde: Fecha inicio (opcional, YYYY-MM-DD). Por defecto últimos 365 días.
        hasta: Fecha fin (opcional, YYYY-MM-DD). Por defecto hoy.
    """
    today = date.today()
    try:
        d_from = _parse_date(desde) if desde.strip() else today - timedelta(days=365)
        d_to = _parse_date(hasta) if hasta.strip() else today
    except ValueError as e:
        return f"Error: {e}"

    session = get_session()
    act = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(d_from, datetime.min.time()),
            Activity.started_at <= datetime.combine(d_to, datetime.max.time()),
            Activity.tss.isnot(None),
        )
        .order_by(desc(Activity.tss))
        .first()
    )
    session.close()

    if not act:
        return f"Sin actividades con TSS entre {d_from} y {d_to}."

    return f"Actividad con mayor TSS:\n- {_activity_line(act)}"


# ── registro de funciones disponibles ──────────────────────────────────────
QUERY_FUNCTIONS: Dict[str, Callable[..., str]] = {
    "buscar_actividades": buscar_actividades,
    "mejor_mmp": mejor_mmp,
    "resumen_periodo": resumen_periodo,
    "fitness_en_fecha": fitness_en_fecha,
    "tendencia_semanal": tendencia_semanal,
    "zonas_periodo": zonas_periodo,
    "buscar_por_nombre": buscar_por_nombre,
    "historial_salud": historial_salud,
    "actividad_mas_larga": actividad_mas_larga,
    "actividad_mayor_tss": actividad_mayor_tss,
}


def get_tools_description() -> str:
    """Genera la descripción de herramientas para el system prompt."""
    from i18n import get_language
    lang = get_language()

    if lang == "en":
        lines = [
            "# Data query tools",
            "",
            "You can query the athlete's database using these functions.",
            "To invoke one, write EXACTLY on a new line:",
            "[QUERY: function_name(arg1, arg2)]",
            "",
            'Use quotes for text arguments: [QUERY: buscar_por_nombre("puerto")]',
            "Dates use YYYY-MM-DD format.",
            "When you don't have enough data in your context to answer a question, "
            "use the appropriate function to query the database.",
            "You can use multiple queries in a single response if needed.",
            "",
            "Available functions:",
        ]
    else:
        lines = [
            "# Herramientas de consulta de datos",
            "",
            "Puedes consultar la base de datos del atleta usando estas funciones.",
            "Para invocar una, escribe EXACTAMENTE en una línea nueva:",
            "[QUERY: nombre_funcion(argumento1, argumento2)]",
            "",
            'Usa comillas para argumentos de texto: [QUERY: buscar_por_nombre("puerto")]',
            "Las fechas van en formato YYYY-MM-DD.",
            "Cuando no tengas datos suficientes en tu contexto para responder una pregunta, "
            "usa la función apropiada para consultar la base de datos.",
            "Puedes usar múltiples consultas en una sola respuesta si lo necesitas.",
            "",
            "Funciones disponibles:",
        ]

    params_label = "Parameters" if lang == "en" else "Parámetros"
    for name, fn in QUERY_FUNCTIONS.items():
        doc = fn.__doc__ or ""
        # Extraer primera línea de descripción
        first_line = doc.strip().split("\n")[0] if doc.strip() else name
        # Extraer args
        args_section = ""
        if "Args:" in doc:
            args_text = doc.split("Args:")[1].strip()
            arg_lines = []
            for aline in args_text.split("\n"):
                aline = aline.strip()
                if aline.startswith("-") or aline.startswith("Returns") or not aline:
                    break
                arg_lines.append(aline)
            args_section = " | ".join(arg_lines)

        lines.append(f"- {name}: {first_line}")
        if args_section:
            lines.append(f"  {params_label}: {args_section}")

    return "\n".join(lines)


# ── ejecución de queries ───────────────────────────────────────────────────

# Regex para detectar [QUERY: func(args)]
QUERY_PATTERN = re.compile(
    r"\[QUERY:\s*(\w+)\(([^)]*)\)\]",
    re.IGNORECASE,
)


def parse_and_execute_queries(text: str) -> List[Tuple[str, str, str]]:
    """Busca patrones [QUERY: ...] en el texto, los ejecuta y devuelve resultados.

    Returns:
        Lista de (match_original, nombre_funcion, resultado_str).
    """
    results = []
    for match in QUERY_PATTERN.finditer(text):
        func_name = match.group(1).strip().lower()
        raw_args = match.group(2).strip()

        fn = QUERY_FUNCTIONS.get(func_name)
        if fn is None:
            results.append((match.group(0), func_name,
                           f"Error: Función '{func_name}' no existe."))
            continue

        # Parsear argumentos
        args = _parse_args(raw_args)

        try:
            result = fn(*args)
        except Exception as exc:
            log.error("Error ejecutando %s(%s): %s", func_name, args, exc)
            result = f"Error al ejecutar {func_name}: {exc}"

        results.append((match.group(0), func_name, result))

    return results


def _parse_args(raw: str) -> List[str]:
    """Parsea argumentos de una llamada a función.

    Soporta: func("arg1", arg2, 'arg3')
    """
    if not raw.strip():
        return []

    args = []
    current = ""
    in_quotes = False
    quote_char = ""

    for ch in raw:
        if ch in ('"', "'") and not in_quotes:
            in_quotes = True
            quote_char = ch
        elif ch == quote_char and in_quotes:
            in_quotes = False
            quote_char = ""
        elif ch == "," and not in_quotes:
            args.append(current.strip())
            current = ""
            continue
        else:
            current += ch

    if current.strip():
        args.append(current.strip())

    return args
