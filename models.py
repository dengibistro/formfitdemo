"""FormFit data contracts.

Pydantic schemas only — Matrix machine constants (the Synthetic Equipment
Passport), the user anthropometry profile (incl. scan confidence/error
thresholds), and injury logging structures.

No trigonometry, axis resolution, coupling index, or resistive-moment math
lives here. Field-level validators are limited to structural sanity checks
(ordering, required companions) that hold regardless of any formula — see
the individual `machines/*.md` files and `04_coupling_mechanism.md` /
`05_resistive_moment.md` for the logic that will eventually consume these
models.
"""

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------

class FormFitConstant(BaseModel):
    """Immutable data pulled straight from constants.md / machines/*.md.

    Frozen: these are the single source of truth per README.md and must not
    be mutated at runtime — a new instance is the only way to change one.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class FormFitRecord(BaseModel):
    """Mutable, per-user data captured or logged at runtime (scans, injuries)."""

    model_config = ConfigDict(strict=True, extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------------------
# Vocabulary enums — 01_axioms_and_conventions.md
# ---------------------------------------------------------------------------

class AxisType(str, Enum):
    CONGRUENCE = "congruence"
    CAPPING = "capping"


class ScaleDirection(str, Enum):
    """Direct: 1 = bottom/shortest, P0 = minimum, Δ positive.
    Inverted: 1 = top/shortest lever, P0 = maximum, Δ negative."""

    DIRECT = "direct"
    INVERTED = "inverted"


class CouplingFlag(str, Enum):
    """Whether an axis shares one physical rail with another (seat/depth)."""

    COUPLED = "coupled"
    DECOUPLED = "decoupled"
    INDEPENDENT = "independent"


class ResistanceProfile(str, Enum):
    CAM = "cam"
    LEVER = "lever"
    LINEAR = "linear"


class FeasibilityState(str, Enum):
    IN_RANGE = "in_range"
    CLAMPED_LOW = "clamped_low"
    CLAMPED_HIGH = "clamped_high"
    NO_SOLUTION = "no_solution"
    CLAMPED_BY_COUPLING = "clamped_by_coupling"
    NO_SOLUTION_BY_COUPLING = "no_solution_by_coupling"


class ConfidenceTag(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class MachineName(str, Enum):
    CHEST_PRESS = "Chest Press"
    SHOULDER_PRESS = "Shoulder Press"
    PEC_DECK = "Pec Deck (Chest Fly)"  # this machine's live/computed exercise is
    # specifically Chest Fly (see pec_deck.py's `exercise_mode`) — Rear Delt
    # exists on the same physical frame but has no real formula yet (fixed
    # placeholder only, never routed to from chat), so the plain "Pec Deck"
    # name was ambiguous about which exercise was actually being set up.
    LAT_PULLDOWN = "Lat Pulldown"
    SEATED_ROW = "Seated Row"
    LEG_EXTENSION = "Leg Extension"
    SEATED_LEG_CURL = "Seated Leg Curl"
    LEG_PRESS_45 = "Leg Press 45°"


class AxisPurpose(str, Enum):
    """What a given axis exists to protect or align — one per axis, taken
    directly from that axis's own one-line description in its machines/*.md
    file (not a new biomechanical claim). Lets a future explanation/AI layer
    say *what kind of thing* was compromised on a CLAMPED/NO_SOLUTION
    result without re-deriving it from the machine's prose each time."""

    SEAT_HEIGHT_SHOULDER_ALIGNMENT = "seat_height_shoulder_alignment"  # chest/shoulder press, pec deck, seated row seat
    KNEE_AXIS_ALIGNMENT = "knee_axis_alignment"  # leg extension/curl seat depth: knee axis onto cam pivot
    SHIN_ANKLE_PAD_LEVER_ALIGNMENT = "shin_ankle_pad_lever_alignment"  # leg extension shin pad / leg curl ankle pad
    SHOULDER_HORIZONTAL_EXTENSION_CAP = "shoulder_horizontal_extension_cap"  # chest press handle depth
    SHOULDER_PRE_STRETCH_CAP = "shoulder_pre_stretch_cap"  # pec deck arm open offset
    FULL_EXTENSION_STRETCH_CAP = "full_extension_stretch_cap"  # seated row chest pad
    PELVIC_LOCK_THIGH_PAD = "pelvic_lock_thigh_pad"  # lat pulldown thigh pad: locks pelvis, not a capping stop
    THIGH_FIXATOR_LOCK = "thigh_fixator_lock"  # leg curl thigh fixator: locks femur, blocks hip substitution
    TERMINAL_ROM_LOCKOUT_STOP = "terminal_rom_lockout_stop"  # leg extension terminal ROM stop
    CARRIAGE_DEPTH_KNEE_HIP_FLEXION = "carriage_depth_knee_hip_flexion"  # leg press carriage D
    BACKREST_RECLINE_HIP_FLEXION = "backrest_recline_hip_flexion"  # leg press backrest recline
    GRIP_WIDTH_SHOULDER_ABDUCTION = "grip_width_shoulder_abduction"  # shoulder press fixed grip
    OVERHEAD_REACH_SHOULDER_ELEVATION = "overhead_reach_shoulder_elevation"  # lat pulldown fixed bar
    REAR_DELT_PRE_STRETCH_CAP = "rear_delt_pre_stretch_cap"  # pec deck rear-delt/pec-dec arm open (not yet biomechanically modeled — see pec_deck.py)


class InjuryZone(str, Enum):
    SHOULDER = "Shoulder"
    KNEE = "Knee"
    HIP = "Hip"
    LUMBAR = "Lumbar"


class InjuryJoint(str, Enum):
    """Per 03_injury_mechanism.md — InjuryConstraint profile `joint`."""

    SHOULDER_L = "shoulder_L"
    SHOULDER_R = "shoulder_R"
    KNEE_L = "knee_L"
    KNEE_R = "knee_R"
    HIP_L = "hip_L"
    HIP_R = "hip_R"
    LUMBAR = "lumbar"


class InjuryProvenance(str, Enum):
    SELF_REPORT = "self_report"
    APP_ASSESSED = "app_assessed"
    CLINICIAN_SET = "clinician_set"


class InjuryTier(int, Enum):
    TIER_1 = 1  # managed/low
    TIER_2 = 2  # sub-acute/moderate
    TIER_3 = 3  # acute/high


class ScanProvenance(str, Enum):
    """MVP has exactly one provenance — no manual re-measurement flow."""

    SCANNED = "scanned"


# ---------------------------------------------------------------------------
# Matrix machine constants — constants.md "Global coefficients"
# ---------------------------------------------------------------------------

class GlobalCoefficients(FormFitConstant):
    k_sh: float = Field(0.63, description="GH-joint height above seat ÷ sitting height")
    phi_lp_deg: float = Field(60.0, description="Target leg-press start knee flexion φ_LP")
    kappa: float = Field(0.35, description="Knee-coupling weight in the Coupling Index")
    beta_default_deg: float = Field(5.0, description="Default angular capping tolerance β")
    grip_width_ratio_min: float = Field(1.0, description="g_grip lower bound (Shoulder Press, flag-only)")
    grip_width_ratio_max: float = Field(1.5, description="g_grip upper bound (Shoulder Press, flag-only)")


class ScanErrorConstants(FormFitConstant):
    """σ per segment, mm — Section 8. Single provenance in MVP: scanned."""

    sigma_T_mm: float = Field(15.0, gt=0, description="sitting height scan noise")
    sigma_F_mm: float = Field(15.0, gt=0, description="femur scan noise")
    sigma_Ti_mm: float = Field(15.0, gt=0, description="tibia scan noise")
    sigma_A_mm: float = Field(18.0, gt=0, description="arm scan noise (compounds two sub-segments)")
    sigma_BAW_mm: float = Field(20.0, gt=0, description="biacromial width — foreshortening penalty")
    sigma_Cd_mm: float = Field(20.0, gt=0, description="chest depth — foreshortening penalty")


class ConfidenceThresholds(FormFitConstant):
    """r = M / σ_C thresholds that select the confidence tag."""

    high_min_r: float = Field(3.0, description="r ≥ this → HIGH")
    medium_min_r: float = Field(1.0, description="this ≤ r < high_min_r → MEDIUM; r below this → LOW")

    @model_validator(mode="after")
    def _ordered(self) -> "ConfidenceThresholds":
        if self.medium_min_r >= self.high_min_r:
            raise ValueError("medium_min_r must be < high_min_r")
        return self


class LimbDecomposition(FormFitConstant):
    """Used only if arm is captured as one segment (not humerus+forearm separately)."""

    humerus_share_of_A: float = Field(0.52, gt=0, lt=1)
    forearm_hand_share_of_A: float = Field(0.48, gt=0, lt=1)

    @model_validator(mode="after")
    def _shares_sum_to_one(self) -> "LimbDecomposition":
        if abs(self.humerus_share_of_A + self.forearm_hand_share_of_A - 1.0) > 1e-6:
            raise ValueError("humerus + forearm/hand shares must sum to 1.0")
        return self


class InjuryTierBand(FormFitConstant):
    tier: InjuryTier
    severity_min: float = Field(..., ge=0, le=1)
    severity_max: float = Field(..., ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "InjuryTierBand":
        if self.severity_min > self.severity_max:
            raise ValueError("severity_min must be <= severity_max")
        return self


class InjuryTierBands(FormFitConstant):
    """Section 6 — all m_β/Δψ/m_lumbar/m_hip/m_knee/m_τ figures elsewhere are Tier-3."""

    tier_1: InjuryTierBand = InjuryTierBand(tier=InjuryTier.TIER_1, severity_min=0.00, severity_max=0.30)
    tier_2: InjuryTierBand = InjuryTierBand(tier=InjuryTier.TIER_2, severity_min=0.30, severity_max=0.70)
    tier_3: InjuryTierBand = InjuryTierBand(tier=InjuryTier.TIER_3, severity_min=0.70, severity_max=1.00)


class InjuryModifier(FormFitConstant):
    """One row of "Injury modifiers by zone × machine × axis" (Tier-3 baseline)."""

    zone: InjuryZone
    machine: MachineName
    axis: str
    instrument: str = Field(..., description="e.g. 'm_β · Δθ_cap · gate'")
    m_beta: float | None = Field(None, ge=0, le=1, description="budget multiplier, narrows tolerance")
    delta_theta_cap_from_deg: float | None = Field(None, description="healthy-baseline cap")
    delta_theta_cap_to_deg: float | None = Field(None, description="Tier-3 shifted cap")
    gate_severity_threshold: float | None = Field(
        None, ge=0, le=1, description="severity s at/above which the machine gate fires"
    )
    note: str | None = Field(None, description="free-text detail that doesn't fit the numeric fields")


class CouplingIndexThresholds(FormFitConstant):
    """Section 7 CI bands."""

    in_range_max: float = Field(0.90, description="CI ≤ this → IN_RANGE")
    caution_max: float = Field(1.00, description="this ≤ CI → CLAMPED_BY_COUPLING (remediable) or NO_SOLUTION")

    @model_validator(mode="after")
    def _ordered(self) -> "CouplingIndexThresholds":
        if self.in_range_max >= self.caution_max:
            raise ValueError("in_range_max must be < caution_max")
        return self


class CouplingConstants(FormFitConstant):
    """Coupling Index constants, Section 7 (Leg Press / Hack Squat only)."""

    kappa: float = Field(0.35, description="shared with GlobalCoefficients.kappa")
    thresholds: CouplingIndexThresholds = CouplingIndexThresholds()
    a_ham: float = Field(
        ..., description="hamstring-tightness weight — illustrative low weight, value not fixed by spec"
    )
    a_fem: float = Field(
        ..., description="femur-dominance penalty above r0 — illustrative, value not fixed by spec"
    )
    r0_reference_femur_tibia_ratio: float = Field(1.09, description="reference F:Ti, petite-user profile baseline")
    fatigue_reserve_deg: float = Field(
        ..., gt=0, description="Θ_env fixed fatigue reserve — a few degrees held back from the "
        "screened θ_hip_onset; static, setup-time only, value not fixed by spec"
    )
    m_lumbar_tier3: float = Field(0.60, ge=0, le=1, description="Θ_env lumbar modifier, Tier-3 baseline")
    m_hip_tier3: float = Field(
        ..., ge=0, le=1, description="Θ_env hip modifier (FAIS-type impingement), Tier-3 baseline — value not fixed by spec"
    )
    m_knee_tier3: float = Field(
        0.70, ge=0, le=1,
        description="Θ_env knee modifier, Tier-3 baseline — closes the gap single-axis knee modifiers don't reach",
    )


class ResistiveMomentConstants(FormFitConstant):
    """Section 9 — m_τ moment ceiling coefficient."""

    m_tau_coefficient: float = Field(
        0.65, description="m_τ ≈ this × the joint's unconstrained peak moment, Tier-3 baseline"
    )


class MachineAxis(FormFitConstant):
    """One row of a machine's Synthetic Equipment Passport axis register."""

    name: str
    axis_type: AxisType
    total_holes: int = Field(..., gt=0)
    direction: ScaleDirection
    alpha_deg: float = Field(..., ge=0, le=90, description="α — rail inclination from horizontal")
    p0_mm: float = Field(..., description="P₀ — coordinate at n = 1")
    delta_mm: float = Field(..., description="Δ — signed step increment between adjacent holes")
    reach_min_mm: float = Field(..., description="lower bound of achievable coordinate")
    reach_max_mm: float = Field(..., description="upper bound of achievable coordinate")
    coupling: CouplingFlag | None = None
    safe_direction: str | None = Field(
        None, description="σ — the safe rounding direction; required on capping axes only"
    )
    beta_deg: float | None = Field(None, description="angular budget β for this axis; capping axes only")
    first_pin_label: int = Field(
        1,
        description="number printed on the machine at hole n=1 — e.g. 0 on Chest Press, whose lowest "
        "seat position is marked 0 (field-confirmed 2026-09). Every pin shown to a user goes "
        "through `biomechanics.pin_label`, never the raw hole index.",
    )

    @model_validator(mode="after")
    def _reach_is_ordered(self) -> "MachineAxis":
        if self.reach_min_mm > self.reach_max_mm:
            raise ValueError("reach_min_mm must be <= reach_max_mm")
        return self

    @model_validator(mode="after")
    def _capping_axes_declare_safe_direction(self) -> "MachineAxis":
        if self.axis_type is AxisType.CAPPING and self.safe_direction is None:
            raise ValueError("capping axes must declare a safe direction (σ)")
        if self.axis_type is AxisType.CONGRUENCE and self.safe_direction is not None:
            raise ValueError("congruence axes are symmetric and must not declare a safe direction (σ)")
        return self


class Machine(FormFitConstant):
    """A machine's Passport entry: axes, resistance profile, injury modifiers."""

    name: MachineName
    machine_class: str = Field(..., description="e.g. 'Seated horizontal press'")
    mechanic: str = Field(..., description="e.g. 'Converging'")
    plane: str = Field(..., description="e.g. 'Transverse (horizontal adduction)'")
    resistance_profile: ResistanceProfile
    axes: list[MachineAxis] = Field(..., min_length=1)
    injury_modifiers: list[InjuryModifier] = Field(default_factory=list)
    coupling_envelope_applies: bool = Field(
        False, description="only True for Leg Press 45° / Hack Squat"
    )
    notes: str | None = None


class MatrixConstants(FormFitConstant):
    """Top-level bundle — the whole of constants.md, single source of truth."""

    global_coefficients: GlobalCoefficients = GlobalCoefficients()
    scan_error: ScanErrorConstants = ScanErrorConstants()
    confidence_thresholds: ConfidenceThresholds = ConfidenceThresholds()
    limb_decomposition: LimbDecomposition = LimbDecomposition()
    injury_tier_bands: InjuryTierBands = InjuryTierBands()
    coupling: CouplingConstants
    resistive_moment: ResistiveMomentConstants = ResistiveMomentConstants()
    machines: dict[MachineName, Machine] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# User anthropometry profile — 02_anthropometry.md
# ---------------------------------------------------------------------------

class BilateralSegment(FormFitRecord):
    """A segment captured per side (F, Ti, A). Never silently symmetrised."""

    left_mm: float | None = Field(None, gt=0)
    right_mm: float | None = Field(None, gt=0)
    single_sided: bool = Field(
        False, description="True if the scanner could not separate L/R — flag reduced confidence"
    )

    @model_validator(mode="after")
    def _at_least_one_side_present(self) -> "BilateralSegment":
        if self.left_mm is None and self.right_mm is None:
            raise ValueError("at least one side must be captured")
        return self

    @model_validator(mode="after")
    def _single_sided_has_exactly_one_value(self) -> "BilateralSegment":
        if self.single_sided and self.left_mm is not None and self.right_mm is not None:
            raise ValueError("single_sided segments must not have both sides populated")
        return self


class ScanSigmaOverrides(FormFitRecord):
    """Per-scan σ (mm), computed by the scanner from how well it actually saw
    the landmarks behind each segment (scan/measurements.mjs's
    segmentConfidenceSigmaMm). Field names match ScanErrorConstants; any
    field left None falls back to that constant."""

    sigma_T_mm: float | None = Field(None, gt=0)
    sigma_F_mm: float | None = Field(None, gt=0)
    sigma_Ti_mm: float | None = Field(None, gt=0)
    sigma_A_mm: float | None = Field(None, gt=0)
    sigma_BAW_mm: float | None = Field(None, gt=0)
    sigma_Cd_mm: float | None = Field(None, gt=0)


class AnthropometryProfile(FormFitRecord):
    """The seven inputs (Section 02) plus scan provenance for one user."""

    user_id: str
    provenance: ScanProvenance = ScanProvenance.SCANNED
    captured_at: date
    scan_sigma_mm: ScanSigmaOverrides | None = Field(
        None, description="this scan's own σ per segment; None -> constants.md defaults"
    )

    height_H_mm: float = Field(
        ..., gt=0, description="Total height — calibration/sanity bound only, never a direct machine input"
    )
    sitting_height_T_mm: float = Field(..., gt=0, description="T — seat height on all seated push/pull machines")
    femur: BilateralSegment = Field(..., description="F — per-side, knee-machine backrest depth / leg-press carriage")
    tibia: BilateralSegment = Field(..., description="Ti — per-side, knee-machine pad position / leg-press carriage")
    arm: BilateralSegment = Field(..., description="A — per-side, handle/pad start depth or reach")
    biacromial_width_BAW_mm: float = Field(..., gt=0, description="BAW — midline, grip/handle width & pad spacing")
    chest_depth_Cd_mm: float = Field(..., gt=0, description="Cd — midline, horizontal start position on chest machines")


# ---------------------------------------------------------------------------
# Injury logging — 03_injury_mechanism.md
# ---------------------------------------------------------------------------

class InjuryConstraint(FormFitRecord):
    """Stored functional limit with provenance and review date — never a diagnosis.

    `candidate_severity` follows the time-based decay model; `applied_severity`
    is the evidence-gated value the engine actually uses (it can lag behind
    the candidate). The temporal update rules themselves are out of scope here.
    """

    constraint_id: str
    joint: InjuryJoint
    tier: InjuryTier
    candidate_severity: float = Field(..., ge=0, le=1, description="time-decayed severity, smooth-case path")
    applied_severity: float = Field(..., ge=0, le=1, description="evidence-gated severity actually used by the engine")
    functional_limit_deg: float = Field(
        ..., description="measured/estimated safe angle for the joint's primary motion"
    )
    provenance: InjuryProvenance
    onset_date: date
    review_date: date
    pain_free_counter: int = Field(0, ge=0, description="consecutive clean sessions since last flare")
    last_pain_report_date: date | None = Field(
        None, description="set on any pain report; snaps applied_severity back up and resets pain_free_counter"
    )

    @model_validator(mode="after")
    def _review_not_before_onset(self) -> "InjuryConstraint":
        if self.review_date < self.onset_date:
            raise ValueError("review_date cannot precede onset_date")
        return self
