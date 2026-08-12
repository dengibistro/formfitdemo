# 03 — Injury Overlay Mechanism (Generic)

This file defines **how** the injury layer works. Which zone affects which machine/axis, and by how much, lives in `constants.md` (table: "Injury modifiers by zone × machine × axis") and is restated per-machine in each `machines/*.md` file's own "Injury Modifiers" section.

## What it touches

Injury acts **only on capping axes**, through three instruments, never on congruence axes (an injured joint's axis is in the same place; congruence is pure geometry).

| Instrument | Symbol | Effect |
|---|---|---|
| Budget multiplier | m_β ∈ (0,1] | Shrinks the tolerance band τ = β/\|dψ/dC\|, so resolution rounds harder toward the safe edge and flags sooner |
| Cap shift | Δψ | Moves the dangerous edge inward |
| Machine gate | — | When even the safest achievable geometry can't hold the joint inside the shifted window → NO_SOLUTION-by-injury, offer substitute |

Safe direction σ is reinforced, not reversed, in every mapped case (a genuine σ-reversal is structurally possible but not required by any of the eight machines).

## InjuryConstraint profile

```
joint: {shoulder_L, shoulder_R, knee_L, knee_R, hip_L, hip_R, lumbar}
severity s: 0–1 (1 = full acute restriction, 0 = resolved to normal)
functional_limit: measured/estimated safe angle for the joint's primary motion
provenance: {self_report, app_assessed, clinician_set}
onset_date / review_date
pain_free_counter: consecutive clean sessions since last flare
```

Not a diagnosis. The system stores a functional limit ("safe shoulder horizontal abduction ≤ 12°") with provenance and a review date — never a named condition.

## Severity tiers

See `constants.md`. All quoted m_β/Δψ/m_lumbar/m_hip/m_knee/m_τ values are Tier-3 (worst-case); scale toward 1.0 as tier falls.

## Temporal model — widening and re-narrowing

- **Candidate decay (time):** severity eases toward 0 over an injury-class horizon H. Smooth-case path only.
- **Applied severity (evidence-gated):** the value the engine actually uses only advances when evidence exists — N consecutive pain-free sessions on affected machines, or a passed re-assessment. The candidate can run ahead; the applied value waits.
- **Instant re-narrowing:** any pain report snaps applied severity back up to a floor set by that report and resets the pain-free counter to zero. Up is immediate; down is earned.
- **Measurement overrides the model:** a re-test result (from the app's functional screen) overrides modelled decay outright, in either direction.
- **Provenance sets caution:** self_report widens slowest and cannot cross out of Tier 2 without a re-test; app_assessed tracks the periodic screen; clinician_set requires a new clinician input to widen past the clinician's ceiling.
- **No silent healing:** if review_date passes with no logged progress, applied severity holds at its current tier and prompts a re-assessment. Default is "still injured until shown otherwise."

## Interaction with feasibility states

Injury-driven CLAMPED is distinct from geometric CLAMPED (Section 1 states). Geometric CLAMPED → "this frame doesn't fit you." Injury CLAMPED → "your safe range is limited today; the movement is shortened / repositioned to protect the joint." NO_SOLUTION-by-injury reuses the standard gate: exclude machine, offer substitute.

## Interaction with the Resistive Moment Model (Section 9/05)

An injury constrains **angle** via this file's instruments. It also constrains **moment**, via `m_τ` in `05_resistive_moment.md` — the two stack; an injured joint is protected on both range and load, and the safe weight ceiling this implies is per-user (a longer lever reaches the same moment ceiling at a lower weight — see `05_resistive_moment.md`).

## Interaction with the Coupling Envelope (Section 7/04)

On Leg Press/Hack Squat, lumbar/hip/knee constraints additionally multiply the coupled envelope threshold Θ_env (m_lumbar, m_hip, m_knee — see `04_coupling_mechanism.md`), on top of whatever single-axis capping instrument this file applies to the carriage/recline axes directly. Both apply; take the stricter result.
