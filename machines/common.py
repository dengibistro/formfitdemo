"""Shared building blocks for concrete machine modules (machines/*.py).

Not part of the generic engines (biomechanics.py, safety.py) — these are
conventions for how the individual machine modules are wired together: the
shared result shape, the Tier-3-only gating convention (no interpolation
formula exists yet for Tier 1/2 — temporal model out of scope), the
single-sided-bilateral fallback, the congruence seat-height *pattern*
(`Seat = Y_machine − k_sh·T`) that Chest Press and Shoulder Press both use
via `resolve_congruence_seat` — Shoulder Press no longer shares Chest
Press's raw k_sh value, though; it passes its own backrest-recline-corrected
`K_SH_EFFECTIVE` instead (see `shoulder_press.py`'s own comment) — and the
femur-driven seat-depth pattern Leg Extension and Leg Curl both use verbatim
(`leg_curl.md`: "identical relation to Leg Extension"). Factored out once a
second machine needed them, rather than re-derived per file.
"""

from dataclasses import dataclass

from biomechanics import ground_to_nearest_hole, margin_to_reach_boundary
from models import (
    AxisPurpose,
    AxisType,
    BilateralSegment,
    ConfidenceTag,
    ConfidenceThresholds,
    CouplingFlag,
    FeasibilityState,
    InjuryConstraint,
    InjuryTierBands,
    MachineAxis,
    ScaleDirection,
)
from safety import classify_confidence, confidence_ratio, dominant_sigma_contributor, propagate_single_segment_sigma, propagate_sigma

TIER_BANDS = InjuryTierBands()


@dataclass(frozen=True)
class AxisResolution:
    """The standard structured response for one resolved (or flagged) axis:
    target pin, achieved coordinate, feasibility state, and confidence tag.
    `pin`/`achieved_coordinate_mm` are None for fixed (non-adjustable)
    hardware that only ever produces a flag (e.g. a moulded grip).

    `target_coordinate_mm`/`causing_segment`/`purpose` exist purely for a
    downstream explanation layer (machines/explanations.py) — none of them
    change resolution behavior. `causing_segment` names which anthropometric
    input(s) drove `target_coordinate_mm`; it is a different concept from
    `dominant_segment`, which names whichever segment's *scan noise*
    dominates the confidence tag, not which segment produced the target.
    """

    axis_name: str
    pin: int | None
    achieved_coordinate_mm: float | None
    state: FeasibilityState
    confidence: ConfidenceTag
    dominant_segment: str | None = None
    note: str | None = None
    target_coordinate_mm: float | None = None
    causing_segment: str | None = None
    purpose: AxisPurpose | None = None


def is_tier3(injury: InjuryConstraint | None) -> bool:
    """Whether an injury's applied severity sits in the Tier-3 band the
    quoted m_β/Δψ figures are baselined to. No interpolation formula exists
    for Tier 1/2 (temporal/tiering model out of scope per Step 3), so a
    sub-Tier-3 injury leaves the healthy baseline in force."""
    return injury is not None and injury.applied_severity >= TIER_BANDS.tier_3.severity_min


def bilateral_values(segment: BilateralSegment) -> tuple[float, float, bool]:
    """(left, right, reduced_confidence). Falls back to the one captured side
    for both when the scanner couldn't separate L/R, rather than pretending
    symmetry was actually measured (02_anthropometry.md, "Per-side capture")."""
    if segment.left_mm is not None and segment.right_mm is not None:
        return segment.left_mm, segment.right_mm, False
    value = segment.left_mm if segment.left_mm is not None else segment.right_mm
    return value, value, True


def resolve_congruence_axis(
    axis: MachineAxis,
    target_coordinate_mm: float,
    confidence_coefficient: float,
    confidence_sigma_mm: float,
    thresholds: ConfidenceThresholds,
    dominant_segment_name: str,
    purpose: AxisPurpose | None = None,
) -> AxisResolution:
    """Generic single-segment congruence-axis resolution: nearest-node
    grounding plus a single-segment confidence tag (σ_C = coefficient · σ).

    Congruence axes are symmetric (01, Axis types) — there is no "safer"
    hole to retreat to on LOW confidence, so the tag is surfaced but the
    nearest-node result itself is not overridden.
    """
    grounded = ground_to_nearest_hole(axis, target_coordinate_mm)

    sigma_c = propagate_single_segment_sigma(confidence_coefficient, confidence_sigma_mm)
    margin = margin_to_reach_boundary(axis, target_coordinate_mm)
    confidence = classify_confidence(confidence_ratio(margin, sigma_c), thresholds)

    return AxisResolution(
        axis_name=axis.name,
        pin=grounded.index,
        achieved_coordinate_mm=grounded.achieved_coordinate_mm,
        state=grounded.state,
        confidence=confidence,
        dominant_segment=dominant_segment_name if confidence is ConfidenceTag.LOW else None,
        note="residual exceeds half a step" if grounded.exceeds_half_step else None,
        target_coordinate_mm=target_coordinate_mm,
        causing_segment=dominant_segment_name,
        purpose=purpose,
    )


def resolve_congruence_seat(
    axis: MachineAxis,
    y_machine_mm: float,
    k_sh: float,
    sitting_height_T_mm: float,
    sigma_T_mm: float,
    thresholds: ConfidenceThresholds,
    purpose: AxisPurpose = AxisPurpose.SEAT_HEIGHT_SHOULDER_ALIGNMENT,
) -> AxisResolution:
    """Seat = Y_machine − k_sh·T. Shared by Chest Press and Shoulder Press
    (identical rule and sensitivity in both machine files)."""
    target_seat_mm = y_machine_mm - k_sh * sitting_height_T_mm
    return resolve_congruence_axis(
        axis, target_seat_mm, k_sh, sigma_T_mm, thresholds, "T (sitting height)", purpose=purpose
    )


def resolve_bilateral_congruence_axis(
    axis: MachineAxis,
    left_value_mm: float,
    right_value_mm: float,
    offset_mm: float,
    sigma_segment_mm: float,
    thresholds: ConfidenceThresholds,
    segment_label: str,
    extra_note: str | None = None,
    purpose: AxisPurpose | None = None,
) -> AxisResolution:
    """Minimax-midpoint bilateral congruence resolution:
    `Coord = (L + R)/2 − offset`, nearest-node grounded.

    σ_C is propagated as two half-weighted segment terms (Coord's partial
    derivative w.r.t. each side is 0.5 after averaging), not the raw
    single-side σ — this refines a machine file's simplified "σ_C = σ_segment
    directly" note for the single-segment case into the correct two-sided
    form once L/R are actually being averaged (02_anthropometry.md, general
    σ_C formula).

    Flags (via `note`, not a state change) when the L/R half-offset exceeds
    twice the axis tolerance (one full step) — the same escalation threshold
    used throughout this codebase for congruence-axis asymmetry.
    """
    avg_mm = (left_value_mm + right_value_mm) / 2
    half_offset_mm = abs(left_value_mm - right_value_mm) / 2
    target_mm = avg_mm - offset_mm

    grounded = ground_to_nearest_hole(axis, target_mm)

    partials = {f"{segment_label}_L": (0.5, sigma_segment_mm), f"{segment_label}_R": (0.5, sigma_segment_mm)}
    sigma_c = propagate_sigma(partials)
    margin = margin_to_reach_boundary(axis, target_mm)
    confidence = classify_confidence(confidence_ratio(margin, sigma_c), thresholds)

    notes = []
    if half_offset_mm > abs(axis.delta_mm):
        notes.append(
            f"L/R {segment_label} half-offset ({half_offset_mm:.1f}mm) exceeds twice the axis tolerance — "
            "flagged poorly suited to this body; consider an independently-adjustable substitute"
        )
    if extra_note:
        notes.append(extra_note)

    return AxisResolution(
        axis_name=axis.name,
        pin=grounded.index,
        achieved_coordinate_mm=grounded.achieved_coordinate_mm,
        state=grounded.state,
        confidence=confidence,
        dominant_segment=dominant_sigma_contributor(partials) if confidence is ConfidenceTag.LOW else None,
        note="; ".join(notes) if notes else None,
        target_coordinate_mm=target_mm,
        causing_segment=f"{segment_label} (L/R average)",
        purpose=purpose,
    )


LEG_MACHINE_SEAT_DEPTH_AXIS = MachineAxis(
    name="Seat depth / backrest",
    axis_type=AxisType.CONGRUENCE,
    total_holes=7,
    direction=ScaleDirection.DIRECT,  # n=1 = shallowest/short femur, n=7 = deepest/long femur
    alpha_deg=0,
    p0_mm=340,
    delta_mm=30,
    reach_min_mm=340,
    reach_max_mm=520,
    coupling=CouplingFlag.INDEPENDENT,
)

FEMUR_SEAT_DEPTH_OFFSET_MM = 30.0  # δ_F ≈ 30mm


def resolve_seat_depth_from_femur(
    femur: BilateralSegment,
    sigma_F_mm: float,
    thresholds: ConfidenceThresholds,
) -> AxisResolution:
    """Seat_depth = F − δ_F. Shared verbatim by Leg Extension and Leg Curl
    (leg_curl.md: "identical relation to Leg Extension")."""
    femur_left, femur_right, single_sided = bilateral_values(femur)
    extra_note = (
        "femur length captured single-sided; both legs resolved from the one available reading"
        if single_sided
        else None
    )
    return resolve_bilateral_congruence_axis(
        LEG_MACHINE_SEAT_DEPTH_AXIS,
        femur_left,
        femur_right,
        FEMUR_SEAT_DEPTH_OFFSET_MM,
        sigma_F_mm,
        thresholds,
        "F (femur)",
        extra_note=extra_note,
        purpose=AxisPurpose.KNEE_AXIS_ALIGNMENT,
    )
