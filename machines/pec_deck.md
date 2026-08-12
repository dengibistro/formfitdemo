# Machine: Pec Deck / Fly

**Class:** Seated fly · **Mechanic:** Rotary, single fixed pivot · **Plane:** Transverse · **resistance_profile:** lever (torque correction applies — see `../05_resistive_moment.md`)

Fixed pivot height = 1050 mm from floor (not re-measured in the 2026-08 field audit — no known discrepancy, but not independently re-verified either). **Strictest congruence case on the line** — the GH joint must sit level with the pivot, or the arm path becomes rotation plus vertical translation.

## Axis A — Seat height (Congruence, strict)

| Field | Value |
|---|---|
| total_holes | 7 |
| step_mm | 30 |
| direction | Inverted (1 = highest, 7 = lowest) |
| α | 90° |
| P₀ (n=1) | 570 |
| Δ | −30 |
| reach_mm | [390, 570] |
| coupling | Independent |

**Field audit 2026-08:** hole count confirmed unchanged (7, matching two independent on-site measurements) — only the reach range shifted, [390, 570]mm (was [420, 600]mm).

**Rule:** `Seat = Y_pivot − k_sh·T`. A miss here becomes vertical translation of the whole arm arc — tightest half-step flag on the line; do not relax the flagging threshold on this axis.

## Axis B — Arm open offset — structural rewrite (field audit 2026-08)

**This was never one continuous 5-position range.** The machine physically has 8 holes, in two mechanically separate groups labeled on the frame itself: **"Chest Fly" (1-4)** and **"Pec Dec / Rear Delt" (5-8)** — two different exercises with different ranges of motion, not one axis on a shared linear rail. The old table below (kept struck through as historical record) was never real:

~~| Field | Value |~~
~~|---|---|~~
~~| total_holes | 5 |~~
~~| step_mm | 25 |~~
~~| direction | Direct (1 = least open, 5 = most open) |~~
~~| α | N/A (angular start-stop on rotary arm) |~~
~~| P₀ (n=1) | 0 |~~
~~| Δ | +25 |~~
~~| reach_mm | [0, 100] |~~
~~| axis_type | Capping |~~
~~| σ | less open |~~
~~| β | 5° default |~~

### Axis B1 — Chest Fly arm open (holes 1-4)

| Field | Value |
|---|---|
| total_holes | 4 |
| step_deg | ~15° (Matrix's typical hole spacing — **illustrative, pending real measurement**, not a confirmed number) |
| direction | Direct (1 = least open, 4 = most open) |
| P₀ (n=1) | ~30° |
| reach_deg | [~30°, ~75°] |
| axis_type | Capping |
| σ | less open |
| β | 5° default |

Now that real per-hole values are angles directly (not an mm proxy), the axis grounds a target `θ_cap` (25° healthy baseline, injury-shiftable — same policy constant as before) directly to the nearest safe hole. **No arm-length conversion anymore** — the old `Open_offset = R(θ_e)·sin(θ_cap)` mm-projection existed only to translate an assumed-linear rail into an angle; that conversion is gone now that the real machine positions are angles. Concrete consequence, confirmed in code: the 25° healthy-baseline cap sits *below* this axis's real minimum (30°), so absent an injury shift (which only ever narrows the cap further, away from range), every user grounds to the same pin (least-open hole) regardless of arm length — a tension worth revisiting once real angles replace the ~15°-step estimate.

### Axis B2 — Pec Dec / Rear Delt arm open (holes 5-8) — NOT modeled

| Field | Value |
|---|---|
| total_holes | 4 |
| step_deg | ~15° (same caveat as above — illustrative) |
| direction | Direct (1 = least open, 4 = most open) |
| P₀ (n=1) | ~90° |
| reach_deg | [~90°, ~135°] (last hole uncertain, ~125-130° alt) |
| axis_type | Capping |

Very likely a biomechanically different exercise from Chest Fly — posterior deltoid, arms move backward, not the same forward pre-stretch geometry Chest Fly's formula assumes. **Deliberately not wired to Chest Fly's formula** (would be inventing a relationship, not applying an established one). Structurally present in code (real hole positions exist) but resolves to a fixed placeholder position with a clear "not yet modeled" flag until this mode gets its own biomechanical treatment.

## Injury modifiers (from `../constants.md`)

| Zone | Axis | Instrument |
|---|---|---|
| Shoulder | Chest Fly arm open | m_β 0.30 · Δθ_cap 25°→10° · **gate at s ≥ 0.85** |

No lumbar/hip/knee modifiers apply. None apply to Rear Delt / Pec Dec either — that mode isn't modeled yet at all.

## Resistive Moment (Section 5/09) — applies here

`resistance_profile = lever`. Effective moment arm depends on the arm-open offset geometry; joint torque at a given plate setting is limb-length dependent. Report effective load (use a) is in scope for MVP; no torque ceiling override unless a shoulder injury constraint is active (then apply `m_τ` per `05_resistive_moment.md`).

## Not applicable here

Bilateral asymmetry: single shared seat/pivot, arms move symmetrically. Coupling Envelope: not closed-chain.
