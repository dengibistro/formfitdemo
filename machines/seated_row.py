"""Matrix Seated Row (Chest-Supported) — concrete machine implementation.

Reads `machines/seated_row.md`. Seat height reuses `machines/common.py`'s
congruence pattern (`Seat = Y_target − k_sh·T`), but unlike Chest Press/
Shoulder Press/Pec Deck, this file never states a numeric `Y_target` — only
the relationship. Rather than inventing one, it's exposed as a required
`SeatedRowFrameConstants.y_target_mm` field, same discipline as
`LatPulldownFrameConstants` (illustrative-but-unfixed numbers must be
supplied consciously, not assumed).

Chest pad depth: field audit (2026-08) found this is FIXED hardware, not
adjustable — the original capping axis (and its two injury modifiers) never
existed in reality. Resolved as a flag-only fixed axis, same pattern as
Chest Press's handle depth / Shoulder Press's grip width.

`resistance_profile: lever` (torque correction applies per `05`) — this
module only constructs the `Machine` Passport entry with that hardcoded
profile; the torque math itself is out of scope, same as every machine
module so far.

Run as `python3 -m machines.seated_row` from the `formfit_spec/` directory.
"""

from dataclasses import dataclass

from machines.common import AxisResolution, resolve_congruence_seat
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
    Machine,
    MachineAxis,
    MachineName,
    ResistanceProfile,
    ScaleDirection,
    ScanErrorConstants,
)

# ---------------------------------------------------------------------------
# Seated Row Passport — constants.md via models.py, plus this machine's own
# fixed-frame numbers (canonical only in machines/seated_row.md)
# ---------------------------------------------------------------------------

GLOBAL = GlobalCoefficients()
SCAN_ERROR = ScanErrorConstants()
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

SEAT_AXIS = MachineAxis(
    name="Seat height",
    axis_type=AxisType.CONGRUENCE,
    total_holes=6,  # field-confirmed 2026-08: 6 holes, not 7
    direction=ScaleDirection.INVERTED,  # n=1 = highest seat, n=6 = lowest
    alpha_deg=90,
    p0_mm=560,
    delta_mm=-30,  # step confirmed on-site
    reach_min_mm=410,
    reach_max_mm=560,
    coupling=CouplingFlag.INDEPENDENT,
)

# Chest pad depth: field audit (2026-08) found the pad is fixed — confirmed
# on-site not to move. What the spec assumed was a 4-position capping axis
# is actually fixed hardware; resolved below as a flag-only fixed axis (same
# pattern as Chest Press's handle depth / Shoulder Press's grip width), not
# a `MachineAxis`. Exact fixed position in mm wasn't recorded during this
# field pass — TODO, next on-site visit.
#
# The old chest-pad capping axis is gone, so its two injury modifiers
# (`SHOULDER_CHEST_PAD_MODIFIER`, `LUMBAR_CHEST_PAD_MODIFIER`) no longer
# have an axis to modify — removed rather than left dangling.

# New reference point, absent from the original spec (field audit 2026-08):
# height of the backrest/chest-pad support base off the floor, confirmed
# real measurement — not yet wired into any resolution formula. The field
# note only says "add as a new constant"; it doesn't define a relationship
# to compute from it, so this is documented, not used, until one exists.
SUPPORT_BASE_HEIGHT_MM = 800.0

SEATED_ROW_MACHINE = Machine(
    name=MachineName.SEATED_ROW,
    machine_class="Chest-supported horizontal row",
    mechanic="Converging",
    plane="Transverse",
    resistance_profile=ResistanceProfile.LEVER,
    axes=[SEAT_AXIS],
    injury_modifiers=[],
)


@dataclass(frozen=True)
class SeatedRowFrameConstants:
    """`Y_target` (`Seat = Y_target − k_sh·T`) is named but never given a
    number in seated_row.md — unlike Chest Press/Shoulder Press/Pec Deck's
    explicit fixed-frame datums. Required, no default — same discipline as
    `LatPulldownFrameConstants`."""

    y_target_mm: float


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeatedRowResolution:
    seat: AxisResolution
    chest_pad: AxisResolution


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_chest_pad() -> AxisResolution:
    """Axis B — FIXED hardware (field audit 2026-08: confirmed on-site,
    doesn't move). Same flag-only pattern as Chest Press's handle depth /
    Shoulder Press's grip width for fixed, non-adjustable equipment:
    `pin=None`.

    Exact fixed position in mm wasn't recorded during this field pass, so
    `achieved_coordinate_mm=None` too — reports the structural fact (fixed,
    not adjustable) with low confidence rather than inventing a number.
    """
    return AxisResolution(
        axis_name="Chest pad depth (fixed)",
        pin=None,
        achieved_coordinate_mm=None,
        state=FeasibilityState.IN_RANGE,
        confidence=ConfidenceTag.LOW,
        note="fixed hardware, exact depth not yet measured on-site — feasibility check pending",
        purpose=AxisPurpose.FULL_EXTENSION_STRETCH_CAP,
    )


def resolve_seated_row(
    profile: AnthropometryProfile,
    frame: SeatedRowFrameConstants,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
) -> SeatedRowResolution:
    """Resolve Seated Row seat height + chest pad depth for one user.

    `injuries` is accepted (not dropped) for interface stability with the
    other `resolve_*` functions and `api.py`'s dispatch table, but is
    currently unused — both injury modifiers that used to apply here
    targeted the chest-pad capping axis, which no longer exists now that
    the pad is confirmed fixed hardware.
    """
    seat = resolve_congruence_seat(
        SEAT_AXIS, frame.y_target_mm, GLOBAL.k_sh, profile.sitting_height_T_mm, SCAN_ERROR.sigma_T_mm, CONFIDENCE_THRESHOLDS
    )
    chest_pad = _resolve_chest_pad()
    return SeatedRowResolution(seat=seat, chest_pad=chest_pad)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    from models import BilateralSegment

    assert SEATED_ROW_MACHINE.resistance_profile is ResistanceProfile.LEVER

    # Illustrative fixed-frame datum (not given by seated_row.md — see
    # SeatedRowFrameConstants docstring), chosen in the same 1150-1200mm
    # neighborhood as its sibling machines' explicit datums.
    FRAME = SeatedRowFrameConstants(y_target_mm=1180.0)

    def _show(label: str, res: SeatedRowResolution) -> None:
        print(f"{label}:")
        for axis in (res.seat, res.chest_pad):
            achieved_str = "n/a" if axis.achieved_coordinate_mm is None else f"{axis.achieved_coordinate_mm:.1f}mm"
            pin_str = "n/a" if axis.pin is None else str(axis.pin)
            print(
                f"  {axis.axis_name}: pin={pin_str} achieved={achieved_str} "
                f"state={axis.state.value} confidence={axis.confidence.value}"
                + (f" note={axis.note!r}" if axis.note else "")
            )

    # --- Edge case 1: tall basketball-player profile ---
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
    result_1 = resolve_seated_row(basketball_player, FRAME)
    _show("Basketball player", result_1)

    assert result_1.seat.state is FeasibilityState.CLAMPED_LOW
    assert result_1.seat.pin == 6  # Inverted axis: n=6 is the LOWEST physical seat coordinate (6 holes now)
    assert result_1.chest_pad.pin is None
    assert result_1.chest_pad.achieved_coordinate_mm is None
    assert result_1.chest_pad.confidence is ConfidenceTag.LOW

    # --- Edge case 2: petite user ---
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
    result_2 = resolve_seated_row(petite_user, FRAME)
    _show("Petite user", result_2)

    assert result_2.seat.state is FeasibilityState.CLAMPED_HIGH
    assert result_2.seat.pin == 1  # Inverted axis: n=1 is the HIGHEST physical seat coordinate
    assert result_2.chest_pad.note is not None and "not yet measured" in result_2.chest_pad.note

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
    result_3 = resolve_seated_row(mid_user, FRAME)
    _show("Mid-range user", result_3)

    # target = 1180 - 0.63*900 = 613mm, above reach_max (560) -> CLAMPED_HIGH
    assert result_3.seat.state is FeasibilityState.CLAMPED_HIGH
    assert result_3.chest_pad.state is FeasibilityState.IN_RANGE  # fixed hardware always reports IN_RANGE for now

    print("\nAll machines/seated_row.py smoke tests passed.")
