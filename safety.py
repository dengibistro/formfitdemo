"""Safety overlay functions: injury mitigation, Kinematic Coupling Index,
and anthropometric confidence degradation.

Reads `03_injury_mechanism.md` and `04_coupling_mechanism.md`. Layers on top
of `biomechanics.py`'s pure vector/hole-grounding math and `models.py`'s
schemas — it does not recompute axis positions itself, only the three
cross-cutting safety mechanisms:

1. Injury Mitigation Filters — the three instruments from 03: budget
   multiplier (m_β), cap shift (Δψ), machine gate.
2. Kinematic Coupling Index — the CI formula and Θ_env modifiers from 04.
3. Anthropometric Confidence Degradation — Section 8's scan-error
   propagation and the r < 1 → LOW / safe-edge-resolution rule from 02.

Out of scope (unchanged from Steps 1-2): the temporal decay model
(candidate vs. applied severity over time), and any per-machine formula
that derives θ_hip/θ_knee/dψ/dC from D, F, Ti (Leg Press's own geometry) —
those values are supplied by the caller here, not derived.
"""

import math
from dataclasses import dataclass

from models import (
    ConfidenceTag,
    ConfidenceThresholds,
    CouplingConstants,
    CouplingIndexThresholds,
    FeasibilityState,
    InjuryConstraint,
    InjuryModifier,
)

# ---------------------------------------------------------------------------
# 1. Injury Mitigation Filters — 03_injury_mechanism.md, "What it touches"
# ---------------------------------------------------------------------------


def effective_angular_budget(beta_default_deg: float, modifier: InjuryModifier) -> float:
    """β_eff = β_default · m_β.

    Budget multiplier m_β ∈ (0,1] shrinks the capping tolerance band so
    resolution rounds harder toward the safe edge and flags sooner.
    """
    m_beta = modifier.m_beta if modifier.m_beta is not None else 1.0
    return beta_default_deg * m_beta


def capping_tolerance_mm(beta_eff_deg: float, sensitivity_dpsi_dC: float) -> float:
    """τ = β_eff / |dψ/dC|.

    `sensitivity_dpsi_dC` (the joint angle's change per mm of coordinate) is
    a per-machine quantity supplied by the caller — deriving it from a
    machine's own geometry is out of scope for this generic module.
    """
    if sensitivity_dpsi_dC == 0:
        raise ValueError("sensitivity dψ/dC must be nonzero")
    return beta_eff_deg / abs(sensitivity_dpsi_dC)


def cap_shift_deg(modifier: InjuryModifier) -> float:
    """Δψ — magnitude of the inward cap shift, healthy baseline to Tier-adjusted cap."""
    if modifier.delta_theta_cap_from_deg is None or modifier.delta_theta_cap_to_deg is None:
        raise ValueError(f"{modifier.axis!r} has no healthy/Tier cap pair to shift between")
    return abs(modifier.delta_theta_cap_from_deg - modifier.delta_theta_cap_to_deg)


def machine_gate_fires(
    modifier: InjuryModifier,
    injury: InjuryConstraint,
    safest_achievable_deg: float | None = None,
    safe_side_is_smaller_angle: bool = True,
) -> bool:
    """Absolute block (03, "Machine gate"). Fires when either:

    (a) the modifier's own severity gate is crossed (`gate_severity_threshold`,
        e.g. Pec Deck/Leg Extension "gate at s≥0.85"), or
    (b) even the safest achievable geometry can't stay inside the shifted cap
        window — NO_SOLUTION-by-injury, offer substitute.

    `safe_side_is_smaller_angle` says whether staying under the cap (True) or
    over it (False) is the safe direction for this axis; which one applies is
    machine-specific and is the caller's call, not inferred here.
    """
    severity_gate = (
        modifier.gate_severity_threshold is not None
        and injury.applied_severity >= modifier.gate_severity_threshold
    )
    geometry_gate = False
    if safest_achievable_deg is not None and modifier.delta_theta_cap_to_deg is not None:
        cap = modifier.delta_theta_cap_to_deg
        geometry_gate = (
            safest_achievable_deg > cap if safe_side_is_smaller_angle else safest_achievable_deg < cap
        )
    return severity_gate or geometry_gate


@dataclass(frozen=True)
class InjuryFilterResult:
    """Bundled result of applying all three injury instruments to one axis/modifier pair."""

    effective_beta_deg: float
    tolerance_mm: float | None
    cap_shift_deg: float | None
    shifted_cap_deg: float | None
    gate_fired: bool
    state: FeasibilityState  # NO_SOLUTION if gated; otherwise IN_RANGE — capping/grounding still applies upstream


def apply_injury_filters(
    modifier: InjuryModifier,
    injury: InjuryConstraint,
    beta_default_deg: float,
    sensitivity_dpsi_dC: float | None = None,
    safest_achievable_deg: float | None = None,
    safe_side_is_smaller_angle: bool = True,
) -> InjuryFilterResult:
    """Apply budget multiplier, cap shift, and machine gate together for one axis."""
    beta_eff = effective_angular_budget(beta_default_deg, modifier)
    tolerance = (
        capping_tolerance_mm(beta_eff, sensitivity_dpsi_dC) if sensitivity_dpsi_dC is not None else None
    )
    has_cap_pair = modifier.delta_theta_cap_from_deg is not None and modifier.delta_theta_cap_to_deg is not None
    gated = machine_gate_fires(modifier, injury, safest_achievable_deg, safe_side_is_smaller_angle)
    return InjuryFilterResult(
        effective_beta_deg=beta_eff,
        tolerance_mm=tolerance,
        cap_shift_deg=cap_shift_deg(modifier) if has_cap_pair else None,
        shifted_cap_deg=modifier.delta_theta_cap_to_deg if has_cap_pair else None,
        gate_fired=gated,
        state=FeasibilityState.NO_SOLUTION if gated else FeasibilityState.IN_RANGE,
    )


# ---------------------------------------------------------------------------
# 2. Kinematic Coupling Index — 04_coupling_mechanism.md
# ---------------------------------------------------------------------------


def compute_theta_env(
    theta_hip_onset_deg: float,
    theta_knee_screen_deg: float,
    coupling: CouplingConstants,
    hamstring_tightness: float = 0.0,
    femur_tibia_ratio: float | None = None,
    m_lumbar: float | None = None,
    m_hip: float | None = None,
    m_knee: float | None = None,
) -> float:
    """Θ_env(effective) =
        (θ_hip_onset − a_ham·Ham − a_fem·max(0, F:Ti − r0) − fatigue_reserve)
        · m_lumbar · m_hip · m_knee + κ·θ_knee_screen

    The fatigue reserve is held back from θ_hip_onset alongside the
    hamstring/femur-dominance terms, per "a few degrees held back from the
    screened onset" (constants.md). `m_lumbar`/`m_hip`/`m_knee` default to
    `coupling`'s Tier-3 baseline; pass 1.0 explicitly for an uninjured joint
    (no restriction).
    """
    m_lumbar = coupling.m_lumbar_tier3 if m_lumbar is None else m_lumbar
    m_hip = coupling.m_hip_tier3 if m_hip is None else m_hip
    m_knee = coupling.m_knee_tier3 if m_knee is None else m_knee

    femur_dominance_penalty = 0.0
    if femur_tibia_ratio is not None:
        femur_dominance_penalty = coupling.a_fem * max(
            0.0, femur_tibia_ratio - coupling.r0_reference_femur_tibia_ratio
        )

    hip_term = (
        theta_hip_onset_deg
        - coupling.a_ham * hamstring_tightness
        - femur_dominance_penalty
        - coupling.fatigue_reserve_deg
    )
    return hip_term * m_lumbar * m_hip * m_knee + coupling.kappa * theta_knee_screen_deg


def compute_coupling_index(
    theta_hip_deg: float, theta_knee_deg: float, theta_env_deg: float, kappa: float = 0.35
) -> float:
    """CI = (θ_hip + κ·θ_knee) / Θ_env, evaluated at the terminal (deepest) position."""
    if theta_env_deg <= 0:
        raise ValueError("Θ_env must be positive")
    return (theta_hip_deg + kappa * theta_knee_deg) / theta_env_deg


def classify_coupling_index(
    ci: float,
    thresholds: CouplingIndexThresholds,
    at_shallowest_useful_rom: bool = False,
) -> tuple[FeasibilityState, bool]:
    """(state, caution) per the CI table in 04_coupling_mechanism.md.

    Dual-vector remediation (Path A carriage restriction / Path B foot
    placement) is not implemented here — only classification of the raw CI.
    """
    if ci <= thresholds.in_range_max:
        return FeasibilityState.IN_RANGE, False
    if ci <= thresholds.caution_max:
        return FeasibilityState.IN_RANGE, True  # caution band: trigger Path B proactively (elsewhere)
    if at_shallowest_useful_rom:
        return FeasibilityState.NO_SOLUTION_BY_COUPLING, False
    return FeasibilityState.CLAMPED_BY_COUPLING, False


@dataclass(frozen=True)
class CouplingResult:
    ci: float
    theta_env_deg: float
    state: FeasibilityState
    caution: bool


def evaluate_coupling(
    theta_hip_deg: float,
    theta_knee_deg: float,
    theta_hip_onset_deg: float,
    theta_knee_screen_deg: float,
    coupling: CouplingConstants,
    hamstring_tightness: float = 0.0,
    femur_tibia_ratio: float | None = None,
    m_lumbar: float | None = None,
    m_hip: float | None = None,
    m_knee: float | None = None,
    at_shallowest_useful_rom: bool = False,
) -> CouplingResult:
    """End-to-end CI evaluation: Θ_env, CI, and its (state, caution) classification."""
    theta_env = compute_theta_env(
        theta_hip_onset_deg,
        theta_knee_screen_deg,
        coupling,
        hamstring_tightness,
        femur_tibia_ratio,
        m_lumbar,
        m_hip,
        m_knee,
    )
    ci = compute_coupling_index(theta_hip_deg, theta_knee_deg, theta_env, coupling.kappa)
    state, caution = classify_coupling_index(ci, coupling.thresholds, at_shallowest_useful_rom)
    return CouplingResult(ci=ci, theta_env_deg=theta_env, state=state, caution=caution)


# ---------------------------------------------------------------------------
# 3. Anthropometric Confidence Degradation — 02_anthropometry.md, "Confidence layer"
# ---------------------------------------------------------------------------


def propagate_sigma(partials_and_sigmas_mm: dict[str, tuple[float, float]]) -> float:
    """σ_C = sqrt( Σᵢ (∂C/∂Xᵢ)² · σ_Xᵢ² ) — general scan-error propagation."""
    return math.sqrt(sum((partial**2) * (sigma**2) for partial, sigma in partials_and_sigmas_mm.values()))


def propagate_single_segment_sigma(coefficient: float, sigma_segment_mm: float) -> float:
    """Single-segment axis, e.g. σ_Seat = k_sh · σ_T."""
    return abs(coefficient) * sigma_segment_mm


def propagate_two_segment_sigma(partial_1: float, sigma_1_mm: float, partial_2: float, sigma_2_mm: float) -> float:
    """Two-segment axis, e.g. leg-press carriage D over (F, Ti)."""
    return propagate_sigma({"1": (partial_1, sigma_1_mm), "2": (partial_2, sigma_2_mm)})


def dominant_sigma_contributor(partials_and_sigmas_mm: dict[str, tuple[float, float]]) -> str:
    """Name of the segment whose (∂C/∂Xᵢ · σ_Xᵢ)² term dominates σ_C² — surfaced
    on LOW-confidence resolutions "purely for user-facing transparency" (02,
    "Output contract addition")."""
    return max(
        partials_and_sigmas_mm,
        key=lambda name: (partials_and_sigmas_mm[name][0] * partials_and_sigmas_mm[name][1]) ** 2,
    )


def confidence_ratio(margin_mm: float, sigma_C_mm: float) -> float:
    """r = M / σ_C — M is the distance from the resolved coordinate to the nearest decision boundary."""
    if sigma_C_mm <= 0:
        raise ValueError("σ_C must be positive")
    return margin_mm / sigma_C_mm


def exceeds_scan_uncertainty(clearance_mm: float, sigma_scan_mm: float) -> bool:
    """τ ≤ σ_scan — the literal form of the degrade-to-LOW condition; equivalent
    to r < 1 when `clearance_mm`/`sigma_scan_mm` are the same (M, σ_C) pair
    `confidence_ratio` uses. Exposed directly because the calling contract
    (Step 3 spec) states the check this way."""
    return clearance_mm <= sigma_scan_mm


def classify_confidence(r: float, thresholds: ConfidenceThresholds) -> ConfidenceTag:
    """r ≥ 3 → HIGH; 1 ≤ r < 3 → MEDIUM; r < 1 → LOW."""
    if r >= thresholds.high_min_r:
        return ConfidenceTag.HIGH
    if r >= thresholds.medium_min_r:
        return ConfidenceTag.MEDIUM
    return ConfidenceTag.LOW


@dataclass(frozen=True)
class ConfidenceResolution:
    state: FeasibilityState
    confidence: ConfidenceTag
    dominant_segment: str | None
    degraded_to_safe_edge: bool


def resolve_with_confidence(
    proposed_state: FeasibilityState,
    margin_mm: float,
    sigma_C_mm: float,
    thresholds: ConfidenceThresholds,
    safe_edge_state: FeasibilityState,
    dominant_segment: str | None = None,
) -> ConfidenceResolution:
    """Section 8's output contract: every axis resolution is the pair (state, confidence).

    Two hard rules enforced here:
    1. NO_SOLUTION is confidence-immune — stands at HIGH regardless of r.
    2. Below r=1 (LOW, i.e. τ ≤ σ_scan): never state a confident
       IN_RANGE/CLAMPED. Degrade to `safe_edge_state` (must be CLAMPED_LOW or
       CLAMPED_HIGH — whichever this axis's safe direction is, decided by the
       caller) and surface LOW with its dominant σ contributor. This never
       triggers a manual re-measurement flow — MVP has no such flow to trigger,
       provenance is always `scanned`.
    """
    if safe_edge_state not in (FeasibilityState.CLAMPED_LOW, FeasibilityState.CLAMPED_HIGH):
        raise ValueError("safe_edge_state must be CLAMPED_LOW or CLAMPED_HIGH")

    if proposed_state is FeasibilityState.NO_SOLUTION:
        return ConfidenceResolution(FeasibilityState.NO_SOLUTION, ConfidenceTag.HIGH, None, False)

    r = confidence_ratio(margin_mm, sigma_C_mm)
    tag = classify_confidence(r, thresholds)

    if tag is ConfidenceTag.LOW:
        return ConfidenceResolution(safe_edge_state, ConfidenceTag.LOW, dominant_segment, True)

    return ConfidenceResolution(proposed_state, tag, None, False)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    from models import InjuryJoint, InjuryProvenance, InjuryTier, InjuryZone, MachineName

    # === 1. Injury Mitigation Filters ===
    # Chest Press shoulder modifier: healthy θ_cap 25° -> Tier-3 15°, m_β 0.50
    chest_press_modifier = InjuryModifier(
        zone=InjuryZone.SHOULDER,
        machine=MachineName.CHEST_PRESS,
        axis="Handle start depth",
        instrument="m_β · Δθ_cap",
        m_beta=0.50,
        delta_theta_cap_from_deg=25,
        delta_theta_cap_to_deg=15,
    )
    shoulder_injury = InjuryConstraint(
        constraint_id="inj-1",
        joint=InjuryJoint.SHOULDER_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=12,
        provenance=InjuryProvenance.SELF_REPORT,
        onset_date=date(2026, 1, 1),
        review_date=date(2026, 2, 1),
    )

    beta_eff = effective_angular_budget(beta_default_deg=5.0, modifier=chest_press_modifier)
    assert math.isclose(beta_eff, 2.5)
    tol = capping_tolerance_mm(beta_eff, sensitivity_dpsi_dC=0.1)
    assert math.isclose(tol, 25.0)
    assert math.isclose(cap_shift_deg(chest_press_modifier), 10.0)

    # Safest achievable position (20°) still exceeds the shifted cap (15°) -> gate fires
    blocked = apply_injury_filters(
        chest_press_modifier, shoulder_injury, beta_default_deg=5.0,
        sensitivity_dpsi_dC=0.1, safest_achievable_deg=20.0,
    )
    assert blocked.gate_fired is True and blocked.state is FeasibilityState.NO_SOLUTION

    # Safest achievable position (10°) sits inside the shifted cap -> no gate
    clear = apply_injury_filters(
        chest_press_modifier, shoulder_injury, beta_default_deg=5.0,
        sensitivity_dpsi_dC=0.1, safest_achievable_deg=10.0,
    )
    assert clear.gate_fired is False and clear.state is FeasibilityState.IN_RANGE

    # Severity-threshold gate (Pec Deck-style "gate at s>=0.85"), independent of geometry
    pec_deck_modifier = InjuryModifier(
        zone=InjuryZone.SHOULDER, machine=MachineName.PEC_DECK, axis="Arm open offset",
        instrument="m_β · Δθ_cap · gate", m_beta=0.30,
        delta_theta_cap_from_deg=25, delta_theta_cap_to_deg=10,
        gate_severity_threshold=0.85,
    )
    high_severity = shoulder_injury.model_copy(update={"applied_severity": 0.90})
    severity_blocked = apply_injury_filters(pec_deck_modifier, high_severity, beta_default_deg=5.0)
    assert severity_blocked.gate_fired is True

    low_severity = shoulder_injury.model_copy(update={"applied_severity": 0.50})
    severity_clear = apply_injury_filters(pec_deck_modifier, low_severity, beta_default_deg=5.0)
    assert severity_clear.gate_fired is False
    print("Injury Mitigation Filters: OK")

    # === 2. Kinematic Coupling Index ===
    coupling_constants = CouplingConstants(a_ham=0.1, a_fem=0.2, fatigue_reserve_deg=3.0, m_hip_tier3=0.75)

    # Healthy (uninjured) envelope: no modifiers restrict Θ_env
    healthy = evaluate_coupling(
        theta_hip_deg=108, theta_knee_deg=84,
        theta_hip_onset_deg=120, theta_knee_screen_deg=80,
        coupling=coupling_constants,
        m_lumbar=1.0, m_hip=1.0, m_knee=1.0,
    )
    assert math.isclose(healthy.theta_env_deg, 145.0)  # (120-3)*1*1*1 + 0.35*80
    assert healthy.caution is True and healthy.state is FeasibilityState.IN_RANGE  # CI ~0.947, caution band

    # Same geometry, Tier-3 injury modifiers now active -> Θ_env shrinks, CI blows past 1.0
    injured = evaluate_coupling(
        theta_hip_deg=108, theta_knee_deg=84,
        theta_hip_onset_deg=120, theta_knee_screen_deg=80,
        coupling=coupling_constants,  # defaults to coupling's own Tier-3 m_lumbar/m_hip/m_knee
    )
    assert injured.theta_env_deg < healthy.theta_env_deg
    assert injured.ci > healthy.ci
    assert injured.state is FeasibilityState.CLAMPED_BY_COUPLING

    # Same CI, but this is already the shallowest useful ROM -> escalates to NO_SOLUTION
    no_solution = evaluate_coupling(
        theta_hip_deg=108, theta_knee_deg=84,
        theta_hip_onset_deg=120, theta_knee_screen_deg=80,
        coupling=coupling_constants, at_shallowest_useful_rom=True,
    )
    assert no_solution.state is FeasibilityState.NO_SOLUTION_BY_COUPLING
    print("Kinematic Coupling Index: OK")
    print(
        f"  healthy Θ_env={healthy.theta_env_deg:.1f} CI={healthy.ci:.3f} ({healthy.state.value}, caution={healthy.caution})"
    )
    print(f"  injured Θ_env={injured.theta_env_deg:.1f} CI={injured.ci:.3f} ({injured.state.value})")

    # === 3. Anthropometric Confidence Degradation ===
    scan_error_sigma_T = 15.0
    k_sh = 0.63
    sigma_seat = propagate_single_segment_sigma(k_sh, scan_error_sigma_T)
    assert math.isclose(sigma_seat, 9.45)

    thresholds = ConfidenceThresholds()

    # Small margin relative to sigma -> LOW, degrade to the safe edge, no calibration flow invoked
    tight_margin_mm = 5.0
    assert exceeds_scan_uncertainty(tight_margin_mm, sigma_seat) is True
    degraded = resolve_with_confidence(
        proposed_state=FeasibilityState.IN_RANGE,
        margin_mm=tight_margin_mm,
        sigma_C_mm=sigma_seat,
        thresholds=thresholds,
        safe_edge_state=FeasibilityState.CLAMPED_LOW,
        dominant_segment="T (sitting height)",
    )
    assert degraded.confidence is ConfidenceTag.LOW
    assert degraded.state is FeasibilityState.CLAMPED_LOW
    assert degraded.degraded_to_safe_edge is True
    assert degraded.dominant_segment == "T (sitting height)"

    # Comfortable margin -> HIGH, proposed state stands, nothing degraded
    wide_margin_mm = 40.0
    assert exceeds_scan_uncertainty(wide_margin_mm, sigma_seat) is False
    confident = resolve_with_confidence(
        proposed_state=FeasibilityState.IN_RANGE,
        margin_mm=wide_margin_mm,
        sigma_C_mm=sigma_seat,
        thresholds=thresholds,
        safe_edge_state=FeasibilityState.CLAMPED_LOW,
    )
    assert confident.confidence is ConfidenceTag.HIGH
    assert confident.state is FeasibilityState.IN_RANGE
    assert confident.degraded_to_safe_edge is False

    # NO_SOLUTION is confidence-immune: stands at HIGH even with a razor-thin margin
    immune = resolve_with_confidence(
        proposed_state=FeasibilityState.NO_SOLUTION,
        margin_mm=0.1,
        sigma_C_mm=sigma_seat,
        thresholds=thresholds,
        safe_edge_state=FeasibilityState.CLAMPED_LOW,
    )
    assert immune.state is FeasibilityState.NO_SOLUTION and immune.confidence is ConfidenceTag.HIGH
    print("Anthropometric Confidence Degradation: OK")

    print("\nAll safety.py smoke tests passed.")
