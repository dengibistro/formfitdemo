# Machine: Seated Leg Curl

**⚠️ Field audit finding (2026-08) — everything below this notice is WRONG for the actual machine at this gym and kept only as historical record.** The physical machine at this location is a **prone/lying Leg Curl**, not the seated design this whole document describes: the user lies face-down, chest/arms braced against an upper pad, ankle roller flexes the leg upward against resistance. This is a structurally different machine, not a numbers discrepancy — no axis, constant, or formula below carries over. Zero measurements have been taken of the real prone machine yet (no pivot height, no upper-pad geometry, no ankle-roller travel) — a full respec from scratch is pending a future field visit. Gated as "not supported yet" in the live assistant in the meantime (see `api.py`) rather than serving this seated spec's wrong instructions for equipment that isn't there.

The former shared-pivot assumption with Leg Extension (both previously coded at 430mm, "same congruence alignment target") no longer holds now that this machine is confirmed a different design entirely — see `leg_extension.md`'s own note.

---

## Historical record (seated design, confirmed wrong for this location)

**Class:** Seated knee flexion · **Mechanic:** Rotary (cam) · **Plane:** Sagittal · **resistance_profile:** cam (no torque correction needed for the cam itself — same pad-lever caveat as Leg Extension)

Cam pivot height (fixed) = 430 mm from floor. Same congruence alignment target as Leg Extension.

## Axis A — Seat depth / backrest (Congruence)

| Field | Value |
|---|---|
| total_holes | 7 |
| step_mm | 30 |
| direction | Direct (1 = short femur, 7 = long) |
| α | 0° |
| P₀ (n=1) | 340 |
| Δ | +30 |
| reach_mm | [340, 520] |

**Rule:** `Seat_depth = F − δ_F`, identical relation to Leg Extension.

## Axis B — Thigh fixator / top clamp (Capping)

Locks the femur; blocks hip substitution so the hamstring pulls the tibia, not the hip into extension.

| Field | Value |
|---|---|
| total_holes | 5 |
| step_mm | 30 |
| direction | Inverted (1 = loosest/highest, 5 = tightest/lowest) |
| P₀ (n=1) | 240 |
| Δ | −30 |
| reach_mm | [120, 240] |
| axis_type | Capping |
| σ | tighter clamp |

## Axis C — Ankle pad / lever length (Congruence)

Pad above the heel/Achilles.

| Field | Value |
|---|---|
| total_holes | 5 |
| step_mm | 30 |
| direction | Direct |
| P₀ (n=1) | 330 |
| Δ | +30 |
| reach_mm | [330, 450] |

**Rule:** `L_pad = Ti − δ_Ti'`. This is also the resistive lever — see Resistive Moment note below.

**Working angle window:** start 0–10° flexion (near extension); curl to ≈ 95–100°, capped to avoid over-shortening/cramp.

## Injury modifiers (from `../constants.md`)

| Zone | Axis | Instrument |
|---|---|---|
| Knee | Curl-depth window | m_β 0.80 (light restriction — mainly post-hamstring-graft caution) |

## Resistive Moment (Section 5/09) — applies here despite cam profile

Same caveat as Leg Extension: cam normalises torque about its own axis, but the ankle-pad lever length (Axis C) still scales the effective external moment arm with tibia length. Report effective load in scope for MVP; apply `m_τ` ceiling if a knee injury constraint is active.

## Bilateral asymmetry

Apply minimax-midpoint (`../02_anthropometry.md`) to Axis A and Axis C if F/Ti differ L/R. Axis B (thigh fixator) is capping-type — tighter side governs for both legs.

## Not applicable here

Coupling Envelope (`04`): open kinetic chain, not applicable.
