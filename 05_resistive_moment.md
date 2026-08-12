# 05 — Resistive Moment Model (Generic)

Governs how much joint torque the user actually receives at a given stack setting — a dimension separate from positioning (Sections 1–4/01–04 position the body; this file loads it). MVP: all `resistance_profile` and `m_τ` values are hardcoded baselines from `constants.md`, not measured hardware.

## Three regimes (Passport field: `resistance_profile`)

| Profile | Behaviour | Engine action |
|---|---|---|
| **cam** | True cam shaped to deliver a target torque profile about the machine axis; when the joint axis is aligned to it (congruence rule), joint torque is largely limb-independent | **Do not correct.** The manufacturer already normalised it. |
| **lever** | Plate hangs at a fixed radius; pad is the lever, effective moment arm ≈ `Ti − δ` (or equivalent segment) | Treat as limb-dependent, same as linear |
| **linear** | Sled machines (Leg Press, Hack Squat); no cam normalises anything | Strongly limb- and angle-dependent; largest effect |

Each machine's assigned profile: `constants.md`.

## Linear/lever moment formula

For a 45° sled, force acts along the rail; moment at each joint is force × perpendicular distance from the joint axis to the force line:

```
τ_knee = F_sled · Ti · sin(η_Ti)
τ_hip  = F_sled · F  · sin(η_F)
```

η_Ti, η_F = angle each segment makes with the rail at the position in question (varies through the stroke — peak knee and peak hip torque occur at different points, individual to the user's segments). Two consequences: joint torque scales with segment length (longer lever → more torque at the same external load), and it varies through range in a way that depends on the individual.

## What the product does with it — MVP scope

Three possible uses; only one is required for MVP.

| Use | Scope | MVP status |
|---|---|---|
| (a) Report effective load | Surface the joint moment a user's geometry produces at a given stack setting — pure transparency, no auto-adjustment | **In scope** — cheap, honest, ships with MVP |
| (b) Normalise prescription | Recommend per-user stack setting targeting equivalent joint moment across users | Out of scope — needs a strength/capacity model |
| (c) Cap load for injury safety | Convert an injury's moment ceiling into a max safe stack weight, per user | **In scope** — required, see below |

## Torque ceiling (required — closes the Section 3/06 gap)

Section 3/06 (Injury Overlay) constrains injured joints by **angle**. A rehabilitating joint also needs a **moment** ceiling — angle alone doesn't provide it, since a longer lever reaches any given torque at a lower stack weight.

```
W_max = m_τ / ( lever · sin η )_peak
```

`m_τ`: `constants.md`, Tier-3 baseline (≈ 0.65 × unconstrained peak moment at the joint's current tier). Same tier bands and temporal model as `03_injury_mechanism.md` — relaxes on logged progress, re-tightens instantly on pain flag. Stacks with the angle cap; does not replace it. Two users with the identical knee injury correctly get different W_max if their tibia lengths differ — same injury, different lever, different safe weight.
