"""Matrix Lat Pulldown — concrete machine implementation.

Reads `machines/lat_pulldown.md`. Two axes, both unlike anything Chest Press
or Shoulder Press needed:

- Axis A (Thigh pad height, capping): the safety-critical piece the task
  calls out — locking the pelvis so the lat pulls the trunk, not the pelvis,
  toward the bar under heavy external resistance. Its bilateral rule is
  explicitly hybrid: "treat as congruence for this purpose since it's a
  physical lock, not a capping stop" (minimax-midpoint the L/R leg lengths)
  even though the axis's own injury handling is capping-style (safe-edge,
  hard-enforced under a lumbar injury).
- Axis B (Overhead bar, fixed at 1650mm): not a solvable axis at all, only a
  feasibility flag on seated overhead reach.

Neither axis gives a numeric coefficient in lat_pulldown.md/constants.md
(only a qualitative relationship: "height driven by seated leg geometry
F+Ti"; "flag when reach forces over-elevation"). Rather than silently
inventing one, both are exposed as required `LatPulldownFrameConstants`
fields — the same discipline models.py already uses for a_ham/a_fem/
m_hip_tier3/fatigue_reserve_deg: illustrative-but-unfixed numbers must be
supplied consciously, not assumed inside the function body.

The Coupling Index (`04`) does not apply, and the Resistive Moment Model
needs no correction — `resistance_profile: cam`.

Run as `python3 -m machines.lat_pulldown` from the `formfit_spec/` directory.
"""

import math
from dataclasses import dataclass

from biomechanics import ground_toward_safe_edge, margin_to_reach_boundary
from machines.common import AxisResolution, bilateral_values, is_tier3, scan_error_for
from models import (
    AnthropometryProfile,
    AxisPurpose,
    AxisType,
    ConfidenceTag,
    ConfidenceThresholds,
    FeasibilityState,
    GlobalCoefficients,
    InjuryConstraint,
    InjuryJoint,
    MachineAxis,
    ScaleDirection,
)
from safety import classify_confidence, confidence_ratio, dominant_sigma_contributor, propagate_sigma, resolve_with_confidence

# ---------------------------------------------------------------------------
# Lat Pulldown Passport — constants.md via models.py, plus this machine's own
# fixed-frame numbers (canonical only in machines/lat_pulldown.md)
# ---------------------------------------------------------------------------

GLOBAL = GlobalCoefficients()      # k_sh = 0.63, ...
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

BAR_HEIGHT_MM = 1940.0  # fixed overhead bar height at grip, from floor (field-measured 2026-08: floor to bar's bottom edge, was 1650)

# KNOWN-STALE, NOT FIXED THIS ROUND (field audit 2026-08): the field
# measurement for this axis came back as [530, 780]mm from the FLOOR, but
# `p0_mm`/`delta_mm`/`reach_*_mm` below are all "from seat" per the formula
# this axis was designed against (seat_pan_height_mm doesn't move on this
# machine and only needs measuring once) — converting the raw field numbers
# into the "from seat" frame this axis expects needs that one extra
# measurement, which wasn't taken yet. Re-measured 2026-09 to the roller's
# CENTRE (its edge is hard to find): 53/58/63/68/73/78 cm, pin 1 = lowest.
# Bar 194 cm. Confirmed clean on-site: 6 holes
# (not 5), 50mm step (not 35mm) — only the reference frame conversion is
# blocking the update, not measurement quality. Left untouched rather than
# guessing the missing seat-height offset.
THIGH_PAD_AXIS = MachineAxis(
    name="Thigh pad height",
    axis_type=AxisType.CAPPING,
    total_holes=5,
    direction=ScaleDirection.DIRECT,  # n=1 = lowest/small legs, n=5 = highest/large legs
    alpha_deg=90,
    p0_mm=110,
    delta_mm=35,
    reach_min_mm=110,
    reach_max_mm=250,
    safe_direction="tighter clamp (pad down onto thigh)",
    beta_deg=4,
)


@dataclass(frozen=True)
class LatPulldownFrameConstants:
    """Numbers `lat_pulldown.md` states only as a relationship, not a value —
    required, no defaults, same discipline as models.py's a_ham/a_fem/
    m_hip_tier3 (illustrative-but-unfixed constants must be supplied
    consciously)."""

    thigh_pad_leg_length_coefficient: float  # TargetPadHeight_mm = coeff * (F + Ti)
    seat_pan_height_mm: float  # bench height off the floor — needed for the overhead-reach check
    overhead_reach_tolerance_mm: float  # ± band around the fixed bar before CLAMPED, 2x before NO_SOLUTION


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatPulldownResolution:
    thigh_pad: AxisResolution
    overhead_reach: AxisResolution


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_thigh_pad(
    profile: AnthropometryProfile,
    frame: LatPulldownFrameConstants,
    lumbar_injury: InjuryConstraint | None,
) -> AxisResolution:
    """Axis A — height driven by seated leg geometry (F+Ti), safe direction
    is the tighter clamp (lower mm). Bilateral: minimax-midpoint the L/R leg
    lengths (treated as congruence for this purpose, per lat_pulldown.md),
    then resolve that single shared coordinate as a capping axis.

    A Tier-3 lumbar injury hard-enforces the tight clamp outright — per the
    doc, this "does not merely narrow tolerance... makes the already-safe
    direction mandatory" — so the normal computed target is bypassed
    entirely rather than merely biased toward it.
    """
    femur_left, femur_right, femur_single_sided = bilateral_values(profile.femur)
    tibia_left, tibia_right, tibia_single_sided = bilateral_values(profile.tibia)

    leg_length_left_mm = femur_left + tibia_left
    leg_length_right_mm = femur_right + tibia_right
    leg_length_mm = (leg_length_left_mm + leg_length_right_mm) / 2
    half_offset_mm = abs(leg_length_left_mm - leg_length_right_mm) / 2

    coeff = frame.thigh_pad_leg_length_coefficient
    target_pad_mm = coeff * leg_length_mm

    asymmetry_note = None
    if half_offset_mm > abs(THIGH_PAD_AXIS.delta_mm):  # > twice the axis tolerance (half-step), 02_anthropometry.md
        asymmetry_note = (
            f"L/R leg-length half-offset ({half_offset_mm:.1f}mm) exceeds twice the axis tolerance — "
            "flagged poorly suited to this body; consider an independently-adjustable substitute"
        )

    if is_tier3(lumbar_injury):
        grounded = ground_toward_safe_edge(THIGH_PAD_AXIS, THIGH_PAD_AXIS.reach_min_mm, safe_direction="lower")
        note = "Tier-3 lumbar: tight clamp hard-enforced (mandatory override, not just narrowed tolerance)"
        if asymmetry_note:
            note = f"{note}; {asymmetry_note}"
        return AxisResolution(
            axis_name=THIGH_PAD_AXIS.name,
            pin=grounded.index,
            achieved_coordinate_mm=grounded.achieved_coordinate_mm,
            state=FeasibilityState.CLAMPED_LOW,
            confidence=ConfidenceTag.HIGH,  # a mandatory rule, not a computed estimate — no uncertainty in it
            note=note,
            target_coordinate_mm=target_pad_mm,
            causing_segment="F, Ti (leg length)",
            purpose=AxisPurpose.PELVIC_LOCK_THIGH_PAD,
        )

    grounded = ground_toward_safe_edge(THIGH_PAD_AXIS, target_pad_mm, safe_direction="lower")

    partials = {
        "F_L (left femur)": (coeff / 2, scan_error_for(profile).sigma_F_mm),
        "Ti_L (left tibia)": (coeff / 2, scan_error_for(profile).sigma_Ti_mm),
        "F_R (right femur)": (coeff / 2, scan_error_for(profile).sigma_F_mm),
        "Ti_R (right tibia)": (coeff / 2, scan_error_for(profile).sigma_Ti_mm),
    }
    sigma_pad = propagate_sigma(partials)
    margin = margin_to_reach_boundary(THIGH_PAD_AXIS, target_pad_mm)

    resolution = resolve_with_confidence(
        proposed_state=grounded.state,
        margin_mm=margin,
        sigma_C_mm=sigma_pad,
        thresholds=CONFIDENCE_THRESHOLDS,
        safe_edge_state=FeasibilityState.CLAMPED_LOW,
        dominant_segment=dominant_sigma_contributor(partials),
    )
    if resolution.degraded_to_safe_edge:
        grounded = ground_toward_safe_edge(THIGH_PAD_AXIS, THIGH_PAD_AXIS.reach_min_mm, safe_direction="lower")

    note_parts = []
    if femur_single_sided or tibia_single_sided:
        note_parts.append("leg length captured single-sided on at least one segment; reduced confidence in the split")
    if asymmetry_note:
        note_parts.append(asymmetry_note)

    return AxisResolution(
        axis_name=THIGH_PAD_AXIS.name,
        pin=grounded.index,
        achieved_coordinate_mm=grounded.achieved_coordinate_mm,
        state=resolution.state,
        confidence=resolution.confidence,
        dominant_segment=resolution.dominant_segment,
        note="; ".join(note_parts) if note_parts else None,
        target_coordinate_mm=target_pad_mm,
        causing_segment="F, Ti (leg length)",
        purpose=AxisPurpose.PELVIC_LOCK_THIGH_PAD,
    )


def _resolve_overhead_reach(
    profile: AnthropometryProfile,
    frame: LatPulldownFrameConstants,
    shoulder_left: InjuryConstraint | None,
    shoulder_right: InjuryConstraint | None,
    lumbar_injury: InjuryConstraint | None,
) -> AxisResolution:
    """Axis B — Overhead bar, FIXED at 1650mm. Not a solvable axis: flags
    CLAMPED/NO_SOLUTION when seated overhead reach forces shoulder
    over-elevation (long arm/torso) or fails to load full ROM (short
    arm/torso). Reach uses the full-extension collapse (R = A) established
    in chest_press.py — same law-of-cosines edge case, θ_e = 180°.
    """
    arm_left, arm_right, _ = bilateral_values(profile.arm)
    arm_reach_mm = max(arm_left, arm_right)  # governing/longer side for an overhead reach check

    shoulder_height_seated_mm = frame.seat_pan_height_mm + GLOBAL.k_sh * profile.sitting_height_T_mm
    seated_overhead_reach_mm = shoulder_height_seated_mm + arm_reach_mm
    margin_mm = seated_overhead_reach_mm - BAR_HEIGHT_MM

    sigma_reach = math.sqrt((GLOBAL.k_sh * scan_error_for(profile).sigma_T_mm) ** 2 + scan_error_for(profile).sigma_A_mm**2)
    confidence = classify_confidence(confidence_ratio(abs(margin_mm), sigma_reach), CONFIDENCE_THRESHOLDS)

    tolerance = frame.overhead_reach_tolerance_mm
    if abs(margin_mm) <= tolerance:
        state, note = FeasibilityState.IN_RANGE, None
    elif abs(margin_mm) <= 2 * tolerance:
        if margin_mm > 0:
            state = FeasibilityState.CLAMPED_HIGH
            note = "seated reach exceeds the fixed bar — shoulder over-elevation risk; bar effectively low relative to reach"
        else:
            state = FeasibilityState.CLAMPED_LOW
            note = "seated reach falls short of the fixed bar — reduced ROM; bar effectively high relative to reach"
    else:
        state = FeasibilityState.NO_SOLUTION
        confidence = ConfidenceTag.HIGH  # confidence-immune (02, hard rule 2)
        note = (
            "seated reach far exceeds the fixed bar — severe over-elevation risk, offer substitute"
            if margin_mm > 0
            else "seated reach falls far short of the fixed bar — cannot load meaningful ROM, offer substitute"
        )

    flags = [note] if note else []
    if is_tier3(shoulder_left) or is_tier3(shoulder_right):
        flags.append("Tier-3 shoulder: ROM restricted to front-to-chest pull path only, no full overhead reach")
    if is_tier3(lumbar_injury):
        flags.append("Tier-3 lumbar: overhead-extension flag — end-range reach loads the lumbar spine, monitor closely")

    return AxisResolution(
        axis_name="Overhead bar (fixed)",
        pin=None,
        achieved_coordinate_mm=BAR_HEIGHT_MM,
        state=state,
        confidence=confidence,
        note="; ".join(flags) if flags else None,
        target_coordinate_mm=seated_overhead_reach_mm,
        causing_segment="T (sitting height), A (arm length)",
        purpose=AxisPurpose.OVERHEAD_REACH_SHOULDER_ELEVATION,
    )


def resolve_lat_pulldown(
    profile: AnthropometryProfile,
    frame: LatPulldownFrameConstants,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
) -> LatPulldownResolution:
    """Resolve Lat Pulldown thigh-pad height + overhead-reach flag for one user."""
    injuries = injuries or {}
    lumbar = injuries.get(InjuryJoint.LUMBAR)
    shoulder_l = injuries.get(InjuryJoint.SHOULDER_L)
    shoulder_r = injuries.get(InjuryJoint.SHOULDER_R)

    thigh_pad = _resolve_thigh_pad(profile, frame, lumbar)
    overhead_reach = _resolve_overhead_reach(profile, frame, shoulder_l, shoulder_r, lumbar)
    return LatPulldownResolution(thigh_pad=thigh_pad, overhead_reach=overhead_reach)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    from models import BilateralSegment, InjuryProvenance, InjuryTier

    # Illustrative frame constants (not given by the spec — see
    # LatPulldownFrameConstants docstring): coefficient chosen so a
    # typical adult F+Ti (~880mm) lands mid-range (~180mm, hole 3);
    # seat_pan_height chosen as a plausible fixed bench height; tolerance
    # a generous illustrative band, mirroring the "twice tolerance"
    # escalation pattern used elsewhere in the spec.
    FRAME = LatPulldownFrameConstants(
        thigh_pad_leg_length_coefficient=0.20,
        seat_pan_height_mm=450.0,
        overhead_reach_tolerance_mm=60.0,
    )

    def _show(label: str, res: LatPulldownResolution) -> None:
        print(f"{label}:")
        for axis in (res.thigh_pad, res.overhead_reach):
            pin_str = "n/a" if axis.pin is None else str(axis.pin)
            coord_str = "n/a" if axis.achieved_coordinate_mm is None else f"{axis.achieved_coordinate_mm:.1f}mm"
            print(
                f"  {axis.axis_name}: pin={pin_str} achieved={coord_str} "
                f"state={axis.state.value} confidence={axis.confidence.value}"
                + (f" note={axis.note!r}" if axis.note else "")
            )

    # --- Edge case 1: tall basketball-player profile, no injury ---
    # T/arm pushed further out than the other machines' shared basketball-
    # player fixture (2026-08: BAR_HEIGHT_MM rose 290mm, so the old fixture's
    # margin no longer clears the fixed bar) — deliberately extreme enough to
    # still exercise the over-elevation clamp against the new, higher bar.
    basketball_player = AnthropometryProfile(
        user_id="basketball_player",
        captured_at=date(2026, 7, 6),
        height_H_mm=2290,
        sitting_height_T_mm=1350,
        femur=BilateralSegment(left_mm=560, right_mm=558),
        tibia=BilateralSegment(left_mm=520, right_mm=522),
        arm=BilateralSegment(left_mm=800, right_mm=795),
        biacromial_width_BAW_mm=480,
        chest_depth_Cd_mm=290,
    )
    result_1 = resolve_lat_pulldown(basketball_player, FRAME)
    _show("Basketball player (no injury)", result_1)

    # F+Ti ~ 1080mm avg -> target pad 216mm, within [110,250]: comfortably IN_RANGE.
    assert result_1.thigh_pad.state is FeasibilityState.IN_RANGE
    # Long arms + tall torso: seated reach should exceed the fixed bar -> over-elevation risk.
    assert result_1.overhead_reach.state in (FeasibilityState.CLAMPED_HIGH, FeasibilityState.NO_SOLUTION)

    # --- Edge case 2: petite female profile, Tier-3 lumbar injury ---
    petite_user = AnthropometryProfile(
        user_id="petite_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=1550,
        sitting_height_T_mm=780,
        femur=BilateralSegment(left_mm=380, right_mm=378),
        tibia=BilateralSegment(left_mm=350, right_mm=352),
        arm=BilateralSegment(left_mm=520, right_mm=515),
        biacromial_width_BAW_mm=340,
        chest_depth_Cd_mm=195,
    )
    lumbar_injury = InjuryConstraint(
        constraint_id="petite-lumbar",
        joint=InjuryJoint.LUMBAR,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=20,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    result_2 = resolve_lat_pulldown(petite_user, FRAME, injuries={InjuryJoint.LUMBAR: lumbar_injury})
    _show("Petite user (Tier-3 lumbar -> hard-enforced tight clamp)", result_2)

    assert result_2.thigh_pad.state is FeasibilityState.CLAMPED_LOW
    assert math.isclose(result_2.thigh_pad.achieved_coordinate_mm, THIGH_PAD_AXIS.reach_min_mm)
    assert result_2.thigh_pad.confidence is ConfidenceTag.HIGH
    assert "hard-enforced" in result_2.thigh_pad.note
    # Short arms + short torso: seated reach should fall short of the fixed bar.
    assert result_2.overhead_reach.state in (FeasibilityState.CLAMPED_LOW, FeasibilityState.NO_SOLUTION)
    assert "overhead-extension flag" in result_2.overhead_reach.note

    # --- Dedicated check: L/R leg-length asymmetry flag fires ---
    asymmetric_legs = AnthropometryProfile(
        user_id="asymmetric_legs",
        captured_at=date(2026, 7, 6),
        height_H_mm=1750,
        sitting_height_T_mm=920,
        femur=BilateralSegment(left_mm=480, right_mm=430),  # 50mm difference
        tibia=BilateralSegment(left_mm=430, right_mm=390),  # 40mm difference
        arm=BilateralSegment(left_mm=630, right_mm=625),
        biacromial_width_BAW_mm=400,
        chest_depth_Cd_mm=230,
    )
    result_3 = resolve_lat_pulldown(asymmetric_legs, FRAME)
    _show("Asymmetric legs (no injury, escalation flag expected)", result_3)

    assert result_3.thigh_pad.note is not None and "half-offset" in result_3.thigh_pad.note

    print("\nAll machines/lat_pulldown.py smoke tests passed.")
