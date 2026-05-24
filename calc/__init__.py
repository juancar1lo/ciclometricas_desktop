"""ciclométricas — módulos de cálculo de rendimiento ciclista.

15 módulos portados fielmente de la web app TypeScript.
"""

# Power metrics
from .power import (
    PowerMetrics,
    calc_average_power,
    calc_intensity_factor,
    calc_normalized_power,
    calc_tss,
    calc_work_kj,
    calculate_power_metrics,
)

# MMP
from .mmp import (
    MMP_DURATIONS,
    PR_DURATIONS,
    compute_mmp,
    merge_mmp_max,
    power_from_samples,
    sanitize_power_series,
)

# CP model
from .cp_model import (
    CpModelResult,
    PowerTestPoint,
    ReliabilityLabel,
    TteResult,
    calc_mftp_vo2max_percentage,
    calc_tte,
    estimate_mftp,
    estimate_p_vo2max,
    estimate_vo2max,
    fit_cp_model,
    reliability_from_r2,
)

# Zones
from .zones import (
    HR_ZONES,
    POWER_ZONES,
    ZoneDef,
    ZoneRef,
    bucket_series,
    resolve_zone_ref,
)

# Fitness
from .fitness import (
    FitnessPoint,
    build_fitness_series,
    calc_ramp_rate,
    last_real_point,
)

# W' Balance
from .wbal import (
    WbalPoint,
    compute_wbal,
    compute_wbal_from_samples,
)

# Intervals
from .intervals import (
    DetectIntervalsOptions,
    WorkInterval,
    detect_intervals,
)

# Activity metrics
from .activity_metrics import (
    PwHrResult,
    TissResult,
    calc_ef,
    calc_pw_hr_decoupling,
    calc_tiss,
    calc_vf,
)

# PDC Fatigue
from .pdc_fatigue import (
    FATIGUE_THRESHOLDS,
    PDC_DURATIONS,
    PdcFatigueCurve,
    PdcFatigueResult,
    calc_pdc_fatigue,
)

# Climbs
from .climbs import (
    ClimbDetectionOptions,
    DetectedClimb,
    detect_climbs,
)

# Monotony
from .monotony import (
    WeekMonotonyResult,
    calc_week_monotony,
    classify_monotony,
    classify_strain,
)

# Fatigue Resistance
from .fatigue_resistance import (
    FatigueResistanceResult,
    calc_fatigue_resistance,
    classify_fr,
)

# Recovery
from .recovery import (
    RecoveryProjection,
    estimate_activity_recovery,
    project_recovery,
)

# FTP Estimator
from .ftp_estimator import (
    FTP_SUGGESTION_THRESHOLD,
    FtpEstimate,
    estimate_ftp_from_mmp,
    estimate_ftp_from_power,
    ftp_coefficient,
)

# Race Readiness
from .race_readiness import (
    RrsInput,
    RrsResult,
    calc_race_readiness,
)

__all__ = [
    # power
    "calc_normalized_power", "calc_average_power", "calc_work_kj",
    "calc_intensity_factor", "calc_tss", "calculate_power_metrics", "PowerMetrics",
    # mmp
    "MMP_DURATIONS", "PR_DURATIONS", "sanitize_power_series",
    "compute_mmp", "power_from_samples", "merge_mmp_max",
    # cp_model
    "PowerTestPoint", "CpModelResult", "fit_cp_model",
    "estimate_vo2max", "estimate_mftp", "estimate_p_vo2max",
    "calc_mftp_vo2max_percentage", "TteResult", "calc_tte",
    "ReliabilityLabel", "reliability_from_r2",
    # zones
    "ZoneDef", "POWER_ZONES", "HR_ZONES", "bucket_series",
    "resolve_zone_ref", "ZoneRef",
    # fitness
    "FitnessPoint", "build_fitness_series", "calc_ramp_rate", "last_real_point",
    # wbal
    "WbalPoint", "compute_wbal", "compute_wbal_from_samples",
    # intervals
    "WorkInterval", "DetectIntervalsOptions", "detect_intervals",
    # activity_metrics
    "TissResult", "calc_tiss", "calc_ef", "calc_vf",
    "PwHrResult", "calc_pw_hr_decoupling",
    # pdc_fatigue
    "FATIGUE_THRESHOLDS", "PDC_DURATIONS",
    "PdcFatigueCurve", "PdcFatigueResult", "calc_pdc_fatigue",
    # climbs
    "DetectedClimb", "ClimbDetectionOptions", "detect_climbs",
    # monotony
    "WeekMonotonyResult", "calc_week_monotony", "classify_monotony", "classify_strain",
    # fatigue_resistance
    "FatigueResistanceResult", "calc_fatigue_resistance", "classify_fr",
    # recovery
    "RecoveryProjection", "project_recovery", "estimate_activity_recovery",
    # ftp_estimator
    "FtpEstimate", "ftp_coefficient", "estimate_ftp_from_power",
    "estimate_ftp_from_mmp", "FTP_SUGGESTION_THRESHOLD",
    # race_readiness
    "RrsInput", "RrsResult", "calc_race_readiness",
]
