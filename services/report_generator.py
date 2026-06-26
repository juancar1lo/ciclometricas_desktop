"""Generador de informe PDF del atleta.

Usa *reportlab* para la estructura del PDF y *matplotlib* para gráficos
estáticos incrustados como imágenes. Todo local, sin dependencias externas.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── dependencias opcionales (reportlab / matplotlib / Pillow) ──────────────
# Se cargan con _ensure_pdf_deps() antes de usarlas.
# Esto permite que el módulo se importe siempre, aunque falten los paquetes.
_PDF_DEPS_LOADED = False
_PDF_DEPS_ERROR: str = ""

# Placeholders — se rellenan con _ensure_pdf_deps()
plt = None  # type: ignore
ticker = None  # type: ignore
rl_colors = None  # type: ignore
TA_CENTER = 1
TA_LEFT = 0
TA_RIGHT = 2
A4 = (595.27, 841.89)
cm = 28.346456692913385
mm = 2.8346456692913385
ParagraphStyle = None  # type: ignore
getSampleStyleSheet = None  # type: ignore
RLImage = None  # type: ignore
PageBreak = None  # type: ignore
Paragraph = None  # type: ignore
SimpleDocTemplate = None  # type: ignore
Spacer = None  # type: ignore
Table = None  # type: ignore
TableStyle = None  # type: ignore


def _ensure_pdf_deps() -> None:
    """Importa matplotlib + reportlab de forma lazy; lanza ImportError si falta algo."""
    global _PDF_DEPS_LOADED, _PDF_DEPS_ERROR
    global plt, ticker, rl_colors
    global TA_CENTER, TA_LEFT, TA_RIGHT, A4, cm, mm
    global ParagraphStyle, getSampleStyleSheet
    global RLImage, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    if _PDF_DEPS_LOADED:
        return

    missing: list[str] = []
    for pkg in ("reportlab", "matplotlib", "PIL"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append("Pillow" if pkg == "PIL" else pkg)
    if missing:
        _PDF_DEPS_ERROR = (
            f"Paquetes no encontrados: {', '.join(missing)}.\n"
            f"Instálalos con:  pip install {' '.join(missing)}"
        )
        raise ImportError(_PDF_DEPS_ERROR)

    import matplotlib as _mpl
    _mpl.use("Agg")
    import matplotlib.pyplot as _plt
    import matplotlib.ticker as _ticker

    from reportlab.lib import colors as _rl_colors
    from reportlab.lib.enums import TA_CENTER as _TA_CENTER, TA_LEFT as _TA_LEFT, TA_RIGHT as _TA_RIGHT
    from reportlab.lib.pagesizes import A4 as _A4
    from reportlab.lib.styles import ParagraphStyle as _PS, getSampleStyleSheet as _gSS
    from reportlab.lib.units import cm as _cm, mm as _mm
    from reportlab.platypus import (
        Image as _RLImage,
        PageBreak as _PageBreak,
        Paragraph as _Paragraph,
        SimpleDocTemplate as _SimpleDocTemplate,
        Spacer as _Spacer,
        Table as _Table,
        TableStyle as _TableStyle,
    )

    plt = _plt
    ticker = _ticker
    rl_colors = _rl_colors
    TA_CENTER = _TA_CENTER
    TA_LEFT = _TA_LEFT
    TA_RIGHT = _TA_RIGHT
    A4 = _A4
    cm = _cm
    mm = _mm
    ParagraphStyle = _PS
    getSampleStyleSheet = _gSS
    RLImage = _RLImage
    PageBreak = _PageBreak
    Paragraph = _Paragraph
    SimpleDocTemplate = _SimpleDocTemplate
    Spacer = _Spacer
    Table = _Table
    TableStyle = _TableStyle

    _PDF_DEPS_LOADED = True

# ── proyecto (imports absolutos, como el resto del proyecto) ────────────────
from calc.fitness import FitnessPoint, build_fitness_series
from calc.zones import POWER_ZONES, HR_ZONES, ZoneDef
from calc.mmp import compute_mmp
from calc.cp_model import (
    fit_cp_model, CpModelResult, PowerTestPoint,
    estimate_vo2max, estimate_mftp, reliability_from_r2,
)
from calc.monotony import calc_week_monotony, classify_monotony, classify_strain
from calc.race_readiness import calc_race_readiness, RrsInput
from db.models import Activity, ProfileSnapshot, PowerTestSet, HealthMetric
from db.engine import get_session

from sqlalchemy import desc

# ── constantes de estilo ────────────────────────────────────────────────────
COLOR_PRIMARY = "#FF6B35"       # naranja Ciclométricas
COLOR_BG_DARK = "#0F172A"       # navy oscuro
COLOR_TEXT = "#1E293B"
COLOR_MUTED = "#64748B"
COLOR_GREEN = "#22C55E"
COLOR_RED = "#EF4444"
COLOR_AMBER = "#F59E0B"
COLOR_CYAN = "#06B6D4"

# PAGE_W, PAGE_H, _page_dims()[2] se resuelven en tiempo de ejecución
# (dependen de A4/cm que se cargan con _ensure_pdf_deps)
def _page_dims():
    return A4[0], A4[1], 1.8 * cm


# ── helpers ─────────────────────────────────────────────────────────────────
def _hex(h: str):
    """Convierte '#RRGGBB' a reportlab Color."""
    _ensure_pdf_deps()
    h = h.lstrip("#")
    return rl_colors.Color(
        int(h[0:2], 16) / 255,
        int(h[2:4], 16) / 255,
        int(h[4:6], 16) / 255,
    )


def _fmt_duration(secs: float) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def _chart_to_image(fig, width_cm: float = 16, dpi: int = 150):
    """Convierte un Figure de matplotlib a una Image de reportlab."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    w = width_cm * cm
    # Calcular ratio del chart para mantener aspect ratio
    buf_copy = io.BytesIO(buf.read())
    buf.seek(0)
    from PIL import Image as PILImage
    try:
        pil = PILImage.open(buf_copy)
        ratio = pil.height / pil.width
        h = w * ratio
    except Exception:
        h = w * 0.55
    return RLImage(buf, width=w, height=h)


# ── gráficos matplotlib ────────────────────────────────────────────────────
def _chart_fitness(series: List[FitnessPoint]) -> Optional[plt.Figure]:
    """Gráfico de CTL/ATL/TSB."""
    _ensure_pdf_deps()
    if not series or len(series) < 7:
        return None
    dates = [p.date for p in series]
    ctl = [p.ctl for p in series]
    atl = [p.atl for p in series]
    tsb = [p.tsb for p in series]

    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.plot(dates, ctl, color=COLOR_CYAN, linewidth=1.5, label="CTL (Fitness)")
    ax.plot(dates, atl, color=COLOR_RED, linewidth=1.5, label="ATL (Fatiga)")
    ax.fill_between(dates, tsb, 0, alpha=0.25,
                    color=COLOR_GREEN, label="TSB (Forma)")
    ax.axhline(0, color="#94A3B8", linewidth=0.5, linestyle="--")
    ax.set_ylabel("Valor")
    ax.legend(loc="upper left", fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def _chart_zones_bar(zone_secs: Dict[str, float], zone_defs: List[ZoneDef],
                     title: str) -> Optional[plt.Figure]:
    """Gráfico de barras horizontal de zonas."""
    _ensure_pdf_deps()
    if not zone_secs:
        return None
    keys = sorted(zone_secs.keys())
    total = sum(zone_secs.values()) or 1
    labels = []
    pcts = []
    bar_colors = []
    zd_map = {z.key: z for z in zone_defs}
    for k in keys:
        zd = zd_map.get(k)
        lbl = zd.short_label if zd else k.upper()
        labels.append(lbl)
        pcts.append(zone_secs[k] / total * 100)
        bar_colors.append(zd.color if zd else "#94A3B8")

    fig, ax = plt.subplots(figsize=(7, max(2, len(keys) * 0.45)))
    y_pos = range(len(keys))
    bars = ax.barh(y_pos, pcts, color=bar_colors, edgecolor="white", height=0.6)
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("%")
    ax.set_title(title, fontsize=9, fontweight="bold")
    for bar, pct in zip(bars, pcts):
        if pct >= 2:
            ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                    f"{pct:.1f}%", va="center", fontsize=7)
    ax.set_xlim(0, max(pcts) * 1.15 if pcts else 100)
    ax.invert_yaxis()
    fig.tight_layout()
    return fig


def _chart_mmp(mmp_data: Dict[int, float], cp: Optional[float] = None) -> Optional[plt.Figure]:
    """Curva MMP en escala logarítmica."""
    _ensure_pdf_deps()
    if not mmp_data:
        return None
    durations = sorted(mmp_data.keys())
    watts = [mmp_data[d] for d in durations]

    fig, ax = plt.subplots(figsize=(7, 3))
    ax.plot(durations, watts, color=COLOR_PRIMARY, linewidth=1.8)
    if cp:
        ax.axhline(cp, color=COLOR_CYAN, linewidth=1, linestyle="--",
                   label=f"CP = {round(cp)} W")
        ax.legend(fontsize=7)
    ax.set_xscale("log")
    ax.set_xlabel("Duración")
    ax.set_ylabel("Potencia (W)")
    ax.set_title("Curva de Potencia Máxima (MMP)", fontsize=9, fontweight="bold")

    # Ticks personalizados
    tick_vals = [5, 10, 30, 60, 300, 600, 1200, 3600]
    tick_labels = ["5s", "10s", "30s", "1m", "5m", "10m", "20m", "60m"]
    ax.set_xticks(tick_vals)
    ax.set_xticklabels(tick_labels, fontsize=7)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def _chart_weekly_tss(weekly_data: List[Tuple[str, float, float]]) -> Optional[plt.Figure]:
    """Gráfico de barras de TSS semanal con línea de horas."""
    _ensure_pdf_deps()
    if not weekly_data:
        return None
    weeks = [w[0] for w in weekly_data]
    tss_vals = [w[1] for w in weekly_data]
    hrs_vals = [w[2] for w in weekly_data]

    fig, ax1 = plt.subplots(figsize=(7, 2.8))
    x = range(len(weeks))
    ax1.bar(x, tss_vals, color=COLOR_PRIMARY, alpha=0.8, label="TSS")
    ax1.set_ylabel("TSS", fontsize=8)
    ax1.set_xticks(x)
    ax1.set_xticklabels(weeks, fontsize=7, rotation=15)

    ax2 = ax1.twinx()
    ax2.plot(x, hrs_vals, color=COLOR_CYAN, marker="o", markersize=4,
             linewidth=1.5, label="Horas")
    ax2.set_ylabel("Horas", fontsize=8)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=7, loc="upper left")
    ax1.grid(True, alpha=0.2)
    fig.tight_layout()
    return fig


# ── clase principal ─────────────────────────────────────────────────────────
@dataclass
class ReportData:
    """Datos recopilados para el informe."""
    generated_at: datetime = field(default_factory=datetime.now)

    # Perfil
    athlete_name: str = "Atleta"
    ftp: Optional[int] = None
    weight_kg: Optional[float] = None
    hr_max: Optional[int] = None
    hr_lthr: Optional[int] = None

    # CP model
    cp: Optional[float] = None
    w_prime_kj: Optional[float] = None
    vo2max: Optional[float] = None
    m_ftp: Optional[float] = None
    r_squared: Optional[float] = None

    # Fitness
    ctl: Optional[float] = None
    atl: Optional[float] = None
    tsb: Optional[float] = None
    fitness_series: List[FitnessPoint] = field(default_factory=list)

    # Zonas (30d)
    zones_power: Dict[str, float] = field(default_factory=dict)
    zones_hr: Dict[str, float] = field(default_factory=dict)

    # MMP (90d)
    mmp_best: Dict[int, float] = field(default_factory=dict)

    # Semanas
    weekly_summary: List[Tuple[str, float, float]] = field(default_factory=list)  # (label, tss, hrs)

    # Monotonía
    monotony: Optional[float] = None
    monotony_class: str = ""
    strain: Optional[float] = None
    strain_class: str = ""

    # Race Readiness
    rrs_score: Optional[int] = None
    rrs_advice: str = ""

    # Salud
    health_weight: Optional[float] = None
    health_rhr: Optional[int] = None
    health_hrv: Optional[float] = None
    health_readiness: Optional[float] = None

    # Resumen reciente
    recent_sessions: int = 0
    recent_hours: float = 0
    recent_tss: float = 0
    recent_distance_km: float = 0


def collect_report_data() -> ReportData:
    """Recopila todos los datos del atleta desde la BD."""
    rd = ReportData()
    try:
        session = get_session()
    except RuntimeError:
        return rd

    today = date.today()

    # --- Perfil ---
    profile: Optional[ProfileSnapshot] = (
        session.query(ProfileSnapshot)
        .order_by(desc(ProfileSnapshot.effective_at))
        .first()
    )
    if profile:
        rd.ftp = profile.ftp
        rd.weight_kg = profile.weight_kg
        rd.hr_max = profile.hr_max
        rd.hr_lthr = profile.hr_lthr

    # --- CP model ---
    cp_test: Optional[PowerTestSet] = (
        session.query(PowerTestSet)
        .order_by(desc(PowerTestSet.tested_at))
        .first()
    )
    if cp_test and cp_test.cp:
        rd.cp = cp_test.cp
        rd.w_prime_kj = round(cp_test.w_prime / 1000, 1) if cp_test.w_prime else None
        rd.vo2max = round(cp_test.vo2max, 1) if cp_test.vo2max else None
        rd.m_ftp = round(cp_test.m_ftp) if cp_test.m_ftp else None
        rd.r_squared = cp_test.r_squared

    # --- Fitness (90d) ---
    lookback = today - timedelta(days=90)
    activities = (
        session.query(Activity.started_at, Activity.tss)
        .filter(
            Activity.started_at >= datetime.combine(lookback, datetime.min.time()),
            Activity.tss.isnot(None),
        )
        .all()
    )
    if activities:
        act_dicts = [{"started_at": a.started_at, "tss": a.tss} for a in activities]
        series = build_fitness_series(act_dicts, lookback, today)
        if series:
            rd.fitness_series = series
            last = series[-1]
            rd.ctl = round(last.ctl, 1)
            rd.atl = round(last.atl, 1)
            rd.tsb = round(last.tsb, 1)

    # --- Zonas (30d) ---
    zone_lookback = today - timedelta(days=30)
    zone_acts: List[Activity] = (
        session.query(Activity)
        .filter(Activity.started_at >= datetime.combine(zone_lookback, datetime.min.time()))
        .all()
    )
    for act in zone_acts:
        pz = act.get_zones_power()
        if pz:
            for k, v in pz.items():
                rd.zones_power[k] = rd.zones_power.get(k, 0) + (v or 0)
        hz = act.get_zones_hr()
        if hz:
            for k, v in hz.items():
                rd.zones_hr[k] = rd.zones_hr.get(k, 0) + (v or 0)

    # --- MMP (90d) ---
    mmp_acts: List[Activity] = (
        session.query(Activity)
        .filter(
            Activity.started_at >= datetime.combine(lookback, datetime.min.time()),
            Activity.mmp.isnot(None),
        )
        .all()
    )
    best_mmp: Dict[int, float] = {}
    for act in mmp_acts:
        mmp_data = act.get_mmp()
        if mmp_data:
            for dur_str, watts in mmp_data.items():
                dur = int(dur_str)
                if dur not in best_mmp or watts > best_mmp[dur]:
                    best_mmp[dur] = watts
    rd.mmp_best = best_mmp

    # --- Tendencias semanales (4 semanas) ---
    trend_lookback = today - timedelta(days=28)
    trend_acts: List[Activity] = (
        session.query(Activity)
        .filter(Activity.started_at >= datetime.combine(trend_lookback, datetime.min.time()))
        .order_by(Activity.started_at)
        .all()
    )
    if trend_acts:
        weekly: Dict[str, List[Activity]] = {}
        for a in trend_acts:
            if a.started_at:
                iso = a.started_at.isocalendar()
                wk = f"{iso[0]}-W{iso[1]:02d}"
                weekly.setdefault(wk, []).append(a)
        for wk_key in sorted(weekly.keys()):
            acts = weekly[wk_key]
            tss = sum(a.tss or 0 for a in acts)
            hrs = sum((a.duration_sec or 0) for a in acts) / 3600
            rd.weekly_summary.append((wk_key, round(tss), round(hrs, 1)))

    # --- Últimos 7 días ---
    week_ago = today - timedelta(days=7)
    recent: List[Activity] = (
        session.query(Activity)
        .filter(Activity.started_at >= datetime.combine(week_ago, datetime.min.time()))
        .all()
    )
    if recent:
        rd.recent_sessions = len(recent)
        rd.recent_hours = round(sum((a.duration_sec or 0) for a in recent) / 3600, 1)
        rd.recent_tss = round(sum(a.tss or 0 for a in recent))
        rd.recent_distance_km = round(sum(a.distance_km or 0 for a in recent))

    # --- Monotonía ---
    mon_acts: List[Activity] = (
        session.query(Activity)
        .filter(Activity.started_at >= datetime.combine(week_ago, datetime.min.time()))
        .all()
    )
    if mon_acts:
        daily_tss: Dict[int, float] = {}
        for a in mon_acts:
            if a.started_at:
                wd = a.started_at.weekday()
                daily_tss[wd] = daily_tss.get(wd, 0) + (a.tss or 0)
        daily_list = [daily_tss.get(d, 0) for d in range(7)]
        mon_r = calc_week_monotony(daily_list)
        if mon_r.monotony is not None:
            rd.monotony = round(mon_r.monotony, 2)
            cls, _ = classify_monotony(mon_r.monotony)
            rd.monotony_class = cls
            if mon_r.strain is not None:
                rd.strain = round(mon_r.strain)
                s_cls, _ = classify_strain(mon_r.strain)
                rd.strain_class = s_cls

    # --- Race Readiness ---
    if rd.fitness_series and len(rd.fitness_series) > 0:
        last_pt = rd.fitness_series[-1]
        ctl_max = max(p.ctl for p in rd.fitness_series)
        ramp = None
        if len(rd.fitness_series) >= 8:
            ramp = rd.fitness_series[-1].ctl - rd.fitness_series[-8].ctl
        rrs = calc_race_readiness(RrsInput(
            tsb=last_pt.tsb,
            ctl=last_pt.ctl,
            ctl_max=ctl_max,
            ramp_rate=ramp,
            monotony=rd.monotony,
        ))
        rd.rrs_score = rrs.score
        rd.rrs_advice = rrs.advice or ""

    # --- Salud ---
    health: Optional[HealthMetric] = (
        session.query(HealthMetric)
        .order_by(desc(HealthMetric.date))
        .first()
    )
    if health:
        rd.health_weight = health.weight_kg
        rd.health_rhr = health.resting_hr
        rd.health_hrv = health.hrv
        rd.health_readiness = health.readiness

    return rd


# ── generación del PDF ──────────────────────────────────────────────────────
def _make_styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "CTitle", parent=base["Title"],
            fontSize=22, leading=26, textColor=_hex(COLOR_PRIMARY),
            alignment=TA_CENTER, spaceAfter=4 * mm,
        ),
        "subtitle": ParagraphStyle(
            "CSubtitle", parent=base["Normal"],
            fontSize=10, leading=13, textColor=_hex(COLOR_MUTED),
            alignment=TA_CENTER, spaceAfter=8 * mm,
        ),
        "h2": ParagraphStyle(
            "CH2", parent=base["Heading2"],
            fontSize=14, leading=18, textColor=_hex(COLOR_TEXT),
            spaceBefore=10 * mm, spaceAfter=4 * mm,
            borderPadding=(0, 0, 2, 0),
        ),
        "body": ParagraphStyle(
            "CBody", parent=base["Normal"],
            fontSize=9, leading=13, textColor=_hex(COLOR_TEXT),
        ),
        "metric_label": ParagraphStyle(
            "CMetricL", parent=base["Normal"],
            fontSize=8, leading=11, textColor=_hex(COLOR_MUTED),
        ),
        "metric_value": ParagraphStyle(
            "CMetricV", parent=base["Normal"],
            fontSize=12, leading=15, textColor=_hex(COLOR_TEXT),
            alignment=TA_CENTER,
        ),
    }


def _kv_table(pairs: List[Tuple[str, str]], col_widths: Optional[List[float]] = None) -> Table:
    """Tabla simple clave-valor."""
    data = [[Paragraph(f"<b>{k}</b>", getSampleStyleSheet()["Normal"]),
             Paragraph(v, getSampleStyleSheet()["Normal"])]
            for k, v in pairs if v]
    if not data:
        return Spacer(1, 0)
    widths = col_widths or [5.5 * cm, 10 * cm]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), _hex("#F1F5F9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, _hex("#E2E8F0")),
    ]))
    return t


def generate_report(output_path: str, data: Optional[ReportData] = None) -> str:
    """Genera el informe PDF y devuelve la ruta del archivo.

    Si *data* es None, recopila automáticamente desde la BD.
    Lanza ImportError si faltan reportlab/matplotlib/Pillow.
    """
    _ensure_pdf_deps()
    if data is None:
        data = collect_report_data()

    styles = _make_styles()
    elements: List[Any] = []

    # ── Portada ─────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 3 * cm))
    elements.append(Paragraph("Ciclométricas", styles["title"]))
    elements.append(Paragraph("Informe completo del atleta", ParagraphStyle(
        "Sub2", fontSize=13, leading=16, textColor=_hex(COLOR_MUTED),
        alignment=TA_CENTER, spaceAfter=6 * mm,
    )))

    date_str = data.generated_at.strftime("%d/%m/%Y %H:%M")
    elements.append(Paragraph(f"Generado: {date_str}", styles["subtitle"]))
    elements.append(Spacer(1, 1 * cm))

    # Resumen rápido en portada
    summary_items = []
    if data.ftp:
        wkg = round(data.ftp / data.weight_kg, 2) if data.weight_kg else "—"
        summary_items.append(("FTP", f"{data.ftp} W ({wkg} W/kg)"))
    if data.cp:
        summary_items.append(("CP", f"{round(data.cp)} W"))
    if data.w_prime_kj:
        summary_items.append(("W'", f"{data.w_prime_kj} kJ"))
    if data.ctl is not None:
        summary_items.append(("CTL (Fitness)", str(data.ctl)))
    if data.tsb is not None:
        summary_items.append(("TSB (Forma)", str(data.tsb)))
    if data.rrs_score is not None:
        summary_items.append(("Race Readiness", f"{data.rrs_score}/100"))
    if summary_items:
        elements.append(_kv_table(summary_items))

    elements.append(PageBreak())

    # ── 1. Perfil ───────────────────────────────────────────────────────────
    elements.append(Paragraph("1. Perfil del atleta", styles["h2"]))
    profile_pairs = []
    if data.ftp:
        profile_pairs.append(("FTP", f"{data.ftp} W"))
    if data.weight_kg:
        profile_pairs.append(("Peso", f"{data.weight_kg} kg"))
    if data.ftp and data.weight_kg:
        profile_pairs.append(("W/kg", f"{round(data.ftp / data.weight_kg, 2)}"))
    if data.hr_max:
        profile_pairs.append(("FC máx", f"{data.hr_max} ppm"))
    if data.hr_lthr:
        profile_pairs.append(("FCL (umbral)", f"{data.hr_lthr} ppm"))
    if profile_pairs:
        elements.append(_kv_table(profile_pairs))
    else:
        elements.append(Paragraph("No hay perfil configurado.", styles["body"]))

    # ── 2. Modelo CP ────────────────────────────────────────────────────────
    if data.cp:
        elements.append(Paragraph("2. Modelo Critical Power", styles["h2"]))
        cp_pairs = [
            ("CP", f"{round(data.cp)} W"),
        ]
        if data.w_prime_kj:
            cp_pairs.append(("W'", f"{data.w_prime_kj} kJ"))
        if data.m_ftp:
            cp_pairs.append(("mFTP", f"{data.m_ftp} W"))
        if data.vo2max:
            cp_pairs.append(("VO2max est.", f"{data.vo2max} ml/kg/min"))
        if data.r_squared is not None:
            rel = reliability_from_r2(data.r_squared)
            cp_pairs.append(("R²", f"{round(data.r_squared, 3)} ({rel.text})"))
        elements.append(_kv_table(cp_pairs))

    # ── 3. Estado de forma ──────────────────────────────────────────────────
    elements.append(Paragraph("3. Estado de forma (90 días)", styles["h2"]))
    if data.ctl is not None:
        fitness_pairs = [
            ("CTL (Fitness)", str(data.ctl)),
            ("ATL (Fatiga)", str(data.atl)),
            ("TSB (Forma)", str(data.tsb)),
        ]
        # Estado textual
        if data.tsb is not None:
            if data.tsb > 15:
                estado = "Fresco / Transición"
            elif data.tsb > 5:
                estado = "Fresco"
            elif data.tsb > -10:
                estado = "Óptimo para rendir"
            elif data.tsb > -30:
                estado = "Carga productiva"
            else:
                estado = "⚠️ Alto riesgo sobreentrenamiento"
            fitness_pairs.append(("Estado", estado))
        elements.append(_kv_table(fitness_pairs))

        # Gráfico fitness
        fig = _chart_fitness(data.fitness_series)
        if fig:
            elements.append(Spacer(1, 4 * mm))
            elements.append(_chart_to_image(fig))
    else:
        elements.append(Paragraph("Sin datos de fitness disponibles.", styles["body"]))

    # ── 4. Resumen semanal ──────────────────────────────────────────────────
    if data.weekly_summary:
        elements.append(Paragraph("4. Carga semanal (últimas 4 semanas)", styles["h2"]))

        # Tabla
        header = ["Semana", "TSS", "Horas", "TSS/h"]
        rows = [header]
        for wk, tss, hrs in data.weekly_summary:
            tss_h = round(tss / hrs, 1) if hrs > 0 else "—"
            rows.append([wk, str(round(tss)), f"{hrs}h", str(tss_h)])
        t = Table(rows, colWidths=[4 * cm, 3 * cm, 3 * cm, 3 * cm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _hex(COLOR_PRIMARY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, _hex("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, _hex("#F8FAFC")]),
        ]))
        elements.append(t)

        # Gráfico
        fig = _chart_weekly_tss(data.weekly_summary)
        if fig:
            elements.append(Spacer(1, 4 * mm))
            elements.append(_chart_to_image(fig))

    # ── 5. Zonas de potencia ────────────────────────────────────────────────
    if data.zones_power:
        elements.append(Paragraph("5. Distribución de zonas de potencia (30 días)", styles["h2"]))
        fig = _chart_zones_bar(data.zones_power, POWER_ZONES, "Zonas de potencia")
        if fig:
            elements.append(_chart_to_image(fig))

    # ── 6. Zonas de FC ──────────────────────────────────────────────────────
    if data.zones_hr:
        elements.append(Paragraph("6. Distribución de zonas de FC (30 días)", styles["h2"]))
        fig = _chart_zones_bar(data.zones_hr, HR_ZONES, "Zonas de frecuencia cardíaca")
        if fig:
            elements.append(_chart_to_image(fig))

    # ── 7. Curva MMP ────────────────────────────────────────────────────────
    if data.mmp_best:
        elements.append(Paragraph("7. Curva de Potencia Máxima (90 días)", styles["h2"]))

        # Tabla de valores clave
        key_durations = [
            (5, "5s"), (10, "10s"), (30, "30s"),
            (60, "1 min"), (300, "5 min"), (600, "10 min"),
            (1200, "20 min"), (3600, "60 min"),
        ]
        mmp_pairs = []
        for dur, label in key_durations:
            val = data.mmp_best.get(dur)
            if val:
                wkg = ""
                if data.weight_kg:
                    wkg = f" ({round(val / data.weight_kg, 2)} W/kg)"
                mmp_pairs.append((label, f"{round(val)} W{wkg}"))
        if mmp_pairs:
            elements.append(_kv_table(mmp_pairs))
            elements.append(Spacer(1, 3 * mm))

        fig = _chart_mmp(data.mmp_best, data.cp)
        if fig:
            elements.append(_chart_to_image(fig))

    # ── 8. Monotonía y Strain ───────────────────────────────────────────────
    if data.monotony is not None:
        elements.append(Paragraph("8. Monotonía y Strain (última semana)", styles["h2"]))
        mon_pairs = [
            ("Monotonía", f"{data.monotony} ({data.monotony_class})"),
        ]
        if data.strain is not None:
            mon_pairs.append(("Strain", f"{data.strain} ({data.strain_class})"))
        elements.append(_kv_table(mon_pairs))

    # ── 9. Race Readiness ───────────────────────────────────────────────────
    if data.rrs_score is not None:
        elements.append(Paragraph("9. Preparación para competir", styles["h2"]))
        rrs_pairs = [
            ("Score", f"{data.rrs_score} / 100"),
        ]
        if data.rrs_advice:
            rrs_pairs.append(("Consejo", data.rrs_advice))
        elements.append(_kv_table(rrs_pairs))

    # ── 10. Salud ───────────────────────────────────────────────────────────
    has_health = any([data.health_weight, data.health_rhr, data.health_hrv, data.health_readiness])
    if has_health:
        elements.append(Paragraph("10. Salud (último registro)", styles["h2"]))
        health_pairs = []
        if data.health_weight:
            health_pairs.append(("Peso", f"{data.health_weight} kg"))
        if data.health_rhr:
            health_pairs.append(("FC reposo", f"{data.health_rhr} ppm"))
        if data.health_hrv:
            health_pairs.append(("HRV (RMSSD)", f"{data.health_hrv} ms"))
        if data.health_readiness:
            health_pairs.append(("Readiness", f"{data.health_readiness}/10"))
        elements.append(_kv_table(health_pairs))

    # ── 11. Resumen últimos 7 días ──────────────────────────────────────────
    if data.recent_sessions:
        elements.append(Paragraph("11. Resumen últimos 7 días", styles["h2"]))
        recent_pairs = [
            ("Sesiones", str(data.recent_sessions)),
            ("Horas", f"{data.recent_hours}h"),
            ("TSS total", str(round(data.recent_tss))),
        ]
        if data.recent_distance_km:
            recent_pairs.append(("Distancia", f"{data.recent_distance_km} km"))
        elements.append(_kv_table(recent_pairs))

    # ── Footer con nota ─────────────────────────────────────────────────────
    elements.append(Spacer(1, 1 * cm))
    elements.append(Paragraph(
        "<i>Generado por Ciclométricas Desktop v3 · Todos los datos procesados localmente.</i>",
        ParagraphStyle("Footer", fontSize=7, textColor=_hex(COLOR_MUTED), alignment=TA_CENTER),
    ))

    # ── Construir PDF ───────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=_page_dims()[2],
        rightMargin=_page_dims()[2],
        topMargin=_page_dims()[2],
        bottomMargin=_page_dims()[2],
        title="Ciclométricas — Informe del Atleta",
        author="Ciclométricas Desktop",
    )
    doc.build(elements)
    return output_path


# ── Exportar plan de entrenamiento a PDF ─────────────────────────────────────

def generate_plan_pdf(output_path: str, plan_text: str, goal: str = "") -> str:
    """Genera un PDF estético a partir de un plan de entrenamiento en Markdown.

    Parsea encabezados, negritas y bullets del texto generado por el coach
    y produce un documento PDF con formato profesional.
    Lanza ImportError si faltan reportlab/matplotlib/Pillow.

    Args:
        output_path: Ruta de salida del PDF.
        plan_text: Texto Markdown del plan (respuesta del coach).
        goal: Objetivo del plan (opcional, se muestra en la portada).

    Returns:
        Ruta del archivo generado.
    """
    _ensure_pdf_deps()

    import re as _re
    from datetime import datetime as _dt

    styles = _make_styles()
    base = getSampleStyleSheet()
    elements: List[Any] = []

    # --- Estilos adicionales para el plan ---
    style_h3 = ParagraphStyle(
        "PlanH3", parent=base["Heading3"],
        fontSize=12, leading=15, textColor=_hex(COLOR_PRIMARY),
        spaceBefore=6 * mm, spaceAfter=2 * mm,
    )
    style_session = ParagraphStyle(
        "PlanSession", parent=base["Normal"],
        fontSize=9, leading=13, textColor=_hex(COLOR_TEXT),
        leftIndent=4 * mm, spaceAfter=1.5 * mm,
    )
    style_bullet = ParagraphStyle(
        "PlanBullet", parent=base["Normal"],
        fontSize=8.5, leading=12, textColor=_hex(COLOR_MUTED),
        leftIndent=8 * mm, spaceAfter=1 * mm,
        bulletIndent=4 * mm,
    )

    # --- Portada ---
    elements.append(Spacer(1, 3 * cm))
    elements.append(Paragraph("Ciclométricas", styles["title"]))
    elements.append(Paragraph("Plan de Entrenamiento", ParagraphStyle(
        "PlanSub", fontSize=14, leading=18, textColor=_hex(COLOR_MUTED),
        alignment=TA_CENTER, spaceAfter=6 * mm,
    )))
    if goal:
        elements.append(Paragraph(
            f"<b>Objetivo:</b> {goal}",
            ParagraphStyle("PlanGoal", fontSize=10, leading=14,
                           textColor=_hex(COLOR_TEXT), alignment=TA_CENTER,
                           spaceAfter=4 * mm),
        ))
    date_str = _dt.now().strftime("%d/%m/%Y %H:%M")
    elements.append(Paragraph(f"Generado: {date_str}", styles["subtitle"]))
    elements.append(PageBreak())

    # --- Parsear plan Markdown y generar elementos ---
    for raw_line in plan_text.split("\n"):
        line = raw_line.strip()
        if not line:
            elements.append(Spacer(1, 2 * mm))
            continue

        # Encabezados ## o ###
        hdr = _re.match(r"^#{1,3}\s+(.+)", line)
        if hdr:
            text = hdr.group(1).strip()
            # Limpiar markdown bold
            text = _re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<b>\1</b>", text)
            elements.append(Paragraph(text, styles["h2"]))
            continue

        # Líneas que empiezan con día de la semana en negrita
        day_hdr = _re.match(
            r"^\*{0,2}(Lunes|Martes|Miércoles|Miercoles|Jueves|Viernes|"
            r"Sábado|Sabado|Domingo|Monday|Tuesday|Wednesday|Thursday|"
            r"Friday|Saturday|Sunday)\*{0,2}\s*[::\-\u2014]\s*(.+)",
            line, _re.IGNORECASE,
        )
        if day_hdr:
            day = day_hdr.group(1)
            content = day_hdr.group(2).strip()
            content = _re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<b>\1</b>", content)
            elements.append(Paragraph(
                f"<b>{day}:</b> {content}", style_session,
            ))
            continue

        # "Día X" / "Day X" headers
        day_num = _re.match(r"^\*{0,2}(?:D[ií]a|Day)\s+\d+\*{0,2}\s*[::\-\u2014]?\s*(.*)", line, _re.IGNORECASE)
        if day_num:
            text = _re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<b>\1</b>", line.lstrip("*").strip())
            elements.append(Paragraph(text, style_session))
            continue

        # Bullets
        bullet = _re.match(r"^[-\u2022*]\s+(.+)", line)
        if bullet:
            text = bullet.group(1)
            text = _re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<b>\1</b>", text)
            elements.append(Paragraph(f"• {text}", style_bullet))
            continue

        # Texto genérico
        text = _re.sub(r"\*{1,2}(.+?)\*{1,2}", r"<b>\1</b>", line)
        elements.append(Paragraph(text, styles["body"]))

    # --- Construir PDF ---
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=_page_dims()[2], rightMargin=_page_dims()[2],
        topMargin=_page_dims()[2], bottomMargin=_page_dims()[2],
        title="Ciclométricas — Plan de Entrenamiento",
        author="Ciclométricas Desktop",
    )
    doc.build(elements)
    return output_path