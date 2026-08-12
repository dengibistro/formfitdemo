# 04 — Coupling Envelope Mechanism (Generic)

Applies only to closed kinetic chain machines where hip and knee flex together against a fixed foot: **Leg Press 45° and Hack Squat**. Open-chain leg machines (Extension, Curl) are unaffected — their joints don't co-load the lumbopelvic region.

**Predictive, not live.** No motion tracking exists. The Coupling Index (CI) is evaluated at setup time from geometry, before the user loads the machine, not measured under load.

**Precedence.** When active, this supersedes the single-axis carriage depth cap and σ from the machine's own Passport entry — the single-axis cap sees knee depth only; CI sees the hip contribution too.

All angles are flexion angles (0° = full extension).

## Predicting the coupled state from setup

```
Knee flexion (exact):     cos θ_knee = (D² − F² − Ti²) / (2·F·Ti)
Femur interior angle:     cos φ_HF   = (F² + D² − Ti²) / (2·F·D)
Hip flexion:              θ_hip = Ω_trunk − O_HF(D, h_foot) − φ_HF(D)
```

`Ω_trunk` = trunk orientation from backrest recline setting. `O_HF(D, h_foot)` = orientation of the hip-to-foot chord, a function of sled depth and foot height on the plate — the machine-frame term, calibrated per machine (hardcoded baseline for MVP, see the machine file).

**Key mechanism for Path B (below):** raising the foot up the plate rotates the hip-to-foot chord in the direction that lowers θ_hip at a given depth.

## Coupling Index

```
CI = ( θ_hip + κ · θ_knee ) / Θ_env
```

κ from `constants.md`. Θ_env is the personal envelope constant — the coupled sum tolerated before posterior pelvic tilt begins, anchored to a functional screen: `Θ_env = θ_hip_onset + κ·θ_knee_screen`.

Evaluate CI at the terminal (deepest) position of the intended range, or its maximum if the trajectory is non-monotonic.

| CI | State |
|---|---|
| ≤ 0.90 | IN_RANGE |
| 0.90–1.00 | IN_RANGE, caution — trigger Path B proactively |
| > 1.00, remediable | CLAMPED_BY_COUPLING |
| > 1.00 at shallowest useful ROM | NO_SOLUTION_BY_COUPLING — gate, substitute |

## Modifiers on Θ_env

```
Θ_env(effective) = ( θ_hip_onset − a_ham·Ham − a_fem·max(0, F:Ti − r₀) ) · m_lumbar · m_hip · m_knee + κ·θ_knee_screen
```

| Modifier | Effect | Note |
|---|---|---|
| Hamstring tightness (Ham) | Lowers onset by a_ham·Ham | **Secondary** in closed chain — biarticular hamstring slackens at knee while lengthening at hip as both flex together, so net length change is small. Direct hip-flexion measurement outranks it. |
| Femur dominance (F:Ti) | Lowers onset above reference ratio r₀ | Long femur raises hip-flexion demand at depth and pushes knee forward |
| m_lumbar | Multiplies hip term down | This is where the Section 3/06 lumbar constraint does its real work — on the combined index, not just the single-axis depth cap |
| m_hip | Multiplies hip term down | FAIS-type impingement provoked by deep hip flexion |
| m_knee | Multiplies hip term down | Closes the gap where Section 3/06 knee constraints only touch single-axis caps — without this, a knee injury wouldn't reach the coupled envelope at all |

All modifier values: `constants.md`, Tier-3 baseline, temporal model from `03_injury_mechanism.md` applies unchanged (evidence-gated widening, instant re-narrowing on pain flag).

## Intra-set fatigue reserve

CI is static and setup-time; it cannot see the eighth repetition. Posterior tilt often appears late in a set as stabilisers fatigue. Handled two ways: (1) Θ_env carries a small fixed fatigue reserve — a few degrees held back from the screened onset; (2) any setup resolving into the caution band (CI ∈ [0.90, 1.00]) triggers a **repetition-indexed** text cue ("watch your pelvis on the final reps"), not a time-based one. Triggered by CI proximity, not issued blanket.

## Dual-vector resolution when CI > 1.0

**Path A — carriage travel restriction (cap depth).** Stop the sled before the offending depth; both angles fall together. Find D_A where CI(D_A) = 0.97. Always available. Costs ROM.

**Path B — foot-placement override (raise feet on plate).** Lowers θ_hip at a given depth via O_HF without shortening range — redistributes load, less hip-flexion share, more knee-flexion share. Preserves ROM; bounded by plate size and heel-lift risk (feet too high + long tibia → heel lifts → reintroduces lumbar flexion from the other end).

**Order:**
1. If plate allows a higher foot position without heel-lift risk (given the user's F:Ti), apply **Path B first**.
2. Apply **Path A** to cap whatever residual remains.
3. **Injury override:** if a lumbar or hip constraint (Section 3/06) is active, impose a mandatory Path A depth floor regardless of Path B — a repositioning instruction can't be trusted to hold under load near an injured spine. Path B then adds margin on top.
4. If Path B is maxed and Path A truncates ROM below a useful minimum → escalate to NO_SOLUTION_BY_COUPLING, substitute.

**Output contract:** every coupling-remediated setting returns verdict flag, which path(s) fired, resulting achievable depth/ROM, the foot-height instruction if Path B fired, and the CI it resolved to.
