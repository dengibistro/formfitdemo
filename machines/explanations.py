"""Structured, tone-agnostic explanation facts for CLAMPED/NO_SOLUTION results.

Not a text generator in the product sense. The plan (per project discussion)
is a future AI dialogue layer that narrates results conversationally, in
whatever tone that separate system decides (bro/pro/care) — deliberately
NOT built here. This module's only job is to make sure the *facts* that
narration needs actually exist as clean, structured data, instead of being
buried inside free-text `note` strings or not exposed at all:

- which anthropometric input caused the axis to miss its ideal position
  (`causing_segment` — distinct from `AxisResolution.dominant_segment`,
  which names the dominant *scan-noise* contributor to the confidence tag,
  not the cause of a clamp)
- how far off the achieved position is from the ideal one (`residual_mm`)
- what the axis exists to protect (`purpose` / `purpose_description`)

It also ships one neutral, factual fallback sentence per verdict so the
prototype has something honest to show today, before the AI layer exists.
This fallback is deliberately plain — no tone, no invented substitute
machines (per project decision: no redirect table yet) — just the facts for
*this* user's *this* geometry, never a generic disclaimer.
"""

from dataclasses import dataclass

from machines.common import AxisResolution
from models import AxisPurpose, ConfidenceTag, FeasibilityState

# Plain-language gloss of each axis's biomechanical role — grounding data for
# a future narrator, not itself a sentence template. One entry per
# AxisPurpose value; each traces back to that axis's own one-line
# description in its machines/*.md file (see models.py's AxisPurpose).
AXIS_PURPOSE_DESCRIPTIONS: dict[AxisPurpose, str] = {
    AxisPurpose.SEAT_HEIGHT_SHOULDER_ALIGNMENT: "aligning your shoulder joint with the machine's handle line",
    AxisPurpose.KNEE_AXIS_ALIGNMENT: "aligning your knee joint with the machine's cam pivot",
    AxisPurpose.SHIN_ANKLE_PAD_LEVER_ALIGNMENT: "positioning the pad against your shin/ankle at the right lever length",
    AxisPurpose.SHOULDER_HORIZONTAL_EXTENSION_CAP: "limiting how far your shoulder extends backward at the stretch",
    AxisPurpose.SHOULDER_PRE_STRETCH_CAP: "limiting how far your arms open at the pre-stretch",
    AxisPurpose.FULL_EXTENSION_STRETCH_CAP: "limiting your reach at full arm extension so your chest stays on the pad",
    AxisPurpose.PELVIC_LOCK_THIGH_PAD: "locking your pelvis so the pull works your back, not your hips",
    AxisPurpose.THIGH_FIXATOR_LOCK: "locking your thigh so the curl works your hamstring, not your hip",
    AxisPurpose.TERMINAL_ROM_LOCKOUT_STOP: "limiting how far your knee locks out at the top",
    AxisPurpose.CARRIAGE_DEPTH_KNEE_HIP_FLEXION: "limiting how deep your knees/hips bend at the bottom",
    AxisPurpose.BACKREST_RECLINE_HIP_FLEXION: "limiting your hip flexion via backrest angle",
    AxisPurpose.GRIP_WIDTH_SHOULDER_ABDUCTION: "keeping your grip width safe for your shoulder width",
    AxisPurpose.OVERHEAD_REACH_SHOULDER_ELEVATION: "keeping the overhead reach safe for your arm/torso length",
    AxisPurpose.REAR_DELT_PRE_STRETCH_CAP: "limiting how far your arms open on the rear-delt setting (not yet fully modeled)",
}


@dataclass(frozen=True)
class ExplanationFacts:
    """Pure facts about one axis's resolution — no prose, no tone. Meant to
    be handed to a future AI dialogue layer as grounding, or rendered by
    `fallback_text` below when that layer doesn't exist yet."""

    machine_name: str | None
    axis_name: str
    verdict: FeasibilityState
    purpose: AxisPurpose | None
    purpose_description: str | None
    causing_segment: str | None
    residual_mm: float | None  # achieved - target, signed; None if this axis has no continuous target
    achieved_pin: int | None
    achieved_coordinate_mm: float | None
    confidence: ConfidenceTag
    dominant_segment: str | None
    engineering_note: str | None  # the existing free-text note — kept for debugging/audit, not for narration
    alternative_pin: int | None = None  # neighbouring pin the scan can't rule out (LOW confidence)
    user_cue: str | None = None  # physical instruction for the user, e.g. how to pick between pin and alternative_pin


def build_explanation_facts(resolution: AxisResolution, machine_name: str | None = None) -> ExplanationFacts:
    """Assemble `ExplanationFacts` from an already-resolved `AxisResolution`.
    Pure data assembly — no new computation, nothing fabricated."""
    residual_mm = None
    if resolution.achieved_coordinate_mm is not None and resolution.target_coordinate_mm is not None:
        residual_mm = resolution.achieved_coordinate_mm - resolution.target_coordinate_mm

    return ExplanationFacts(
        machine_name=machine_name,
        axis_name=resolution.axis_name,
        verdict=resolution.state,
        purpose=resolution.purpose,
        purpose_description=AXIS_PURPOSE_DESCRIPTIONS.get(resolution.purpose) if resolution.purpose else None,
        causing_segment=resolution.causing_segment,
        residual_mm=residual_mm,
        achieved_pin=resolution.pin,
        achieved_coordinate_mm=resolution.achieved_coordinate_mm,
        confidence=resolution.confidence,
        dominant_segment=resolution.dominant_segment,
        engineering_note=resolution.note,
        alternative_pin=resolution.alternative_pin,
        user_cue=resolution.user_cue,
    )


_NO_SOLUTION_STATES = (FeasibilityState.NO_SOLUTION, FeasibilityState.NO_SOLUTION_BY_COUPLING)
_CLAMPED_STATES = (
    FeasibilityState.CLAMPED_LOW,
    FeasibilityState.CLAMPED_HIGH,
    FeasibilityState.CLAMPED_BY_COUPLING,
)


def fallback_text(facts: ExplanationFacts) -> str:
    """One neutral, tone-agnostic, factual sentence — a stand-in for the
    product's real chat-driven explanation until the AI dialogue layer
    exists. Deliberately plain (no "bro/pro/care" voice): states the facts
    for *this* user's *this* geometry, never a generic disclaimer."""
    machine_prefix = f"{facts.machine_name} — " if facts.machine_name else ""

    if facts.verdict is FeasibilityState.IN_RANGE:
        if facts.achieved_pin is None:
            return f"{machine_prefix}{facts.axis_name}: within range (fixed, not adjustable)."
        return f"{machine_prefix}{facts.axis_name}: within range at pin {facts.achieved_pin}."

    if facts.verdict in _NO_SOLUTION_STATES:
        reason = f" ({facts.purpose_description})" if facts.purpose_description else ""
        return (
            f"{machine_prefix}{facts.axis_name}: no safe setting exists on this machine for your proportions"
            f"{reason} — this exercise isn't available to you on this machine right now."
        )

    if facts.verdict in _CLAMPED_STATES:
        cause = f" driven by {facts.causing_segment}" if facts.causing_segment else ""
        residual = f", {abs(facts.residual_mm):.0f}mm off the ideal position" if facts.residual_mm is not None else ""
        reason = f" — this axis is {facts.purpose_description}" if facts.purpose_description else ""
        coord = f"{facts.achieved_coordinate_mm:.0f}mm" if facts.achieved_coordinate_mm is not None else "n/a"
        return (
            f"{machine_prefix}{facts.axis_name}: your proportions{cause} exceed this machine's range; "
            f"set to pin {facts.achieved_pin} ({coord}){residual}, the best this frame can do{reason}."
        )

    # Any other/coupling-caution state not covered above.
    return f"{machine_prefix}{facts.axis_name}: {facts.verdict.value}."


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date

    from machines.chest_press import resolve_chest_press
    from machines.leg_press import CouplingConstants, LegPressFrameConstants, resolve_leg_press
    from models import AnthropometryProfile, BilateralSegment, InjuryConstraint, InjuryJoint, InjuryProvenance, InjuryTier

    # --- Chest Press: petite user, Tier-3 shoulder injury (CLAMPED_HIGH seat + CLAMPED_LOW handle) ---
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
    chest_result = resolve_chest_press(petite_user, injuries={InjuryJoint.SHOULDER_L: left_shoulder_injury})

    seat_facts = build_explanation_facts(chest_result.seat, machine_name="Chest Press")
    assert seat_facts.verdict is FeasibilityState.CLAMPED_HIGH
    assert seat_facts.causing_segment == "T (sitting height)"
    # Petite user's ideal seat target exceeds the frame's max — achieved (clamped at max) sits below that ideal.
    assert seat_facts.residual_mm is not None and seat_facts.residual_mm < 0
    assert seat_facts.purpose_description is not None
    print("Chest Press seat:", fallback_text(seat_facts))

    # Handle depth is now fixed hardware (2026-08 field audit — see
    # chest_press.py), not the capping axis this used to exercise: always
    # IN_RANGE, no pin, no anthropometric causing_segment.
    handle_facts = build_explanation_facts(chest_result.handle_depth, machine_name="Chest Press")
    assert handle_facts.verdict is FeasibilityState.IN_RANGE
    assert handle_facts.achieved_pin is None
    assert handle_facts.causing_segment is None
    print("Chest Press handle depth:", fallback_text(handle_facts))

    # --- Leg Press: reuse the three Step 6 scenarios (IN_RANGE / CLAMPED_BY_COUPLING / NO_SOLUTION_BY_COUPLING) ---
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
    coupling = CouplingConstants(a_ham=0.1, a_fem=0.15, fatigue_reserve_deg=3.0, m_hip_tier3=0.75)
    frame = LegPressFrameConstants(recline_hip_reduction_per_step_deg=6.0)

    leg_press_result = resolve_leg_press(healthy_user, coupling, frame, theta_hip_onset_deg=140.0, theta_knee_screen_deg=90.0)
    carriage_facts = build_explanation_facts(leg_press_result.carriage_d, machine_name="Leg Press 45°")
    assert carriage_facts.verdict is FeasibilityState.IN_RANGE
    print("Leg Press carriage (healthy):", fallback_text(carriage_facts))

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
    no_solution_result = resolve_leg_press(
        unfeasible_user,
        coupling,
        frame,
        theta_hip_onset_deg=115.0,
        theta_knee_screen_deg=70.0,
        injuries={InjuryJoint.LUMBAR: lumbar_injury},
    )
    no_solution_facts = build_explanation_facts(no_solution_result.carriage_d, machine_name="Leg Press 45°")
    assert no_solution_facts.verdict is FeasibilityState.NO_SOLUTION_BY_COUPLING
    assert no_solution_facts.confidence is ConfidenceTag.HIGH
    text = fallback_text(no_solution_facts)
    assert "not available" in text or "isn't available" in text
    print("Leg Press carriage (unfeasible):", text)

    print("\nAll machines/explanations.py smoke tests passed.")
