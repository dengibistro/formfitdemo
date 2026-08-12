# 01 — Axioms & Conventions (Engine Runtime Contract)

Read this first. It defines the vocabulary every other file assumes.

## Design axioms

**Axiom 1 — Axis congruence.** The anatomical axis of the working joint must coincide with the machine's axis of rotation (or its resultant force line). Misalignment converts intended rotation into rotation plus translation, loading passive stabilisers instead of the target muscle.

**Axiom 2 — Angle capping.** The joint must stay inside a safe angular window across the full range of motion. The window edges are anatomical, so the linear setting that enforces them scales with the individual's segments.

**Anti-averaging (non-negotiable).** Body segments are never averaged across people. Machine geometry may be approximated from industry ergonomic standards (that averaging lands on the equipment, not the body) — see `constants.md` for which numbers are of that kind. Two users at identical standing height can require opposite-direction corrections.

## Axis types

Every adjustable axis in every machine file is one of two types. This determines its rounding rule and how injury/coupling modifiers may touch it.

| | Congruence | Capping |
|---|---|---|
| Purpose | Land a joint axis on a mechanical axis | Keep a joint angle inside a safe window |
| Error shape | Symmetric — over or under both misalign equally | Asymmetric — one direction is dangerous, one is safe |
| Rounding | Nearest node; flag if residual > half a step | Toward the safe edge σ; tolerance from angular budget β |
| Injury modifiers touch it? | **Never** | Yes — m_β narrows tolerance, Δψ shifts the cap, gate excludes the machine |
| Coupling (Section 7) touch it? | No | Only Leg Press / Hack Squat carriage + recline |

## Feasibility states

Every resolved axis returns a **state**, never a silent number.

- **IN_RANGE** — resolves inside reach with residual inside tolerance.
- **CLAMPED** (± LOW/HIGH) — nearest achievable position returned; residual outside tolerance; state and resulting real-world angle both reported.
- **NO_SOLUTION** — no position on this machine achieves a safe/valid geometry; gate the machine, offer a substitute.

Extended states added by later mechanism files, always layered on top of the three above, never replacing them:
- **CLAMPED_BY_COUPLING / NO_SOLUTION_BY_COUPLING** (Section 7 — Leg Press/Hack Squat only)
- Confidence tag **(state, HIGH/MEDIUM/LOW)** attached to every state (Section 8, all machines)

## The α convention (rail inclination)

**α is measured from the horizontal.** 0° = horizontal rail, 90° = vertical post, diagonal between. This is the operative convention used by every formula in every mechanism file:

```
Δ_vertical   = pitch · sin α
Δ_horizontal = pitch · cos α
u = (cos α, sin α)      — unit travel vector, (horizontal x, vertical y)
```

A vertical seat column is α = 90° (all travel is vertical, no horizontal leak). A horizontal handle rail is α = 0°. Leg Press 45° is α = 45° (worst-case 1:1 split between vertical and horizontal, coupling coefficient cot α = 1).

## Scale mapping

Every discrete linear axis resolves through:

```
P(n) = P₀ + (n − 1)·Δ
```

**Inverted** scale: 1 = top/shortest lever, P₀ = maximum coordinate, Δ negative. **Direct** scale: 1 = bottom/shortest, P₀ = minimum, Δ positive. Each machine file states which convention its axis uses.

## Coupling flag

A machine axis is **coupled** when seat and handle/pad depth share one physical rail (no independent horizontal adjuster). Coupled axes trade vertical accuracy for horizontal leak per `cot α`; **decoupled** axes (independent horizontal adjuster) resolve with zero residual on both. Each machine file states its coupling flag per axis.

## Reading order for the rest of the spec

1. `constants.md` — every number, once.
2. `02_anthropometry.md` — the seven inputs, bilateral handling, confidence layer.
3. `03_injury_mechanism.md`, `04_coupling_mechanism.md`, `05_resistive_moment.md` — the three cross-cutting mechanisms, read once each, applied per-machine.
4. `machines/*.md` — one file per machine, read on demand when implementing that machine. Each is self-contained: it states its own axes, which mechanisms apply to it, and which constants it pulls.
