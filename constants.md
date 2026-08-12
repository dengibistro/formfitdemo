# FormFit — Constants (Single Source of Truth)

**MVP scope note:** this build is 100% software, running entirely on synthetic data. Every value below is a hardcoded baseline constant — nothing here is measured on-site, nothing is pending calibration. "Illustrative" means: physically plausible, not yet validated against real hardware or clinical input, but final for MVP purposes. No other file restates these numbers; they reference this file by symbol.

---

## Global coefficients

| Symbol | Meaning | Value | Used in |
|---|---|---|---|
| k_sh | GH-joint height above seat ÷ sitting height | 0.63 | Seat height on all push/pull machines |
| θ_cap (generic) | Max horizontal shoulder extension behind frontal plane | 15–30° (per machine, see machine files) | Push block capping axes |
| φ_LP | Target leg-press start knee flexion | 60° | Leg Press carriage |
| g_grip | Grip width ÷ biacromial width | 1.0–1.5 | Shoulder Press (flag-only, grip is fixed) |
| δ (generic pad/clearance offset) | machine-specific, see machine files | — | Congruence axes |
| κ | Knee-coupling weight in the Coupling Index | 0.35 | Section 7, Leg Press / Hack Squat |
| β (default angular budget) | Default capping tolerance angle | 5° | Capping axes generally |

## Anthropometric scan-error constants (Section 8, MVP)

Single provenance in MVP: `scanned`. No manual re-measurement flow exists; these are the only σ values the engine uses.

| Segment | σ (mm) | Why |
|---|---|---|
| T (sitting height) | 15 | Standard scan noise |
| F (femur) | 15 | Standard scan noise |
| Ti (tibia) | 15 | Standard scan noise |
| A (arm) | 18 | Compounds two sub-segments if decomposed |
| BAW (biacromial width) | 20 | Measured across the body toward the camera — worse foreshortening |
| Cd (chest depth) | 20 | Same foreshortening issue as BAW |

**Confidence thresholds:** r = M/σ_C. r ≥ 3 → HIGH. 1 ≤ r < 3 → MEDIUM. r < 1 → LOW (resolve to safe edge, never emit a confident IN_RANGE/CLAMPED).

## Derived-limb decomposition (used only if arm is captured as one segment)

| Symbol | Value |
|---|---|
| Humerus share of A | 0.52 |
| Forearm+hand share of A | 0.48 |

## Injury tiers (Section 6)

| Tier | Severity s range |
|---|---|
| 3 (acute/high) | 0.70 – 1.00 |
| 2 (sub-acute/moderate) | 0.30 – 0.70 |
| 1 (managed/low) | 0.00 – 0.30 |

All m_β, Δψ, m_lumbar, m_hip, m_knee, m_τ values quoted elsewhere are **Tier-3 (worst case)** figures; scale towards 1.0 (no restriction) as tier falls, per the temporal model in `03_injury_mechanism.md`.

## Injury modifiers by zone × machine × axis (Tier 3, illustrative)

| Zone | Machine | Axis | Instrument | Value |
|---|---|---|---|---|
| Shoulder | Pec Deck | Arm open offset | m_β · Δθ_cap · gate | 0.30 · (25°→10°) · gate at s≥0.85 |
| Shoulder | Chest Press | Handle start depth | m_β · Δθ_cap | 0.50 · (25°→15°) |
| Shoulder | Seated Row | Chest pad depth | m_β | 0.70 |
| Shoulder | Shoulder Press | (whole machine) | gate at Tier 3 | reduced ROM at Tier 2 |
| Shoulder | Lat Pulldown | (ROM only, bar fixed) | ROM restriction flag | front-to-chest only |
| Knee | Leg Extension | Terminal ROM stop | m_β · remove lockout · gate | 0.40 · stop short · gate at s≥0.85 |
| Knee | Leg Press | Carriage D | m_β · φ floor · σ toward larger D | 0.50 |
| Knee | Seated Leg Curl | Curl-depth window | m_β | 0.80 |
| Knee | Leg Press (coupling) | Θ_env (Section 7) | m_knee | 0.70 |
| Hip | Leg Press | Backrest recline | m_β · bias max recline | 0.40 |
| Hip | Leg Press | Carriage D | m_β · shallower | 0.50 |
| Hip | Leg Press (coupling) | Θ_env (Section 7) | m_hip | see Section 7 default |
| Lumbar | Leg Press | Carriage D + recline | m_β · shallower + more recline | 0.40 |
| Lumbar | Lat Pulldown | Thigh pad | m_β · hard-enforce σ | 0.60 |
| Lumbar | Seated Row | Chest pad depth | protective, σ held, no relaxation | — |
| Lumbar | Shoulder Press | (whole machine) | partial gate Tier 3 | — |
| Lumbar | Leg Press (coupling) | Θ_env (Section 7) | m_lumbar | 0.60 |

## Coupling Index constants (Section 7, Leg Press / Hack Squat)

| Symbol | Value | Note |
|---|---|---|
| κ | 0.35 | shared with global table above |
| CI thresholds | ≤0.90 IN_RANGE · 0.90–1.00 caution · >1.00 CLAMPED_BY_COUPLING · >1.00 at shallowest useful ROM → NO_SOLUTION_BY_COUPLING | |
| a_ham | illustrative, low weight | hamstring tightness is secondary in closed chain |
| a_fem | illustrative | femur-dominance penalty above reference ratio r₀ |
| r₀ (reference F:Ti) | ≈ 1.09 (petite-user profile) | baseline, not a population claim — see anti-averaging proof |
| Fatigue reserve | a few degrees held back from screened θ_hip_onset | static, setup-time only |

## Resistive Moment Model constants (Section 9, MVP hardcoded)

`resistance_profile` per machine — hardcoded, not measured:

| Machine | resistance_profile |
|---|---|
| Chest Press | cam |
| Shoulder Press | cam |
| Pec Deck | lever |
| Lat Pulldown | cam |
| Seated Row | lever |
| Leg Extension | cam |
| Seated Leg Curl | cam |
| Leg Press 45° | linear |

`m_τ` (moment ceiling, Tier-3 illustrative, applies only where an injury constraint is active on a lever/linear machine): **m_τ ≈ 0.65 × the joint's unconstrained peak moment** at the same tier the angle cap uses. Same tier bands as above; same temporal model.

## Synthetic Equipment Passport — axis register

Full per-axis table (holes, step_mm, direction, α, P₀, Δ, reach_mm, axis type, σ) lives in each machine file under `machines/`, sourced originally from `FormFit_Synthetic_Equipment_Passport_MVP.md`. Not duplicated here to avoid two sources of truth for the same numbers; machine files are canonical for their own axes.
