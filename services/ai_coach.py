"""Servicio Consejero IA — integración local con Ollama.

Conecta con Ollama (localhost:11434) para proporcionar
coaching personalizado basado en los datos del atleta.
Todo el procesamiento es 100 % local, sin conexión a internet.
Conversaciones persistidas en SQLite.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests
from requests.exceptions import ConnectionError, Timeout
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from db.engine import get_session
from db.models import (
    Activity, AiConversation, AiMessage, DurabilityTest, HealthMetric,
    PowerTestSet, ProfileSnapshot,
)
from calc.fitness import build_fitness_series, FitnessPoint
from calc.zones import POWER_ZONES, HR_ZONES
from calc.activity_metrics import (
    calc_ef, calc_vf, calc_pw_hr_decoupling, calc_tiss,
)
from calc.intervals import detect_intervals, SampleRow, DetectIntervalsOptions
from calc.quadrant_analysis import calc_quadrant_analysis, QuadrantSample
from calc.monotony import calc_week_monotony, classify_monotony, classify_strain
from calc.race_readiness import calc_race_readiness, RrsInput
from calc.fatigue_resistance import calc_fatigue_resistance, classify_fr
from calc.climbs import DetectedClimb

log = logging.getLogger(__name__)

# Instancia global del store de embeddings (lazy)
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
# Configuración
# ---------------------------------------------------------------------------
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"
CONNECT_TIMEOUT = 5   # segundos
READ_TIMEOUT = 120     # segundos (respuestas largas)
MAX_TITLE_LEN = 60

# Gestión inteligente del contexto
MAX_CONTEXT_CHARS = 6000   # ~1500 tokens aprox → cabe en 8K context window
# Prioridades de secciones (menor = más importante, se incluye primero)
SECTION_PRIORITIES: Dict[str, int] = {
    "Perfil del atleta": 1,
    "Estado de forma actual": 2,
    "Modelo Critical Power": 3,
    "Tendencias semanales": 4,
    "Monotonía y Strain": 5,
    "Race Readiness": 6,
    "Curva de Potencia Máxima": 7,
    "Distribución zonas de potencia": 8,
    "Distribución zonas de FC": 9,
    "Últimas actividades": 10,
    "Test de Durabilidad": 11,
    "Salud": 12,
    "Métricas avanzadas": 13,
}


@dataclass
class ChatMessage:
    """Mensaje en el historial de chat."""
    role: str       # 'system' | 'user' | 'assistant'
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class OllamaModel:
    """Modelo instalado en Ollama."""
    name: str
    size_gb: float
    modified_at: str


@dataclass
class ConversationSummary:
    """Resumen de una conversación para el listado."""
    id: int
    title: str
    model: str
    message_count: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Servicio principal
# ---------------------------------------------------------------------------
class AiCoachService:
    """Servicio de coaching IA con Ollama y persistencia."""

    def __init__(
        self,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
    ):
        self._base_url = ollama_url.rstrip("/")
        self._model = model
        self._history: List[ChatMessage] = []
        self._system_prompt: str = ""
        self._connected: bool = False
        self._conversation_id: Optional[int] = None
        self._last_context_summary: str = ""

    # ---- Propiedades -------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @base_url.setter
    def base_url(self, url: str) -> None:
        self._base_url = url.rstrip("/")
        self._connected = False

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, name: str) -> None:
        self._model = name

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def history(self) -> List[ChatMessage]:
        return list(self._history)

    @property
    def conversation_id(self) -> Optional[int]:
        return self._conversation_id

    @property
    def last_context_summary(self) -> str:
        """Resumen del contexto usado en la última consulta (para 🔍 indicador)."""
        return self._last_context_summary

    # ---- Conexión y modelos ------------------------------------------------

    def check_connection(self) -> bool:
        """Comprueba si Ollama está accesible."""
        try:
            r = requests.get(
                f"{self._base_url}/api/tags",
                timeout=CONNECT_TIMEOUT,
            )
            self._connected = r.status_code == 200
        except (ConnectionError, Timeout, Exception):
            self._connected = False
        return self._connected

    def list_models(self) -> List[OllamaModel]:
        """Lista los modelos instalados en Ollama."""
        try:
            r = requests.get(
                f"{self._base_url}/api/tags",
                timeout=CONNECT_TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
            models = []
            for m in data.get("models", []):
                size_bytes = m.get("size", 0)
                models.append(OllamaModel(
                    name=m.get("name", "unknown"),
                    size_gb=round(size_bytes / (1024 ** 3), 1),
                    modified_at=m.get("modified_at", ""),
                ))
            return models
        except Exception as exc:
            log.warning("No se pudieron listar modelos: %s", exc)
            return []

    # ---- Contexto del atleta -----------------------------------------------

    def _get_athlete_context(self) -> str:
        """Construye un resumen textual del estado del atleta desde la DB."""
        try:
            session = get_session()
        except RuntimeError:
            return "(No hay perfil de atleta cargado.)"

        parts: List[str] = []

        try:
            # --- Perfil actual ---
            profile: ProfileSnapshot | None = (
                session.query(ProfileSnapshot)
                .order_by(desc(ProfileSnapshot.effective_at))
                .first()
            )
            if profile:
                parts.append("## Perfil del atleta")
                parts.append(f"- FTP: {profile.ftp} W")
                parts.append(f"- Peso: {profile.weight_kg} kg")
                parts.append(f"- W/kg: {round(profile.ftp / profile.weight_kg, 2) if profile.weight_kg else 'N/A'}")
                parts.append(f"- FC máx: {profile.hr_max} ppm")
                if profile.hr_lthr:
                    parts.append(f"- FCL (umbral): {profile.hr_lthr} ppm")

            # --- Modelo CP / W' ---
            cp_test: PowerTestSet | None = (
                session.query(PowerTestSet)
                .order_by(desc(PowerTestSet.tested_at))
                .first()
            )
            if cp_test and cp_test.cp:
                parts.append("\n## Modelo Critical Power")
                parts.append(f"- CP: {round(cp_test.cp)} W")
                w_kj = round(cp_test.w_prime / 1000, 1) if cp_test.w_prime else None
                if w_kj:
                    parts.append(f"- W': {w_kj} kJ")
                if cp_test.vo2max:
                    parts.append(f"- VO2max estimado: {round(cp_test.vo2max, 1)} ml/kg/min")
                if cp_test.m_ftp:
                    parts.append(f"- mFTP: {round(cp_test.m_ftp)} W")
                if cp_test.r_squared is not None:
                    parts.append(f"- R² del modelo: {round(cp_test.r_squared, 3)}")

            # --- Fitness (CTL / ATL / TSB) ---
            today = date.today()
            lookback = today - timedelta(days=90)
            # Cargar TODAS las actividades (sin límite inferior de fecha)
            # para que el warmup de build_fitness_series tenga datos reales
            activities = (
                session.query(Activity.started_at, Activity.tss)
                .filter(
                    Activity.started_at <= datetime.combine(today, datetime.max.time()),
                    Activity.tss.isnot(None),
                )
                .all()
            )

            if activities:
                act_dicts = [
                    {"started_at": a.started_at, "tss": a.tss}
                    for a in activities
                ]
                series = build_fitness_series(act_dicts, lookback, today)
                if series:
                    last = series[-1]
                    parts.append("\n## Estado de forma actual")
                    parts.append(f"- CTL (Fitness): {round(last.ctl, 1)}")
                    parts.append(f"- ATL (Fatiga): {round(last.atl, 1)}")
                    parts.append(f"- TSB (Forma): {round(last.tsb, 1)}")
                    if last.tsb > 15:
                        parts.append("- Estado: Fresco / Transición")
                    elif last.tsb > 5:
                        parts.append("- Estado: Fresco")
                    elif last.tsb > -10:
                        parts.append("- Estado: Óptimo para rendir")
                    elif last.tsb > -30:
                        parts.append("- Estado: Carga productiva")
                    else:
                        parts.append("- Estado: ⚠️ Alto riesgo de sobreentrenamiento")

            # --- Últimas actividades (7 días) ---
            week_ago = today - timedelta(days=7)
            recent: List[Activity] = (
                session.query(Activity)
                .filter(Activity.started_at >= datetime.combine(week_ago, datetime.min.time()))
                .order_by(desc(Activity.started_at))
                .limit(10)
                .all()
            )
            if recent:
                parts.append("\n## Últimas actividades (7 días)")
                for a in recent:
                    date_str = a.started_at.strftime("%d/%m") if a.started_at else "?"
                    name = a.display_name
                    dur_min = round(a.duration_sec / 60) if a.duration_sec else 0
                    tss_str = f"TSS={round(a.tss)}" if a.tss else "sin TSS"
                    pwr_str = f"NP={round(a.normalized_power)}W" if a.normalized_power else ""
                    line = f"- {date_str} · {name} · {dur_min}min · {tss_str}"
                    if pwr_str:
                        line += f" · {pwr_str}"
                    if a.is_manual:
                        line += f" · (manual: {a.activity_type or 'otro'})"
                    parts.append(line)

                # Resumen semanal
                total_tss = sum(a.tss or 0 for a in recent)
                total_hrs = sum((a.duration_sec or 0) for a in recent) / 3600
                parts.append(f"\nResumen semana: {len(recent)} sesiones, "
                             f"{round(total_hrs, 1)}h, TSS total={round(total_tss)}")

            # --- Salud reciente ---
            health: HealthMetric | None = (
                session.query(HealthMetric)
                .order_by(desc(HealthMetric.date))
                .first()
            )
            if health:
                parts.append("\n## Salud (último registro)")
                if health.weight_kg:
                    parts.append(f"- Peso: {health.weight_kg} kg")
                if health.resting_hr:
                    parts.append(f"- FC reposo: {health.resting_hr} ppm")
                if health.hrv:
                    parts.append(f"- HRV (RMSSD): {health.hrv} ms")
                if health.readiness:
                    parts.append(f"- Readiness: {health.readiness}/10")

            # --- Curva de Potencia Máxima (MMP) ---
            month_ago = today - timedelta(days=90)
            mmp_activities: List[Activity] = (
                session.query(Activity)
                .filter(
                    Activity.started_at >= datetime.combine(month_ago, datetime.min.time()),
                    Activity.mmp.isnot(None),
                )
                .all()
            )
            if mmp_activities:
                best_mmp: dict[int, float] = {}
                for act in mmp_activities:
                    mmp_data = act.get_mmp()
                    if mmp_data:
                        for dur_str, watts in mmp_data.items():
                            dur = int(dur_str)
                            if dur not in best_mmp or watts > best_mmp[dur]:
                                best_mmp[dur] = watts
                if best_mmp:
                    parts.append("\n## Curva de Potencia Máxima (MMP, 90 días)")
                    key_durations = [
                        (5, "5s"), (10, "10s"), (30, "30s"),
                        (60, "1min"), (300, "5min"), (600, "10min"),
                        (1200, "20min"), (3600, "60min"),
                    ]
                    for dur_sec, label in key_durations:
                        val = best_mmp.get(dur_sec)
                        if val:
                            parts.append(f"- {label}: {round(val)} W")

            # --- Distribución de zonas (30 días) ---
            zone_lookback = today - timedelta(days=30)
            zone_activities: List[Activity] = (
                session.query(Activity)
                .filter(
                    Activity.started_at >= datetime.combine(zone_lookback, datetime.min.time()),
                )
                .all()
            )
            agg_pz: dict[str, float] = {}
            agg_hz: dict[str, float] = {}
            for act in zone_activities:
                pz = act.get_zones_power()
                if pz:
                    for k, v in pz.items():
                        agg_pz[k] = agg_pz.get(k, 0) + (v or 0)
                hz = act.get_zones_hr()
                if hz:
                    for k, v in hz.items():
                        agg_hz[k] = agg_hz.get(k, 0) + (v or 0)

            if agg_pz:
                parts.append("\n## Distribución zonas de potencia (30 días)")
                pz_labels = {z.key: z.label for z in POWER_ZONES}
                total_pz = sum(agg_pz.values()) or 1
                for zk in sorted(agg_pz.keys()):
                    secs = agg_pz[zk]
                    pct = round(secs / total_pz * 100, 1)
                    lbl = pz_labels.get(zk, zk)
                    h, m = divmod(int(secs), 3600)
                    m = m // 60
                    parts.append(f"- {zk.upper()} ({lbl}): {h}h{m:02d}m ({pct}%)")

            if agg_hz:
                parts.append("\n## Distribución zonas de FC (30 días)")
                hz_labels = {z.key: z.label for z in HR_ZONES}
                total_hz = sum(agg_hz.values()) or 1
                for zk in sorted(agg_hz.keys()):
                    secs = agg_hz[zk]
                    pct = round(secs / total_hz * 100, 1)
                    lbl = hz_labels.get(zk, zk)
                    h, m = divmod(int(secs), 3600)
                    m = m // 60
                    parts.append(f"- {zk.upper()} ({lbl}): {h}h{m:02d}m ({pct}%)")

            # --- Métricas avanzadas (últimas 5 actividades con potencia) ---
            pwr_activities: List[Activity] = (
                session.query(Activity)
                .filter(
                    Activity.started_at >= datetime.combine(
                        today - timedelta(days=30), datetime.min.time()),
                    Activity.normalized_power.isnot(None),
                    Activity.is_manual == False,
                )
                .order_by(desc(Activity.started_at))
                .limit(5)
                .all()
            )

            ref_power = None
            if cp_test and cp_test.cp:
                ref_power = cp_test.cp
            elif profile and profile.ftp:
                ref_power = profile.ftp

            if pwr_activities and ref_power:
                parts.append("\n## Métricas avanzadas (últimas actividades)")
                for a in pwr_activities:
                    date_str = a.started_at.strftime("%d/%m") if a.started_at else "?"
                    name = a.display_name
                    line_parts: List[str] = [f"### {date_str} — {name}"]

                    # EF, VF
                    ef = calc_ef(a.normalized_power, a.avg_hr)
                    vf = calc_vf(a.normalized_power, a.avg_power)
                    if ef is not None:
                        line_parts.append(f"- EF (Efficiency Factor): {round(ef, 2)}")
                    if vf is not None:
                        line_parts.append(f"- VF (Variability Factor): {round(vf, 2)}")

                    # Balance pedaleo
                    if a.avg_left_balance is not None:
                        lb = round(a.avg_left_balance, 1)
                        line_parts.append(f"- Balance pedaleo: {lb}% izq / {round(100 - lb, 1)}% der")

                    # Pw:Hr decoupling — necesita samples
                    raw_samples = a.get_samples()
                    if raw_samples and len(raw_samples) > 20:
                        pw_hr_samples = [
                            (s.get("t", i), s.get("p"), s.get("hr"))
                            for i, s in enumerate(raw_samples)
                            if s.get("p") is not None or s.get("hr") is not None
                        ]
                        dec = calc_pw_hr_decoupling(pw_hr_samples)
                        if dec is not None:
                            line_parts.append(
                                f"- Pw:Hr decoupling: {round(dec.decoupling, 1)}% "
                                f"(EF 1ª mitad={round(dec.ef_first, 2)}, 2ª={round(dec.ef_second, 2)})"
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
                                line_parts.append(
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
                            line_parts.append(
                                f"- Cuadrante: Q1(Neuromusc)={qa.q1_pct}%, "
                                f"Q2(FuerzaRes)={qa.q2_pct}%, "
                                f"Q3(Recup)={qa.q3_pct}%, "
                                f"Q4(Efic.CV)={qa.q4_pct}%"
                            )

                        # Fatigue Resistance
                        power_vals = [
                            s.get("p", 0) or 0
                            for s in raw_samples
                        ]
                        if len(power_vals) >= 600:  # >10 min
                            fr_result = calc_fatigue_resistance(power_vals)
                            if fr_result.fr_index is not None:
                                fr_cls, fr_label = classify_fr(fr_result.fr_index)
                                line_parts.append(
                                    f"- Fatigue Resistance: {round(fr_result.fr_index * 100, 1)}% "
                                    f"({fr_label})"
                                )

                        # Intervalos detectados
                        int_samples = [
                            SampleRow(
                                t=s.get("t", i),
                                p=s.get("p"),
                                hr=s.get("hr"),
                                c=s.get("c"),
                            )
                            for i, s in enumerate(raw_samples)
                        ]
                        intervals = detect_intervals(int_samples, ref_power)
                        if intervals:
                            line_parts.append(f"- Intervalos detectados: {len(intervals)}")
                            for iv in intervals[:6]:  # máx 6 para no saturar
                                dur_m = round(iv.duration_sec / 60, 1)
                                iv_line = f"  · #{iv.num}: {dur_m}min, {iv.avg_power}W"
                                if iv.avg_hr:
                                    iv_line += f", {iv.avg_hr}ppm"
                                if iv.avg_cadence:
                                    iv_line += f", {iv.avg_cadence}rpm"
                                if iv.recovery_sec:
                                    iv_line += f" (rec {round(iv.recovery_sec)}s)"
                                line_parts.append(iv_line)

                    # Subidas detectadas
                    climbs_data = a.get_climbs()
                    if climbs_data and len(climbs_data) > 0:
                        top_climbs = sorted(
                            climbs_data, key=lambda c: c.get("elev_gain_m", 0), reverse=True
                        )[:3]
                        if top_climbs:
                            line_parts.append(f"- Subidas ({len(climbs_data)} total):")
                            for cl in top_climbs:
                                cl_line = (
                                    f"  · {round(cl.get('distance_m', 0))}m, "
                                    f"+{round(cl.get('elev_gain_m', 0))}m, "
                                    f"{round(cl.get('avg_gradient', 0), 1)}% grad"
                                )
                                if cl.get("avg_power"):
                                    cl_line += f", {cl['avg_power']}W"
                                line_parts.append(cl_line)

                    parts.append("\n".join(line_parts))

            # --- Tendencias semanales (últimas 4 semanas) ---
            trend_lookback = today - timedelta(days=28)
            trend_activities: List[Activity] = (
                session.query(Activity)
                .filter(
                    Activity.started_at >= datetime.combine(
                        trend_lookback, datetime.min.time()),
                )
                .order_by(Activity.started_at)
                .all()
            )
            if trend_activities:
                # Agrupar por semana ISO
                weekly: dict[str, List[Activity]] = {}
                for a in trend_activities:
                    if a.started_at:
                        iso = a.started_at.isocalendar()
                        wk = f"{iso[0]}-W{iso[1]:02d}"
                        weekly.setdefault(wk, []).append(a)

                if weekly:
                    parts.append("\n## Tendencias semanales (4 semanas)")
                    for wk_key in sorted(weekly.keys()):
                        acts = weekly[wk_key]
                        n_sessions = len(acts)
                        total_hrs = sum((a.duration_sec or 0) for a in acts) / 3600
                        total_tss_wk = sum(a.tss or 0 for a in acts)
                        total_dist = sum(a.distance_km or 0 for a in acts)
                        total_elev = sum(a.elevation_gain_m or 0 for a in acts)

                        # Intensidad media (IF medio ponderado por duración)
                        dur_if_pairs = [
                            (a.duration_sec or 0, a.intensity_factor or 0)
                            for a in acts if a.intensity_factor
                        ]
                        if dur_if_pairs:
                            total_dur_if = sum(d for d, _ in dur_if_pairs)
                            avg_if = sum(d * i for d, i in dur_if_pairs) / total_dur_if if total_dur_if else 0
                        else:
                            avg_if = 0

                        # Distribución polarizada (% bajo Z2 vs % Z5+)
                        wk_z_lo = 0.0  # Z1+Z2
                        wk_z_hi = 0.0  # Z5+Z6+Z7
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
                            f"- {wk_key}: {n_sessions} sesiones, "
                            f"{round(total_hrs, 1)}h, "
                            f"TSS={round(total_tss_wk)}, "
                            f"{round(total_dist)}km"
                        )
                        if total_elev:
                            line += f", +{round(total_elev)}m"
                        if avg_if:
                            line += f", IF medio={round(avg_if, 2)}"
                        if wk_z_total > 0:
                            lo_pct = round(wk_z_lo / wk_z_total * 100)
                            hi_pct = round(wk_z_hi / wk_z_total * 100)
                            line += f", polarización: {lo_pct}% baja / {hi_pct}% alta"
                        parts.append(line)

            # --- Monotonía y Strain (última semana) ---
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
                daily_tss_map: dict[int, float] = {}
                for a in mon_acts:
                    if a.started_at:
                        wd = a.started_at.weekday()  # 0=Mon
                        daily_tss_map[wd] = daily_tss_map.get(wd, 0) + (a.tss or 0)
                daily_tss_list = [daily_tss_map.get(d, 0) for d in range(7)]
                mon_result = calc_week_monotony(daily_tss_list)
                if mon_result.monotony is not None:
                    m_cls, _ = classify_monotony(mon_result.monotony)
                    parts.append("\n## Monotonía y Strain (última semana)")
                    parts.append(f"- Monotonía: {round(mon_result.monotony, 2)} ({m_cls})")
                    if mon_result.strain is not None:
                        s_cls, _ = classify_strain(mon_result.strain)
                        parts.append(f"- Strain: {round(mon_result.strain)} ({s_cls})")

            # --- Race Readiness Score ---
            if activities and series:
                last_pt = series[-1]
                ctl_max_val = max(p.ctl for p in series) if series else last_pt.ctl

                # Ramp rate
                ramp = None
                if len(series) >= 8:
                    ramp = series[-1].ctl - series[-8].ctl

                # Monotonía para RRS
                mon_val = None
                if mon_acts:
                    daily_tss_map2: dict[int, float] = {}
                    for a in mon_acts:
                        if a.started_at:
                            wd = a.started_at.weekday()
                            daily_tss_map2[wd] = daily_tss_map2.get(wd, 0) + (a.tss or 0)
                    daily_list2 = [daily_tss_map2.get(d, 0) for d in range(7)]
                    mon_r2 = calc_week_monotony(daily_list2)
                    mon_val = mon_r2.monotony

                rrs = calc_race_readiness(RrsInput(
                    tsb=last_pt.tsb,
                    ctl=last_pt.ctl,
                    ctl_max=ctl_max_val,
                    ramp_rate=ramp,
                    monotony=mon_val,
                ))
                parts.append("\n## Race Readiness")
                parts.append(f"- Score: {rrs.score}/100")
                parts.append(f"- Forma: {rrs.form_score}, Fitness: {rrs.fitness_score}, Variabilidad: {rrs.variability_score}")
                if rrs.advice:
                    parts.append(f"- Consejo: {rrs.advice}")

            # --- Test de Durabilidad ---
            dur_test: DurabilityTest | None = (
                session.query(DurabilityTest)
                .order_by(desc(DurabilityTest.id))
                .first()
            )
            if dur_test:
                parts.append("\n## Test de Durabilidad (último)")
                if dur_test.dri_percent is not None:
                    parts.append(f"- DRI: {round(dur_test.dri_percent, 1)}%")
                if dur_test.classification:
                    parts.append(f"- Clasificación: {dur_test.classification}")
                if dur_test.cp_fresh is not None and dur_test.cp_fatigued is not None:
                    parts.append(f"- CP fresco: {round(dur_test.cp_fresh)} W → fatigado: {round(dur_test.cp_fatigued)} W")
                if dur_test.w_prime_fatigued is not None:
                    parts.append(f"- W' fatigado: {round(dur_test.w_prime_fatigued / 1000, 1)} kJ")
                if dur_test.kj_consumed is not None:
                    parts.append(f"- kJ consumidos en test: {round(dur_test.kj_consumed)}")

        except Exception as exc:
            log.error("Error al construir contexto del atleta: %s", exc)
            parts.append("(Error al leer datos del atleta.)")
        finally:
            session.close()

        return "\n".join(parts) if parts else "(No hay datos del atleta disponibles.)"

    @staticmethod
    def _trim_context(raw_context: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
        """Recorta el contexto priorizando las secciones más importantes.

        Si el contexto cabe en max_chars, lo devuelve tal cual.
        Si no, selecciona secciones por prioridad hasta llenar el límite.
        Las métricas avanzadas por actividad se resumen si hay exceso.
        """
        if len(raw_context) <= max_chars:
            return raw_context

        # Dividir en secciones por '## '
        sections: List[tuple[str, str]] = []  # (titulo, contenido_completo)
        current_title = ""
        current_lines: List[str] = []

        for line in raw_context.split("\n"):
            if line.startswith("## "):
                if current_title or current_lines:
                    sections.append((current_title, "\n".join(current_lines)))
                current_title = line.replace("## ", "").split("(")[0].strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        if current_title or current_lines:
            sections.append((current_title, "\n".join(current_lines)))

        # Ordenar por prioridad
        def priority(title: str) -> int:
            for key, prio in SECTION_PRIORITIES.items():
                if key.lower() in title.lower():
                    return prio
            return 99

        sorted_sections = sorted(sections, key=lambda s: priority(s[0]))

        # Reconstruir contexto respetando el límite
        result_parts: List[str] = []
        used = 0
        for title, content in sorted_sections:
            # Resumen agresivo de métricas avanzadas si excede
            if "métricas avanzadas" in title.lower() and len(content) > 800:
                # Mantener solo encabezado y resumen por actividad
                trimmed_lines: List[str] = []
                for cl in content.split("\n"):
                    if cl.startswith("## ") or cl.startswith("### ") or "EF" in cl or "VF" in cl or "Fatigue" in cl:
                        trimmed_lines.append(cl)
                content = "\n".join(trimmed_lines)

            if used + len(content) + 2 > max_chars:
                # Intentar incluir recortado
                remaining = max_chars - used - 20
                if remaining > 100:
                    result_parts.append(content[:remaining] + "\n(...)")
                break
            result_parts.append(content)
            used += len(content) + 2

        return "\n\n".join(result_parts)

    def _build_system_prompt(self, user_msg: str = "") -> str:
        """Genera el prompt del sistema con contexto inteligente.

        Si *user_msg* se proporciona, usa el motor de contexto inteligente
        para seleccionar solo las secciones relevantes.  Si está vacío,
        usa el método clásico (retrocompatibilidad).
        """
        from i18n import get_language
        lang = get_language()

        if user_msg:
            try:
                from services.context_engine import build_smart_context
            except ImportError:
                from .context_engine import build_smart_context
            cr = build_smart_context(user_msg)
            ctx = cr.context_text
            self._last_context_summary = cr.data_summary
        else:
            raw_ctx = self._get_athlete_context()
            ctx = self._trim_context(raw_ctx)
            self._last_context_summary = ""
        try:
            from .data_queries import get_tools_description
            tools_desc = get_tools_description()
        except ImportError:
            from services.data_queries import get_tools_description
            tools_desc = get_tools_description()
        today_str = date.today().isoformat()

        if lang == "en":
            return (
                "You are an expert cycling and sports performance coach. "
                "Your name is AI Coach from Ciclométricas. "
                "You always respond in English with a friendly but professional tone. "
                "You base your recommendations on the real athlete data provided below. "
                "You use cycling terminology: FTP, TSS, CTL, ATL, TSB, NP, IF, CP, W', EF, VF, Pw:Hr, TISS, "
                "Coggan power zones, Friel HR zones (based on LTHR), "
                "quadrant analysis, Fatigue Resistance, monotony, strain, Race Readiness, polarization. "
                "When giving power ranges, express them in watts and % of FTP/CP. "
                "If you don't have enough data for a recommendation, say so clearly. "
                "Do not invent data not present in the context.\n\n"
                f"# Current date: {today_str}\n"
                "Use this date as reference for 'today', 'this week', 'recent days', etc.\n\n"
                "# Athlete data\n"
                f"{ctx}\n\n"
                f"{tools_desc}\n\n"
                "IMPORTANT: If the user asks for specific data (personal records, activities in a period, "
                "comparisons, historical statistics), USE the query tools to get real data. "
                "Do not answer with invented data if you can look it up. "
                f"When the user says 'today' they mean {today_str}. "
                "When they say 'this week', calculate the most recent Monday as the start.\n\n"
                "Respond concisely and in a structured way. "
                "Use bullet points and bold text to highlight what's important."
            )

        return (
            "Eres un entrenador experto en ciclismo y rendimiento deportivo. "
            "Tu nombre es Consejero IA de Ciclométricas. "
            "Respondes siempre en español con un tono cercano pero profesional. "
            "Basas tus recomendaciones en los datos reales del atleta que se proporcionan a continuación. "
            "Usas terminología ciclista: FTP, TSS, CTL, ATL, TSB, NP, IF, CP, W', EF, VF, Pw:Hr, TISS, "
            "zonas de potencia Coggan, zonas de FC Friel (basadas en FCL), "
            "análisis de cuadrantes, Fatigue Resistance, monotonía, strain, Race Readiness, polarización. "
            "Cuando das rangos de potencia, los expresas en vatios y en % de FTP/CP. "
            "Si no tienes datos suficientes para una recomendación, lo indicas claramente. "
            "No inventes datos que no aparecen en el contexto.\n\n"
            f"# Fecha actual: {today_str}\n"
            "Usa esta fecha como referencia para 'hoy', 'esta semana', 'últimos días', etc.\n\n"
            "# Datos del atleta\n"
            f"{ctx}\n\n"
            f"{tools_desc}\n\n"
            "IMPORTANTE: Si el usuario pide datos específicos (mejores marcas, actividades de un periodo, "
            "comparaciones, estadísticas históricas), USA las herramientas de consulta para obtener datos reales. "
            "No respondas con datos inventados si puedes consultarlos. "
            f"Cuando el usuario dice 'hoy' se refiere a {today_str}. "
            "Cuando dice 'esta semana' calcula el lunes más reciente como inicio.\n\n"
            "Responde de forma concisa y estructurada. "
            "Usa bullet points y negritas para destacar lo importante."
        )

    # ---- Gestión de conversaciones (persistencia) --------------------------

    def new_conversation(self) -> int:
        """Crea una nueva conversación en DB y la activa."""
        self._history.clear()
        self._system_prompt = ""
        try:
            session = get_session()
            conv = AiConversation(title="Nueva conversación", model=self._model)
            session.add(conv)
            session.commit()
            self._conversation_id = conv.id
            session.close()
        except Exception as exc:
            log.error("Error al crear conversación: %s", exc)
            self._conversation_id = None
        return self._conversation_id or 0

    def load_conversation(self, conv_id: int) -> bool:
        """Carga una conversación existente desde la DB."""
        try:
            session = get_session()
            conv = session.query(AiConversation).filter_by(id=conv_id).first()
            if conv is None:
                session.close()
                return False

            messages = (
                session.query(AiMessage)
                .filter_by(conversation_id=conv_id)
                .order_by(AiMessage.created_at)
                .all()
            )

            self._history.clear()
            for msg in messages:
                self._history.append(ChatMessage(
                    role=msg.role,
                    content=msg.content,
                    timestamp=msg.created_at,
                ))

            self._conversation_id = conv_id
            self._system_prompt = ""  # se regenerará al enviar
            session.close()
            return True
        except Exception as exc:
            log.error("Error al cargar conversación %d: %s", conv_id, exc)
            return False

    def list_conversations(self) -> List[ConversationSummary]:
        """Lista todas las conversaciones, más recientes primero."""
        try:
            session = get_session()
            convs = (
                session.query(AiConversation)
                .order_by(desc(AiConversation.updated_at))
                .all()
            )
            result = []
            for c in convs:
                count = (
                    session.query(AiMessage)
                    .filter_by(conversation_id=c.id)
                    .count()
                )
                result.append(ConversationSummary(
                    id=c.id,
                    title=c.title,
                    model=c.model,
                    message_count=count,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                ))
            session.close()
            return result
        except Exception as exc:
            log.error("Error al listar conversaciones: %s", exc)
            return []

    def delete_conversation(self, conv_id: int) -> bool:
        """Elimina una conversación y todos sus mensajes."""
        try:
            session = get_session()
            session.query(AiMessage).filter_by(conversation_id=conv_id).delete()
            session.query(AiConversation).filter_by(id=conv_id).delete()
            session.commit()
            session.close()
            if self._conversation_id == conv_id:
                self._conversation_id = None
                self._history.clear()
            return True
        except Exception as exc:
            log.error("Error al eliminar conversación %d: %s", conv_id, exc)
            return False

    def search_conversations(self, query: str) -> List[ConversationSummary]:
        """Busca conversaciones por contenido de mensajes o título."""
        if not query.strip():
            return self.list_conversations()
        try:
            session = get_session()
            pattern = f"%{query.strip()}%"

            # IDs de conversaciones con mensajes que coinciden
            msg_conv_ids = (
                session.query(AiMessage.conversation_id)
                .filter(AiMessage.content.ilike(pattern))
                .distinct()
                .all()
            )
            msg_ids = {r[0] for r in msg_conv_ids}

            # Conversaciones cuyo título coincide
            title_convs = (
                session.query(AiConversation)
                .filter(AiConversation.title.ilike(pattern))
                .all()
            )
            title_ids = {c.id for c in title_convs}

            all_ids = msg_ids | title_ids
            if not all_ids:
                session.close()
                return []

            convs = (
                session.query(AiConversation)
                .filter(AiConversation.id.in_(all_ids))
                .order_by(desc(AiConversation.updated_at))
                .all()
            )
            result = []
            for c in convs:
                count = (
                    session.query(AiMessage)
                    .filter_by(conversation_id=c.id)
                    .count()
                )
                result.append(ConversationSummary(
                    id=c.id,
                    title=c.title,
                    model=c.model,
                    message_count=count,
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                ))
            session.close()
            return result
        except Exception as exc:
            log.error("Error al buscar conversaciones: %s", exc)
            return []

    def _persist_message(self, role: str, content: str) -> None:
        """Guarda un mensaje en la DB."""
        if self._conversation_id is None:
            return
        try:
            session = get_session()
            msg = AiMessage(
                conversation_id=self._conversation_id,
                role=role,
                content=content,
            )
            session.add(msg)

            # Actualizar updated_at de la conversación
            conv = session.query(AiConversation).filter_by(id=self._conversation_id).first()
            if conv:
                conv.updated_at = datetime.now(timezone.utc)

            session.commit()
            session.close()
        except Exception as exc:
            log.error("Error al persistir mensaje: %s", exc)

    def _auto_title(self, first_user_msg: str) -> None:
        """Genera título automático a partir del primer mensaje del usuario."""
        if self._conversation_id is None:
            return
        title = first_user_msg.strip().replace("\n", " ")
        if len(title) > MAX_TITLE_LEN:
            title = title[:MAX_TITLE_LEN - 1] + "…"
        try:
            session = get_session()
            conv = session.query(AiConversation).filter_by(id=self._conversation_id).first()
            if conv and conv.title == "Nueva conversación":
                conv.title = title
                session.commit()
            session.close()
        except Exception as exc:
            log.error("Error al auto-titular: %s", exc)

    # ---- Exportar conversación ---------------------------------------------

    def export_conversation_md(self, conv_id: Optional[int] = None) -> str:
        """Exporta una conversación como texto Markdown."""
        target_id = conv_id or self._conversation_id
        if target_id is None:
            return ""
        try:
            session = get_session()
            conv = session.query(AiConversation).filter_by(id=target_id).first()
            if conv is None:
                session.close()
                return ""

            messages = (
                session.query(AiMessage)
                .filter_by(conversation_id=target_id)
                .order_by(AiMessage.created_at)
                .all()
            )

            lines: List[str] = []
            lines.append(f"# {conv.title}")
            lines.append(f"Modelo: {conv.model}")
            date_str = conv.created_at.strftime("%d/%m/%Y %H:%M") if conv.created_at else ""
            lines.append(f"Fecha: {date_str}")
            lines.append("")
            lines.append("---")
            lines.append("")

            for msg in messages:
                role_label = "🚴 **Tú**" if msg.role == "user" else "🤖 **Consejero IA**"
                time_str = msg.created_at.strftime("%H:%M") if msg.created_at else ""
                lines.append(f"### {role_label} — {time_str}")
                lines.append("")
                lines.append(msg.content)
                lines.append("")

            session.close()
            return "\n".join(lines)
        except Exception as exc:
            log.error("Error al exportar conversación: %s", exc)
            return ""

    # ---- Chat (streaming) --------------------------------------------------

    def refresh_context(self, user_msg: str = "") -> None:
        """Actualiza el system prompt con datos frescos de la DB."""
        self._system_prompt = self._build_system_prompt(user_msg)

    def clear_history(self) -> None:
        """Limpia el historial de conversación en memoria (no borra de DB)."""
        self._history.clear()
        self._conversation_id = None

    def _build_messages(self, user_msg: str) -> List[Dict[str, str]]:
        """Compone la lista de mensajes para la API de Ollama."""
        if not self._system_prompt:
            self.refresh_context(user_msg)

        messages = [{"role": "system", "content": self._system_prompt}]

        # Historial (últimos 20 mensajes para no exceder contexto)
        for msg in self._history[-20:]:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": user_msg})
        return messages

    def send_message_stream(
        self,
        user_msg: str,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Envía un mensaje y procesa la respuesta en streaming.

        Persiste automáticamente en la DB. Si no hay conversación activa,
        crea una nueva.

        Args:
            user_msg: Mensaje del usuario.
            on_token: Callback invocado con cada fragmento de texto.

        Returns:
            Respuesta completa del modelo.

        Raises:
            ConnectionError: Si Ollama no está accesible.
            RuntimeError: Si el modelo devuelve un error.
        """
        # Crear conversación si no existe
        if self._conversation_id is None:
            self.new_conversation()

        is_first_message = len(self._history) == 0

        messages = self._build_messages(user_msg)

        # Registrar mensaje del usuario
        self._history.append(ChatMessage(role="user", content=user_msg))
        self._persist_message("user", user_msg)

        # Auto-titular con el primer mensaje
        if is_first_message:
            self._auto_title(user_msg)

        try:
            r = requests.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": True,
                },
                stream=True,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            r.raise_for_status()
        except ConnectionError:
            self._history.pop()  # quitar el msg del usuario si falla
            raise ConnectionError(
                f"No se puede conectar con Ollama en {self._base_url}. "
                "Verifica que Ollama está ejecutándose."
            )
        except Exception as exc:
            self._history.pop()
            raise RuntimeError(f"Error al comunicar con Ollama: {exc}")

        # ── Importar tool-use antes de la primera llamada ──────────────
        try:
            from .data_queries import parse_and_execute_queries, QUERY_PATTERN
        except ImportError:
            from services.data_queries import parse_and_execute_queries, QUERY_PATTERN

        # ── Primera llamada: recoger respuesta SIN streamear ─────────────
        # Bufferamos para detectar [QUERY:...] antes de mostrar nada.
        first_response_tokens: list[str] = []
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            token = chunk.get("message", {}).get("content", "")
            if token:
                first_response_tokens.append(token)
            if chunk.get("done", False):
                break

        first_text = "".join(first_response_tokens)
        first_text = self._strip_think_tags(first_text)

        # ── Tool-use: detectar y ejecutar [QUERY: ...] ──────────────────
        if QUERY_PATTERN.search(first_text):
            query_results = parse_and_execute_queries(first_text)
            if query_results:
                tool_output_parts = []
                for original, func_name, result in query_results:
                    tool_output_parts.append(
                        f"Resultado de {func_name}:\n{result}"
                    )
                tool_output = "\n\n".join(tool_output_parts)

                # Notificar que estamos consultando datos
                if on_token:
                    on_token("✨ *Consultando tus datos...*\n\n")

                # Segunda llamada: inyectar resultados y pedir respuesta final
                followup_messages = messages.copy()
                followup_messages.append({"role": "assistant", "content": first_text})
                followup_messages.append({
                    "role": "system",
                    "content": (
                        "He ejecutado tus consultas. Aquí están los resultados:\n\n"
                        f"{tool_output}\n\n"
                        "Ahora responde al usuario usando estos datos reales. "
                        "No incluyas los tags [QUERY: ...] en tu respuesta final. "
                        "Presenta los datos de forma clara y amigable."
                    ),
                })

                try:
                    r2 = requests.post(
                        f"{self._base_url}/api/chat",
                        json={
                            "model": self._model,
                            "messages": followup_messages,
                            "stream": True,
                        },
                        stream=True,
                        timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                    )
                    r2.raise_for_status()

                    final_response = []
                    for line2 in r2.iter_lines(decode_unicode=True):
                        if not line2:
                            continue
                        try:
                            chunk2 = json.loads(line2)
                        except json.JSONDecodeError:
                            continue
                        token2 = chunk2.get("message", {}).get("content", "")
                        if token2:
                            final_response.append(token2)
                            if on_token:
                                on_token(token2)
                        if chunk2.get("done", False):
                            break

                    assistant_text = self._strip_think_tags("".join(final_response))

                except Exception as exc:
                    log.warning("Error en segunda llamada tool-use: %s", exc)
                    assistant_text = QUERY_PATTERN.sub("", first_text).strip()
            else:
                # Queries detectadas pero no ejecutables — emitir el texto limpio
                assistant_text = QUERY_PATTERN.sub("", first_text).strip()
                if on_token:
                    on_token(assistant_text)
        else:
            # Sin queries: emitir los tokens bufferizados al UI
            assistant_text = first_text
            if on_token:
                on_token(assistant_text)

        # Registrar respuesta en memoria y DB
        self._history.append(ChatMessage(role="assistant", content=assistant_text))
        self._persist_message("assistant", assistant_text)

        # Indexar la conversación en el store de embeddings (async-safe)
        self._try_index_conversation()

        return assistant_text

    def _try_index_conversation(self) -> None:
        """Intenta indexar la conversación actual en el store de embeddings.

        No falla si el store no está disponible (Ollama sin modelo de embeddings).
        """
        if self._conversation_id is None:
            return
        try:
            store = _get_embedding_store()
            if store.is_available():
                store.index_conversation(self._conversation_id)
        except Exception as exc:
            log.debug("No se pudo indexar conversación %d: %s",
                      self._conversation_id, exc)

    @staticmethod
    def get_embedding_store():
        """Acceso público al store de embeddings para la UI."""
        return _get_embedding_store()

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Elimina bloques <think>...</think> que DeepSeek R1 usa internamente."""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # ---- Acciones rápidas --------------------------------------------------

    @staticmethod
    def _is_english() -> bool:
        from i18n import get_language
        return get_language() == "en"

    def quick_form_analysis(self) -> str:
        if self._is_english():
            return (
                "Analyze my current form based on CTL, ATL and TSB. "
                "Tell me if I'm in good shape, fatigued or at risk of overtraining. "
                "Suggest how to adjust load for the next 3-5 days."
            )
        return (
            "Analiza mi estado de forma actual basándote en CTL, ATL y TSB. "
            "Indica si estoy en buena forma, fatigado o en riesgo de sobreentrenamiento. "
            "Sugiere cómo ajustar la carga de los próximos 3-5 días."
        )

    def quick_week_review(self) -> str:
        if self._is_english():
            return (
                "Give me a summary of my training week. "
                "Analyze load distribution, sessions completed, "
                "and suggest improvements for next week."
            )
        return (
            "Haz un resumen de mi semana de entrenamiento. "
            "Analiza la distribución de carga, las sesiones realizadas, "
            "y sugiere mejoras para la próxima semana."
        )

    def quick_training_suggestion(self) -> str:
        if self._is_english():
            return (
                "Based on my current form (TSB) and recent sessions, "
                "suggest an appropriate workout for today. "
                "Include power zones, duration and workout structure."
            )
        return (
            "Basándote en mi estado de forma actual (TSB) y las sesiones recientes, "
            "sugiere un entrenamiento adecuado para hoy. "
            "Incluye zonas de potencia, duración y estructura del entreno."
        )

    def quick_ftp_advice(self) -> str:
        if self._is_english():
            return (
                "Analyze my current FTP and, if CP/W' data is available, discuss how they relate. "
                "Should I do an FTP test soon? How is my W/kg ratio?"
            )
        return (
            "Analiza mi FTP actual y, si tengo datos de CP/W', comenta cómo se relacionan. "
            "¿Debería hacer un test de FTP pronto? ¿Cómo está mi ratio W/kg?"
        )

    def quick_full_report(self) -> str:
        """Prompt para un informe completo del estado del ciclista."""
        if self._is_english():
            return (
                "Generate a FULL REPORT of my cycling status analyzing ALL available data. "
                "The report should include these sections:\n\n"
                "1. **Form status** — CTL, ATL, TSB and what they mean for me now.\n"
                "2. **Power model** — FTP, CP, W', W/kg ratio and what they say about my profile.\n"
                "3. **MMP curve** — strengths and weaknesses by duration (sprint, VO2max, threshold, endurance).\n"
                "4. **Recent trends** — volume, load, intensity and polarized distribution evolution.\n"
                "5. **Efficiency and durability** — EF, Pw:Hr decoupling, Fatigue Resistance, quadrant analysis.\n"
                "6. **Monotony and variability** — overtraining risk, stimulus variation.\n"
                "7. **Race Readiness** — score and current competitive readiness.\n"
                "8. **Areas for improvement** — 3-5 specific points with recommended actions.\n"
                "9. **2-4 week forecast** — what to expect if I continue the current trend.\n\n"
                "Be thorough but structured. Use concrete data (numbers) from my profile."
            )
        return (
            "Genera un INFORME COMPLETO de mi estado como ciclista analizando TODOS mis datos disponibles. "
            "El informe debe incluir estas secciones:\n\n"
            "1. **Estado de forma** — CTL, ATL, TSB y qué significan para mí ahora.\n"
            "2. **Modelo de potencia** — FTP, CP, W', ratio W/kg y qué dicen de mi perfil.\n"
            "3. **Curva MMP** — fortalezas y debilidades por duración (sprint, VO2max, umbral, resistencia).\n"
            "4. **Tendencias recientes** — evolución de volumen, carga, intensidad y distribución polarizada.\n"
            "5. **Eficiencia y durabilidad** — EF, Pw:Hr decoupling, Fatigue Resistance, análisis de cuadrantes.\n"
            "6. **Monotonía y variabilidad** — riesgo de sobreentrenamiento, variación de estímulos.\n"
            "7. **Race Readiness** — puntuación y preparación competitiva actual.\n"
            "8. **Áreas de mejora** — 3-5 puntos concretos con acciones recomendadas.\n"
            "9. **Pronóstico a 2-4 semanas** — qué esperar si sigo la tendencia actual.\n\n"
            "Sé exhaustivo pero estructurado. Usa datos concretos (números) de mi perfil."
        )

    def quick_training_plan(self, goal: str = "") -> str:
        if self._is_english():
            goal_text = goal.strip() if goal else "improve overall cycling performance"
            return (
                f"Design a structured 4 to 6 week training plan for the following goal: "
                f"{goal_text}.\n\n"
                "The plan should:\n"
                "- Be based on my current data (FTP, CP/W', CTL/ATL/TSB, MMP, zone distribution, durability, "
                "EF, Pw:Hr, quadrants, Fatigue Resistance, monotony/strain, weekly trends, Race Readiness).\n"
                "- Include mesocycles with load progression and recovery weeks.\n"
                "- Detail each week: number of sessions, duration, type (base, VO2max, threshold, sprint, recovery), "
                "target power zones and estimated TSS per session and weekly.\n"
                "- Include key sessions with detailed structure (warm-up, intervals, cool-down).\n"
                "- Adapt load to my current form and fatigue.\n"
                "- Include progress indicators and when to do verification tests."
            )
        goal_text = goal.strip() if goal else "mejorar el rendimiento general en ciclismo"
        return (
            f"Diseña un plan de entrenamiento estructurado de 4 a 6 semanas para el siguiente objetivo: "
            f"{goal_text}.\n\n"
            "El plan debe:\n"
            "- Basarse en mis datos actuales (FTP, CP/W', CTL/ATL/TSB, MMP, distribución de zonas, durabilidad, "
            "EF, Pw:Hr, cuadrantes, Fatigue Resistance, monotonía/strain, tendencias semanales, Race Readiness).\n"
            "- Incluir mesociclos con progresión de carga y semanas de descarga.\n"
            "- Detallar cada semana: número de sesiones, duración, tipo (base, VO2max, umbral, sprint, recuperación), "
            "zonas de potencia objetivo y TSS estimado por sesión y semanal.\n"
            "- Incluir sesiones clave con estructura detallada (calentamiento, intervalos, recuperación).\n"
            "- Adaptar la carga a mi estado de forma y fatiga actuales.\n"
            "- Incluir indicadores de progreso y cuándo hacer test de verificación."
        )


    # ---- Preguntas sugeridas -----------------------------------------------

    def generate_follow_ups(self, assistant_response: str) -> List[str]:
        """Genera 2-3 preguntas de seguimiento basadas en la última respuesta
        y en el contexto real de datos del atleta.

        Combina:
        1) Heurísticas sobre el contenido de la respuesta
        2) Sugerencias contextuales basadas en datos reales (CTL, TSB, etc.)
        No llama al LLM — es instantáneo.
        """
        text = assistant_response.lower()
        suggestions: List[str] = []
        en = self._is_english()

        # --- 1. Reglas basadas en contenido de la respuesta ---
        if "ftp" in text or "umbral" in text or "threshold" in text:
            suggestions.append("When should I do an FTP test?" if en else "¿Cuándo debería hacer un test de FTP?")
        if "ctl" in text or "forma" in text or "form" in text or "tsb" in text:
            suggestions.append("How to peak my form for a race?" if en else "¿Cómo optimizar mi pico de forma para una carrera?")
        if "intervalo" in text or "interval" in text or "vo2" in text or "hiit" in text:
            suggestions.append("Can you detail an interval session for this week?" if en else "¿Puedes detallar una sesión de intervalos para esta semana?")
        if "polariz" in text or "z1" in text or "z2" in text:
            suggestions.append("Is my zone distribution correct for my goals?" if en else "¿Mi distribución de zonas es correcta para mis objetivos?")
        if "descanso" in text or "rest" in text or "recuper" in text or "recover" in text or "fatiga" in text or "fatigue" in text:
            suggestions.append("How many rest days before training hard again?" if en else "¿Cuántos días debería descansar antes de volver a entrenar fuerte?")
        if "plan" in text or "semana" in text or "week" in text or "mesociclo" in text or "mesocycle" in text:
            suggestions.append("Can you export this plan to my calendar?" if en else "¿Puedes exportar este plan a mi calendario?")
            suggestions.append("How to adjust the plan if I miss a key session?" if en else "¿Cómo ajustar el plan si pierdo una sesión clave?")
        if "subida" in text or "mont" in text or "escalad" in text or "climb" in text:
            suggestions.append("How to improve my climbing performance?" if en else "¿Cómo mejorar mi rendimiento en puertos largos?")
        if "sprint" in text or "neuromuscular" in text:
            suggestions.append("What specific sprint work do you recommend?" if en else "¿Qué trabajo específico de sprint me recomiendas?")
        if "ef" in text or "eficiencia" in text or "efficiency" in text or "decoupling" in text:
            suggestions.append("How to improve my aerobic efficiency?" if en else "¿Cómo mejorar mi eficiencia aeróbica?")
        if "monoton" in text or "strain" in text:
            suggestions.append("How to better vary my training stimuli?" if en else "¿Cómo variar mejor mis estímulos de entrenamiento?")
        if "race" in text or "carrera" in text or "competición" in text or "competition" in text:
            suggestions.append("What would be an ideal tapering plan for my next race?" if en else "¿Cuál sería un plan de tapering ideal para mi próxima carrera?")
        if "cp" in text and "w'" in text:
            suggestions.append("How can I work to increase my W'?" if en else "¿Cómo puedo trabajar para aumentar mi W'?")
        if "durabilidad" in text or "durability" in text or "dri" in text:
            suggestions.append("What workouts improve durability?" if en else "¿Qué entrenos mejoran la durabilidad?")

        # --- 2. Sugerencias contextuales basadas en datos reales ---
        if len(suggestions) < 3:
            data_suggestions = self._generate_data_suggestions(en)
            suggestions.extend(data_suggestions)

        # Siempre incluir una genérica si hay pocas
        if len(suggestions) < 2:
            suggestions.append("What should I train tomorrow?" if en else "¿Qué debería entrenar mañana?")
            suggestions.append("Give me a full status summary" if en else "Hazme un resumen completo de mi estado")

        # Deduplicar y limitar a 3
        seen: set[str] = set()
        unique: List[str] = []
        for s in suggestions:
            if s not in seen:
                seen.add(s)
                unique.append(s)
        return unique[:3]

    def _generate_data_suggestions(self, en: bool) -> List[str]:
        """Genera sugerencias basadas en datos reales del atleta.

        Analiza CTL/ATL/TSB, actividades recientes, objetivos activos, etc.
        para proponer preguntas altamente relevantes.
        """
        suggestions: List[str] = []
        try:
            from db.engine import get_session
            from db.models import Activity, TrainingGoal
            from datetime import date, timedelta

            session = get_session()
            today = date.today()

            # --- Analizar actividades recientes ---
            recent = (
                session.query(Activity)
                .filter(Activity.started_at >= datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(days=7))
                .order_by(Activity.started_at.desc())
                .all()
            )

            if not recent:
                # No hay actividades en 7 días
                suggestions.append(
                    "I haven't trained in a while — how should I restart?" if en
                    else "Llevo días sin entrenar, ¿cómo debería retomar?"
                )
            else:
                # TSS de la semana
                week_tss = sum(a.tss or 0 for a in recent)
                n_sessions = len(recent)

                if week_tss > 600:
                    suggestions.append(
                        f"My weekly TSS is {round(week_tss)} — am I overtraining?" if en
                        else f"Mi TSS semanal es {round(week_tss)}, ¿estoy sobreentrenando?"
                    )
                elif week_tss < 200 and n_sessions >= 2:
                    suggestions.append(
                        "My training load is low — can I increase volume safely?" if en
                        else "Mi carga de entrenamiento es baja, ¿puedo subir volumen con seguridad?"
                    )

                # Última actividad
                last_act = recent[0]
                if last_act.tss and last_act.tss > 150:
                    suggestions.append(
                        f"My last session had TSS={round(last_act.tss)} — what recovery do I need?" if en
                        else f"Mi última sesión tuvo TSS={round(last_act.tss)}, ¿qué recuperación necesito?"
                    )

                # Muchas sesiones seguidas sin descanso
                if n_sessions >= 5:
                    suggestions.append(
                        f"{n_sessions} sessions this week — should I take a rest day?" if en
                        else f"{n_sessions} sesiones esta semana, ¿debería descansar?"
                    )

            # --- Objetivos activos ---
            active_goals = (
                session.query(TrainingGoal)
                .filter_by(status="active")
                .order_by(TrainingGoal.created_at.desc())
                .limit(2)
                .all()
            )
            for goal in active_goals:
                suggestions.append(
                    f"How is my progress toward '{goal.title}'?" if en
                    else f"¿Cómo voy con mi objetivo '{goal.title}'?"
                )

            session.close()
        except Exception:
            pass  # nunca bloquear la UI por sugerencias

        return suggestions[:3]

    # ---- Exportar plan a calendario (.ics) ---------------------------------

    @staticmethod
    def _ics_fold_line(line: str) -> str:
        """Pliega una línea según RFC 5545 (max 75 octets por línea).

        Las líneas de continuación empiezan con un espacio.
        """
        encoded = line.encode("utf-8")
        if len(encoded) <= 75:
            return line
        parts: List[str] = []
        while len(encoded) > 75:
            # Cortar en 75 bytes sin romper secuencias UTF-8
            cut = 75 if not parts else 74  # continuaciones tienen " " prefijo
            chunk = encoded[:cut]
            # No cortar en medio de un carácter multi-byte
            while cut > 0 and (chunk[-1] & 0xC0) == 0x80:
                cut -= 1
                chunk = encoded[:cut]
            parts.append(chunk.decode("utf-8"))
            encoded = encoded[cut:]
        if encoded:
            parts.append(encoded.decode("utf-8"))
        return "\r\n ".join(parts)

    @staticmethod
    def _is_rest_day(title: str) -> bool:
        """Detecta si un título corresponde a un día de descanso."""
        rest_words = [
            "descanso", "rest", "off", "día libre", "day off",
            "recuperación pasiva", "passive recovery",
            "yoga", "estiramientos", "stretching",
        ]
        lower = title.lower()
        # Extraer parte tras separador (día: contenido)
        content = lower
        for sep in (":", "—"):
            if sep in lower:
                content = lower.split(sep, 1)[1].strip()
                break
        # Comprobar si el contenido EMPIEZA con una palabra de descanso
        for kw in rest_words:
            if content == kw or content.startswith(kw + " ") or content.startswith(kw + ","):
                return True
        return False

    @staticmethod
    def export_plan_to_ics(plan_text: str, start_date: Optional[date] = None) -> str:
        """Convierte un plan de entrenamiento en texto a formato iCalendar (.ics).

        Parsea la respuesta del coach buscando patrones de sesiones
        y genera eventos con título, descripción y duración.
        Cumple RFC 5545 (line folding, CRLF, codificación UTF-8).

        Args:
            plan_text: Texto del plan generado por el coach.
            start_date: Fecha de inicio del plan (default: próximo lunes).

        Returns:
            Contenido del archivo .ics como string.
        """
        if start_date is None:
            # Próximo lunes
            today = date.today()
            days_ahead = (7 - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            start_date = today + timedelta(days=days_ahead)

        events: List[Dict[str, Any]] = []
        current_week = 0
        day_in_week = 0  # 0=Lun, 6=Dom

        lines = plan_text.split("\n")
        for line in lines:
            stripped = line.strip().lower()

            # Detectar encabezado de semana (ES/EN)
            week_match = re.search(r"(?:semana|week)\s*(\d+)", stripped)
            if week_match:
                current_week = int(week_match.group(1)) - 1  # 0-indexed
                day_in_week = 0
                continue

            # Detectar sesiones
            is_session = False
            session_title = ""
            session_duration_min = 60  # default

            # Patrón: día de la semana (ES + EN)
            day_names = {
                "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
                "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6,
                "monday": 0, "tuesday": 1, "wednesday": 2,
                "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            }
            # Limpiar prefijos comunes antes de buscar día
            clean = re.sub(r'^[\s\-•*|📅🔹▸]+', '', stripped)
            clean = re.sub(r'\*{1,2}', '', clean).strip()
            for day_name, day_num in day_names.items():
                if clean.startswith(day_name) or day_name in clean:
                    day_in_week = day_num
                    session_title = line.strip().lstrip("- •*|📅🔹▸").strip()
                    session_title = re.sub(r'\*{1,2}', '', session_title).strip()
                    is_session = True
                    break

            # Patrón: "Día X:" / "Day X:" o bullets con tipo de entreno
            if not is_session:
                day_match = re.search(r"(?:d[ií]a|day)\s*(\d+)", stripped)
                if day_match:
                    day_in_week = (int(day_match.group(1)) - 1) % 7
                    session_title = line.strip().lstrip("- *").strip()
                    is_session = True

            if not is_session:
                # Buscar bullets con palabras clave de sesión
                session_keywords = [
                    "base", "resistencia", "tempo", "umbral", "vo2", "sprint",
                    "intervalos", "intervals", "recuperación", "recovery",
                    "fuerza", "strength", "endurance", "rodillo", "bici",
                    "sweet spot", "threshold", "z1", "z2", "z3", "z4", "z5",
                    "aerob", "anaerob", "potencia", "power", "cadencia",
                    "series", "repeticiones", "reps", "hiit", "tabata",
                    "calentamiento", "warm", "cool", "progresivo",
                ]
                is_bullet = stripped.startswith(("-", "•", "*", "▸", "🔹"))
                if is_bullet and any(kw in stripped for kw in session_keywords):
                    session_title = line.strip().lstrip("- •*▸🔹").strip()
                    session_title = re.sub(r'\*{1,2}', '', session_title).strip()
                    is_session = True

            if not is_session:
                continue

            # Detectar duración en la línea
            dur_match = re.search(r"(\d+)\s*(?:min(?:utos?|utes?)?|')", stripped)
            if dur_match:
                session_duration_min = int(dur_match.group(1))
            dur_h_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:h(?:oras?|ours?|r)?)", stripped)
            if dur_h_match:
                hours = float(dur_h_match.group(1).replace(",", "."))
                session_duration_min = round(hours * 60)

            # Limpiar título
            session_title = re.sub(r"\*{1,2}", "", session_title).strip()
            if not session_title or AiCoachService._is_rest_day(session_title):
                continue

            event_date = start_date + timedelta(weeks=current_week, days=day_in_week)

            events.append({
                "date": event_date,
                "title": session_title[:80],
                "description": session_title,
                "duration_min": session_duration_min,
            })

            day_in_week = min(day_in_week + 1, 6)

        # Generar .ics — RFC 5545 compliant
        fold = AiCoachService._ics_fold_line
        cal_lines: List[str] = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Ciclometricas//AI Coach//ES",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            fold("X-WR-CALNAME:Plan Entrenamiento Ciclometricas"),
        ]

        for i, ev in enumerate(events):
            dt_start = datetime.combine(ev["date"], datetime.min.time().replace(hour=7))
            dt_end = dt_start + timedelta(minutes=ev["duration_min"])
            uid = f"cm-plan-{ev['date'].isoformat()}-{i}@ciclometricas"

            # Escapar caracteres especiales en iCal
            desc = ev["description"].replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
            summary = ev["title"].replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")

            cal_lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}",
                f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}",
                fold(f"SUMMARY:{summary}"),
                fold(f"DESCRIPTION:{desc}"),
                "STATUS:TENTATIVE",
                f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
                "BEGIN:VALARM",
                "TRIGGER:-PT30M",
                "ACTION:DISPLAY",
                "DESCRIPTION:Entrenamiento en 30 minutos",
                "END:VALARM",
                "END:VEVENT",
            ])

        cal_lines.append("END:VCALENDAR")
        return "\r\n".join(cal_lines)


# ---------------------------------------------------------------------------
# Instancia global (singleton)
# ---------------------------------------------------------------------------
_instance: AiCoachService | None = None

_SENTINEL = object()

def get_ai_coach(
    ollama_url: str | object = _SENTINEL,
    model: str | object = _SENTINEL,
) -> AiCoachService:
    """Devuelve la instancia singleton del Consejero IA.

    Si se llama sin argumentos y ya existe la instancia, la devuelve sin
    modificar su configuración (evita sobreescribir url/modelo guardados).
    """
    global _instance
    if _instance is None:
        url = ollama_url if ollama_url is not _SENTINEL else DEFAULT_OLLAMA_URL
        mdl = model if model is not _SENTINEL else DEFAULT_MODEL
        _instance = AiCoachService(ollama_url=str(url), model=str(mdl))
    else:
        if ollama_url is not _SENTINEL:
            _instance.base_url = str(ollama_url)
        if model is not _SENTINEL:
            _instance.model = str(model)
    return _instance
