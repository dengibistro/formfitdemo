"""Core biomechanics math library.

Pure functions only, strictly scoped to what `01_axioms_and_conventions.md`
and `02_anthropometry.md` define generically:

1. Vector & Coordinate Space Engine — the α (rail inclination) convention:
   unit travel vector and vertical/horizontal displacement.
2. Hole Grounding Logic — the linear-to-discrete index rounding algorithm
   that maps a continuous required coordinate onto a machine's physical
   holes/pins, per the two rounding rules in 01's axis-type table
   (congruence: nearest node; capping: toward the safe edge).

No injury overlays, no Coupling Index, no per-machine formulas (seat-height
rule, leg-press carriage law of cosines, etc.) — those consume this module
but live elsewhere.
"""

import math
from dataclasses import dataclass
from typing import Literal

from models import AxisType, FeasibilityState, MachineAxis

# ---------------------------------------------------------------------------
# Vector & Coordinate Space Engine — 01_axioms_and_conventions.md, "The α convention"
# ---------------------------------------------------------------------------


def unit_travel_vector(alpha_deg: float) -> tuple[float, float]:
    """u = (cos α, sin α) — unit travel vector, (horizontal x, vertical y).

    α is measured from the horizontal: 0° = horizontal rail, 90° = vertical
    post, diagonal between.
    """
    alpha_rad = math.radians(alpha_deg)
    return (math.cos(alpha_rad), math.sin(alpha_rad))


def vertical_delta(pitch_mm: float, alpha_deg: float) -> float:
    """Δ_vertical = pitch · sin α."""
    return pitch_mm * math.sin(math.radians(alpha_deg))


def horizontal_delta(pitch_mm: float, alpha_deg: float) -> float:
    """Δ_horizontal = pitch · cos α."""
    return pitch_mm * math.cos(math.radians(alpha_deg))


@dataclass(frozen=True)
class RailDisplacement:
    """Vertical/horizontal components of one `pitch_mm` step along a rail at α."""

    vertical_mm: float
    horizontal_mm: float
    unit: tuple[float, float]


def resolve_rail_displacement(pitch_mm: float, alpha_deg: float) -> RailDisplacement:
    """Resolve one step of `pitch_mm` along a rail inclined at `alpha_deg` into
    its vertical/horizontal components and unit travel vector."""
    return RailDisplacement(
        vertical_mm=vertical_delta(pitch_mm, alpha_deg),
        horizontal_mm=horizontal_delta(pitch_mm, alpha_deg),
        unit=unit_travel_vector(alpha_deg),
    )


def axis_step_displacement(axis: MachineAxis) -> RailDisplacement:
    """`resolve_rail_displacement` for one hole-to-hole step of a Passport axis
    (pitch = axis.delta_mm, signed per its Direct/Inverted scale direction)."""
    return resolve_rail_displacement(pitch_mm=axis.delta_mm, alpha_deg=axis.alpha_deg)


# ---------------------------------------------------------------------------
# Hole Grounding Logic — 01_axioms_and_conventions.md, "Scale mapping" + "Axis types"
# ---------------------------------------------------------------------------


def node_position(axis: MachineAxis, n: int) -> float:
    """P(n) = P0 + (n-1)·Δ — the scale-mapping formula for hole index `n`."""
    return axis.p0_mm + (n - 1) * axis.delta_mm


def _raw_index(axis: MachineAxis, coordinate_mm: float) -> float:
    """Inverse of `node_position`: the real-valued (unrounded, unclamped) hole
    index that would exactly place the axis at `coordinate_mm`."""
    return (coordinate_mm - axis.p0_mm) / axis.delta_mm + 1


def _round_half_away_from_zero(x: float) -> int:
    return math.floor(x + 0.5) if x >= 0 else math.ceil(x - 0.5)


def _clamp_and_classify(axis: MachineAxis, n: int) -> tuple[int, FeasibilityState]:
    """Clamp a hole index to [1, total_holes]. `CLAMPED_LOW`/`CLAMPED_HIGH` refer
    to the physical reach bound that ends up occupied (`reach_min_mm` vs
    `reach_max_mm`), not the index bound — on an Inverted axis n=1 is the
    *high* physical coordinate, so index and physical direction disagree."""
    if 1 <= n <= axis.total_holes:
        return n, FeasibilityState.IN_RANGE
    clamped_n = 1 if n < 1 else axis.total_holes
    achieved = node_position(axis, clamped_n)
    state = (
        FeasibilityState.CLAMPED_LOW
        if math.isclose(achieved, axis.reach_min_mm, abs_tol=1e-6)
        else FeasibilityState.CLAMPED_HIGH
    )
    return clamped_n, state


@dataclass(frozen=True)
class HoleGroundingResult:
    """Result of mapping one continuous target coordinate onto a discrete hole."""

    index: int
    achieved_coordinate_mm: float
    residual_mm: float  # achieved - target; sign shows which side it landed on
    state: FeasibilityState
    exceeds_half_step: bool | None = None  # congruence axes only


def ground_to_nearest_hole(axis: MachineAxis, target_coordinate_mm: float) -> HoleGroundingResult:
    """Congruence-axis rounding: nearest node, flagged if the residual exceeds
    half a step (01, Axis types — "Rounding: Nearest node; flag if residual
    > half a step")."""
    if axis.axis_type is not AxisType.CONGRUENCE:
        raise ValueError(
            "ground_to_nearest_hole is for congruence axes only; "
            "use ground_toward_safe_edge for capping axes"
        )
    n_clamped, state = _clamp_and_classify(axis, _round_half_away_from_zero(_raw_index(axis, target_coordinate_mm)))
    achieved = node_position(axis, n_clamped)
    residual = achieved - target_coordinate_mm
    half_step = abs(axis.delta_mm) / 2
    return HoleGroundingResult(
        index=n_clamped,
        achieved_coordinate_mm=achieved,
        residual_mm=residual,
        state=state,
        exceeds_half_step=abs(residual) > half_step,
    )


def _index_at_or_below(axis: MachineAxis, coordinate_mm: float) -> int:
    """Nearest hole index whose achieved coordinate is <= `coordinate_mm`."""
    n_raw = _raw_index(axis, coordinate_mm)
    return math.floor(n_raw) if axis.delta_mm > 0 else math.ceil(n_raw)


def _index_at_or_above(axis: MachineAxis, coordinate_mm: float) -> int:
    """Nearest hole index whose achieved coordinate is >= `coordinate_mm`."""
    n_raw = _raw_index(axis, coordinate_mm)
    return math.ceil(n_raw) if axis.delta_mm > 0 else math.floor(n_raw)


def ground_toward_safe_edge(
    axis: MachineAxis,
    target_coordinate_mm: float,
    safe_direction: Literal["lower", "higher"],
) -> HoleGroundingResult:
    """Capping-axis rounding: always resolve toward the safe edge σ, never
    toward more range (01, Axis types; 02, "Uncertainty always resolves
    toward the safe side, never toward more range").

    `safe_direction` says whether a lower or higher physical coordinate (mm)
    is the safe side for this specific requirement. Translating a Passport
    axis's free-text σ (e.g. "shallower start", "larger D") into "lower"/
    "higher" is machine-specific and is the caller's job, not this function's.
    """
    if axis.axis_type is not AxisType.CAPPING:
        raise ValueError(
            "ground_toward_safe_edge is for capping axes only; "
            "use ground_to_nearest_hole for congruence axes"
        )
    n_raw_index = (
        _index_at_or_below(axis, target_coordinate_mm)
        if safe_direction == "lower"
        else _index_at_or_above(axis, target_coordinate_mm)
    )
    n_clamped, state = _clamp_and_classify(axis, n_raw_index)
    achieved = node_position(axis, n_clamped)
    residual = achieved - target_coordinate_mm
    return HoleGroundingResult(
        index=n_clamped,
        achieved_coordinate_mm=achieved,
        residual_mm=residual,
        state=state,
    )


def ground_to_hole(
    axis: MachineAxis,
    target_coordinate_mm: float,
    safe_direction: Literal["lower", "higher"] | None = None,
) -> HoleGroundingResult:
    """Dispatch to the rounding rule appropriate for `axis.axis_type`."""
    if axis.axis_type is AxisType.CONGRUENCE:
        return ground_to_nearest_hole(axis, target_coordinate_mm)
    if safe_direction is None:
        raise ValueError("capping axes require an explicit safe_direction ('lower' or 'higher')")
    return ground_toward_safe_edge(axis, target_coordinate_mm, safe_direction=safe_direction)


def margin_to_reach_boundary(axis: MachineAxis, target_coordinate_mm: float) -> float:
    """M — distance from a continuous target coordinate to the nearer edge of
    the axis's reach, the "decision boundary" a confidence margin is measured
    against (02_anthropometry.md, "Confidence tag": `r = M / σ_C`).

    Always non-negative and symmetric about the reach interval: a target far
    outside reach (confidently CLAMPED) has as large a margin as one far
    inside it (confidently IN_RANGE) — only a target near either edge is
    genuinely uncertain.
    """
    return min(abs(target_coordinate_mm - axis.reach_min_mm), abs(target_coordinate_mm - axis.reach_max_mm))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from models import CouplingFlag, ScaleDirection

    # --- Vector & Coordinate Space Engine ---
    u0 = unit_travel_vector(0)
    u90 = unit_travel_vector(90)
    u45 = unit_travel_vector(45)
    assert math.isclose(u0[0], 1.0, abs_tol=1e-9) and math.isclose(u0[1], 0.0, abs_tol=1e-9)
    assert math.isclose(u90[0], 0.0, abs_tol=1e-9) and math.isclose(u90[1], 1.0, abs_tol=1e-9)
    assert math.isclose(u45[0], u45[1], abs_tol=1e-9)

    horizontal_rail = resolve_rail_displacement(pitch_mm=30, alpha_deg=0)
    assert math.isclose(horizontal_rail.vertical_mm, 0.0, abs_tol=1e-9)
    assert math.isclose(horizontal_rail.horizontal_mm, 30.0, abs_tol=1e-9)

    vertical_post = resolve_rail_displacement(pitch_mm=30, alpha_deg=90)
    assert math.isclose(vertical_post.vertical_mm, 30.0, abs_tol=1e-9)
    assert math.isclose(vertical_post.horizontal_mm, 0.0, abs_tol=1e-9)

    leg_press_45 = resolve_rail_displacement(pitch_mm=40, alpha_deg=45)
    assert math.isclose(leg_press_45.vertical_mm, leg_press_45.horizontal_mm, rel_tol=1e-9)
    print("Vector & Coordinate Space Engine: OK")
    print(f"  u(0)={u0}  u(45)={u45}  u(90)={u90}")
    print(f"  45° step of 40mm -> vertical={leg_press_45.vertical_mm:.2f}  horizontal={leg_press_45.horizontal_mm:.2f}")

    # --- Hole Grounding Logic ---
    # Chest Press Axis A — Seat height (Congruence, Inverted, from constants.md)
    seat_axis = MachineAxis(
        name="Seat height",
        axis_type=AxisType.CONGRUENCE,
        total_holes=7,
        direction=ScaleDirection.INVERTED,
        alpha_deg=90,
        p0_mm=610,
        delta_mm=-30,
        reach_min_mm=430,
        reach_max_mm=610,
        coupling=CouplingFlag.INDEPENDENT,
    )
    assert math.isclose(node_position(seat_axis, 1), 610)
    assert math.isclose(node_position(seat_axis, 7), 430)

    # Exact node: T implies Seat = 520 -> should land exactly on hole 4, zero residual
    exact = ground_to_nearest_hole(seat_axis, target_coordinate_mm=520)
    assert exact.index == 4 and math.isclose(exact.achieved_coordinate_mm, 520)
    assert exact.state is FeasibilityState.IN_RANGE and exact.exceeds_half_step is False

    # Off-node target within reach: nearest-node rounding
    near = ground_to_nearest_hole(seat_axis, target_coordinate_mm=515)  # 5mm off hole 4 (520)
    assert near.index == 4
    assert math.isclose(near.residual_mm, 5.0)
    assert near.exceeds_half_step is False

    # Out of reach (too tall a torso): clamps to shortest-seat hole (n=7, lowest coordinate)
    too_low = ground_to_nearest_hole(seat_axis, target_coordinate_mm=300)
    assert too_low.index == 7 and too_low.state is FeasibilityState.CLAMPED_LOW
    print("Hole grounding (congruence, nearest-node): OK")

    # Chest Press Axis B — Handle start depth (Capping, Direct, safe = shallower = lower mm)
    depth_axis = MachineAxis(
        name="Handle start depth",
        axis_type=AxisType.CAPPING,
        total_holes=4,
        direction=ScaleDirection.DIRECT,
        alpha_deg=0,
        p0_mm=120,
        delta_mm=25,
        reach_min_mm=120,
        reach_max_mm=195,
        safe_direction="shallower start",
        beta_deg=5,
    )
    assert math.isclose(node_position(depth_axis, 1), 120)
    assert math.isclose(node_position(depth_axis, 4), 195)

    # Ideal depth 150mm, shallower (lower mm) is safe -> must not overshoot deeper than 150
    safe = ground_toward_safe_edge(depth_axis, target_coordinate_mm=150, safe_direction="lower")
    assert safe.achieved_coordinate_mm <= 150
    assert safe.index == 2  # holes: 120, 145, 170, 195 -> 145 is the deepest hole still <= 150

    # Same ideal depth, if deeper were the safe side instead
    other_safe = ground_toward_safe_edge(depth_axis, target_coordinate_mm=150, safe_direction="higher")
    assert other_safe.achieved_coordinate_mm >= 150
    assert other_safe.index == 3  # 170 is the shallowest hole still >= 150

    # Out of reach beyond the deepest hole -> clamps to n=4 (index-space high)
    deep_overshoot = ground_toward_safe_edge(depth_axis, target_coordinate_mm=250, safe_direction="lower")
    assert deep_overshoot.index == 4 and deep_overshoot.state is FeasibilityState.CLAMPED_HIGH
    print("Hole grounding (capping, safe-edge): OK")

    # ground_to_hole dispatch + guard rails
    dispatched = ground_to_hole(seat_axis, 520)
    assert dispatched == exact
    try:
        ground_to_hole(depth_axis, 150)  # missing safe_direction on a capping axis
        raise AssertionError("expected ValueError for missing safe_direction")
    except ValueError:
        pass
    try:
        ground_toward_safe_edge(seat_axis, 520, safe_direction="lower")  # wrong axis type
        raise AssertionError("expected ValueError for congruence axis")
    except ValueError:
        pass
    print("Dispatch + guard rails: OK")

    print("\nAll biomechanics.py smoke tests passed.")
