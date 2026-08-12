# Machine: Leg Extension

**Class:** Seated knee extension · **Mechanic:** Rotary (cam) · **Plane:** Sagittal · **resistance_profile:** cam (no torque correction needed — but see resistance-lever note below)

Cam pivot height (fixed) = 430 mm from floor. Not re-measured or otherwise found discrepant in the 2026-08 field audit — this machine's own numbers stand as-is.

**Note (2026-08):** this 430mm pivot was previously assumed shared with Leg Curl (`leg_curl.py`'s own comment called it "same congruence alignment target as Leg Extension"). That assumption no longer holds — the field audit found Leg Curl is actually a structurally different (prone/lying) machine at this gym, not a seated one sharing this frame. Leg Extension's own 430mm figure is unaffected by that finding; only the cross-machine sharing assumption is retracted. Also gated as "not supported yet" in the live assistant this round, alongside Leg Curl — not because anything is confirmed wrong here, but to keep this round's scope to the machines with confirmed real data.

## Axis A — Seat depth / backrest (Congruence)

Knee axis onto the cam pivot.

| Field | Value |
|---|---|
| total_holes | 7 |
| step_mm | 30 |
| direction | Direct (1 = shallowest/short femur, 7 = deepest/long femur) |
| α | 0° |
| P₀ (n=1) | 340 |
| Δ | +30 |
| reach_mm | [340, 520] |
| coupling | Independent |

**Rule:** `Seat_depth = F − δ_F` (δ_F ≈ 30 mm). Linear in F, 1:1.

**Confidence (Section 8/02):** `σ_depth = σ_F` directly (single-segment, coefficient 1).

## Axis B — Shin pad / lever length (Congruence)

Pad just above the malleoli.

| Field | Value |
|---|---|
| total_holes | 5 |
| step_mm | 30 |
| direction | Direct |
| P₀ (n=1) | 330 |
| Δ | +30 |
| reach_mm | [330, 450] |

**Rule:** `L_pad = Ti − δ_Ti` (δ_Ti ≈ 20 mm). Linear in Ti, 1:1. **This is also the resistive moment arm** — see below.

## Axis C — Terminal ROM stop (Capping, discrete)

| Field | Value |
|---|---|
| Settings | {full lockout, −5°, −10°, −15°} |
| axis_type | Capping |
| σ | short of lockout |
| Start flexion | ≈ 90° |

Protects against patellofemoral stress at low flexion near full extension.

## Injury modifiers (from `../constants.md`)

| Zone | Axis | Instrument |
|---|---|---|
| Knee | Terminal ROM stop | m_β 0.40 · remove terminal lockout (stop short) · **gate at s ≥ 0.85** |

## Resistive Moment (Section 5/09) — applies here despite cam profile

Marked `cam` for the cam-normalisation rule (don't double-correct the torque curve the cam already delivers about its own axis). **However**, the shin-pad lever length (Axis B, `L_pad = Ti − δ_Ti`) still varies the effective resistance arm between the pad and the ankle: a longer tibia is a longer external lever regardless of the cam. Report effective load (use a) applies to this pad-lever effect specifically, not to the cam-normalised torque about the pivot. If a knee injury constraint is active, apply the `m_τ` ceiling from `05_resistive_moment.md` using this pad-lever relation.

## Bilateral asymmetry

Both axes are single shared coordinates for two legs. Apply the minimax-midpoint rule from `../02_anthropometry.md` (Congruence type) to both Seat depth and Shin pad if F/Ti differ meaningfully L/R; flag if half-offset exceeds axis tolerance.

## Not applicable here

Coupling Envelope (`04`): open kinetic chain, not applicable.
