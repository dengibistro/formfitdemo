# Machine: Seated Row (Chest-Supported)

**Class:** Chest-supported horizontal row · **Mechanic:** Converging · **Plane:** Transverse · **resistance_profile:** lever (torque correction applies)

**New reference point (field audit 2026-08, absent from the original spec):** height of the backrest/chest-pad support base off the floor = 800mm from floor, confirmed real measurement. Not yet wired into any resolution formula — documented here so it isn't lost, not computed with yet.

## Axis A — Seat height (Congruence)

Sets handle path onto the target back region (low-sternum path for lat/lower-trap emphasis; higher for rhomboid/rear-delt).

| Field | Value |
|---|---|
| total_holes | 6 |
| step_mm | 30 |
| direction | Inverted (1 = highest, 6 = lowest) |
| α | 90° |
| P₀ (n=1) | 560 |
| Δ | −30 |
| reach_mm | [410, 560] |
| coupling | Independent |

**Field audit 2026-08:** confirmed 6 holes (not 7), reach [410, 560]mm (not [410, 590]mm) — the low end of the range was already right, only the top end moved.

**Rule:** `Seat = Y_target − k_sh·T`. Handle-too-high → shrug/upper-trap takeover; this rule prevents it.

## Axis B — Chest pad depth (FIXED, not adjustable)

**Corrected 2026-08:** field audit confirmed on-site that the pad doesn't move. The original 4-position capping axis below was never real; kept here struck through as historical record only.

~~| Field | Value |~~
~~|---|---|~~
~~| total_holes | 4 |~~
~~| step_mm | 30 |~~
~~| direction | Direct (1 = nearest handles, 4 = furthest back) |~~
~~| α | 0° |~~
~~| P₀ (n=1) | 140 |~~
~~| Δ | +30 |~~
~~| reach_mm | [140, 230] |~~
~~| axis_type | Capping |~~
~~| σ | nearer handles (less stretch) |~~
~~| β | 5° default |~~

Exact fixed depth in mm not yet measured on-site — TODO, next field visit. Resolved as a flag-only fixed axis in code (same pattern as Chest Press's handle depth) until that number exists.

**Anatomical target rule:** finish is scapular retraction; elbow path set by handle height (low/close → lat emphasis, ~90° abduction → rhomboid/mid-trap). Chest pad removes lumbar extension as a cheat.

## Axis C — Handle height (low/high grip) — not modeled

Textual only in the original spec (no numbers ever given): a low/close handle emphasizes lats, a ~90°-abduction handle emphasizes rhomboid/mid-trap. Not re-measured in the 2026-08 field audit either — still an open TODO, no axis implemented.

## Injury modifiers (from `../constants.md`)

None currently apply. Both modifiers previously listed here targeted the chest-pad capping axis — removed along with that axis, since fixed hardware has nothing to shift or narrow.

## Resistive Moment (Section 5/09) — applies here

`resistance_profile = lever`. Effective moment arm scales with arm length at a given chest-pad/handle geometry; report effective load (use a) in scope for MVP. Apply `m_τ` ceiling only if a shoulder/lumbar injury constraint is active.

## Not applicable here

Bilateral asymmetry: single shared seat/pad, arms move symmetrically. Coupling Envelope: not closed-chain.
