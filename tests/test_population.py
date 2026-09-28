"""Population sweep: run a range of realistic bodies through every machine the
live assistant serves, and fail when the output stops depending on the body.

Every module's own smoke test checks hand-picked edge cases (petite user,
basketball player). None of them caught that, for ordinary people, Lat
Pulldown said "doesn't fit" to almost everyone, Seated Row put everyone on
the top hole, and Pec Deck reported a clamp for every single user
(2026-09-28 review). Those are population-level failures, so this test looks
at the population.

Bodies are generated from height with standard segment proportions — the
same quantities the scanner is designed to produce (see
scan/measurements.mjs), not scan output itself.

Run: `python3 -m pytest tests/`.
"""

from datetime import date

import pytest

from api import _MACHINE_RESOLVERS, _UNSUPPORTED_MACHINES, _extract_facts
from models import AnthropometryProfile, BilateralSegment, FeasibilityState

LIVE_MACHINES = [slug for slug in _MACHINE_RESOLVERS if slug not in _UNSUPPORTED_MACHINES]

FULL_RANGE_MM = range(1550, 1951, 25)  # 155–195cm
TYPICAL_RANGE_MM = range(1700, 1851, 25)  # 170–185cm: the middle of the adult population

_CLAMPED = {FeasibilityState.CLAMPED_LOW, FeasibilityState.CLAMPED_HIGH}
_NO_SOLUTION = {FeasibilityState.NO_SOLUTION, FeasibilityState.NO_SOLUTION_BY_COUPLING}


def _profile(height_mm: float) -> AnthropometryProfile:
    """Standard adult proportions of stature (Drillis & Contini / ANSUR-style)."""

    def both(ratio: float) -> BilateralSegment:
        return BilateralSegment(left_mm=ratio * height_mm, right_mm=ratio * height_mm)

    return AnthropometryProfile(
        user_id=f"population_{height_mm}",
        captured_at=date(2026, 9, 28),
        height_H_mm=height_mm,
        sitting_height_T_mm=0.52 * height_mm,  # seat to crown
        femur=both(0.245),
        tibia=both(0.246),
        arm=both(0.332),  # shoulder -> elbow -> wrist, as the scanner sums it
        biacromial_width_BAW_mm=0.225 * height_mm,
        chest_depth_Cd_mm=0.135 * height_mm,
    )


def _facts(slug: str, height_mm: float):
    machine_enum, resolver = _MACHINE_RESOLVERS[slug]
    return _extract_facts(resolver(_profile(height_mm), {}, None), machine_enum.value)


def test_some_machines_are_live():
    assert LIVE_MACHINES, "every machine is gated — nothing left to serve"


@pytest.mark.parametrize("slug", LIVE_MACHINES)
def test_typical_bodies_fit_without_clamps(slug):
    """A healthy person of average height must get a normal setup: nothing
    "doesn't fit", nothing pinned against the frame's limit."""
    for height_mm in TYPICAL_RANGE_MM:
        for f in _facts(slug, height_mm):
            assert f.verdict not in _NO_SOLUTION, f"{slug} @ {height_mm}mm: {f.axis_name} -> {f.verdict.value}"
            assert f.verdict not in _CLAMPED, f"{slug} @ {height_mm}mm: {f.axis_name} -> {f.verdict.value}"


@pytest.mark.parametrize("slug", LIVE_MACHINES)
def test_body_driven_axes_actually_vary(slug):
    """Any adjustable axis computed from a body measurement must give
    different people different pins — a constant pin across 155–195cm means
    the formula or its constants are broken."""
    pins_by_axis: dict[str, set[int]] = {}
    for height_mm in FULL_RANGE_MM:
        for f in _facts(slug, height_mm):
            if f.achieved_pin is not None and f.causing_segment is not None:
                pins_by_axis.setdefault(f.axis_name, set()).add(f.achieved_pin)
    for axis_name, pins in pins_by_axis.items():
        assert len(pins) >= 3, f"{slug}: {axis_name} only ever gives pins {sorted(pins)} across 155–195cm"


@pytest.mark.parametrize("slug", LIVE_MACHINES)
def test_no_placeholder_axes_reach_the_user(slug):
    """Fixed hardware the engine knows nothing about must be dropped before
    it reaches the setup card or the narration."""
    for f in _facts(slug, 1750):
        assert not (f.achieved_pin is None and f.achieved_coordinate_mm is None and f.verdict is FeasibilityState.IN_RANGE)
