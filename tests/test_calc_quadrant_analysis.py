"""Tests para el módulo calc.quadrant_analysis (AEPF/CPV — Coggan)."""
import pytest
import math
from calc.quadrant_analysis import (
    calc_quadrant_analysis, QuadrantSample, QuadrantResult,
    _to_aepf, _to_cpv,
)

CL_MM = 175.0
CL_M = CL_MM / 1000.0


def test_empty_samples_returns_none():
    assert calc_quadrant_analysis([], 250.0) is None


def test_zero_ref_power_returns_none():
    samples = [QuadrantSample(p=200, c=90)]
    assert calc_quadrant_analysis(samples, 0) is None


def test_no_valid_samples_returns_none():
    # All None values
    samples = [QuadrantSample(p=None, c=None) for _ in range(10)]
    assert calc_quadrant_analysis(samples, 250.0) is None


def test_aepf_cpv_formulas():
    """Verify the AEPF and CPV formulas match Coggan's."""
    # AEPF = (P × 60) / (C × 2π × CL)
    aepf = _to_aepf(250.0, 90.0, CL_M)
    expected_aepf = (250 * 60) / (90 * 2 * math.pi * CL_M)
    assert abs(aepf - expected_aepf) < 0.01

    # CPV = C × CL × 2π / 60
    cpv = _to_cpv(90.0, CL_M)
    expected_cpv = (90 * CL_M * 2 * math.pi) / 60
    assert abs(cpv - expected_cpv) < 0.001


def test_all_q1():
    """All samples high AEPF + high CPV → 100% Q1.
    Need power and cadence well above ref to be in Q1."""
    # ref = 250W @ 90rpm. Samples at 400W @ 100rpm → clearly Q1
    samples = [QuadrantSample(p=400, c=100) for _ in range(100)]
    result = calc_quadrant_analysis(samples, 250.0, 90.0, CL_MM)
    assert result is not None
    assert result.q1_pct == 100.0


def test_all_q3():
    """All samples low AEPF + low CPV → 100% Q3."""
    samples = [QuadrantSample(p=80, c=60) for _ in range(50)]
    result = calc_quadrant_analysis(samples, 250.0, 90.0, CL_MM)
    assert result is not None
    assert result.q3_pct == 100.0


def test_q2_high_force_low_velocity():
    """High AEPF + low CPV → Q2 (grinding uphill)."""
    # 250W @ 50rpm = very high AEPF, low CPV
    samples = [QuadrantSample(p=250, c=50) for _ in range(50)]
    result = calc_quadrant_analysis(samples, 200.0, 90.0, CL_MM)
    assert result is not None
    assert result.q2_pct == 100.0


def test_q4_low_force_high_velocity():
    """Low AEPF + high CPV → Q4 (spinning easy)."""
    # 80W @ 110rpm = low AEPF, high CPV
    samples = [QuadrantSample(p=80, c=110) for _ in range(50)]
    result = calc_quadrant_analysis(samples, 200.0, 90.0, CL_MM)
    assert result is not None
    assert result.q4_pct == 100.0


def test_skips_invalid_samples():
    """None, zero, and negative values are skipped."""
    samples = [
        QuadrantSample(p=None, c=90),      # skip
        QuadrantSample(p=300, c=None),      # skip
        QuadrantSample(p=0, c=90),          # skip (p=0)
        QuadrantSample(p=300, c=0),         # skip (c=0)
        QuadrantSample(p=-10, c=90),        # skip (negative)
        QuadrantSample(p=400, c=100),       # valid → Q1
    ]
    result = calc_quadrant_analysis(samples, 250.0, 90.0, CL_MM)
    assert result is not None
    assert result.total_samples == 1
    assert result.q1_pct == 100.0


def test_boundary_values():
    """Power == ref and cadence == ref → AEPF == ref_AEPF and CPV == ref_CPV → Q1 (>= comparison)."""
    samples = [QuadrantSample(p=250, c=90)]
    result = calc_quadrant_analysis(samples, 250.0, 90.0, CL_MM)
    assert result is not None
    assert result.q1_pct == 100.0


def test_ref_values_stored():
    samples = [QuadrantSample(p=300, c=100)]
    result = calc_quadrant_analysis(samples, 275.0, 85.0, CL_MM)
    assert result is not None
    assert result.ref_power == 275.0
    assert result.ref_cadence == 85.0
    assert result.ref_aepf > 0
    assert result.ref_cpv > 0
    assert result.crank_length_mm == CL_MM


def test_default_ref_cadence_is_90():
    """Default ref cadence should be 90 rpm (Coggan standard)."""
    samples = [QuadrantSample(p=300, c=95)]
    result = calc_quadrant_analysis(samples, 250.0)
    assert result is not None
    assert result.ref_cadence == 90.0


def test_default_crank_length_is_175():
    """Default crank length should be 175 mm (paridad con app web)."""
    samples = [QuadrantSample(p=300, c=95)]
    result = calc_quadrant_analysis(samples, 250.0)
    assert result is not None
    assert result.crank_length_mm == 175.0


def test_crank_length_invariance():
    """Los porcentajes Q1-Q4 son invariantes a la longitud de biela
    (CL se cancela en la comparación AEPF/CPV)."""
    samples = [
        QuadrantSample(p=350, c=100),  # Q1
        QuadrantSample(p=350, c=60),   # Q2
        QuadrantSample(p=80, c=60),    # Q3
        QuadrantSample(p=80, c=100),   # Q4
    ]
    r1 = calc_quadrant_analysis(samples, 250.0, 90.0, 165.0)
    r2 = calc_quadrant_analysis(samples, 250.0, 90.0, 175.0)
    r3 = calc_quadrant_analysis(samples, 250.0, 90.0, 180.0)
    assert r1 is not None and r2 is not None and r3 is not None
    # Los porcentajes deben ser idénticos
    assert r1.q1_pct == r2.q1_pct == r3.q1_pct
    assert r1.q2_pct == r2.q2_pct == r3.q2_pct
    assert r1.q3_pct == r2.q3_pct == r3.q3_pct
    assert r1.q4_pct == r2.q4_pct == r3.q4_pct
    # Pero los valores absolutos de referencia difieren
    assert r1.ref_aepf != r2.ref_aepf
    assert r1.ref_cpv != r2.ref_cpv
