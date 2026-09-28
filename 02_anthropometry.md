# 02 — Anthropometry, Bilateral Asymmetry & Confidence

## The seven inputs

| Symbol | Parameter | Governs | Never used as |
|---|---|---|---|
| H | Total Height | Calibration/sanity bound only | A direct machine input |
| T | Sitting height (torso) | Seat height on all seated push/pull machines | — |
| F | Femur length | Knee-machine backrest depth; leg-press carriage; hip lever in Section 7/9 | — |
| Ti | Tibia length | Knee-machine pad position; leg-press carriage; knee lever in Section 7/9 | — |
| A | Arm length | Handle/pad start depth (push), start reach (pull) | — |
| BAW | Biacromial width | Grip/handle width, lateral pad spacing | — |
| Cd | Chest depth | Horizontal start position on chest machines | — |

**Per-side capture.** F, Ti, and A are captured **per side** (F_L/F_R, Ti_L/Ti_R, A_L/A_R). BAW and Cd are midline measures and stay single-valued. If the scanner cannot separate sides, flag the segment single-sided with reduced confidence (see confidence layer below) rather than silently symmetrising.

**Arm decomposition** (only if A is captured as one segment, not humerus+forearm separately): humerus ≈ 0.52·A, forearm+hand ≈ 0.48·A (see `constants.md`). Effective reach at elbow angle θ_e via law of cosines:

```
R(θ_e) = √( L_h² + L_f² − 2·L_h·L_f·cos θ_e )
```

## Bilateral asymmetry — resolving one shared axis for two limbs

Most machines have one shared coordinate for both legs/arms (one carriage, one seat depth, one seat height). The resolution rule depends on axis type, and is deliberately different for each:

- **Congruence axes → minimax midpoint.** `Coord = (Coord_L + Coord_R) / 2`. Each limb absorbs half the asymmetry as offset. This is the least-worst placement — it minimises the largest single-side congruence error. Not population averaging: this resolves one individual's own two-sided constraint on an axis that cannot physically split. Surface the half-offset; if it exceeds the axis tolerance, raise an asymmetry flag and recommend a unilateral/independently-adjustable substitute.
- **Capping axes → the tighter side governs.** Safety never splits. The side that reaches its safe edge first sets the coordinate for both sides; the other side sits further inside its own safe window.
- **Independent left/right hardware** (dual shin pad, independent handles): resolve each side on its own inputs, no special handling needed.

**Escalation:** left/right difference on a shared congruence axis exceeding twice the axis tolerance → machine flagged poorly suited to that body, unilateral/independent substitute offered (same gate pattern as injury and coupling mechanisms).

---

## Confidence layer (Section 8) — MVP scope

**MVP constraint: 100% software, no manual re-measurement flow.** There is exactly one provenance — `scanned` — with fixed σ per segment from `constants.md`. The engine computes and displays a confidence tag on every resolved axis; it never prompts the user to go get a tape measure.

### Propagating scan error into a machine coordinate

For a resolved coordinate C = f(segments):

```
σ_C = √( Σᵢ ( ∂C/∂Xᵢ )² · σ_{Xᵢ}² )
```

Two worked forms used repeatedly across machine files:

- **Single-segment axis** (e.g. seat height `Seat = Y_machine − k_sh·T`): `σ_Seat = k_sh · σ_T`.
- **Two-segment axis** (e.g. Leg Press carriage `D = √(F² + Ti² + F·Ti)`): `∂D/∂F = (2F+Ti)/2D`, `∂D/∂Ti = (2Ti+F)/2D`, then combine per the general formula above.

### Confidence tag

```
Margin M = distance from resolved coordinate to nearest decision boundary
           (congruence axes: the midpoint with the neighbouring hole — the
            decision scan error can flip is WHICH pin; revised 2026-09-28,
            previously the edge of the axis's reach)
r = M / σ_C
```

| r | Tag | Engine behaviour |
|---|---|---|
| ≥ 3 | HIGH | State the verdict plainly |
| 1 – 3 | MEDIUM | State it, mark provisional |
| < 1 | LOW | Capping axes: do not state a confident IN_RANGE/CLAMPED; resolve to the safe edge σ. Congruence axes (no safe edge): keep the nearest pin; offer the neighbouring pin as an alternative, with a physical check, only on a near-tie (target within 10% of a step of the midpoint) — offering two pins every time LOW fires reads as the product being unsure. Both: surface LOW with the dominant contributing segment named |

**Two hard rules:**
1. Uncertainty always resolves toward the safe side, never toward more range.
2. **NO_SOLUTION is confidence-immune.** If the coordinate still fails to fit even shifted by +3σ toward fitting, NO_SOLUTION stands at HIGH confidence regardless of r.

### Output contract addition

Every axis resolution is now the pair **(state, confidence)**, where state ∈ {IN_RANGE, CLAMPED_LOW, CLAMPED_HIGH, NO_SOLUTION [+ _BY_COUPLING variants from Section 7]} and confidence ∈ {HIGH, MEDIUM, LOW}. LOW confidence additionally names the dominant σ contributor, purely for user-facing transparency — MVP takes no re-measurement action on it.
