# Machine: Shoulder Press

**Class:** Seated overhead press · **Mechanic:** Converging · **Plane:** Scapular (near-frontal) · **resistance_profile:** cam (no torque correction needed)

Fixed frame: back pad reclined ~10–15° from vertical (~75–80° from the
floor), midpoint 12.5° used in code as `BACKREST_RECLINE_DEG`. **This
replaces the earlier "88° from horizontal" figure** (only ~2° of recline)
— that number predated the 2026-08 field audit and was never itself
field-verified; the audit only touched Y_machine and seat holes/reach.
The 12.5° figure is a visual estimate from a real MG-PL23 photo
(2026-08-08), not a field measurement either — still pending a real
protractor/level reading on-site. Handle-bottom datum Y_machine = 1000 mm
(fixed, from floor — field-measured 2026-08, was assumed 1150mm).

## Axis A — Seat height (Congruence)

Places handle bottom at shoulder level.

| Field | Value |
|---|---|
| total_holes | 5 |
| step_mm | 30 |
| direction | Direct (1 = lowest, 5 = highest) |
| α | 90° |
| P₀ (n=1) | 350 |
| Δ | +30 |
| reach_mm | [350, 470] |
| coupling | Independent |

**Field visit 2026-09:** 35/38/41/44/47 cm, pin 1 = lowest — previously coded Inverted, mirroring every pin.

**Field audit 2026-08:** confirmed 5 holes (not 7), reach [350, 470]mm (not [400, 580]mm), step 30mm unchanged.

**Rule:** `Seat = Y_machine − K_SH_EFFECTIVE·T`, where `K_SH_EFFECTIVE =
k_sh · cos(BACKREST_RECLINE_DEG) ≈ 0.63 · cos(12.5°) ≈ 0.615` — **not**
the raw −0.63 Chest Press uses. `k_sh` (`constants.md`) is a GH-joint-
height-above-seat ratio defined for an upright/vertical torso (same
posture sitting height T itself assumes); this machine's reclined backrest
tilts that same fixed torso segment back, shrinking its vertical
projection by `cos(θ)`. Left uncorrected, the shared formula would place
the seat systematically too low. See `shoulder_press.py`'s own comment for
the full derivation and the estimate's provenance/caveat.

## Axis B — Grip width — FIXED

Moulded dual handle, effective span ≈ 520 mm. **Not adjustable — no discrete axis.** Not independently re-verified in the 2026-08 field audit — no known discrepancy, but not re-measured either.

**Engine action (revised 2026-09-28):** when 520 mm falls outside [BAW, 1.5·BAW] (g_grip, `constants.md`), report CLAMPED (the frame's limit for this body) with a technique cue — narrow BAW → handles wide for them, keep elbows forward; wide BAW → handles narrow, stop short if the shoulders pinch. Previously NO_SOLUTION, which is far too strong for a fixed grip; also the scanner's BAW (shoulder landmarks ≈ joint centres) reads narrower than true acromion-to-acromion breadth, so the upper bound fires early.

## Injury modifiers (from `../constants.md`)

| Zone | Scope | Instrument |
|---|---|---|
| Shoulder | Whole machine | Gate at Tier 3; reduced ROM at Tier 2 (overhead loading commonly contraindicated acutely — nothing on-axis to tune, so gate the machine) |
| Lumbar | Whole machine | Partial gate at Tier 3 (upright spinal compression) |

## Not applicable here

Bilateral asymmetry: single shared seat/grip, not per-limb. Coupling Envelope: not closed-chain. Resistive Moment: cam profile, no correction.
