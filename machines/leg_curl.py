"""Matrix Seated Leg Curl — concrete machine implementation.

Reads `machines/leg_curl.md`. Seat depth reuses `machines/common.py`'s
`resolve_seat_depth_from_femur` unchanged — the doc states this axis is an
"identical relation to Leg Extension", so it's the same shared helper
`leg_extension.py` uses, not a re-derivation.

Thigh fixator (Axis B) is the one axis in this whole codebase with no
anthropometry-driven formula at all — only Passport data and "tighter clamp"
as the safe direction. Its job is to lock the femur as tightly as the
mechanism allows regardless of body size, so it always resolves to the
tightest available setting; there's no computed target to degrade under low
confidence, and no per-user injury modifier targets it directly either.

Ankle pad / lever length (Axis C) mirrors Leg Extension's shin pad pattern,
but leg_curl.md names its offset with a distinct symbol (δ_Ti') and never
gives it a number — unlike Leg Extension's explicit δ_Ti ≈ 20mm. Exposed as
a required `LegCurlFrameConstants.ankle_pad_offset_mm`, same discipline as
`LatPulldownFrameConstants`/`SeatedRowFrameConstants`.

`resistance_profile: cam` for the cam itself (constants.md) — this module
constructs the `Machine` Passport entry with that hardcoded profile; the
ankle-pad lever effect is reported, the cam-normalised torque math itself is
out of scope, same as every machine module so far.

Run as `python3 -m machines.leg_curl` from the `formfit_spec/` directory.
"""

from dataclasses import dataclass, replace

from biomechanics import ground_toward_safe_edge
from machines.common import (
    LEG_MACHINE_SEAT_DEPTH_AXIS,
    AxisResolution,
    bilateral_values,
    is_tier3,
    resolve_bilateral_congruence_axis,
    resolve_seat_depth_from_femur,
)
from models import (
    AnthropometryProfile,
    AxisPurpose,
    AxisType,
    ConfidenceTag,
    ConfidenceThresholds,
    CouplingFlag,
    FeasibilityState,
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

# ---------------------------------------------------------------------------
# Leg Curl Passport — constants.md via models.py, plus this machine's own
# fixed-frame numbers (canonical only in machines/leg_curl.md)
# ---------------------------------------------------------------------------

SCAN_ERROR = ScanErrorConstants()
CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

CAM_PIVOT_HEIGHT_MM = 430.0  # fixed, from floor — same congruence alignment target as Leg Extension

THIGH_FIXATOR_AXIS = MachineAxis(
    name="Thigh fixator / top clamp",
    axis_type=AxisType.CAPPING,
    total_holes=5,
    direction=ScaleDirection.INVERTED,  # n=1 = loosest/highest, n=5 = tightest/lowest
    alpha_deg=0,
    p0_mm=240,
    delta_mm=-30,
    reach_min_mm=120,
    reach_max_mm=240,
    safe_direction="tighter clamp",
)

ANKLE_PAD_AXIS = MachineAxis(
    name="Ankle pad / lever length",
    axis_type=AxisType.CONGRUENCE,
    total_holes=5,
    direction=ScaleDirection.DIRECT,
    alpha_deg=0,  # not stated in leg_curl.md; not used elsewhere in this module
    p0_mm=330,
    delta_mm=30,
    reach_min_mm=330,
    reach_max_mm=450,
    coupling=CouplingFlag.INDEPENDENT,
)

KNEE_CURL_DEPTH_MODIFIER = InjuryModifier(
    zone=InjuryZone.KNEE,
    machine=MachineName.SEATED_LEG_CURL,
    axis="Curl-depth window",
    instrument="m_β",
    m_beta=0.80,
    note="light restriction — mainly post-hamstring-graft caution",
)

LEG_CURL_MACHINE = Machine(
    name=MachineName.SEATED_LEG_CURL,
    machine_class="Seated knee flexion",
    mechanic="Rotary (cam)",
    plane="Sagittal",
    resistance_profile=ResistanceProfile.CAM,
    axes=[LEG_MACHINE_SEAT_DEPTH_AXIS, THIGH_FIXATOR_AXIS, ANKLE_PAD_AXIS],
    injury_modifiers=[KNEE_CURL_DEPTH_MODIFIER],
)


@dataclass(frozen=True)
class LegCurlFrameConstants:
    """δ_Ti' (`L_pad = Ti − δ_Ti'`) is named with a distinct symbol from Leg
    Extension's δ_Ti but never given its own numeric value in leg_curl.md.
    Required, no default — same discipline as `LatPulldownFrameConstants`."""

    ankle_pad_offset_mm: float


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegCurlResolution:
    seat_depth: AxisResolution
    thigh_fixator: AxisResolution
    ankle_pad: AxisResolution


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_thigh_fixator() -> AxisResolution:
    """Axis B — no anthropometry-driven target is given (only Passport data
    plus "tighter clamp" as the safe direction): the fixator's job is to
    lock the femur as tightly as the mechanism safely allows, independent of
    body size, so it always resolves to the tightest available setting.
    leg_curl.md's bilateral note ("tighter side governs for both legs") is
    trivially satisfied — there's only one answer regardless of L/R, since
    no per-side computation feeds this axis at all.
    """
    grounded = ground_toward_safe_edge(THIGH_FIXATOR_AXIS, THIGH_FIXATOR_AXIS.reach_min_mm, safe_direction="lower")
    return AxisResolution(
        axis_name=THIGH_FIXATOR_AXIS.name,
        pin=grounded.index,
        achieved_coordinate_mm=grounded.achieved_coordinate_mm,
        state=FeasibilityState.IN_RANGE,
        confidence=ConfidenceTag.HIGH,
        note="no per-user formula given in leg_curl.md; always tightened fully (tighter clamp is the safe default)",
        purpose=AxisPurpose.THIGH_FIXATOR_LOCK,
    )


def _resolve_ankle_pad(
    profile: AnthropometryProfile,
    frame: LegCurlFrameConstants,
    knee_left: InjuryConstraint | None,
    knee_right: InjuryConstraint | None,
) -> AxisResolution:
    """Axis C — L_pad = Ti − δ_Ti', bilateral congruence average across both legs."""
    tibia_left, tibia_right, single_sided = bilateral_values(profile.tibia)
    extra_note = (
        "tibia length captured single-sided; both legs resolved from the one available reading"
        if single_sided
        else None
    )
    resolution = resolve_bilateral_congruence_axis(
        ANKLE_PAD_AXIS,
        tibia_left,
        tibia_right,
        frame.ankle_pad_offset_mm,
        SCAN_ERROR.sigma_Ti_mm,
        CONFIDENCE_THRESHOLDS,
        "Ti (tibia)",
        extra_note=extra_note,
        purpose=AxisPurpose.SHIN_ANKLE_PAD_LEVER_ALIGNMENT,
    )

    notes = [resolution.note] if resolution.note else []
    notes.append(
        f"L_pad = {resolution.achieved_coordinate_mm:.1f}mm also doubles as the resistive-moment lever "
        "length (05_resistive_moment.md) — reported here, not converted to a torque figure (out of scope)"
    )
    if is_tier3(knee_left) or is_tier3(knee_right):
        notes.append(
            f"Tier-3 knee: curl-depth window narrowed via m_β={KNEE_CURL_DEPTH_MODIFIER.m_beta} "
            "(light restriction, post-hamstring-graft caution — no ROM figure given to apply beyond this note)"
        )

    return replace(resolution, note="; ".join(notes))


def resolve_leg_curl(
    profile: AnthropometryProfile,
    frame: LegCurlFrameConstants,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
) -> LegCurlResolution:
    """Resolve Seated Leg Curl seat depth + thigh fixator + ankle pad for one user."""
    injuries = injuries or {}
    seat_depth = resolve_seat_depth_from_femur(profile.femur, SCAN_ERROR.sigma_F_mm, CONFIDENCE_THRESHOLDS)
    thigh_fixator = _resolve_thigh_fixator()
    ankle_pad = _resolve_ankle_pad(
        profile,
        frame,
        knee_left=injuries.get(InjuryJoint.KNEE_L),
        knee_right=injuries.get(InjuryJoint.KNEE_R),
    )
    return LegCurlResolution(seat_depth=seat_depth, thigh_fixator=thigh_fixator, ankle_pad=ankle_pad)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import math
    from datetime import date

    from models import BilateralSegment, InjuryProvenance, InjuryTier

    assert LEG_CURL_MACHINE.resistance_profile is ResistanceProfile.CAM

    # Illustrative offset (not given by leg_curl.md — see LegCurlFrameConstants
    # docstring): chosen equal to Leg Extension's δ_Ti as the closest
    # documented analog (same "pad clearance above the ankle/heel" concept),
    # not because the spec says the two values are equal.
    FRAME = LegCurlFrameConstants(ankle_pad_offset_mm=20.0)

    def _show(label: str, res: LegCurlResolution) -> None:
        print(f"{label}:")
        for axis in (res.seat_depth, res.thigh_fixator, res.ankle_pad):
            print(
                f"  {axis.axis_name}: pin={axis.pin} achieved={axis.achieved_coordinate_mm:.1f}mm "
                f"state={axis.state.value} confidence={axis.confidence.value}"
                + (f" note={axis.note!r}" if axis.note else "")
            )

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
    result_1 = resolve_leg_curl(basketball_player, FRAME)
    _show("Basketball player (no injury)", result_1)

    # Same seat-depth relation as Leg Extension: avg F=559 -> 520mm, hole n=7 (valid, not clamped).
    assert result_1.seat_depth.state is FeasibilityState.IN_RANGE
    assert result_1.seat_depth.pin == 7
    # Thigh fixator always tightens fully regardless of body size.
    assert result_1.thigh_fixator.state is FeasibilityState.IN_RANGE
    assert math.isclose(result_1.thigh_fixator.achieved_coordinate_mm, THIGH_FIXATOR_AXIS.reach_min_mm)
    # Same offset as Leg Extension's shin pad (20mm) on the same avg Ti=521 -> clamps deepest hole.
    assert result_1.ankle_pad.state is FeasibilityState.CLAMPED_HIGH
    assert result_1.ankle_pad.pin == 5

    # --- Edge case 2: petite user, Tier-3 knee injury (light restriction, no gate) ---
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
    knee_injury = InjuryConstraint(
        constraint_id="petite-knee",
        joint=InjuryJoint.KNEE_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.8,
        applied_severity=0.8,
        functional_limit_deg=90,
        provenance=InjuryProvenance.SELF_REPORT,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    result_2 = resolve_leg_curl(petite_user, FRAME, injuries={InjuryJoint.KNEE_L: knee_injury})
    _show("Petite user (Tier-3 knee, light restriction -> note only, no gate exists for this modifier)", result_2)

    assert result_2.ankle_pad.state is FeasibilityState.IN_RANGE
    assert "m_β=0.8" in result_2.ankle_pad.note

    # --- Dedicated check: L/R tibia-length asymmetry escalation flag ---
    asymmetric_legs = AnthropometryProfile(
        user_id="asymmetric_legs",
        captured_at=date(2026, 7, 6),
        height_H_mm=1750,
        sitting_height_T_mm=920,
        femur=BilateralSegment(left_mm=520, right_mm=430),  # 90mm difference -> half-offset 45mm
        tibia=BilateralSegment(left_mm=460, right_mm=380),  # 80mm difference -> half-offset 40mm
        arm=BilateralSegment(left_mm=630, right_mm=625),
        biacromial_width_BAW_mm=400,
        chest_depth_Cd_mm=230,
    )
    result_3 = resolve_leg_curl(asymmetric_legs, FRAME)
    _show("Asymmetric legs (no injury, escalation flags expected on both axes)", result_3)

    assert result_3.seat_depth.note is not None and "half-offset" in result_3.seat_depth.note
    assert "half-offset" in result_3.ankle_pad.note

    print("\nAll machines/leg_curl.py smoke tests passed.")
