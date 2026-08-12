# FormFit Biomechanical Spec — Index

**Scope of this build:** 100% software MVP. No physical measurement exists or is planned for this phase. Every numeric constant in this spec is a hardcoded, realistic baseline — see `constants.md`. Nothing here is "pending calibration"; that language has been retired. If a future phase adds real hardware measurement, only `constants.md` and the "confidence layer" provenance in `02_anthropometry.md` need to change — no mechanism file's logic changes.

## Read in this order

1. **`constants.md`** — every number used anywhere in this spec, once. If you need a value and it's not here, that's a bug in the spec, not a reason to invent one.
2. **`01_axioms_and_conventions.md`** — the vocabulary: congruence vs capping axes, the α convention, feasibility states (IN_RANGE/CLAMPED/NO_SOLUTION), scale mapping. Everything downstream assumes this.
3. **`02_anthropometry.md`** — the 7 body inputs, bilateral (left/right) handling, and the confidence layer (scan-error propagation → confidence tag on every verdict).
4. **`03_injury_mechanism.md`**, **`04_coupling_mechanism.md`**, **`05_resistive_moment.md`** — three cross-cutting mechanisms. Read each once. They define *how* injury, coupled hip/knee limits, and joint torque work in general; they do not repeat per-machine numbers (those live in `constants.md` and the machine files).
5. **`machines/*.md`** — one file per machine, read on demand when you implement that machine. Each is self-contained: its own axes with full Passport data, which of the three mechanisms apply to it and how, and its own injury-modifier rows. You should be able to implement one machine module from its one file plus `constants.md`, without re-reading the mechanism files in full.

## What "self-contained" means for machine files

Every `machines/*.md` file states explicitly, even when the answer is "no":
- Its Passport axes (holes, step_mm, direction, α, reach_mm, axis_type, σ)
- Which injury zones/modifiers apply to it
- Whether the Coupling Envelope (`04`) applies — only Leg Press and (future) Hack Squat
- Whether the Resistive Moment Model (`05`) requires correction — cam machines mostly don't; lever and linear machines do
- Bilateral asymmetry handling for its shared axes

This means a machine file is safe to implement in isolation. The "Not applicable here" sections exist so you don't have to guess whether an omission was intentional.

## Build order suggestion

Simplest → most cross-cutting, so later machines can reuse patterns established on earlier ones:

1. `chest_press.md`, `shoulder_press.md` — single congruence + single capping axis, establishes the basic axis-resolution pattern
2. `pec_deck.md` — same pattern, strict congruence tolerance, first lever-type resistive moment case
3. `lat_pulldown.md`, `seated_row.md` — introduces a fixed (non-adjustable) axis and its flag-only handling
4. `leg_extension.md`, `leg_curl.md` — introduces the pad-lever resistive-moment caveat on an otherwise cam machine
5. `leg_press.md` — last, because it is the only file where the Coupling Envelope and the full linear Resistive Moment Model both fire; everything built in 1–4 (axis resolution, injury modifiers, confidence tagging, bilateral handling) composes here plus the two extra mechanisms

## File list

```
formfit_spec/
├── README.md                      (this file)
├── constants.md                   single source of truth for all numbers
├── 01_axioms_and_conventions.md   engine-wide vocabulary and runtime contract
├── 02_anthropometry.md            7 inputs, bilateral asymmetry, confidence layer
├── 03_injury_mechanism.md         generic injury overlay (instruments, tiers, temporal model)
├── 04_coupling_mechanism.md       generic Coupling Index (Leg Press/Hack Squat only)
├── 05_resistive_moment.md         generic joint-torque model, 3 resistance regimes
└── machines/
    ├── chest_press.md
    ├── shoulder_press.md
    ├── pec_deck.md
    ├── lat_pulldown.md
    ├── seated_row.md
    ├── leg_extension.md
    ├── leg_curl.md
    └── leg_press.md
```

## Non-negotiable invariants (apply to every machine, every mechanism)

- Congruence axes are never touched by injury or coupling modifiers — only capping axes are.
- Every axis resolution returns a state (IN_RANGE / CLAMPED_LOW / CLAMPED_HIGH / NO_SOLUTION, or the `_BY_COUPLING` variants on Leg Press) plus a confidence tag (HIGH/MEDIUM/LOW). Never a bare number.
- Rounding on capping axes goes toward the safe edge σ; on congruence axes it goes to the nearest node with a symmetric flag.
- NO_SOLUTION is confidence-immune — low confidence never rescues a body that doesn't fit.
- Body segments are never averaged across people. Where a shared machine axis serves two limbs of one person, use the minimax-midpoint rule (congruence) or the tighter-side rule (capping) from `02_anthropometry.md` — this is resolving one individual's own two-sided geometry, not population averaging.
