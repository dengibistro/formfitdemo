# Machine: Chest Press

**Class:** Seated horizontal press · **Mechanic:** Converging · **Plane:** Transverse (horizontal adduction) · **resistance_profile:** cam (see `../05_resistive_moment.md` — no torque correction needed)

Fixed frame: handle-line datum Y_machine = 1020 mm (fixed, from floor — field-measured 2026-08, was assumed 1200mm). Handle convergence ≈15° inward over the stroke.

**Backrest (field audit 2026-08):** the backrest is actually adjustable — the original "back pad 80° from horizontal" fixed-frame assumption above was wrong, there is no single fixed angle. Per Matrix's own literature the backrest changes chest-to-handle distance/start-point/range-of-motion/stretch, not a lockable degree stop. Not yet modeled as an axis (mechanism not understood well enough yet, no numbers available) — deliberately left unimplemented rather than guessed.

## Axis A — Seat height (Congruence)

Aligns GH joint to the handle force line.

| Field | Value |
|---|---|
| total_holes | 6 |
| step_mm | 30 |
| direction | Direct (lowest seat marked **0**, then 1–5 up to the highest) |
| α | 90° |
| P₀ (n=1, marked 0) | 360 |
| Δ | +30 |
| reach_mm | [360, 510] |
| coupling | Independent |

**Field visit 2026-09:** numbering confirmed on the machine itself — the lowest seat is marked 0 and 1–5 run upward (36/39/42/45/48/51 cm). This axis was previously documented (and coded) as Inverted, which mirrored every pin the assistant gave.

**Rule:** `Seat = Y_machine − k_sh·T` (k_sh = 0.63, `constants.md`). Longer torso → seat drops. Sensitivity dSeat/dT ≈ −0.63.

**Confidence (Section 8/02):** single-segment axis, `σ_Seat = k_sh · σ_T`. See `02_anthropometry.md`.

## Axis B — Handle start depth (FIXED, not adjustable)

**Corrected 2026-08:** field audit found the handles don't move at all — no holes or latches on the hardware for repositioning. The original 4-position capping axis below was never real; kept here struck through as historical record only.

~~| Field | Value |~~
~~|---|---|~~
~~| total_holes | 4 |~~
~~| step_mm | 25 |~~
~~| direction | Direct (1 = shallowest, 4 = deepest) |~~
~~| α | 0° |~~
~~| P₀ (n=1) | 120 |~~
~~| Δ | +25 |~~
~~| reach_mm | [120, 195] |~~
~~| axis_type | Capping |~~
~~| σ (safe direction) | shallower start |~~
~~| β | 5° default |~~

Exact fixed depth in mm not yet measured on-site — TODO, next field visit. Resolved as a flag-only fixed axis in code (same pattern as Shoulder Press's grip width) until that number exists.

## Injury modifiers (from `../constants.md`, Tier-3 baseline)

None currently apply. The shoulder modifier previously listed here shifted the handle-depth capping axis's cap — removed along with that axis, since fixed hardware has nothing to shift.

No lumbar/hip/knee modifiers apply to this machine.

## Not applicable here

Bilateral asymmetry (§`02_anthropometry.md`): both axes are single shared coordinates, not per-limb — resolve normally, no L/R split needed (arms move symmetrically through one seat/handle pair). Coupling Envelope (`04`): not a closed-chain leg machine. Resistive Moment cap: cam profile, no correction.
