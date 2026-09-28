"""Matrix Shoulder Press — concrete machine implementation.

Reads `machines/shoulder_press.md`. Seat height reuses Chest Press's
congruence machinery (`machines/common.py:resolve_congruence_seat`) but NOT
its raw k_sh anymore — see `K_SH_EFFECTIVE` below, a backrest-recline
correction specific to this machine. Grip width is fixed hardware (moulded
dual handle, ~520mm span) — not a discrete axis, only a feasibility flag
against g_grip·BAW. The Coupling Index (`04`) does not apply, and the
Resistive Moment Model needs no correction — `resistance_profile: cam`.

Injury handling here is a whole-machine gate, not an axis-level one: a
Tier-3 shoulder injury blocks the machine outright ("nothing on-axis to
tune, so gate the machine" — shoulder_press.md), unlike Chest Press's
per-axis cap shift.

Run as `python3 -m machines.shoulder_press` from the `formfit_spec/` directory.
"""

import math
from dataclasses import dataclass

from machines.common import AxisResolution, is_tier3, resolve_congruence_seat, scan_error_for
from models import (
    AnthropometryProfile,
    AxisPurpose,
    AxisType,
    ConfidenceTag,
    ConfidenceThresholds,
    CouplingFlag,
    FeasibilityState,
    GlobalCoefficients,
    InjuryConstraint,
    InjuryJoint,
    MachineAxis,
    ScaleDirection,
)
from safety import classify_confidence, confidence_ratio, propagate_single_segment_sigma, resolve_with_confidence

# ---------------------------------------------------------------------------
# Shoulder Press Passport — constants.md via models.py, plus this machine's
# own fixed-frame numbers (canonical only in machines/shoulder_press.md)
# ---------------------------------------------------------------------------

GLOBAL = GlobalCoefficients()      # k_sh = 0.63, g_grip ∈ [1.0, 1.5], ...
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

Y_MACHINE_MM = 1000.0        # fixed handle-bottom datum, from floor (field-measured 2026-08, was 1150)
FIXED_GRIP_SPAN_MM = 520.0   # moulded dual handle, effective span, not adjustable — not re-measured this round

# k_sh (constants.md: "GH-joint height above seat ÷ sitting height" = 0.63) is
# an upright/vertical-torso ratio — that's how sitting height T is itself
# defined anthropometrically. This machine's backrest is NOT vertical: user
# visually estimated ~75-80° from the floor on a real MG-PL23 photo
# (2026-08-08) — i.e. ~10-15° reclined from vertical, midpoint 12.5° used
# here. This supersedes shoulder_press.md's old "88° from horizontal"
# figure, which predates the 2026-08 field audit and was never itself
# field-verified (the audit only touched Y_machine and seat holes/reach).
# Still an eyeballed estimate, NOT a field measurement — flagged the same
# way Pec Deck's illustrative hole-angle spacing was, pending a real
# protractor/level reading on-site.
#
# Physics: k_sh·T is the GH-joint's height above the seat pan for an
# upright torso — a fixed anatomical segment length along the spine. A
# backrest reclined by θ from vertical tilts that same segment back, so
# its VERTICAL projection (what actually matters for aligning the handle
# line) shrinks by cos(θ), while T itself is still measured/scanned
# upright and unaffected. Left uncorrected, the shared formula would place
# the seat systematically too LOW for this machine — handles starting
# above the user's actual (reclined) shoulder height.
BACKREST_RECLINE_DEG = 12.5
K_SH_EFFECTIVE = GLOBAL.k_sh * math.cos(math.radians(BACKREST_RECLINE_DEG))  # ≈ 0.615

# Field-confirmed 2026-09: 35 / 38 / 41 / 44 / 47 cm from the floor, numbered
# from the BOTTOM (1 = lowest, 5 = highest). Previously Inverted — every pin
# the assistant gave was mirrored.
SEAT_AXIS = MachineAxis(
    name="Seat height",
    axis_type=AxisType.CONGRUENCE,
    total_holes=5,
    direction=ScaleDirection.DIRECT,  # n=1 = lowest seat, n=5 = highest
    alpha_deg=90,
    p0_mm=350,
    delta_mm=30,
    reach_min_mm=350,
    reach_max_mm=470,
    coupling=CouplingFlag.INDEPENDENT,
)


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShoulderPressResolution:
    seat: AxisResolution
    grip: AxisResolution
    machine_gated: bool
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_grip(profile: AnthropometryProfile) -> AxisResolution:
    """Axis B — Grip width, FIXED (~520mm span). Not adjustable, so a
    mismatch against [BAW, 1.5·BAW] is reported as the frame's limit for
    this body (CLAMPED). The matching technique advice (elbows forward /
    stop short) lives in machines/coaching.py, keyed on this verdict.

    REVISED 2026-09-28: this used to return NO_SOLUTION ("machine doesn't
    fit you") on any mismatch. That's far too strong for a grip that only
    changes how wide the elbows travel, and the scanner's BAW
    (shoulder-landmark to shoulder-landmark, i.e. roughly joint centres)
    reads narrower than true acromion-to-acromion breadth — so the upper
    bound fired on ordinary narrow-shouldered users. The 1.0-1.5 ratio
    itself is still illustrative (constants.md).
    """
    baw = profile.biacromial_width_BAW_mm
    min_grip_mm = GLOBAL.grip_width_ratio_min * baw
    max_grip_mm = GLOBAL.grip_width_ratio_max * baw

    margin_to_min = abs(FIXED_GRIP_SPAN_MM - min_grip_mm)
    margin_to_max = abs(FIXED_GRIP_SPAN_MM - max_grip_mm)
    nearer_ratio = GLOBAL.grip_width_ratio_min if margin_to_min <= margin_to_max else GLOBAL.grip_width_ratio_max
    sigma_grip = propagate_single_segment_sigma(nearer_ratio, scan_error_for(profile).sigma_BAW_mm)
    confidence = classify_confidence(
        confidence_ratio(min(margin_to_min, margin_to_max), sigma_grip), CONFIDENCE_THRESHOLDS
    )

    target_mm = None
    if FIXED_GRIP_SPAN_MM < min_grip_mm:
        state, target_mm = FeasibilityState.CLAMPED_LOW, min_grip_mm
        note = f"fixed {FIXED_GRIP_SPAN_MM:.0f}mm span is narrower than this user's shoulders ({min_grip_mm:.0f}mm)"
    elif FIXED_GRIP_SPAN_MM > max_grip_mm:
        state, target_mm = FeasibilityState.CLAMPED_HIGH, max_grip_mm
        note = f"fixed {FIXED_GRIP_SPAN_MM:.0f}mm span exceeds 1.5x this user's shoulder width ({max_grip_mm:.0f}mm)"
    else:
        state, note = FeasibilityState.IN_RANGE, None

    return AxisResolution(
        axis_name="Grip width (fixed)",
        pin=None,
        achieved_coordinate_mm=FIXED_GRIP_SPAN_MM,
        state=state,
        confidence=confidence,
        note=note,
        target_coordinate_mm=target_mm,
        causing_segment="BAW (biacromial width)",
        purpose=AxisPurpose.GRIP_WIDTH_SHOULDER_ABDUCTION,
    )


def resolve_shoulder_press(
    profile: AnthropometryProfile,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
) -> ShoulderPressResolution:
    """Resolve Shoulder Press seat height + grip-width flag for one user."""
    injuries = injuries or {}
    shoulder_l = injuries.get(InjuryJoint.SHOULDER_L)
    shoulder_r = injuries.get(InjuryJoint.SHOULDER_R)
    lumbar = injuries.get(InjuryJoint.LUMBAR)

    machine_gated = is_tier3(shoulder_l) or is_tier3(shoulder_r)
    warnings: list[str] = []
    if is_tier3(lumbar) and not machine_gated:
        # "Partial gate" (shoulder_press.md) — distinct from the shoulder's
        # unqualified whole-machine gate: flagged, not blocked outright,
        # since no ROM-reduction formula exists to apply here instead.
        warnings.append("Tier-3 lumbar: partial gate — upright spinal compression risk, review before use")

    if machine_gated:
        gated = resolve_with_confidence(
            proposed_state=FeasibilityState.NO_SOLUTION,
            margin_mm=0.0,
            sigma_C_mm=1.0,  # unused: NO_SOLUTION short-circuits before r is computed
            thresholds=CONFIDENCE_THRESHOLDS,
            safe_edge_state=FeasibilityState.CLAMPED_LOW,
        )
        note = "Tier-3 shoulder: overhead loading gated outright — offer substitute"
        seat = AxisResolution(
            SEAT_AXIS.name, None, None, gated.state, gated.confidence, note=note,
            purpose=AxisPurpose.SEAT_HEIGHT_SHOULDER_ALIGNMENT,
        )
        grip = AxisResolution(
            "Grip width (fixed)", None, None, gated.state, gated.confidence, note=note,
            purpose=AxisPurpose.GRIP_WIDTH_SHOULDER_ABDUCTION,
        )
        return ShoulderPressResolution(seat=seat, grip=grip, machine_gated=True, warnings=tuple(warnings))

    seat = resolve_congruence_seat(
        SEAT_AXIS,
        Y_MACHINE_MM,
        K_SH_EFFECTIVE,
        profile.sitting_height_T_mm,
        scan_error_for(profile).sigma_T_mm,
        CONFIDENCE_THRESHOLDS,
        datum_label="bottoms of the handles",
    )
    grip = _resolve_grip(profile)
    return ShoulderPressResolution(seat=seat, grip=grip, machine_gated=False, warnings=tuple(warnings))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    from models import BilateralSegment, InjuryProvenance, InjuryTier

    def _show(label: str, res: ShoulderPressResolution) -> None:
        print(f"{label}: machine_gated={res.machine_gated}")
        for axis in (res.seat, res.grip):
            pin_str = "n/a" if axis.pin is None else str(axis.pin)
            coord_str = "n/a" if axis.achieved_coordinate_mm is None else f"{axis.achieved_coordinate_mm:.1f}mm"
            print(
                f"  {axis.axis_name}: pin={pin_str} achieved={coord_str} "
                f"state={axis.state.value} confidence={axis.confidence.value}"
                + (f" note={axis.note!r}" if axis.note else "")
            )
        for warning in res.warnings:
            print(f"  warning: {warning}")

    # --- Edge case 1: tall basketball-player profile, no injury ---
    basketball_player = AnthropometryProfile(
        user_id="basketball_player",
        captured_at=date(2026, 7, 6),
        height_H_mm=2290,
        sitting_height_T_mm=1250,
        femur=BilateralSegment(left_mm=560, right_mm=558),
        tibia=BilateralSegment(left_mm=520, right_mm=522),
        arm=BilateralSegment(left_mm=750, right_mm=745),
        biacromial_width_BAW_mm=480,
        chest_depth_Cd_mm=290,
    )
    result_1 = resolve_shoulder_press(basketball_player)
    _show("Basketball player (no injury)", result_1)

    assert result_1.machine_gated is False
    assert result_1.seat.state is FeasibilityState.CLAMPED_LOW
    assert result_1.seat.pin == 1  # pin 1 = lowest seat
    # BAW=480mm -> safe grip range [480, 720]mm; the fixed 520mm span sits inside it.
    assert result_1.grip.state is FeasibilityState.IN_RANGE
    assert result_1.grip.note is None

    # --- Edge case 2: petite female profile, Tier-3 left shoulder injury ---
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
    left_shoulder_injury = InjuryConstraint(
        constraint_id="petite-shoulder-L",
        joint=InjuryJoint.SHOULDER_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=15,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    result_2 = resolve_shoulder_press(petite_user, injuries={InjuryJoint.SHOULDER_L: left_shoulder_injury})
    _show("Petite user (Tier-3 left shoulder injury -> whole-machine gate)", result_2)

    assert result_2.machine_gated is True
    assert result_2.seat.state is FeasibilityState.NO_SOLUTION
    assert result_2.seat.pin is None and result_2.seat.achieved_coordinate_mm is None
    assert result_2.grip.state is FeasibilityState.NO_SOLUTION
    assert result_2.seat.confidence is ConfidenceTag.HIGH  # confidence-immune

    # --- Edge case 3: narrow-shouldered user with a Tier-3 lumbar injury ---
    # Narrow BAW against the fixed 520mm span -> handles wide for them (grip CLAMPED_HIGH);
    # lumbar Tier-3 -> partial-gate warning, not a full block.
    narrow_shoulders = AnthropometryProfile(
        user_id="narrow_shoulders",
        captured_at=date(2026, 7, 6),
        height_H_mm=1600,
        sitting_height_T_mm=850,
        femur=BilateralSegment(left_mm=400, right_mm=400),
        tibia=BilateralSegment(left_mm=380, right_mm=380),
        arm=BilateralSegment(left_mm=560, right_mm=560),
        biacromial_width_BAW_mm=320,  # 1.5x = 480mm, fixed 520mm span exceeds it
        chest_depth_Cd_mm=210,
    )
    lumbar_injury = InjuryConstraint(
        constraint_id="narrow-lumbar",
        joint=InjuryJoint.LUMBAR,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.85,
        applied_severity=0.85,
        functional_limit_deg=20,
        provenance=InjuryProvenance.APP_ASSESSED,
        onset_date=date(2026, 4, 1),
        review_date=date(2026, 7, 1),
    )
    result_3 = resolve_shoulder_press(narrow_shoulders, injuries={InjuryJoint.LUMBAR: lumbar_injury})
    _show("Narrow-shouldered user (Tier-3 lumbar -> partial-gate warning)", result_3)

    assert result_3.machine_gated is False
    assert result_3.grip.state is FeasibilityState.CLAMPED_HIGH  # handled by a coaching tip, not "doesn't fit"
    assert len(result_3.warnings) == 1 and "partial gate" in result_3.warnings[0]

    print("\nAll machines/shoulder_press.py smoke tests passed.")
