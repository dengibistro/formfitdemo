# Machine: Lat Pulldown

**Class:** Vertical cable pulldown · **Mechanic:** Linear (cable) · **Plane:** Frontal/parasagittal · **resistance_profile:** cam (no torque correction needed)

Overhead bar height (fixed) = 1940 mm at grip, from floor (field-measured 2026-08: floor to the bar's bottom edge, was assumed 1650mm — a 290mm discrepancy).

## Axis A — Thigh pad height (Capping)

Locks the pelvis so the lat pulls the trunk, not the pelvis toward the bar.

| Field | Value |
|---|---|
| total_holes | 5 |
| step_mm | 35 |
| direction | Direct (1 = lowest / small legs, 5 = highest / large legs) |
| α | 90° |
| P₀ (n=1) | 110 |
| Δ | +35 |
| reach_mm | [110, 250] |
| axis_type | Capping |
| σ | tighter clamp (pad down onto thigh) |
| β | 4° |

**Rule:** height driven by seated leg geometry (F + Ti) so the top of the thighs is secured with the foot flat.

**Known discrepancy, fix pending (field audit 2026-08):** on-site measurement came back as **6 holes, 50mm step, [530, 780]mm reach — measured from the floor**, not the 5-hole/35mm/[110,250]mm table above. The table above is confirmed stale but **not yet updated** in code or here: the formula this axis feeds expects a "from seat" reference (pad height above the seat pan), and the seat itself doesn't move on this machine — one more measurement (seat height off the floor, a single fixed number) is needed to convert the raw from-floor field numbers into the frame this axis expects. Blocked on that one measurement, not on measurement quality — the on-site numbers themselves were confirmed clean.

## Axis B — Overhead bar — FIXED at 1940 mm

No seat/vertical adjust on this class. Arm-length feasibility is a **fixed constraint**, not a solvable axis.

**Engine action:** flag CLAMPED/NO_SOLUTION when seated reach to the bar forces shoulder over-elevation (very long arms) or fails to load full ROM (very short arms). Longer arm/torso combination → engine notes bar effectively lower relative to reach; shorter → bar effectively higher.

**Anatomical target rule (always enforced, not a tunable axis):** elbow finishes slightly anterior to the frontal plane, bar to upper chest, never behind the neck. If setup would force the bar behind the head, flag — load shifts to anterior capsule/rotator cuff.

## Injury modifiers (from `../constants.md`)

| Zone | Axis | Instrument |
|---|---|---|
| Shoulder | ROM only (bar fixed) | Restriction flag: front-to-chest pull path only, no full overhead reach |
| Lumbar | Thigh pad | m_β 0.60 · **hard-enforce σ** (tight clamp) + overhead-extension flag |

Note the lumbar case: unlike most instruments, this does not merely narrow tolerance — it makes the already-safe direction (tight clamp) mandatory, because a loose pad lets the lumbar spine extend under the pull.

## Not applicable here

Bilateral asymmetry: single shared thigh pad; if F/Ti differ L/R materially, apply the minimax-midpoint rule from `../02_anthropometry.md` (congruence-like clamp — treat as congruence for this purpose since it's a physical lock, not a capping stop). Coupling Envelope: not a leg-drive closed chain. Resistive Moment: cam profile, no correction.
