"""Motor de contexto inteligente para el AI Coach.

Clasifica la pregunta del usuario y selecciona dinámicamente
qué datos del atleta incluir en el prompt, con el nivel de
detalle apropiado para cada tipo de consulta.

Reemplaza el enfoque "enviar todo siempre" por uno selectivo
que optimiza la ventana de contexto del LLM.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import desc
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import (
    Activity, DurabilityTest, HealthMetric,
    PowerTestSet, ProfileSnapshot,
)
from calc.fitness import build_fitness_series, FitnessPoint
from calc.zones import POWER_ZONES, HR_ZONES
from calc.activity_metrics import calc_ef, calc_vf, calc_pw_hr_decoupling, calc_tiss
from calc.intervals import detect_intervals, SampleRow
from calc.quadrant_analysis import calc_quadrant_analysis, QuadrantSample
from calc.monotony import calc_week_monotony, classify_monotony, classify_strain
from calc.race_readiness import calc_race_readiness, RrsInput
from calc.fatigue_resistance import calc_fatigue_resistance, classify_fr

log = logging.getLogger(__name__)

# Instancia global del store de embeddings (lazy init)
_embedding_store = None


def _get_embedding_store():
    """Obtiene la instancia global del EmbeddingStore (lazy)."""
    global _embedding_store
    if _embedding_store is None:
        try:
            from services.embedding_store import EmbeddingStore
        except ImportError:
            from .embedding_store import EmbeddingStore
        _embedding_store = EmbeddingStore()
    return _embedding_store


# ---------------------------------------------------------------------------
# Categorías de consulta
# ---------------------------------------------------------------------------
class QueryCategory:
    """Categorías posibles de pregunta del usuario."""
    FORM = "form"             # forma, TSB, fatiga, descanso
    TRAINING_PLAN = "plan"    # plan, semana, entrenamiento, objetivo
    PERFORMANCE = "perf"      # potencia, CP, W', FTP, MMP, zonas
    ANALYSIS = "analysis"     # actividad específica, cómo rendí, qué pasó
    HEALTH = "health"         # salud, HRV, peso, sueño, recuperación
    RACE = "race"             # carrera, competición, race readiness
    TREND = "trend"           # tendencia, evolución, progreso, mejora
    GENERAL = "general"       # saludo, pregunta genérica


# Palabras clave por categoría (ES + EN)
_KEYWORDS: Dict[str, List[str]] = {
    QueryCategory.FORM: [
        "forma", "tsb", "fatiga", "cansad", "descanso", "sobreentren",
        "fresc", "recuper", "atl", "ctl", "estrés", "stress",
        "form", "tired", "fatigued", "rest", "overtraining", "fresh",
    ],
    QueryCategory.TRAINING_PLAN: [
        "plan", "entrenam", "semana", "programa", "preparar", "objetivo",
        "sesion", "sesión", "interval", "tempo", "sweet spot", "base",
        "training", "workout", "schedule", "prepare", "goal", "week",
    ],
    QueryCategory.PERFORMANCE: [
        "potencia", "ftp", "cp", "w'", "w prime", "wprime", "mmp",
        "zona", "vatio", "watt", "if", "np", "tss", "intensidad",
        "vo2", "mftp", "power", "zone", "intensity", "threshold",
    ],
    QueryCategory.ANALYSIS: [
        "actividad", "rendí", "rendimiento", "pasó", "salida", "ruta",
        "última", "ayer", "jueves", "lunes", "martes", "miércoles",
        "viernes", "sábado", "domingo", "hoy",
        "activity", "perform", "ride", "last", "yesterday", "today",
        "monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday",
    ],
    QueryCategory.HEALTH: [
        "salud", "hrv", "fc reposo", "peso", "sueño", "dormir",
        "readiness", "bienestar",
        "health", "resting", "weight", "sleep", "wellness",
    ],
    QueryCategory.RACE: [
        "carrera", "competición", "competicion", "race", "ready",
        "readiness", "marcha", "evento", "prueba", "gran fondo",
        "crono", "contrareloj",
    ],
    QueryCategory.TREND: [
        "tendencia", "evolución", "evolucion", "progres", "mejor",
        "compar", "históric", "historic", "antes", "mes pasado",
        "trend", "progress", "improv", "compare", "history", "last month",
    ],
}


# Qué secciones de datos son relevantes para cada categoría
_CATEGORY_SECTIONS: Dict[str, List[str]] = {
    QueryCategory.FORM: [
        "profile", "fitness", "recent_activities", "monotony",
        "race_readiness", "health",
    ],
    QueryCategory.TRAINING_PLAN: [
        "profile", "fitness", "cp_model", "weekly_trends",
        "monotony", "zones", "mmp",
    ],
    QueryCategory.PERFORMANCE: [
        "profile", "cp_model", "mmp", "zones",
        "advanced_metrics", "fitness",
    ],
    QueryCategory.ANALYSIS: [
        "profile", "fitness", "recent_activities",
        "advanced_metrics", "health",
    ],
    QueryCategory.HEALTH: [
        "profile", "health", "fitness",
        "recent_activities", "monotony",
    ],
    QueryCategory.RACE: [
        "profile", "fitness", "race_readiness", "cp_model",
        "monotony", "weekly_trends", "durability",
    ],
    QueryCategory.TREND: [
        "profile", "fitness", "weekly_trends",
        "cp_model", "mmp", "zones",
    ],
    QueryCategory.GENERAL: [
        "profile", "fitness", "recent_activities",
    ],
}


# ---------------------------------------------------------------------------
# Resultado del contexto
# ---------------------------------------------------------------------------
@dataclass
class ContextResult:
    """Resultado del motor de contexto."""
    context_text: str           # texto a inyectar en el prompt
    categories: List[str]       # categorías detectadas
    sections_used: List[str]    # secciones de datos incluidas
    data_summary: str           # resumen para mostrar al usuario (🔍)
    semantic_hits: int = 0      # número de resultados semánticos incluidos


# ---------------------------------------------------------------------------
# Clasificador de consultas
# ---------------------------------------------------------------------------
def classify_query(text: str) -> List[str]:
    """Clasifica la pregunta del usuario en 1-3 categorías.

    Devuelve una lista ordenada por relevancia (la más probable primero).
    Si no se detecta nada específico, devuelve [GENERAL].
    """
    text_lower = text.lower()
    scores: Dict[str, int] = {}

    for category, keywords in _KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                score += 1
                # Bonus para coincidencias de palabras completas
                if re.search(rf"\b{re.escape(kw)}\b", text_lower):
                    score += 1
        if score > 0:
            scores[category] = score

    if not scores:
        return [QueryCategory.GENERAL]

    # Ordenar por score descendente, tomar top 2
    sorted_cats = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = [cat for cat, _ in sorted_cats[:2]]
    return result


# ---------------------------------------------------------------------------
# Constructor de contexto inteligente
# ---------------------------------------------------------------------------
def build_smart_context(
    user_msg: str,
    max_chars: int = 8000,
) -> ContextResult:
    """Construye contexto optimizado para la pregunta del usuario.

    En vez de enviar todo siempre, selecciona las secciones más
    relevantes y las llena con más detalle donde es necesario.
    """
    categories = classify_query(user_msg)

    # Reunir todas las secciones necesarias (sin duplicados, orden estable)
    needed_sections: List[str] = []
    seen: Set[str] = set()
    for cat in categories:
        for section in _CATEGORY_SECTIONS.get(cat, []):
            if section not in seen:
                needed_sections.append(section)
                seen.add(section)

    # La categoría principal define el foco de detalle
    primary_cat = categories[0]

    try:
        session = get_session()
    except RuntimeError:
        return ContextResult(
            context_text="(No hay perfil de atleta cargado.)",
            categories=categories,
            sections_used=[],
            data_summary="Sin datos disponibles",
        )

    parts: List[str] = []
    sections_used: List[str] = []
    summary_items: List[str] = []

    try:
        today = date.today()

        # Cache de datos compartidos
        profile = _get_profile(session)
        cp_test = _get_cp_test(session)
        fitness_series = _get_fitness_series(session, today)

        # Construir cada sección solicitada
        builders = {
            "profile": lambda: _section_profile(profile, summary_items),
            "cp_model": lambda: _section_cp_model(cp_test, summary_items),
            "fitness": lambda: _section_fitness(
                fitness_series, primary_cat, summary_items),
            "recent_activities": lambda: _section_recent_activities(
                session, today, primary_cat, summary_items),
            "health": lambda: _section_health(
                session, today, primary_cat, summary_items),
            "mmp": lambda: _section_mmp(
                session, today, primary_cat, summary_items),
            "zones": lambda: _section_zones(
                session, today, primary_cat, summary_items),
            "advanced_metrics": lambda: _section_advanced_metrics(
                session, today, cp_test, profile, primary_cat, summary_items),
            "weekly_trends": lambda: _section_weekly_trends(
                session, today, primary_cat, summary_items),
            "monotony": lambda: _section_monotony(
                session, today, summary_items),
            "race_readiness": lambda: _section_race_readiness(
                fitness_series, session, today, summary_items),
            "durability": lambda: _section_durability(
                session, summary_items),
        }

        total_len = 0
        for section_name in needed_sections:
            builder = builders.get(section_name)
            if not builder:
                continue
            try:
                text = builder()
                if text and text.strip():
                    # Control de tamaño
                    if total_len + len(text) + 4 > max_chars:
                        remaining = max_chars - total_len - 20
                        if remaining > 100:
                            parts.append(text[:remaining] + "\n(...)")
                            sections_used.append(section_name)
                        break
                    parts.append(text)
                    sections_used.append(section_name)
                    total_len += len(text) + 4
            except Exception as exc:
                log.warning("Error en sección '%s': %s", section_name, exc)

    except Exception as exc:
        log.error("Error al construir contexto inteligente: %s", exc)
        parts.append("(Error al leer datos del atleta.)")
    finally:
        session.close()

    # --- Búsqueda semántica (Fase 2 RAG) ---
    semantic_hits = 0
    try:
        store = _get_embedding_store()
        if store.is_available():
            # Determinar tipos de documento relevantes según categorías
            sem_doc_types = _semantic_doc_types(categories)
            remaining_chars = max_chars - total_len - 100
            if remaining_chars > 200:
                sem_text, sem_sources = store.search_for_context(
                    query=user_msg,
                    max_chars=remaining_chars,
                    doc_types=sem_doc_types,
                    top_k=4,
                )
                if sem_text:
                    parts.append(sem_text)
                    sections_used.append("semantic_search")
                    semantic_hits = len(sem_sources)
                    if sem_sources:
                        summary_items.append(
                            f"🔎 {len(sem_sources)} doc. similares"
                        )
    except Exception as exc:
        log.warning("Error en búsqueda semántica: %s", exc)

    context_text = "\n\n".join(parts) if parts else "(No hay datos del atleta disponibles.)"
    data_summary = ", ".join(summary_items) if summary_items else "Perfil básico"

    return ContextResult(
        context_text=context_text,
        categories=categories,
        sections_used=sections_used,
        data_summary=data_summary,
        semantic_hits=semantic_hits,
    )


def _semantic_doc_types(categories: List[str]) -> Optional[List[str]]:
    """Mapea categorías de consulta a tipos de documento para búsqueda semántica.

    Devuelve None si debe buscar en todos los tipos.
    """
    # Mapeo de categorías a tipos de documento prioritarios
    cat_to_types = {
        QueryCategory.FORM: ["activity", "health"],
        QueryCategory.TRAINING_PLAN: ["activity", "conversation"],
        QueryCategory.PERFORMANCE: ["activity"],
        QueryCategory.ANALYSIS: ["activity"],
        QueryCategory.HEALTH: ["health", "profile"],
        QueryCategory.RACE: ["activity", "health"],
        QueryCategory.TREND: ["activity", "profile"],
        QueryCategory.GENERAL: None,  # buscar en todo
    }

    all_types: Set[str] = set()
    for cat in categories:
        types = cat_to_types.get(cat)
        if types is None:
            return None  # GENERAL → buscar en todo
        all_types.update(types)

    return list(all_types) if all_types else None


# ---------------------------------------------------------------------------
# Helpers de datos compartidos
# ---------------------------------------------------------------------------
def _get_profile(session: Session) -> Optional[ProfileSnapshot]:
    return (
        session.query(ProfileSnapshot)
        .order_by(desc(ProfileSnapshot.effective_at))
        .first()
    )


def _get_cp_test(session: Session) -> Optional[PowerTestSet]:
    return (
        session.query(PowerTestSet)
        .order_by(desc(PowerTestSet.tested_at))
        .first()
    )


def _get_fitness_series(
    session: Session, today: date
) -> List[FitnessPoint]:
    activities = (
        session.query(Activity.started_at, Activity.tss)
        .filter(
            Activity.started_at <= datetime.combine(today, datetime.max.time()),
            Activity.tss.isnot(None),
        )
        .all()
    )
    if not activities:
        return []
    act_dicts = [{"started_at": a.started_at, "tss": a.tss} for a in activities]
    lookback = today - timedelta(days=90)
    return build_fitness_series(act_dicts, lookback, today)


# ---------------------------------------------------------------------------
# Constructores de secciones
# ---------------------------------------------------------------------------
def _section_profile(
    profile: Optional[ProfileSnapshot],
    summary_items: List[str],
) -> str:
    if not profile:
        return ""
    summary_items.append("Perfil")
    lines = ["## Perfil del atleta"]
    lines.append(f"- FTP: {profile.ftp} W")
    lines.append(f"- Peso: {profile.weight_kg} kg")
    lines.append(f"- W/kg: {round(profile.ftp / profile.weight_kg, 2) if profile.weight_kg else 'N/A'}")
    lines.append(f"- FC máx: {profile.hr_max} ppm")
    if profile.hr_lthr:
        lines.append(f"- FCL (umbral): {profile.hr_lthr} ppm")
    return "\n".join(lines)


def _section_cp_model(
    cp_test: Optional[PowerTestSet],
    summary_items: List[str],
) -> str:
    if not cp_test or not cp_test.cp:
        return ""
    summary_items.append("Modelo CP")
    lines = ["## Modelo Critical Power"]
    lines.append(f"- CP: {round(cp_test.cp)} W")
    w_kj = round(cp_test.w_prime / 1000, 1) if cp_test.w_prime else None
    if w_kj:
        lines.append(f"- W': {w_kj} kJ")
    if cp_test.vo2max:
        lines.append(f"- VO2max estimado: {round(cp_test.vo2max, 1)} ml/kg/min")
    if cp_test.m_ftp:
        lines.append(f"- mFTP: {round(cp_test.m_ftp)} W")
    if cp_test.r_squared is not None:
        lines.append(f"- R² del modelo: {round(cp_test.r_squared, 3)}")
    return "\n".join(lines)


def _section_fitness(
    series: List[FitnessPoint],
    primary_cat: str,
    summary_items: List[str],
) -> str:
    if not series:
        return ""

    last = series[-1]
    lines = ["## Estado de forma actual"]
    lines.append(f"- CTL (Fitness): {round(last.ctl, 1)}")
    lines.append(f"- ATL (Fatiga): {round(last.atl, 1)}")
    lines.append(f"- TSB (Forma): {round(last.tsb, 1)}")

    # Estado descriptivo
    if last.tsb > 15:
        lines.append("- Estado: Fresco / Transición")
    elif last.tsb > 5:
        lines.append("- Estado: Fresco")
    elif last.tsb > -10:
        lines.append("- Estado: Óptimo para rendir")
    elif last.tsb > -30:
        lines.append("- Estado: Carga productiva")
    else:
        lines.append("- Estado: ⚠️ Alto riesgo de sobreentrenamiento")

    # Ramp rate
    if len(series) >= 8:
        ramp = series[-1].ctl - series[-8].ctl
        lines.append(f"- Ramp rate (7d): {round(ramp, 1)} pts/sem")

    # Si la pregunta es sobre forma/tendencia, dar más detalle
    if primary_cat in (QueryCategory.FORM, QueryCategory.TREND, QueryCategory.RACE):
        # Evolución CTL últimos 14 días
        if len(series) >= 15:
            lines.append("\n### Evolución CTL/TSB (14 días)")
            for pt in series[-14:]:
                d_str = pt.date.strftime("%d/%m")
                lines.append(
                    f"- {d_str}: CTL={round(pt.ctl, 1)}, "
                    f"ATL={round(pt.atl, 1)}, "
                    f"TSB={round(pt.tsb, 1)}"
                )

    summary_items.append(f"Fitness (CTL={round(last.ctl, 1)}, TSB={round(last.tsb, 1)})")
    return "\n".join(lines)


def _section_recent_activities(
    session: Session,
    today: date,
    primary_cat: str,
    summary_items: List[str],
) -> str:
    # Más actividades si se pregunta por análisis
    days_back = 14 if primary_cat == QueryCategory.ANALYSIS else 7
    limit = 15 if primary_cat == QueryCategory.ANALYSIS else 10

    cutoff = today - timedelta(days=days_back)
    recent: List[Activity] = (
        session.query(Activity)
        .filter(Activity.started_at >= datetime.combine(cutoff, datetime.min.time()))
        .order_by(desc(Activity.started_at))
        .limit(limit)
        .all()
    )
    if not recent:
        return ""

    lines = [f"## Últimas actividades ({days_back} días)"]
    for a in recent:
        date_str = a.started_at.strftime("%d/%m") if a.started_at else "?"
        name = a.display_name
        dur_min = round(a.duration_sec / 60) if a.duration_sec else 0
        tss_str = f"TSS={round(a.tss)}" if a.tss else "sin TSS"
        line = f"- {date_str} · {name} · {dur_min}min · {tss_str}"
        if a.normalized_power:
            line += f" · NP={round(a.normalized_power)}W"
        if a.intensity_factor:
            line += f" · IF={round(a.intensity_factor, 2)}"
        if a.is_manual:
            line += f" · (manual: {a.activity_type or 'otro'})"
        lines.append(line)

    # Resumen
    total_tss = sum(a.tss or 0 for a in recent)
    total_hrs = sum((a.duration_sec or 0) for a in recent) / 3600
    lines.append(f"\nResumen: {len(recent)} sesiones, "
                 f"{round(total_hrs, 1)}h, TSS total={round(total_tss)}")

    summary_items.append(f"{len(recent)} actividades recientes")
    return "\n".join(lines)


def _section_health(
    session: Session,
    today: date,
    primary_cat: str,
    summary_items: List[str],
) -> str:
    # Más datos de salud si se pregunta por salud
    if primary_cat == QueryCategory.HEALTH:
        limit = 7
        lookback = today - timedelta(days=14)
        records: List[HealthMetric] = (
            session.query(HealthMetric)
            .filter(HealthMetric.date >= datetime.combine(lookback, datetime.min.time()))
            .order_by(desc(HealthMetric.date))
            .limit(limit)
            .all()
        )
    else:
        records = []
        latest: Optional[HealthMetric] = (
            session.query(HealthMetric)
            .order_by(desc(HealthMetric.date))
            .first()
        )
        if latest:
            records = [latest]

    if not records:
        return ""

    if len(records) == 1:
        h = records[0]
        lines = ["## Salud (último registro)"]
        if h.weight_kg:
            lines.append(f"- Peso: {h.weight_kg} kg")
        if h.resting_hr:
            lines.append(f"- FC reposo: {h.resting_hr} ppm")
        if h.hrv:
            lines.append(f"- HRV (RMSSD): {h.hrv} ms")
        if h.readiness:
            lines.append(f"- Readiness: {h.readiness}/10")
        summary_items.append("Salud")
    else:
        lines = [f"## Salud (últimos {len(records)} registros)"]
        for h in records:
            d_str = h.date.strftime("%d/%m") if h.date else "?"
            parts_h = [d_str]
            if h.weight_kg:
                parts_h.append(f"Peso={h.weight_kg}kg")
            if h.resting_hr:
                parts_h.append(f"FCr={h.resting_hr}ppm")
            if h.hrv:
                parts_h.append(f"HRV={h.hrv}ms")
            if h.readiness:
                parts_h.append(f"Ready={h.readiness}/10")
            lines.append("- " + ", ".join(parts_h))

        # Tendencia
        hrv_vals = [h.hrv for h in records if h.hrv]
        if len(hrv_vals) >= 3:
            avg_hrv = round(sum(hrv_vals) / len(hrv_vals), 1)
            trend = "↑" if hrv_vals[0] > avg_hrv else "↓" if hrv_vals[0] < avg_hrv else "→"
            lines.append(f"\nTendencia HRV: media={avg_hrv}ms, último={hrv_vals[0]}ms {trend}")

        summary_items.append(f"Salud ({len(records)} registros)")

    return "\n".join(lines)


def _section_mmp(
    session: Session,
    today: date,
    primary_cat: str,
    summary_items: List[str],
) -> str:
    lookback = today - timedelta(days=90)
    mmp_activities: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(lookback, datetime.min.time()),
            Activity.mmp.isnot(None),
        )
        .all()
    )
    if not mmp_activities:
        return ""

    best_mmp: Dict[int, float] = {}
    for act in mmp_activities:
        mmp_data = act.get_mmp()
        if mmp_data:
            for dur_str, watts in mmp_data.items():
                dur = int(dur_str)
                if dur not in best_mmp or watts > best_mmp[dur]:
                    best_mmp[dur] = watts
    if not best_mmp:
        return ""

    lines = ["## Curva de Potencia Máxima (MMP, 90 días)"]

    # Más duraciones si la pregunta es sobre rendimiento
    if primary_cat in (QueryCategory.PERFORMANCE, QueryCategory.TREND):
        key_durations = [
            (1, "1s"), (5, "5s"), (10, "10s"), (15, "15s"), (30, "30s"),
            (60, "1min"), (120, "2min"), (180, "3min"), (300, "5min"),
            (480, "8min"), (600, "10min"), (900, "15min"),
            (1200, "20min"), (1800, "30min"), (3600, "60min"),
        ]
    else:
        key_durations = [
            (5, "5s"), (30, "30s"), (60, "1min"),
            (300, "5min"), (600, "10min"),
            (1200, "20min"), (3600, "60min"),
        ]

    for dur_sec, label in key_durations:
        val = best_mmp.get(dur_sec)
        if val:
            lines.append(f"- {label}: {round(val)} W")

    summary_items.append("MMP 90d")
    return "\n".join(lines)


def _section_zones(
    session: Session,
    today: date,
    primary_cat: str,
    summary_items: List[str],
) -> str:
    zone_lookback = today - timedelta(days=30)
    zone_activities: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(zone_lookback, datetime.min.time()),
        )
        .all()
    )
    agg_pz: Dict[str, float] = {}
    agg_hz: Dict[str, float] = {}
    for act in zone_activities:
        pz = act.get_zones_power()
        if pz:
            for k, v in pz.items():
                agg_pz[k] = agg_pz.get(k, 0) + (v or 0)
        hz = act.get_zones_hr()
        if hz:
            for k, v in hz.items():
                agg_hz[k] = agg_hz.get(k, 0) + (v or 0)

    lines: List[str] = []

    if agg_pz:
        lines.append("## Distribución zonas de potencia (30 días)")
        pz_labels = {z.key: z.label for z in POWER_ZONES}
        total_pz = sum(agg_pz.values()) or 1
        for zk in sorted(agg_pz.keys()):
            secs = agg_pz[zk]
            pct = round(secs / total_pz * 100, 1)
            lbl = pz_labels.get(zk, zk)
            h, m = divmod(int(secs), 3600)
            m = m // 60
            lines.append(f"- {zk.upper()} ({lbl}): {h}h{m:02d}m ({pct}%)")

        # Polarización
        z_lo = sum(agg_pz.get(k, 0) for k in ("z1", "z2"))
        z_hi = sum(agg_pz.get(k, 0) for k in ("z5", "z6", "z7"))
        if total_pz > 0:
            lines.append(f"\nPolarización: {round(z_lo / total_pz * 100)}% baja / "
                         f"{round(z_hi / total_pz * 100)}% alta")

    if agg_hz:
        lines.append("\n## Distribución zonas de FC (30 días)")
        hz_labels = {z.key: z.label for z in HR_ZONES}
        total_hz = sum(agg_hz.values()) or 1
        for zk in sorted(agg_hz.keys()):
            secs = agg_hz[zk]
            pct = round(secs / total_hz * 100, 1)
            lbl = hz_labels.get(zk, zk)
            h, m = divmod(int(secs), 3600)
            m = m // 60
            lines.append(f"- {zk.upper()} ({lbl}): {h}h{m:02d}m ({pct}%)")

    if lines:
        summary_items.append("Zonas 30d")
    return "\n".join(lines)


def _section_advanced_metrics(
    session: Session,
    today: date,
    cp_test: Optional[PowerTestSet],
    profile: Optional[ProfileSnapshot],
    primary_cat: str,
    summary_items: List[str],
) -> str:
    limit = 8 if primary_cat == QueryCategory.ANALYSIS else 5
    pwr_activities: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(
                today - timedelta(days=30), datetime.min.time()),
            Activity.normalized_power.isnot(None),
            Activity.is_manual == False,
        )
        .order_by(desc(Activity.started_at))
        .limit(limit)
        .all()
    )

    ref_power = None
    if cp_test and cp_test.cp:
        ref_power = cp_test.cp
    elif profile and profile.ftp:
        ref_power = profile.ftp

    if not pwr_activities or not ref_power:
        return ""

    lines = ["## Métricas avanzadas (últimas actividades)"]
    for a in pwr_activities:
        date_str = a.started_at.strftime("%d/%m") if a.started_at else "?"
        name = a.display_name
        act_lines: List[str] = [f"### {date_str} — {name}"]

        ef = calc_ef(a.normalized_power, a.avg_hr)
        vf = calc_vf(a.normalized_power, a.avg_power)
        if ef is not None:
            act_lines.append(f"- EF: {round(ef, 2)}")
        if vf is not None:
            act_lines.append(f"- VF: {round(vf, 2)}")

        if a.avg_left_balance is not None:
            lb = round(a.avg_left_balance, 1)
            act_lines.append(f"- Balance: {lb}%L / {round(100 - lb, 1)}%R")

        # Detalle extendido para análisis de actividad
        if primary_cat in (QueryCategory.ANALYSIS, QueryCategory.PERFORMANCE):
            raw_samples = a.get_samples()
            if raw_samples and len(raw_samples) > 20:
                # Pw:Hr decoupling
                pw_hr_samples = [
                    (s.get("t", i), s.get("p"), s.get("hr"))
                    for i, s in enumerate(raw_samples)
                    if s.get("p") is not None or s.get("hr") is not None
                ]
                dec = calc_pw_hr_decoupling(pw_hr_samples)
                if dec is not None:
                    act_lines.append(
                        f"- Pw:Hr: {round(dec.decoupling, 1)}% "
                        f"(EF 1ª={round(dec.ef_first, 2)}, 2ª={round(dec.ef_second, 2)})"
                    )

                # TISS
                cp_val = cp_test.cp if (cp_test and cp_test.cp) else None
                wp_val = cp_test.w_prime if (cp_test and cp_test.w_prime) else None
                if cp_val and wp_val:
                    tiss_samples = [
                        (s.get("t", i), s.get("p"))
                        for i, s in enumerate(raw_samples)
                    ]
                    tiss = calc_tiss(tiss_samples, cp_val, wp_val)
                    if tiss:
                        act_lines.append(
                            f"- TISS: {round(tiss.tiss_total, 1)} "
                            f"(aero {round(tiss.pct_aero)}% / anaero {round(tiss.pct_anaero)}%)"
                        )

                # Cuadrante
                q_samples = [
                    QuadrantSample(p=s.get("p"), c=s.get("c"))
                    for s in raw_samples
                ]
                qa = calc_quadrant_analysis(q_samples, ref_power)
                if qa:
                    act_lines.append(
                        f"- Cuadrante: Q1={qa.q1_pct}%, Q2={qa.q2_pct}%, "
                        f"Q3={qa.q3_pct}%, Q4={qa.q4_pct}%"
                    )

                # Fatigue Resistance
                power_vals = [s.get("p", 0) or 0 for s in raw_samples]
                if len(power_vals) >= 600:
                    fr_result = calc_fatigue_resistance(power_vals)
                    if fr_result.fr_index is not None:
                        _, fr_label = classify_fr(fr_result.fr_index)
                        act_lines.append(
                            f"- FR: {round(fr_result.fr_index * 100, 1)}% ({fr_label})"
                        )

                # Intervalos
                int_samples = [
                    SampleRow(
                        t=s.get("t", i), p=s.get("p"),
                        hr=s.get("hr"), c=s.get("c"),
                    )
                    for i, s in enumerate(raw_samples)
                ]
                intervals = detect_intervals(int_samples, ref_power)
                if intervals:
                    act_lines.append(f"- Intervalos: {len(intervals)}")
                    for iv in intervals[:4]:
                        dur_m = round(iv.duration_sec / 60, 1)
                        iv_line = f"  · #{iv.num}: {dur_m}min, {iv.avg_power}W"
                        if iv.avg_hr:
                            iv_line += f", {iv.avg_hr}ppm"
                        act_lines.append(iv_line)

        # Subidas
        climbs_data = a.get_climbs()
        if climbs_data and len(climbs_data) > 0:
            top_climbs = sorted(
                climbs_data, key=lambda c: c.get("elev_gain_m", 0), reverse=True
            )[:3]
            if top_climbs:
                act_lines.append(f"- Subidas ({len(climbs_data)} total):")
                for cl in top_climbs:
                    cl_line = (
                        f"  · {round(cl.get('distance_m', 0))}m, "
                        f"+{round(cl.get('elev_gain_m', 0))}m, "
                        f"{round(cl.get('avg_gradient', 0), 1)}%"
                    )
                    if cl.get("avg_power"):
                        cl_line += f", {cl['avg_power']}W"
                    act_lines.append(cl_line)

        lines.append("\n".join(act_lines))

    summary_items.append(f"Métricas {len(pwr_activities)} act.")
    return "\n".join(lines)


def _section_weekly_trends(
    session: Session,
    today: date,
    primary_cat: str,
    summary_items: List[str],
) -> str:
    weeks_back = 6 if primary_cat in (QueryCategory.TREND, QueryCategory.TRAINING_PLAN) else 4
    trend_lookback = today - timedelta(days=7 * weeks_back)
    trend_activities: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(
                trend_lookback, datetime.min.time()),
        )
        .order_by(Activity.started_at)
        .all()
    )
    if not trend_activities:
        return ""

    weekly: Dict[str, List[Activity]] = {}
    for a in trend_activities:
        if a.started_at:
            iso = a.started_at.isocalendar()
            wk = f"{iso[0]}-W{iso[1]:02d}"
            weekly.setdefault(wk, []).append(a)

    if not weekly:
        return ""

    lines = [f"## Tendencias semanales ({weeks_back} semanas)"]
    for wk_key in sorted(weekly.keys()):
        acts = weekly[wk_key]
        n_sessions = len(acts)
        total_hrs = sum((a.duration_sec or 0) for a in acts) / 3600
        total_tss = sum(a.tss or 0 for a in acts)
        total_dist = sum(a.distance_km or 0 for a in acts)
        total_elev = sum(a.elevation_gain_m or 0 for a in acts)

        dur_if_pairs = [
            (a.duration_sec or 0, a.intensity_factor or 0)
            for a in acts if a.intensity_factor
        ]
        avg_if = 0.0
        if dur_if_pairs:
            total_dur = sum(d for d, _ in dur_if_pairs)
            if total_dur:
                avg_if = sum(d * i for d, i in dur_if_pairs) / total_dur

        # Polarización
        wk_z_lo = 0.0
        wk_z_hi = 0.0
        wk_z_total = 0.0
        for a in acts:
            pz = a.get_zones_power()
            if pz:
                for k, v in pz.items():
                    val = v or 0
                    wk_z_total += val
                    if k in ("z1", "z2"):
                        wk_z_lo += val
                    elif k in ("z5", "z6", "z7"):
                        wk_z_hi += val

        line = (
            f"- {wk_key}: {n_sessions} ses, "
            f"{round(total_hrs, 1)}h, "
            f"TSS={round(total_tss)}, "
            f"{round(total_dist)}km"
        )
        if total_elev:
            line += f", +{round(total_elev)}m"
        if avg_if:
            line += f", IF={round(avg_if, 2)}"
        if wk_z_total > 0:
            lo_pct = round(wk_z_lo / wk_z_total * 100)
            hi_pct = round(wk_z_hi / wk_z_total * 100)
            line += f", pol: {lo_pct}%↓/{hi_pct}%↑"
        lines.append(line)

    summary_items.append(f"Tendencias {weeks_back} sem.")
    return "\n".join(lines)


def _section_monotony(
    session: Session,
    today: date,
    summary_items: List[str],
) -> str:
    mon_lookback = today - timedelta(days=7)
    mon_acts: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(
                mon_lookback, datetime.min.time()),
        )
        .all()
    )
    if not mon_acts:
        return ""

    daily_tss_map: Dict[int, float] = {}
    for a in mon_acts:
        if a.started_at:
            wd = a.started_at.weekday()
            daily_tss_map[wd] = daily_tss_map.get(wd, 0) + (a.tss or 0)
    daily_tss_list = [daily_tss_map.get(d, 0) for d in range(7)]
    mon_result = calc_week_monotony(daily_tss_list)

    if mon_result.monotony is None:
        return ""

    m_cls, _ = classify_monotony(mon_result.monotony)
    lines = ["## Monotonía y Strain (última semana)"]
    lines.append(f"- Monotonía: {round(mon_result.monotony, 2)} ({m_cls})")
    if mon_result.strain is not None:
        s_cls, _ = classify_strain(mon_result.strain)
        lines.append(f"- Strain: {round(mon_result.strain)} ({s_cls})")

    summary_items.append("Monotonía")
    return "\n".join(lines)


def _section_race_readiness(
    series: List[FitnessPoint],
    session: Session,
    today: date,
    summary_items: List[str],
) -> str:
    if not series:
        return ""

    last_pt = series[-1]
    ctl_max_val = max(p.ctl for p in series) if series else last_pt.ctl

    ramp = None
    if len(series) >= 8:
        ramp = series[-1].ctl - series[-8].ctl

    # Monotonía para RRS
    mon_val = None
    mon_lookback = today - timedelta(days=7)
    mon_acts: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(
                mon_lookback, datetime.min.time()),
        )
        .all()
    )
    if mon_acts:
        daily_map: Dict[int, float] = {}
        for a in mon_acts:
            if a.started_at:
                wd = a.started_at.weekday()
                daily_map[wd] = daily_map.get(wd, 0) + (a.tss or 0)
        daily_list = [daily_map.get(d, 0) for d in range(7)]
        mon_r = calc_week_monotony(daily_list)
        mon_val = mon_r.monotony

    rrs = calc_race_readiness(RrsInput(
        tsb=last_pt.tsb,
        ctl=last_pt.ctl,
        ctl_max=ctl_max_val,
        ramp_rate=ramp,
        monotony=mon_val,
    ))

    lines = ["## Race Readiness"]
    lines.append(f"- Score: {rrs.score}/100")
    lines.append(f"- Forma: {rrs.form_score}, Fitness: {rrs.fitness_score}, "
                 f"Variabilidad: {rrs.variability_score}")
    if rrs.advice:
        lines.append(f"- Consejo: {rrs.advice}")

    summary_items.append(f"Race Readiness {rrs.score}/100")
    return "\n".join(lines)


def _section_durability(
    session: Session,
    summary_items: List[str],
) -> str:
    dur_test: Optional[DurabilityTest] = (
        session.query(DurabilityTest)
        .order_by(desc(DurabilityTest.id))
        .first()
    )
    if not dur_test:
        return ""

    lines = ["## Test de Durabilidad (último)"]
    if dur_test.dri_percent is not None:
        lines.append(f"- DRI: {round(dur_test.dri_percent, 1)}%")
    if dur_test.classification:
        lines.append(f"- Clasificación: {dur_test.classification}")
    if dur_test.cp_fresh is not None and dur_test.cp_fatigued is not None:
        lines.append(
            f"- CP fresco: {round(dur_test.cp_fresh)} W → "
            f"fatigado: {round(dur_test.cp_fatigued)} W"
        )
    if dur_test.w_prime_fatigued is not None:
        lines.append(f"- W' fatigado: {round(dur_test.w_prime_fatigued / 1000, 1)} kJ")

    summary_items.append("Durabilidad")
    return "\n".join(lines)
