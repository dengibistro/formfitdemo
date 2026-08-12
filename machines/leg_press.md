# Machine: Leg Press 45°

**Class:** Inclined leg press · **Mechanic:** Linear (sled) · **Plane:** Sagittal · **resistance_profile:** linear (full torque correction applies, largest effect on the line)

Rail inclination α = 45°. Target start flexion φ = 60°.

This is the only machine (besides Hack Squat, not yet in the Passport) where **Coupling Envelope (`../04_coupling_mechanism.md`)** and the **full Resistive Moment Model (`../05_resistive_moment.md`)** both apply in force. Read both before implementing this file.

## Axis A — Carriage distance D (Capping)

Sets bottom knee flexion via the law of cosines.

| Field | Value |
|---|---|
| total_holes | 9 |
| step_mm | 40 |
| direction | Direct (1 = closest/short legs, 9 = furthest/long legs) |
| α | 45° |
| P₀ (n=1) | 500 |
| Δ | +40 |
| reach_mm | [500, 820] |
| axis_type | Capping |
| σ | larger D (shallower bottom, safer) |
| β | 5° default |

**Rule:** `D(φ) = √(F² + Ti² + 2·F·Ti·cos φ)`; at φ=60°: `D_start = √(F² + Ti² + F·Ti)`.

**Resolution note:** coordinate tolerance `τ = β·F·Ti·sin φ / D`. Half-step at 40 mm pitch = 20 mm. If a user's τ falls under 20 mm, raise a **grid-resolution flag** even when D sits inside reach — the grid is too coarse for their angular budget regardless of reach.

**Confidence (Section 8/02):** two-segment axis. `∂D/∂F = (2F+Ti)/2D`, `∂D/∂Ti = (2Ti+F)/2D`; combine per `σ_D` formula in `02_anthropometry.md`.

## Axis B — Backrest recline (Capping, discrete)

Secondary hip-flexion limiter.

| Field | Value |
|---|---|
| Settings | {100°, 113°, 125°} seat-to-back angle |
| axis_type | Capping |
| σ | more recline (less peak hip flexion) |

More recline reduces peak hip flexion at a given sled depth.

## Axis C — Footplate — FIXED (large plate)

Foot height is user-selected, governed by the **F:Ti ratio** (femur-dominant → feet higher, to keep heel down and limit knee travel past the toes). **Not a discrete machine axis** — don't resolve a numeric setting; flag heel-lift risk from the ratio instead. This same foot-height parameter is `h_foot` in the Coupling Envelope's `O_HF(D, h_foot)` term.

## Injury modifiers — single-axis (from `../constants.md`)

| Zone | Axis | Instrument |
|---|---|---|
| Knee | Carriage D | m_β 0.50 · φ floor raised (limit deep flexion) · σ toward larger D |
| Hip | Backrest recline | m_β 0.40 · bias to maximum recline |
| Hip | Carriage D | m_β 0.50 · shallower bottom |
| Lumbar | Carriage D + recline | m_β 0.40 · shallower + more recline |

## Coupling Envelope — full application (`../04_coupling_mechanism.md`)

This machine is where CI is evaluated. Injury modifiers on **Θ_env** (distinct from the single-axis modifiers above — both apply, take the stricter result):

| Zone | Θ_env modifier |
|---|---|
| Lumbar | m_lumbar ≈ 0.60 (Tier 3) |
| Hip | m_hip (Tier 3, see `../constants.md`) |
| Knee | m_knee ≈ 0.70 (Tier 3) — closes the gap where the single-axis knee modifier above doesn't reach the coupled hip/knee sum |

### Worked example (long-femur profile, for validating an implementation)

F = 600 mm, Ti = 500 mm. Frame maxes at D = 820 mm.

```
At D = 820: cos φ_HF = (600² + 820² − 500²)/(2·600·820) = 0.795 → φ_HF ≈ 37.4°
θ_hip ≈ 108° (illustrative, from calibrated frame term at mid-recline)
θ_knee ≈ 84° (from D=820 via the knee-flexion relation — deeper than the 60° target)

CI = (108 + 0.35·84) / Θ_env = 137.4 / Θ_env

Healthy Θ_env ≈ 121  →  CI ≈ 1.14  →  CLAMPED_BY_COUPLING (before any injury)
+ Tier-2 lumbar (m_lumbar ≈ 0.80) → Θ_env ≈ 101 → CI ≈ 1.36 → firmly CLAMPED_BY_COUPLING
```

Resolution: Path B (raise feet) drops θ_hip by ≈12° → CI = (96 + 29.4)/101 = 1.24, still over → Path A caps depth until CI ≤ 0.97, at a mandatory floor because the lumbar flag makes Path A non-optional. If residual ROM is unusably short → NO_SOLUTION_BY_COUPLING, substitute.

This is the same femur length that is NO_SOLUTION on plain reach at D=820 for a 60° target (see `../04_coupling_mechanism.md` context) — the two findings should agree in any implementation: this frame does not fit this user, and shortening depth alone is not sufficient without the foot-height adjustment.

## Resistive Moment Model — full application (`../05_resistive_moment.md`)

`resistance_profile = linear`. No cam to normalise anything — this is where the effect is largest.

```
τ_knee = F_sled · Ti · sin(η_Ti)
τ_hip  = F_sled · F  · sin(η_F)
```

η_Ti, η_F vary through the stroke; peak knee and peak hip torque occur at different points depending on the individual's F/Ti. Report effective load (use a) at minimum. If a knee, hip, or lumbar injury constraint is active, compute `W_max = m_τ / (lever · sin η)_peak` per `../05_resistive_moment.md` and cap the selectable stack weight — this is per-user: a longer lever reaches the same injury moment ceiling at a lower weight, so two users with the same injury tier get different W_max.

## Bilateral asymmetry

Single shared carriage for both legs. Apply minimax-midpoint (`../02_anthropometry.md`) to D using (F_L,Ti_L) and (F_R,Ti_R) if they differ meaningfully; flag if half-offset exceeds the axis tolerance τ. Footplate foot-height is not shared — L/R foot height can differ if the plate allows independent placement.
