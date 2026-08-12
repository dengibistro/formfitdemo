"""Matrix Pec Deck / Fly — concrete machine implementation.

Reads `machines/pec_deck.md`. Seat height reuses `machines/common.py`'s
congruence pattern unchanged — the doc calls this the "strictest congruence
case on the line," but that's already exactly what the shared helper does
(nearest-node, no threshold relaxation exists anywhere in this codebase to
accidentally loosen); nothing extra needs to be coded for that emphasis.

Arm open offset (capping): field audit (2026-08) found the machine's 8
holes split into two mechanically separate groups — "Chest Fly" and "Pec
Dec / Rear Delt" — not one continuous 5-position range. See
`CHEST_FLY_ARM_OPEN_AXIS`/`REAR_DELT_ARM_OPEN_AXIS` below for the split, and
`_resolve_chest_fly_arm_open` for why the old arm-length/mm conversion is
gone now that real hole positions are degrees directly.

`resistance_profile: lever` (torque correction applies per `05`) — this
module only constructs the `Machine` Passport entry with that hardcoded
profile; the torque-report/ceiling math itself is out of scope, same as
every machine module so far.

Run as `python3 -m machines.pec_deck` from the `formfit_spec/` directory.
"""

from dataclasses import dataclass
from typing import Literal

from biomechanics import ground_toward_safe_edge, margin_to_reach_boundary, node_position
from machines.common import AxisResolution, is_tier3, resolve_congruence_seat
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
    InjuryModifier,
    InjuryZone,
    Machine,
    MachineAxis,
    MachineName,
    ResistanceProfile,
    ScaleDirection,
    ScanErrorConstants,
)
from safety import apply_injury_filters, resolve_with_confidence

# ---------------------------------------------------------------------------
# Pec Deck Passport — constants.md via models.py, plus this machine's own
# fixed-frame numbers (canonical only in machines/pec_deck.md)
# ---------------------------------------------------------------------------

GLOBAL = GlobalCoefficients()
SCAN_ERROR = ScanErrorConstants()
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

Y_PIVOT_MM = 1050.0          # fixed pivot height, from floor — not re-measured in the 2026-08 field audit
THETA_CAP_HEALTHY_DEG = 25.0  # healthy-baseline pre-stretch cap

SEAT_AXIS = MachineAxis(
    name="Seat height",
    axis_type=AxisType.CONGRUENCE,
    total_holes=7,  # field-confirmed 2026-08: 7 holes, matches spec — range only was off
    direction=ScaleDirection.INVERTED,  # n=1 = highest seat, n=7 = lowest
    alpha_deg=90,
    p0_mm=570,
    delta_mm=-30,
    reach_min_mm=390,
    reach_max_mm=570,
    coupling=CouplingFlag.INDEPENDENT,
)

# Arm open offset: field audit (2026-08) found this was never one continuous
# 5-position range at all — the machine physically has 8 holes, in two
# mechanically separate groups labeled on the frame itself: "Chest Fly"
# (1-4) and "Pec Dec / Rear Delt" (5-8). These are two different exercises
# with different ROM, not one axis. Split below into two MachineAxis
# instances of 4 holes each.
#
# Real per-hole angle values aren't measured yet — these are the user's own
# illustrative estimate (Matrix's typical ~15° hole spacing), explicitly
# flagged as pending real measurement, not a confirmed number:
#   Chest Fly (1-4):        ~30° / 45° / 60° / 75°
#   Pec Dec / Rear Delt (5-8): ~90° / 105° / 120° / 135° (last hole uncertain, 125-130° alt)
#
# Now that real per-hole values are DEGREES directly (not an mm proxy), the
# old `_open_offset_mm = R(θ_e)·sin(θ_cap)` mm-conversion is no longer
# needed — grounding happens directly in degree-space, reusing the
# `p0_mm`/`delta_mm`/`reach_*_mm` fields to hold degrees (this file already
# treated `alpha_deg=0.0` as "not a translating rail, placeholder only" for
# the old axis, so reusing the mm-named fields for a rotary/degree axis has
# precedent here). This is a simplification of the resolution math, not new
# physics — the mm conversion only ever existed to translate an assumed-
# linear rail into an angle that we now have directly.
CHEST_FLY_ARM_OPEN_AXIS = MachineAxis(
    name="Chest Fly arm open (degrees)",
    axis_type=AxisType.CAPPING,
    total_holes=4,
    direction=ScaleDirection.DIRECT,  # n=1 = least open (30°), n=4 = most open (75°)
    alpha_deg=0.0,  # N/A (angular start-stop on rotary arm) — placeholder, not a translating rail
    p0_mm=30,
    delta_mm=15,
    reach_min_mm=30,
    reach_max_mm=75,
    safe_direction="less open",
    beta_deg=5,
)

REAR_DELT_ARM_OPEN_AXIS = MachineAxis(
    name="Rear Delt / Pec Dec arm open (degrees)",
    axis_type=AxisType.CAPPING,
    total_holes=4,
    direction=ScaleDirection.DIRECT,  # n=1 = least open (90°), n=4 = most open (135°)
    alpha_deg=0.0,
    p0_mm=90,
    delta_mm=15,
    reach_min_mm=90,
    reach_max_mm=135,
    safe_direction="less open",
    beta_deg=5,
)

SHOULDER_ARM_OPEN_MODIFIER = InjuryModifier(
    zone=InjuryZone.SHOULDER,
    machine=MachineName.PEC_DECK,
    axis="Chest Fly arm open (degrees)",
    instrument="m_β · Δθ_cap · gate",
    m_beta=0.30,
    delta_theta_cap_from_deg=25,
    delta_theta_cap_to_deg=10,
    gate_severity_threshold=0.85,
)

PEC_DECK_MACHINE = Machine(
    name=MachineName.PEC_DECK,
    machine_class="Seated fly",
    mechanic="Rotary, single fixed pivot",
    plane="Transverse",
    resistance_profile=ResistanceProfile.LEVER,
    axes=[SEAT_AXIS, CHEST_FLY_ARM_OPEN_AXIS, REAR_DELT_ARM_OPEN_AXIS],
    injury_modifiers=[SHOULDER_ARM_OPEN_MODIFIER],
)


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PecDeckResolution:
    seat: AxisResolution
    arm_open: AxisResolution


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_chest_fly_arm_open(
    shoulder_left: InjuryConstraint | None,
    shoulder_right: InjuryConstraint | None,
) -> AxisResolution:
    """Chest Fly sub-axis — grounds the injury-shiftable pre-stretch cap
    (θ_cap, healthy baseline 25°) directly onto `CHEST_FLY_ARM_OPEN_AXIS`'s
    real degree positions.

    No arm-length conversion anymore: the old `R(θ_e)·sin(θ_cap)` mm-
    projection existed only to translate an assumed-linear rail into an
    angle. Now that the field audit found the machine's positions ARE
    angles directly, the target simply *is* θ_cap, grounded straight to the
    nearest safe hole — arm length has no role in this axis's resolution
    anymore (a real simplification following from the corrected geometry,
    not a dropped input).
    """
    theta_cap_left = THETA_CAP_HEALTHY_DEG
    theta_cap_right = THETA_CAP_HEALTHY_DEG
    gate_fired = False

    # Note: no geometric machine-gate check here (unlike Chest Press) — at
    # the safest position (least open, reach_min) the angle is always at
    # its lowest value, trivially inside any positive cap, so only the
    # severity-threshold gate (s>=0.85) can ever fire for this axis.
    if is_tier3(shoulder_left):
        filt = apply_injury_filters(SHOULDER_ARM_OPEN_MODIFIER, shoulder_left, GLOBAL.beta_default_deg)
        theta_cap_left = filt.shifted_cap_deg
        gate_fired = gate_fired or filt.gate_fired

    if is_tier3(shoulder_right):
        filt = apply_injury_filters(SHOULDER_ARM_OPEN_MODIFIER, shoulder_right, GLOBAL.beta_default_deg)
        theta_cap_right = filt.shifted_cap_deg
        gate_fired = gate_fired or filt.gate_fired

    if gate_fired:
        gated = resolve_with_confidence(
            proposed_state=FeasibilityState.NO_SOLUTION,
            margin_mm=0.0,
            sigma_C_mm=1.0,  # unused: NO_SOLUTION short-circuits before r is computed
            thresholds=CONFIDENCE_THRESHOLDS,
            safe_edge_state=FeasibilityState.CLAMPED_LOW,
        )
        return AxisResolution(
            axis_name=CHEST_FLY_ARM_OPEN_AXIS.name,
            pin=1,
            achieved_coordinate_mm=CHEST_FLY_ARM_OPEN_AXIS.reach_min_mm,
            state=gated.state,
            confidence=gated.confidence,
            note="severity gate (s>=0.85) fired — offer substitute",
            purpose=AxisPurpose.SHOULDER_PRE_STRETCH_CAP,
        )

    target_theta_cap_deg = min(theta_cap_left, theta_cap_right)  # tighter/less-open side governs

    grounded = ground_toward_safe_edge(CHEST_FLY_ARM_OPEN_AXIS, target_theta_cap_deg, safe_direction="lower")
    margin = margin_to_reach_boundary(CHEST_FLY_ARM_OPEN_AXIS, target_theta_cap_deg)

    # θ_cap is a policy constant (healthy baseline or injury-shifted), not
    # derived from a noisy anthropometric scan — there's no propagated scan
    # uncertainty to compute anymore now that arm length dropped out of this
    # axis's target. A small nominal sigma keeps `classify_confidence` from
    # dividing by zero while still reporting HIGH confidence except exactly
    # at a hole boundary, which is the honest behavior here.
    resolution = resolve_with_confidence(
        proposed_state=grounded.state,
        margin_mm=margin,
        sigma_C_mm=0.5,
        thresholds=CONFIDENCE_THRESHOLDS,
        safe_edge_state=FeasibilityState.CLAMPED_LOW,
    )
    if resolution.degraded_to_safe_edge:
        grounded = ground_toward_safe_edge(
            CHEST_FLY_ARM_OPEN_AXIS, CHEST_FLY_ARM_OPEN_AXIS.reach_min_mm, safe_direction="lower"
        )

    return AxisResolution(
        axis_name=CHEST_FLY_ARM_OPEN_AXIS.name,
        pin=grounded.index,
        achieved_coordinate_mm=grounded.achieved_coordinate_mm,
        state=resolution.state,
        confidence=resolution.confidence,
        target_coordinate_mm=target_theta_cap_deg,
        causing_segment="injury-shifted safety cap (no anthropometric input)",
        purpose=AxisPurpose.SHOULDER_PRE_STRETCH_CAP,
    )


def _resolve_rear_delt_arm_open() -> AxisResolution:
    """Rear Delt / Pec Dec sub-axis — deliberately NOT wired to a real
    formula this round. Field audit (2026-08) confirmed this is a
    mechanically separate hole group from Chest Fly, and very likely a
    biomechanically different exercise (posterior deltoid, arms move
    backward — not the same forward pre-stretch geometry Chest Fly's
    Cd/arm-reach formula assumes). Reusing Chest Fly's cap logic here would
    be inventing a relationship, not applying one that's established.

    Structurally present (the real 90-135° hole positions exist and are
    documented) but always grounds to a fixed middle hole with a clearly
    flagged note, until someone actually derives Rear Delt's own
    biomechanics.
    """
    mid_index = 2  # arbitrary fixed middle-ish hole — not derived from anything, placeholder only
    achieved = node_position(REAR_DELT_ARM_OPEN_AXIS, mid_index)
    return AxisResolution(
        axis_name=REAR_DELT_ARM_OPEN_AXIS.name,
        pin=mid_index,
        achieved_coordinate_mm=achieved,
        state=FeasibilityState.IN_RANGE,
        confidence=ConfidenceTag.LOW,
        note="Rear Delt mode not yet biomechanically modeled — different exercise/plane than Chest Fly, needs its own formula",
        purpose=AxisPurpose.REAR_DELT_PRE_STRETCH_CAP,
    )


def resolve_pec_deck(
    profile: AnthropometryProfile,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
    exercise_mode: Literal["chest_fly", "rear_delt"] = "chest_fly",
) -> PecDeckResolution:
    """Resolve Pec Deck seat height + arm open offset for one user.

    `exercise_mode` picks which of the machine's two mechanically separate
    hole groups to resolve (field audit 2026-08: "Chest Fly" holes 1-4 vs.
    "Pec Dec / Rear Delt" holes 5-8 are physically different ranges, not one
    continuous axis — see `CHEST_FLY_ARM_OPEN_AXIS`/`REAR_DELT_ARM_OPEN_AXIS`
    above). Defaults to "chest_fly", the mode the existing injury-cap
    formula actually applies to.
    """
    injuries = injuries or {}
    seat = resolve_congruence_seat(
        SEAT_AXIS, Y_PIVOT_MM, GLOBAL.k_sh, profile.sitting_height_T_mm, SCAN_ERROR.sigma_T_mm, CONFIDENCE_THRESHOLDS
    )
    if exercise_mode == "chest_fly":
        arm_open = _resolve_chest_fly_arm_open(
            shoulder_left=injuries.get(InjuryJoint.SHOULDER_L),
            shoulder_right=injuries.get(InjuryJoint.SHOULDER_R),
        )
    else:
        arm_open = _resolve_rear_delt_arm_open()
    return PecDeckResolution(seat=seat, arm_open=arm_open)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import math
    from datetime import date

    from models import BilateralSegment, InjuryProvenance, InjuryTier

    assert PEC_DECK_MACHINE.resistance_profile is ResistanceProfile.LEVER

    def _show(label: str, res: PecDeckResolution) -> None:
        print(f"{label}:")
        for axis in (res.seat, res.arm_open):
            print(
                f"  {axis.axis_name}: pin={axis.pin} achieved={axis.achieved_coordinate_mm:.1f}mm "
                f"state={axis.state.value} confidence={axis.confidence.value}"
                + (f" note={axis.note!r}" if axis.note else "")
            )

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
    result_1 = resolve_pec_deck(basketball_player)
    _show("Basketball player (chest_fly, no injury)", result_1)

    assert result_1.seat.state is FeasibilityState.CLAMPED_LOW
    assert result_1.seat.pin == 7  # Inverted axis: n=7 is the LOWEST physical seat coordinate
    # Real finding from this rewrite (2026-08): the healthy-baseline safety
    # cap (25°) sits BELOW the real machine's least-open Chest Fly position
    # (30°) — so absent an injury shift (which only ever narrows the cap
    # further), every user grounds to the same hole regardless of arm
    # length, since arm length no longer feeds this axis's target at all.
    # Flagging this tension explicitly rather than papering over it: the
    # 25° policy constant may need revisiting once real Chest Fly angles are
    # measured, since it's currently unreachable given the hardware's range.
    assert result_1.arm_open.state is FeasibilityState.CLAMPED_LOW
    assert result_1.arm_open.pin == 1
    assert math.isclose(result_1.arm_open.achieved_coordinate_mm, CHEST_FLY_ARM_OPEN_AXIS.reach_min_mm)

    # --- Edge case: Tier-3 shoulder injury at the severity gate -> NO_SOLUTION ---
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
    gated_injury = InjuryConstraint(
        constraint_id="petite-shoulder-L-gate",
        joint=InjuryJoint.SHOULDER_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,  # >= 0.85 gate threshold
        functional_limit_deg=10,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    result_2 = resolve_pec_deck(petite_user, injuries={InjuryJoint.SHOULDER_L: gated_injury})
    _show("Petite user (chest_fly, Tier-3 shoulder, severity 0.90 >= gate)", result_2)

    assert result_2.arm_open.state is FeasibilityState.NO_SOLUTION
    assert result_2.arm_open.confidence is ConfidenceTag.HIGH  # confidence-immune

    # --- Edge case: Tier-3 below the severity gate -> cap shifts to 10°, still below reach_min ---
    below_gate_injury = gated_injury.model_copy(update={"constraint_id": "below-gate", "applied_severity": 0.75})
    result_3 = resolve_pec_deck(petite_user, injuries={InjuryJoint.SHOULDER_L: below_gate_injury})
    _show("Petite user (chest_fly, Tier-3 shoulder, severity 0.75 < gate)", result_3)

    assert result_3.arm_open.state is FeasibilityState.CLAMPED_LOW
    assert result_3.arm_open.pin == 1

    # --- exercise_mode="rear_delt": structurally present, deliberately unmodeled ---
    result_4 = resolve_pec_deck(basketball_player, exercise_mode="rear_delt")
    _show("Basketball player (rear_delt)", result_4)

    assert result_4.arm_open.pin == 2
    assert result_4.arm_open.confidence is ConfidenceTag.LOW
    assert result_4.arm_open.note is not None and "not yet biomechanically modeled" in result_4.arm_open.note

    print("\nAll machines/pec_deck.py smoke tests passed.")
