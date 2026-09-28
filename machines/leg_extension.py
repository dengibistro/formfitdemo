"""Matrix Leg Extension — concrete machine implementation.

Reads `machines/leg_extension.md`. Seat depth reuses `machines/common.py`'s
`resolve_seat_depth_from_femur` (`Seat_depth = F − δ_F`) unchanged — this is
the axis leg_curl.md says is an "identical relation to Leg Extension", so
sharing it there rather than re-deriving it here is exactly the point.

Shin pad / lever length is this machine's own axis (own δ_Ti, own name) but
uses the same bilateral-congruence averaging pattern via
`common.resolve_bilateral_congruence_axis`. It doubles as the resistive
moment's pad-lever length ("this is also the resistive moment arm") — noted
for transparency, not converted into a torque figure (out of scope, same as
every machine module so far).

Terminal ROM stop is a small discrete angular setting (not a linear mm
Passport row), so it isn't modeled as a `MachineAxis` — forcing holes/step/
reach onto a 4-option angular stop would misrepresent it.

`resistance_profile: cam` for the cam itself (constants.md) — this module
constructs the `Machine` Passport entry with that hardcoded profile; the
pad-lever effect is reported (see above), the cam-normalised torque math
itself is out of scope.

Run as `python3 -m machines.leg_extension` from the `formfit_spec/` directory.
"""

from dataclasses import dataclass, replace

from machines.common import (
    scan_error_for,
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
)
from safety import resolve_with_confidence

# ---------------------------------------------------------------------------
# Leg Extension Passport — constants.md via models.py, plus this machine's
# own fixed-frame numbers (canonical only in machines/leg_extension.md)
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLDS = ConfidenceThresholds()

CAM_PIVOT_HEIGHT_MM = 430.0  # fixed, from floor
TIBIA_SHIN_PAD_OFFSET_MM = 20.0  # δ_Ti ≈ 20mm

SHIN_PAD_AXIS = MachineAxis(
    name="Shin pad / lever length",
    axis_type=AxisType.CONGRUENCE,
    total_holes=5,
    direction=ScaleDirection.DIRECT,
    alpha_deg=0,  # not stated in leg_extension.md; not used elsewhere in this module
    p0_mm=330,
    delta_mm=30,
    reach_min_mm=330,
    reach_max_mm=450,
    coupling=CouplingFlag.INDEPENDENT,
)

TERMINAL_ROM_STOPS = ("full lockout", "-5°", "-10°", "-15°")  # healthy default -> increasingly short of lockout

KNEE_TERMINAL_ROM_MODIFIER = InjuryModifier(
    zone=InjuryZone.KNEE,
    machine=MachineName.LEG_EXTENSION,
    axis="Terminal ROM stop",
    instrument="m_β · remove lockout · gate",
    m_beta=0.40,
    gate_severity_threshold=0.85,
)

LEG_EXTENSION_MACHINE = Machine(
    name=MachineName.LEG_EXTENSION,
    machine_class="Seated knee extension",
    mechanic="Rotary (cam)",
    plane="Sagittal",
    resistance_profile=ResistanceProfile.CAM,
    axes=[LEG_MACHINE_SEAT_DEPTH_AXIS, SHIN_PAD_AXIS],
    injury_modifiers=[KNEE_TERMINAL_ROM_MODIFIER],
)


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LegExtensionResolution:
    seat_depth: AxisResolution
    shin_pad: AxisResolution
    terminal_rom_stop: AxisResolution


# ---------------------------------------------------------------------------
# Resolution flow
# ---------------------------------------------------------------------------


def _resolve_shin_pad(profile: AnthropometryProfile) -> AxisResolution:
    """Axis B — L_pad = Ti − δ_Ti, bilateral congruence average across both legs."""
    tibia_left, tibia_right, single_sided = bilateral_values(profile.tibia)
    extra_note = (
        "tibia length captured single-sided; both legs resolved from the one available reading"
        if single_sided
        else None
    )
    resolution = resolve_bilateral_congruence_axis(
        SHIN_PAD_AXIS,
        tibia_left,
        tibia_right,
        TIBIA_SHIN_PAD_OFFSET_MM,
        scan_error_for(profile).sigma_Ti_mm,
        CONFIDENCE_THRESHOLDS,
        "Ti (tibia)",
        extra_note=extra_note,
        purpose=AxisPurpose.SHIN_ANKLE_PAD_LEVER_ALIGNMENT,
    )
    pad_lever_note = (
        f"L_pad = {resolution.achieved_coordinate_mm:.1f}mm also doubles as the resistive-moment pad-lever "
        "length (05_resistive_moment.md) — reported here, not converted to a torque figure (out of scope)"
    )
    return replace(resolution, note=f"{resolution.note}; {pad_lever_note}" if resolution.note else pad_lever_note)


def _resolve_terminal_rom_stop(
    knee_left: InjuryConstraint | None,
    knee_right: InjuryConstraint | None,
) -> AxisResolution:
    """Axis C — discrete terminal-ROM stop. Healthy default is full lockout;
    a Tier-3 knee injury mandatorily removes lockout (stop at least "-5°"
    short); severity >= 0.85 gates the machine outright."""
    active_injury = knee_left if is_tier3(knee_left) else (knee_right if is_tier3(knee_right) else None)

    if active_injury is None:
        stop = TERMINAL_ROM_STOPS[0]
        return AxisResolution(
            axis_name="Terminal ROM stop",
            pin=1,
            achieved_coordinate_mm=None,
            state=FeasibilityState.IN_RANGE,
            confidence=ConfidenceTag.HIGH,
            note=f"stop: {stop!r}",
            purpose=AxisPurpose.TERMINAL_ROM_LOCKOUT_STOP,
        )

    if active_injury.applied_severity >= KNEE_TERMINAL_ROM_MODIFIER.gate_severity_threshold:
        gated = resolve_with_confidence(
            proposed_state=FeasibilityState.NO_SOLUTION,
            margin_mm=0.0,
            sigma_C_mm=1.0,  # unused: NO_SOLUTION short-circuits before r is computed
            thresholds=CONFIDENCE_THRESHOLDS,
            safe_edge_state=FeasibilityState.CLAMPED_LOW,
        )
        return AxisResolution(
            axis_name="Terminal ROM stop",
            pin=None,
            achieved_coordinate_mm=None,
            state=gated.state,
            confidence=gated.confidence,
            note="severity gate (s>=0.85) fired — offer substitute",
            purpose=AxisPurpose.TERMINAL_ROM_LOCKOUT_STOP,
        )

    stop = TERMINAL_ROM_STOPS[1]  # "-5°" — lockout removed (mandatory), least-restrictive safe option
    return AxisResolution(
        axis_name="Terminal ROM stop",
        pin=TERMINAL_ROM_STOPS.index(stop) + 1,
        achieved_coordinate_mm=None,
        state=FeasibilityState.CLAMPED_LOW,
        confidence=ConfidenceTag.HIGH,  # a mandatory rule, not a computed estimate — no uncertainty in it
        note=f"Tier-3 knee: terminal lockout removed (mandatory), stopped at {stop!r}",
        purpose=AxisPurpose.TERMINAL_ROM_LOCKOUT_STOP,
    )


def resolve_leg_extension(
    profile: AnthropometryProfile,
    injuries: dict[InjuryJoint, InjuryConstraint] | None = None,
) -> LegExtensionResolution:
    """Resolve Leg Extension seat depth + shin pad + terminal ROM stop for one user."""
    injuries = injuries or {}
    seat_depth = resolve_seat_depth_from_femur(profile.femur, scan_error_for(profile).sigma_F_mm, CONFIDENCE_THRESHOLDS)
    shin_pad = _resolve_shin_pad(profile)
    terminal_rom_stop = _resolve_terminal_rom_stop(
        knee_left=injuries.get(InjuryJoint.KNEE_L),
        knee_right=injuries.get(InjuryJoint.KNEE_R),
    )
    return LegExtensionResolution(seat_depth=seat_depth, shin_pad=shin_pad, terminal_rom_stop=terminal_rom_stop)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import math
    from datetime import date

    from models import BilateralSegment, InjuryProvenance, InjuryTier

    assert LEG_EXTENSION_MACHINE.resistance_profile is ResistanceProfile.CAM

    def _show(label: str, res: LegExtensionResolution) -> None:
        print(f"{label}:")
        for axis in (res.seat_depth, res.shin_pad, res.terminal_rom_stop):
            pin_str = "n/a" if axis.pin is None else str(axis.pin)
            coord_str = "n/a" if axis.achieved_coordinate_mm is None else f"{axis.achieved_coordinate_mm:.1f}mm"
            print(
                f"  {axis.axis_name}: pin={pin_str} achieved={coord_str} "
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
    result_1 = resolve_leg_extension(basketball_player)
    _show("Basketball player (no injury)", result_1)

    # avg F=559 -> 529mm target; deepest hole (n=7) sits at 520mm, which is
    # still the nearest *real* hole (n=7 <= total_holes=7, so this isn't a
    # boundary clamp). The pin choice itself is unambiguous — the boundary
    # with n=6 (490mm) is at 505mm, 24mm away — so MEDIUM, not LOW (the
    # confidence margin is to the neighbouring pin now, not to reach_max).
    assert result_1.seat_depth.state is FeasibilityState.IN_RANGE
    assert result_1.seat_depth.pin == 7
    assert math.isclose(result_1.seat_depth.achieved_coordinate_mm, 520.0)
    assert result_1.seat_depth.confidence is ConfidenceTag.MEDIUM
    assert result_1.seat_depth.alternative_pin is None
    # avg Ti=521 -> 521-20=501mm, past reach_max(450) -> clamps deepest hole
    assert result_1.shin_pad.state is FeasibilityState.CLAMPED_HIGH
    assert result_1.shin_pad.pin == 5
    assert result_1.terminal_rom_stop.state is FeasibilityState.IN_RANGE

    # --- Edge case 2: petite user, no injury (comfortably in range) ---
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
    result_2 = resolve_leg_extension(petite_user)
    _show("Petite user (no injury)", result_2)

    assert result_2.seat_depth.state is FeasibilityState.IN_RANGE
    assert result_2.shin_pad.state is FeasibilityState.IN_RANGE

    # --- Dedicated check: Tier-3 knee, below the severity gate -> lockout removed, not blocked ---
    below_gate_injury = InjuryConstraint(
        constraint_id="knee-below-gate",
        joint=InjuryJoint.KNEE_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.75,
        applied_severity=0.75,  # Tier-3, but under the 0.85 gate
        functional_limit_deg=80,
        provenance=InjuryProvenance.APP_ASSESSED,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    result_3 = resolve_leg_extension(petite_user, injuries={InjuryJoint.KNEE_L: below_gate_injury})
    _show("Petite user (Tier-3 knee, severity 0.75 < gate -> lockout removed)", result_3)

    assert result_3.terminal_rom_stop.state is FeasibilityState.CLAMPED_LOW
    assert "'-5°'" in result_3.terminal_rom_stop.note

    # --- Dedicated check: Tier-3 knee at/above the severity gate -> machine gated ---
    gated_injury = below_gate_injury.model_copy(update={"constraint_id": "knee-at-gate", "applied_severity": 0.9})
    result_4 = resolve_leg_extension(petite_user, injuries={InjuryJoint.KNEE_R: gated_injury})
    _show("Petite user (Tier-3 knee, severity 0.90 >= gate -> NO_SOLUTION)", result_4)

    assert result_4.terminal_rom_stop.state is FeasibilityState.NO_SOLUTION
    assert result_4.terminal_rom_stop.confidence is ConfidenceTag.HIGH  # confidence-immune

    print("\nAll machines/leg_extension.py smoke tests passed.")
