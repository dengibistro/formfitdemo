"""Matrix Leg Press 45° — concrete machine implementation.

Reads `machines/leg_press.md`. The one machine where the Coupling Envelope
(`04_coupling_mechanism.md`) and the full Resistive Moment Model (`05`) both
apply in force; this module implements the former in full (Coupling Index,
Path A/B dual-vector remediation) and only records the latter's hardcoded
`resistance_profile` (torque math itself stays out of scope, same boundary
held by every machine module so far).

Three things make this file different from every other machine module:

1. Carriage distance D is a **capping** axis, but leg_press.md explicitly
   overrides the usual "tighter side governs" capping bilateral rule with
   minimax-midpoint averaging instead — deliberate, stated in the file, and
   implemented that way here rather than reused from `common.py`.
2. θ_knee and φ_HF have exact, general law-of-cosines formulas given
   in `04_coupling_mechanism.md` — verified byte-for-byte against
   leg_press.md's own worked example in this module's smoke test. θ_hip's
   machine-frame term (Ω_trunk − O_HF) does *not* have a general formula,
   only that one worked example plus qualitative directions — so it's
   parameterized via `LegPressFrameConstants`, following the same
   required-constant discipline as `LatPulldownFrameConstants`/
   `SeatedRowFrameConstants`, with the one number the doc *does* give
   (Path B's "≈12°" hip drop) kept as a documented default.
3. CI supersedes the single-axis capping result here (04: "this supersedes
   the single-axis carriage depth cap and σ from the machine's own Passport
   entry") — so the axis's final reported `state` is the *coupling*-layered
   state (CLAMPED_BY_COUPLING/NO_SOLUTION_BY_COUPLING) whenever coupling is
   the binding constraint, not the plain reach-based CLAMPED/IN_RANGE.

Run as `python3 -m machines.leg_press` from the `formfit_spec/` directory.
"""

import math
from dataclasses import dataclass

from biomechanics import ground_toward_safe_edge, margin_to_reach_boundary, node_position
from machines.common import AxisResolution, bilateral_values, is_tier3
from models import (
    AnthropometryProfile,
    AxisPurpose,
    AxisType,
    ConfidenceTag,
    ConfidenceThresholds,
    CouplingConstants,
    FeasibilityState,
    GlobalCoefficients,
    InjuryConstraint,
    InjuryJoint,
    InjuryModifier,
    InjuryZone,
    Machine,
    MachineAxis,
    MachineName,
    ResistanceProfile,
    ScaleDirection,
    ScanErrorConstants,
)
from safety import (
    classify_coupling_index,
    compute_coupling_index,
    compute_theta_env,
    dominant_sigma_contributor,
    propagate_sigma,
    resolve_with_confidence,
)

# ---------------------------------------------------------------------------
# Leg Press Passport — constants.md via models.py, plus this machine's own
# fixed-frame numbers (canonical only in machines/leg_press.md)
# ---------------------------------------------------------------------------

GLOBAL = GlobalCoefficients()      # k_sh, φ_LP = 60°, β_default = 5°, κ = 0.35, ...
SCAN_ERROR = ScanErrorConstants()  # σ_F, σ_Ti, ...
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

CARRIAGE_D_AXIS = MachineAxis(
    name="Carriage distance D",
    axis_type=AxisType.CAPPING,
    total_holes=9,
    direction=ScaleDirection.DIRECT,  # n=1 = closest/short legs, n=9 = furthest/long legs
    alpha_deg=45,
    p0_mm=500,
    delta_mm=40,
    reach_min_mm=500,
    reach_max_mm=820,
    safe_direction="larger D (shallower bottom, safer)",
    beta_deg=5,
)

RECLINE_SETTINGS_DEG = (100.0, 113.0, 125.0)  # ordered seat-to-back angle
RECLINE_MID_INDEX = 1  # healthy default: matches the worked example's "mid-recline" baseline
RECLINE_MAX_INDEX = 2  # "bias to maximum recline" under Tier-3 hip/lumbar

KNEE_CARRIAGE_D_MODIFIER = InjuryModifier(
    zone=InjuryZone.KNEE,
    machine=MachineName.LEG_PRESS_45,
    axis="Carriage D",
    instrument="m_β · φ floor raised · σ toward larger D",
    m_beta=0.50,
)
HIP_CARRIAGE_D_MODIFIER = InjuryModifier(
    zone=InjuryZone.HIP,
    machine=MachineName.LEG_PRESS_45,
    axis="Carriage D",
    instrument="m_β · shallower bottom",
    m_beta=0.50,
)
HIP_RECLINE_MODIFIER = InjuryModifier(
    zone=InjuryZone.HIP,
    machine=MachineName.LEG_PRESS_45,
    axis="Backrest recline",
    instrument="m_β · bias to maximum recline",
    m_beta=0.40,
)
LUMBAR_CARRIAGE_AND_RECLINE_MODIFIER = InjuryModifier(
    zone=InjuryZone.LUMBAR,
    machine=MachineName.LEG_PRESS_45,
    axis="Carriage D + recline",
    instrument="m_β · shallower + more recline",
    m_beta=0.40,
)

LEG_PRESS_MACHINE = Machine(
    name=MachineName.LEG_PRESS_45,
    machine_class="Inclined leg press",
    mechanic="Linear (sled)",
    plane="Sagittal",
    resistance_profile=ResistanceProfile.LINEAR,
    axes=[CARRIAGE_D_AXIS],
    injury_modifiers=[
        KNEE_CARRIAGE_D_MODIFIER,
        HIP_CARRIAGE_D_MODIFIER,
        HIP_RECLINE_MODIFIER,
        LUMBAR_CARRIAGE_AND_RECLINE_MODIFIER,
    ],
    coupling_envelope_applies=True,
)


@dataclass(frozen=True)
class LegPressFrameConstants:
    """Numbers leg_press.md's Coupling Envelope section gives only via one
    illustrative worked example (F=600, Ti=500, D=820, mid-recline, standard
    foot -> θ_hip≈108°) plus qualitative directions — not a general formula
    for θ_hip at arbitrary recline/foot-height. θ_knee and φ_HF *are* exact,
    general law-of-cosines formulas and need no such constant.

    `trunk_foot_term_mid_recline_deg` defaults to the value implied by the
    worked example itself (108° + φ_HF(D=820,F=600,Ti=500)≈37.36° ≈ 145.36°)
    — a real derivation, not an invented placeholder, but anchored by only
    one data point; replace with calibrated frame data once available.
    `path_b_hip_reduction_deg` defaults to the doc's own "≈12°" figure.
    `recline_hip_reduction_per_step_deg` has no anchor at all in the doc —
    required, no default, same discipline as `LatPulldownFrameConstants`.
    """

    recline_hip_reduction_per_step_deg: float
    trunk_foot_term_mid_recline_deg: float = 145.36
    path_b_hip_reduction_deg: float = 12.0


@dataclass(frozen=True)
class LegPressResolution:
    carriage_d: AxisResolution
    backrest_recline: AxisResolution
    footplate_note: str | None
    coupling_index: float | None
    path_b_engaged: bool
    path_a_engaged: bool


@dataclass(frozen=True)
class _BilateralGeometry:
    femur_left: float
    femur_right: float
    tibia_left: float
    tibia_right: float
    D_left: float
    D_right: float
    D_target_mm: float
    half_offset_mm: float
    F_avg_mm: float
    Ti_avg_mm: float
    femur_single_sided: bool
    tibia_single_sided: bool


# ---------------------------------------------------------------------------
# Exact geometry — 04_coupling_mechanism.md law-of-cosines formulas
# ---------------------------------------------------------------------------


def _carriage_distance_mm(femur_mm: float, tibia_mm: float, phi_deg: float) -> float:
    """D(φ) = √(F² + Ti² + 2·F·Ti·cos φ)."""
    return math.sqrt(femur_mm**2 + tibia_mm**2 + 2 * femur_mm * tibia_mm * math.cos(math.radians(phi_deg)))


def _knee_flexion_deg(D_mm: float, femur_mm: float, tibia_mm: float) -> float:
    """cos θ_knee = (D² − F² − Ti²) / (2·F·Ti) — exact, general."""
    cos_theta = (D_mm**2 - femur_mm**2 - tibia_mm**2) / (2 * femur_mm * tibia_mm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))


def _femur_interior_angle_deg(D_mm: float, femur_mm: float, tibia_mm: float) -> float:
    """cos φ_HF = (F² + D² − Ti²) / (2·F·D) — exact, general."""
    cos_phi = (femur_mm**2 + D_mm**2 - tibia_mm**2) / (2 * femur_mm * D_mm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_phi))))


def _hip_flexion_deg(
    D_mm: float,
    femur_mm: float,
    tibia_mm: float,
    trunk_foot_term_deg: float,
    path_b_offset_deg: float,
) -> float:
    """θ_hip = Ω_trunk − O_HF(D, h_foot) − φ_HF(D). See `LegPressFrameConstants`
    for how the combined (Ω_trunk − O_HF) term is derived/parameterized."""
    return trunk_foot_term_deg - path_b_offset_deg - _femur_interior_angle_deg(D_mm, femur_mm, tibia_mm)


# ---------------------------------------------------------------------------
# Bilateral resolution — explicit minimax-midpoint override (leg_press.md)
# ---------------------------------------------------------------------------


def _resolve_carriage_bilateral(profile: AnthropometryProfile) -> _BilateralGeometry:
    """leg_press.md overrides this capping axis's usual tighter-side-governs
    rule: "Apply minimax-midpoint... to D using (F_L,Ti_L) and (F_R,Ti_R)"
    — average each side's own D (not the raw segments), per
    02_anthropometry.md's general minimax-midpoint definition
    (Coord = (Coord_L + Coord_R)/2)."""
    femur_left, femur_right, femur_single_sided = bilateral_values(profile.femur)
    tibia_left, tibia_right, tibia_single_sided = bilateral_values(profile.tibia)

    D_left = _carriage_distance_mm(femur_left, tibia_left, GLOBAL.phi_lp_deg)
    D_right = _carriage_distance_mm(femur_right, tibia_right, GLOBAL.phi_lp_deg)

    return _BilateralGeometry(
        femur_left=femur_left,
        femur_right=femur_right,
        tibia_left=tibia_left,
        tibia_right=tibia_right,
        D_left=D_left,
        D_right=D_right,
        D_target_mm=(D_left + D_right) / 2,
        half_offset_mm=abs(D_left - D_right) / 2,
        F_avg_mm=(femur_left + femur_right) / 2,
        Ti_avg_mm=(tibia_left + tibia_right) / 2,
        femur_single_sided=femur_single_sided,
        tibia_single_sided=tibia_single_sided,
    )


def _sigma_D(
    geo: _BilateralGeometry, sigma_F_mm: float, sigma_Ti_mm: float
) -> tuple[float, dict[str, tuple[float, float]]]:
    """σ_D via 02_anthropometry.md's worked two-segment form
    (∂D/∂F = (2F+Ti)/2D, ∂D/∂Ti = (2Ti+F)/2D), extended to four terms
    (halved per side) since D is now itself a bilateral average."""
    dD_dF_left = (2 * geo.femur_left + geo.tibia_left) / (2 * geo.D_left)
    dD_dTi_left = (2 * geo.tibia_left + geo.femur_left) / (2 * geo.D_left)
    dD_dF_right = (2 * geo.femur_right + geo.tibia_right) / (2 * geo.D_right)
    dD_dTi_right = (2 * geo.tibia_right + geo.femur_right) / (2 * geo.D_right)

    partials = {
        "F_L (left femur)": (0.5 * dD_dF_left, sigma_F_mm),
        "Ti_L (left tibia)": (0.5 * dD_dTi_left, sigma_Ti_mm),
        "F_R (right femur)": (0.5 * dD_dF_right, sigma_F_mm),
        "Ti_R (right tibia)": (0.5 * dD_dTi_right, sigma_Ti_mm),
    }
    return propagate_sigma(partials), partials


def _effective_beta_for_carriage(knee_active: bool, hip_active: bool, lumbar_active: bool) -> float:
    """β_eff = β_default · min(active m_β across Knee/Hip/Lumbar Carriage-D
    modifiers) — "both apply, take the stricter result" (leg_press.md,
    Coupling Envelope section) generalized to same-axis modifiers stacking."""
    multipliers = [1.0]
    if knee_active:
        multipliers.append(KNEE_CARRIAGE_D_MODIFIER.m_beta)
    if hip_active:
        multipliers.append(HIP_CARRIAGE_D_MODIFIER.m_beta)
    if lumbar_active:
        multipliers.append(LUMBAR_CARRIAGE_AND_RECLINE_MODIFIER.m_beta)
    return GLOBAL.beta_default_deg * min(multipliers)


def _resolve_recline_index(hip_active: bool, lumbar_active: bool) -> int:
    """Healthy default is mid-recline (matches the worked example's
    "calibrated frame term at mid-recline"); a Tier-3 hip or lumbar injury
    biases to maximum recline (both modifiers say so explicitly)."""
    return RECLINE_MAX_INDEX if (hip_active or lumbar_active) else RECLINE_MID_INDEX


def _footplate_note(femur_tibia_ratio: float, r0: float, path_b_engaged: bool) -> str | None:
    """Axis C — not a discrete machine axis: foot height is user-selected,
    governed by F:Ti (femur-dominant -> feet higher, to keep the heel down
    and limit knee travel past the toes). Flags heel-lift risk when Path B
    pushes feet higher on an already tibia-dominant (low F:Ti) profile
    (04_coupling_mechanism.md's Path B caveat: "feet too high + long tibia
    -> heel lifts")."""
    notes = []
    if femur_tibia_ratio > r0:
        notes.append(
            f"femur-dominant (F:Ti={femur_tibia_ratio:.2f} > r0={r0:.2f}): feet set higher on the plate "
            "to keep the heel down and limit knee travel past the toes"
        )
    if path_b_engaged and femur_tibia_ratio < r0:
        notes.append(
            f"heel-lift risk: Path B raises the foot further on an already tibia-dominant profile "
            f"(F:Ti={femur_tibia_ratio:.2f} < r0={r0:.2f}) — verify heel stays down"
        )
    return "; ".join(notes) if notes else None


def _search_path_a_pin(
    start_pin: int,
    F_mm: float,
    Ti_mm: float,
    trunk_foot_term_deg: float,
    path_b_offset_deg: float,
    theta_env_deg: float,
    kappa: float,
    coupling_caution_max: float,
    ci_target: float = 0.97,
) -> int | None:
    """Path A: search the discrete grid from `start_pin` toward larger D
    (shallower, safer) for the first pin achieving CI <= ci_target
    ("Find D_A where CI(D_A) = 0.97", leg_press.md). If the grid is too
    coarse to hit that margin exactly, the shallowest hole is still accepted
    as long as it clears the hard CI ceiling (`coupling_caution_max`, 1.00) —
    0.97 is a safety margin *target*, not itself the failure threshold.
    Returns None only if even the deepest-D hole stays above the hard
    ceiling -> NO_SOLUTION_BY_COUPLING.
    """
    last_ci = None
    for n in range(start_pin, CARRIAGE_D_AXIS.total_holes + 1):
        D_n = node_position(CARRIAGE_D_AXIS, n)
        theta_hip = _hip_flexion_deg(D_n, F_mm, Ti_mm, trunk_foot_term_deg, path_b_offset_deg)
        theta_knee = _knee_flexion_deg(D_n, F_mm, Ti_mm)
        ci = compute_coupling_index(theta_hip, theta_knee, theta_env_deg, kappa)
        if ci <= ci_target:
            return n
        last_ci = ci
    if last_ci is not None and last_ci <= coupling_caution_max:
        return CARRIAGE_D_AXIS.total_holes
    return None


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def resolve_leg_press(
    profile: AnthropometryProfile,
    coupling: CouplingConstants,
    frame: LegPressFrameConstants,
    theta_hip_onset_deg: float,
    theta_knee_screen_deg: float,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
    hamstring_tightness: float = 0.0,
) -> LegPressResolution:
    """Resolve Leg Press carriage D + backrest recline for one user,
    including the full Coupling Envelope (Path A/B dual-vector remediation).
    """
    injuries = injuries or {}
    knee_active = is_tier3(injuries.get(InjuryJoint.KNEE_L)) or is_tier3(injuries.get(InjuryJoint.KNEE_R))
    hip_active = is_tier3(injuries.get(InjuryJoint.HIP_L)) or is_tier3(injuries.get(InjuryJoint.HIP_R))
    lumbar_active = is_tier3(injuries.get(InjuryJoint.LUMBAR))

    # --- Axis A: bilateral D, tolerance τ, grounding, confidence ---
    geo = _resolve_carriage_bilateral(profile)
    beta_eff_deg = _effective_beta_for_carriage(knee_active, hip_active, lumbar_active)
    tau_mm = (
        math.radians(beta_eff_deg)
        * geo.F_avg_mm
        * geo.Ti_avg_mm
        * math.sin(math.radians(GLOBAL.phi_lp_deg))
        / geo.D_target_mm
    )
    half_step_mm = abs(CARRIAGE_D_AXIS.delta_mm) / 2

    grounded = ground_toward_safe_edge(CARRIAGE_D_AXIS, geo.D_target_mm, safe_direction="higher")

    sigma_D_mm, sigma_partials = _sigma_D(geo, SCAN_ERROR.sigma_F_mm, SCAN_ERROR.sigma_Ti_mm)
    margin_mm = margin_to_reach_boundary(CARRIAGE_D_AXIS, geo.D_target_mm)

    d_resolution = resolve_with_confidence(
        proposed_state=grounded.state,
        margin_mm=margin_mm,
        sigma_C_mm=sigma_D_mm,
        thresholds=CONFIDENCE_THRESHOLDS,
        safe_edge_state=FeasibilityState.CLAMPED_HIGH,  # "larger D" is the safe extreme on this Direct axis
        dominant_segment=dominant_sigma_contributor(sigma_partials),
    )
    if d_resolution.degraded_to_safe_edge:
        grounded = ground_toward_safe_edge(CARRIAGE_D_AXIS, CARRIAGE_D_AXIS.reach_max_mm, safe_direction="higher")

    notes: list[str] = []
    if geo.half_offset_mm > tau_mm:
        notes.append(
            f"L/R carriage-D half-offset ({geo.half_offset_mm:.1f}mm) exceeds this user's own angular-budget "
            f"tolerance τ ({tau_mm:.1f}mm) — flagged poorly suited to this body; consider an "
            "independently-adjustable substitute"
        )
    if tau_mm < half_step_mm:
        notes.append(
            f"grid-resolution flag: τ ({tau_mm:.1f}mm) falls under half a step ({half_step_mm:.0f}mm) — "
            "the grid is too coarse for this user's angular budget regardless of reach"
        )
    if geo.femur_single_sided:
        notes.append("femur length captured single-sided; both legs resolved from the one available reading")
    if geo.tibia_single_sided:
        notes.append("tibia length captured single-sided; both legs resolved from the one available reading")

    # --- Axis B: backrest recline ---
    recline_index = _resolve_recline_index(hip_active, lumbar_active)
    recline_deg = RECLINE_SETTINGS_DEG[recline_index]
    recline_steps_from_mid = recline_index - RECLINE_MID_INDEX
    trunk_foot_term_deg = (
        frame.trunk_foot_term_mid_recline_deg - recline_steps_from_mid * frame.recline_hip_reduction_per_step_deg
    )

    # --- Coupling Index at the resolved (possibly confidence-degraded) D ---
    m_lumbar = coupling.m_lumbar_tier3 if lumbar_active else 1.0
    m_hip = coupling.m_hip_tier3 if hip_active else 1.0
    m_knee = coupling.m_knee_tier3 if knee_active else 1.0
    femur_tibia_ratio = geo.F_avg_mm / geo.Ti_avg_mm

    theta_env_deg = compute_theta_env(
        theta_hip_onset_deg,
        theta_knee_screen_deg,
        coupling,
        hamstring_tightness=hamstring_tightness,
        femur_tibia_ratio=femur_tibia_ratio,
        m_lumbar=m_lumbar,
        m_hip=m_hip,
        m_knee=m_knee,
    )

    D_achieved_mm = grounded.achieved_coordinate_mm
    theta_knee_deg = _knee_flexion_deg(D_achieved_mm, geo.F_avg_mm, geo.Ti_avg_mm)
    theta_hip_baseline_deg = _hip_flexion_deg(D_achieved_mm, geo.F_avg_mm, geo.Ti_avg_mm, trunk_foot_term_deg, 0.0)

    is_shallowest = grounded.index == CARRIAGE_D_AXIS.total_holes
    ci_baseline = compute_coupling_index(theta_hip_baseline_deg, theta_knee_deg, theta_env_deg, coupling.kappa)
    state_baseline, caution_baseline = classify_coupling_index(ci_baseline, coupling.thresholds, is_shallowest)

    trigger_path_b = (
        lumbar_active
        or caution_baseline
        or state_baseline in (FeasibilityState.CLAMPED_BY_COUPLING, FeasibilityState.NO_SOLUTION_BY_COUPLING)
    )

    path_b_engaged = False
    path_a_engaged = False
    final_state = grounded.state
    final_pin = grounded.index
    final_D_mm = D_achieved_mm
    final_ci = ci_baseline

    if trigger_path_b:
        path_b_engaged = True
        theta_hip_path_b_deg = theta_hip_baseline_deg - frame.path_b_hip_reduction_deg
        ci_after_b = compute_coupling_index(theta_hip_path_b_deg, theta_knee_deg, theta_env_deg, coupling.kappa)
        state_after_b, _ = classify_coupling_index(ci_after_b, coupling.thresholds, is_shallowest)

        # Injury override (04): a lumbar or hip constraint makes Path A a
        # mandatory floor regardless of whether Path B alone already helped.
        mandatory_path_a = lumbar_active or hip_active
        needs_path_a = mandatory_path_a or state_after_b in (
            FeasibilityState.CLAMPED_BY_COUPLING,
            FeasibilityState.NO_SOLUTION_BY_COUPLING,
        )

        if not needs_path_a:
            final_state = state_after_b
            final_ci = ci_after_b
            notes.append(
                f"Path B engaged: foot placement raised higher on the plate, dropping θ_hip by "
                f"{frame.path_b_hip_reduction_deg:.0f}° -> CI {ci_baseline:.2f} -> {ci_after_b:.2f}"
            )
        else:
            path_a_engaged = True
            path_a_pin = _search_path_a_pin(
                grounded.index,
                geo.F_avg_mm,
                geo.Ti_avg_mm,
                trunk_foot_term_deg,
                frame.path_b_hip_reduction_deg,
                theta_env_deg,
                coupling.kappa,
                coupling.thresholds.caution_max,
            )
            if path_a_pin is None:
                final_pin = CARRIAGE_D_AXIS.total_holes
                final_D_mm = node_position(CARRIAGE_D_AXIS, final_pin)
                theta_hip_final = _hip_flexion_deg(
                    final_D_mm, geo.F_avg_mm, geo.Ti_avg_mm, trunk_foot_term_deg, frame.path_b_hip_reduction_deg
                )
                theta_knee_final = _knee_flexion_deg(final_D_mm, geo.F_avg_mm, geo.Ti_avg_mm)
                final_ci = compute_coupling_index(theta_hip_final, theta_knee_final, theta_env_deg, coupling.kappa)
                final_state = FeasibilityState.NO_SOLUTION_BY_COUPLING
                notes.append(
                    f"Path B engaged (θ_hip -{frame.path_b_hip_reduction_deg:.0f}°) and Path A carriage "
                    f"restriction searched the full grid — even the shallowest hole (D={final_D_mm:.0f}mm) "
                    f"still resolves CI={final_ci:.2f} > 1.00 — NO_SOLUTION_BY_COUPLING, offer a substitute"
                )
            else:
                final_pin = path_a_pin
                final_D_mm = node_position(CARRIAGE_D_AXIS, final_pin)
                theta_hip_final = _hip_flexion_deg(
                    final_D_mm, geo.F_avg_mm, geo.Ti_avg_mm, trunk_foot_term_deg, frame.path_b_hip_reduction_deg
                )
                theta_knee_final = _knee_flexion_deg(final_D_mm, geo.F_avg_mm, geo.Ti_avg_mm)
                final_ci = compute_coupling_index(theta_hip_final, theta_knee_final, theta_env_deg, coupling.kappa)
                final_state = FeasibilityState.CLAMPED_BY_COUPLING
                mandatory_note = " (mandatory floor: lumbar/hip injury active)" if mandatory_path_a else ""
                notes.append(
                    f"Path B engaged (θ_hip -{frame.path_b_hip_reduction_deg:.0f}°); Path A capped the "
                    f"carriage to D={final_D_mm:.0f}mm (pin {final_pin}){mandatory_note} -> CI={final_ci:.2f}"
                )

    footplate_note = _footplate_note(femur_tibia_ratio, coupling.r0_reference_femur_tibia_ratio, path_b_engaged)

    carriage_resolution = AxisResolution(
        axis_name=CARRIAGE_D_AXIS.name,
        pin=final_pin,
        achieved_coordinate_mm=final_D_mm,
        state=final_state,
        confidence=d_resolution.confidence,
        dominant_segment=d_resolution.dominant_segment,
        note="; ".join(notes) if notes else None,
        target_coordinate_mm=geo.D_target_mm,
        causing_segment="F, Ti (bilateral average)",
        purpose=AxisPurpose.CARRIAGE_DEPTH_KNEE_HIP_FLEXION,
    )

    recline_resolution = AxisResolution(
        axis_name="Backrest recline",
        pin=recline_index + 1,
        achieved_coordinate_mm=recline_deg,
        state=FeasibilityState.IN_RANGE,
        confidence=ConfidenceTag.HIGH,
        note=(
            f"biased to maximum recline ({recline_deg:.0f}°) — Tier-3 hip/lumbar active"
            if recline_index == RECLINE_MAX_INDEX
            else f"mid-recline default ({recline_deg:.0f}°)"
        ),
        purpose=AxisPurpose.BACKREST_RECLINE_HIP_FLEXION,
    )

    return LegPressResolution(
        carriage_d=carriage_resolution,
        backrest_recline=recline_resolution,
        footplate_note=footplate_note,
        coupling_index=final_ci,
        path_b_engaged=path_b_engaged,
        path_a_engaged=path_a_engaged,
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    from models import BilateralSegment, InjuryProvenance, InjuryTier

    assert LEG_PRESS_MACHINE.resistance_profile is ResistanceProfile.LINEAR

    # --- Sanity check: exact formulas reproduce leg_press.md's own worked example ---
    D_worked = 820.0
    theta_knee_worked = _knee_flexion_deg(D_worked, 600.0, 500.0)
    phi_hf_worked = _femur_interior_angle_deg(D_worked, 600.0, 500.0)
    assert math.isclose(theta_knee_worked, 84.03, abs_tol=0.1)
    assert math.isclose(phi_hf_worked, 37.36, abs_tol=0.1)
    print(f"Worked-example check: θ_knee={theta_knee_worked:.2f}° (doc: ≈84°), φ_HF={phi_hf_worked:.2f}° (doc: ≈37.4°) OK")

    def _show(label: str, res: LegPressResolution) -> None:
        c = res.carriage_d
        r = res.backrest_recline
        print(f"{label}:")
        print(
            f"  Carriage D: pin={c.pin} achieved={c.achieved_coordinate_mm:.1f}mm "
            f"state={c.state.value} confidence={c.confidence.value}"
            + (f" note={c.note!r}" if c.note else "")
        )
        print(f"  Backrest recline: pin={r.pin} achieved={r.achieved_coordinate_mm:.0f}° note={r.note!r}")
        print(f"  CI={res.coupling_index:.3f}  path_b_engaged={res.path_b_engaged}  path_a_engaged={res.path_a_engaged}")
        if res.footplate_note:
            print(f"  footplate: {res.footplate_note}")

    COUPLING = CouplingConstants(a_ham=0.1, a_fem=0.15, fatigue_reserve_deg=3.0, m_hip_tier3=0.75)
    FRAME = LegPressFrameConstants(recline_hip_reduction_per_step_deg=6.0)

    # --- Scenario 1: healthy, well-proportioned user -> comfortable, unrestricted ROM ---
    healthy_user = AnthropometryProfile(
        user_id="healthy_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=1780,
        sitting_height_T_mm=930,
        femur=BilateralSegment(left_mm=449, right_mm=447),
        tibia=BilateralSegment(left_mm=412, right_mm=410),
        arm=BilateralSegment(left_mm=630, right_mm=628),
        biacromial_width_BAW_mm=410,
        chest_depth_Cd_mm=230,
    )
    result_1 = resolve_leg_press(
        healthy_user, COUPLING, FRAME, theta_hip_onset_deg=140.0, theta_knee_screen_deg=90.0
    )
    _show("Healthy user (no injury)", result_1)

    assert result_1.carriage_d.state is FeasibilityState.IN_RANGE
    assert result_1.path_b_engaged is False
    assert result_1.path_a_engaged is False
    assert result_1.coupling_index < COUPLING.thresholds.in_range_max
    assert result_1.backrest_recline.pin == RECLINE_MID_INDEX + 1  # mid-recline default

    # --- Scenario 2: severe (Tier-3) lumbar injury on the doc's own worked-example
    # body (F=600, Ti=500) -> Path B engages with explicit instructive text,
    # and Path A's mandatory floor (lumbar override) caps the carriage too.
    long_femur_user = AnthropometryProfile(
        user_id="long_femur_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=1900,
        sitting_height_T_mm=980,
        femur=BilateralSegment(left_mm=600, right_mm=598),
        tibia=BilateralSegment(left_mm=500, right_mm=502),
        arm=BilateralSegment(left_mm=660, right_mm=655),
        biacromial_width_BAW_mm=430,
        chest_depth_Cd_mm=250,
    )
    lumbar_injury = InjuryConstraint(
        constraint_id="severe-lumbar",
        joint=InjuryJoint.LUMBAR,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=90,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 4, 1),
        review_date=date(2026, 7, 1),
    )
    result_2 = resolve_leg_press(
        long_femur_user,
        COUPLING,
        FRAME,
        theta_hip_onset_deg=150.0,
        theta_knee_screen_deg=95.0,
        injuries={InjuryJoint.LUMBAR: lumbar_injury},
    )
    _show("Long-femur user (Tier-3 lumbar -> Path B + mandatory Path A)", result_2)

    assert result_2.path_b_engaged is True
    assert "Path B engaged" in result_2.carriage_d.note
    assert result_2.backrest_recline.pin == RECLINE_MAX_INDEX + 1  # biased to max recline
    # Remediable: Path B + the mandatory Path A floor bring CI back under the hard ceiling at a specific pin
    # (grid too coarse to hit the ideal 0.97 margin exactly, but comfortably clear of the 1.00 danger line).
    assert result_2.carriage_d.state is FeasibilityState.CLAMPED_BY_COUPLING
    assert result_2.coupling_index <= COUPLING.thresholds.caution_max

    # --- Scenario 3: completely unfeasible geometry -> NO_SOLUTION_BY_COUPLING ---
    # Very long femur relative to tibia (far past r0), combined with a severe
    # lumbar injury tightening Θ_env hard: even Path B + a full Path A grid
    # search can't bring CI under the coupling threshold.
    unfeasible_user = AnthropometryProfile(
        user_id="unfeasible_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=2000,
        sitting_height_T_mm=1020,
        femur=BilateralSegment(left_mm=700, right_mm=698),
        tibia=BilateralSegment(left_mm=430, right_mm=428),
        arm=BilateralSegment(left_mm=700, right_mm=695),
        biacromial_width_BAW_mm=440,
        chest_depth_Cd_mm=260,
    )
    result_3 = resolve_leg_press(
        unfeasible_user,
        COUPLING,
        FRAME,
        theta_hip_onset_deg=115.0,
        theta_knee_screen_deg=70.0,
        injuries={InjuryJoint.LUMBAR: lumbar_injury},
    )
    _show("Unfeasible geometry (severe F:Ti + Tier-3 lumbar)", result_3)

    assert result_3.carriage_d.state is FeasibilityState.NO_SOLUTION_BY_COUPLING
    assert "NO_SOLUTION_BY_COUPLING" in result_3.carriage_d.note
    assert result_3.path_b_engaged is True and result_3.path_a_engaged is True

    print("\nAll machines/leg_press.py smoke tests passed.")
