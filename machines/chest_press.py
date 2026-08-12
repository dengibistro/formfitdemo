"""Matrix Chest Press — concrete machine implementation.

Reads `machines/chest_press.md`. Composes the generic engines from
`biomechanics.py` (vector/coordinate math, hole grounding) and `safety.py`
(injury filters, confidence degradation) with this machine's two Passport
axes and its own fixed-frame numbers. The Coupling Index (`04`) does not
apply — chest press is not a closed-chain leg machine — and the Resistive
Moment Model needs no correction — `resistance_profile: cam`.

Run as `python3 -m machines.chest_press` from the `formfit_spec/` directory.
"""

import math
from dataclasses import dataclass

from machines.common import AxisResolution, resolve_congruence_seat
from models import (
    AnthropometryProfile,
    AxisPurpose,
    AxisType,
    BilateralSegment,
    ConfidenceTag,
    ConfidenceThresholds,
    CouplingFlag,
    FeasibilityState,
    GlobalCoefficients,
    InjuryConstraint,
    InjuryJoint,
    MachineAxis,
    ScaleDirection,
    ScanErrorConstants,
)

# ---------------------------------------------------------------------------
# Chest Press Passport — constants.md via models.py, plus this machine's own
# fixed-frame numbers (canonical only in machines/chest_press.md, per README.md:
# machine files are not restated in constants.md to avoid two sources of truth)
# ---------------------------------------------------------------------------

GLOBAL = GlobalCoefficients()      # k_sh = 0.63, β_default = 5°, ...
SCAN_ERROR = ScanErrorConstants()  # σ_T, σ_A, σ_Cd, ...
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

Y_MACHINE_MM = 1020.0          # fixed handle-line datum, from floor (field-measured 2026-08, was 1200)
THETA_CAP_HEALTHY_DEG = 25.0   # healthy-baseline shoulder horizontal extension cap

SEAT_AXIS = MachineAxis(
    name="Seat height",
    axis_type=AxisType.CONGRUENCE,
    total_holes=6,  # field-confirmed 2026-08: 6 holes, not 7
    direction=ScaleDirection.INVERTED,  # n=1 = highest seat / most restricted reach, n=6 = lowest
    alpha_deg=90,
    p0_mm=510,
    delta_mm=-30,  # step confirmed on-site
    reach_min_mm=360,
    reach_max_mm=510,
    coupling=CouplingFlag.INDEPENDENT,
)

# Handle start depth: field audit (2026-08) found the handles don't move at
# all — no holes/latches on the hardware for repositioning. What the spec
# assumed was a 4-position capping axis is actually fixed hardware; resolved
# below as a flag-only fixed axis (same pattern as Shoulder Press's
# `_resolve_grip`), not a `MachineAxis`. Exact fixed depth in mm wasn't
# recorded during this field pass — TODO, next on-site visit.
#
# The old handle-depth capping axis is gone, so the injury modifier that
# shifted its cap (`SHOULDER_HANDLE_DEPTH_MODIFIER`) no longer has an axis to
# modify — removed rather than left dangling.
#
# Backrest angle: the field audit also found the backrest is actually
# adjustable (this spec previously assumed a fixed 80°) — but unlike handle
# depth, this isn't a simple "measure the missing number" gap. Per Matrix's
# own literature the backrest changes chest-to-handle distance/start-point/
# ROM/stretch, not a lockable degree angle — the adjustment mechanism itself
# isn't understood well enough to model as an axis yet. Deliberately NOT
# implemented this round (no MachineAxis, no resolution logic) — flagging
# here so it isn't silently forgotten, not modeling it with invented numbers.


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChestPressResolution:
    seat: AxisResolution
    handle_depth: AxisResolution


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_handle_depth() -> AxisResolution:
    """Axis B — FIXED hardware (field audit 2026-08: no holes/latches found,
    handles don't move). Same flag-only pattern as Shoulder Press's
    `_resolve_grip` (`shoulder_press.py`) for fixed, non-adjustable
    equipment: `pin=None`.

    Unlike grip width, there's no numeric feasibility check to run here yet
    — the exact fixed depth in mm wasn't recorded during this field pass, so
    `achieved_coordinate_mm=None` too. Once measured, this can grow the same
    kind of BAW/reach-ratio feasibility check `_resolve_grip` has; until
    then this just reports the structural fact (fixed, not adjustable) with
    low confidence rather than inventing a number.
    """
    return AxisResolution(
        axis_name="Handle start depth (fixed)",
        pin=None,
        achieved_coordinate_mm=None,
        state=FeasibilityState.IN_RANGE,
        confidence=ConfidenceTag.LOW,
        note="fixed hardware, exact depth not yet measured on-site — feasibility check pending",
        purpose=AxisPurpose.SHOULDER_HORIZONTAL_EXTENSION_CAP,
    )


def resolve_chest_press(
    profile: AnthropometryProfile,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
) -> ChestPressResolution:
    """Resolve Chest Press seat height + handle start depth for one user.

    `injuries` is accepted (not dropped) for interface stability with the
    other `resolve_*` functions and `api.py`'s dispatch table, but is
    currently unused — the shoulder-injury modifier that used to shift the
    handle-depth cap no longer applies now that the axis is fixed hardware,
    and the seat axis never had an injury modifier of its own.
    """
    seat = resolve_congruence_seat(
        SEAT_AXIS, Y_MACHINE_MM, GLOBAL.k_sh, profile.sitting_height_T_mm, SCAN_ERROR.sigma_T_mm, CONFIDENCE_THRESHOLDS
    )
    handle_depth = _resolve_handle_depth()
    return ChestPressResolution(seat=seat, handle_depth=handle_depth)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    def _show(label: str, res: ChestPressResolution) -> None:
        print(f"{label}:")
        for axis in (res.seat, res.handle_depth):
            achieved_str = "n/a" if axis.achieved_coordinate_mm is None else f"{axis.achieved_coordinate_mm:.1f}mm"
            pin_str = "n/a" if axis.pin is None else str(axis.pin)
            print(
                f"  {axis.axis_name}: pin={pin_str} achieved={achieved_str} "
                f"state={axis.state.value} confidence={axis.confidence.value}"
                + (f" dominant={axis.dominant_segment}" if axis.dominant_segment else "")
                + (f" note={axis.note!r}" if axis.note else "")
            )

    # --- Edge case 1: tall basketball-player profile ---
    # Extreme-outlier sitting height, deliberately chosen to exercise the
    # seat axis's low-reach clamp. Handle depth is now fixed hardware, so it
    # has no reach clamp of its own to exercise here — it just always
    # reports the same fixed-hardware shape.
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
    result_1 = resolve_chest_press(basketball_player)
    _show("Basketball player", result_1)

    assert result_1.seat.state is FeasibilityState.CLAMPED_LOW
    assert result_1.seat.pin == 6  # Inverted axis: n=6 is the LOWEST physical seat coordinate (6 holes now)
    assert math.isclose(result_1.seat.achieved_coordinate_mm, SEAT_AXIS.reach_min_mm)
    assert result_1.handle_depth.pin is None
    assert result_1.handle_depth.achieved_coordinate_mm is None
    assert result_1.handle_depth.confidence is ConfidenceTag.LOW

    # --- Edge case 2: petite female profile ---
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
    result_2 = resolve_chest_press(petite_user)
    _show("Petite user", result_2)

    assert result_2.seat.state is FeasibilityState.CLAMPED_HIGH
    assert result_2.seat.pin == 1  # Inverted axis: n=1 is the HIGHEST physical seat coordinate
    assert math.isclose(result_2.seat.achieved_coordinate_mm, SEAT_AXIS.reach_max_mm)
    # Frame simply can't go high enough for such a short torso -> safe, valid CLAMPED_HIGH, not a crash.
    assert result_2.handle_depth.pin is None

    # --- Edge case 3: mid-range profile -> seat should land IN_RANGE ---
    mid_user = AnthropometryProfile(
        user_id="mid_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=1750,
        sitting_height_T_mm=900,
        femur=BilateralSegment(left_mm=440, right_mm=440),
        tibia=BilateralSegment(left_mm=410, right_mm=410),
        arm=BilateralSegment(left_mm=600, right_mm=600),
        biacromial_width_BAW_mm=400,
        chest_depth_Cd_mm=230,
    )
    result_3 = resolve_chest_press(mid_user)
    _show("Mid-range user", result_3)

    # target = 1020 - 0.63*900 = 453mm, comfortably inside [360, 510]
    assert result_3.seat.state is FeasibilityState.IN_RANGE
    assert result_3.handle_depth.state is FeasibilityState.IN_RANGE  # fixed hardware always reports IN_RANGE for now
    assert result_3.handle_depth.note is not None and "not yet measured" in result_3.handle_depth.note

    print("\nAll machines/chest_press.py smoke tests passed.")
