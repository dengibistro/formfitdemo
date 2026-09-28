"""The approved tip library (machines/coaching.py) and how replies are held to it."""

import re
from datetime import date

import pytest

from api import _MACHINE_RESOLVERS, _UNSUPPORTED_MACHINES, _extract_facts
from machines.coaching import CAP, COACHING, NO_SOLUTION_COACHING, TARGET, Coaching, machine_notes, select_coaching
from machines.narration_common import chat_message_with_notes, enforce_coaching, setup_context_message
from models import (
    AnthropometryProfile,
    BilateralSegment,
    InjuryConstraint,
    InjuryJoint,
    InjuryProvenance,
    InjuryTier,
)

LIVE_MACHINES = [slug for slug in _MACHINE_RESOLVERS if slug not in _UNSUPPORTED_MACHINES]


def _profile(height_mm: float, **overrides) -> AnthropometryProfile:
    def both(ratio: float) -> BilateralSegment:
        return BilateralSegment(left_mm=ratio * height_mm, right_mm=ratio * height_mm)

    fields = dict(
        user_id="coaching_test",
        captured_at=date(2026, 9, 28),
        height_H_mm=height_mm,
        sitting_height_T_mm=0.52 * height_mm,
        femur=both(0.245),
        tibia=both(0.246),
        arm=both(0.332),
        biacromial_width_BAW_mm=0.225 * height_mm,
        chest_depth_Cd_mm=0.135 * height_mm,
    )
    fields.update(overrides)
    return AnthropometryProfile(**fields)


def _facts(slug: str, profile: AnthropometryProfile, injuries=None):
    machine_enum, resolver = _MACHINE_RESOLVERS[slug]
    return _extract_facts(resolver(profile, injuries or {}, None), machine_enum.value)


@pytest.mark.parametrize("slug", LIVE_MACHINES)
def test_every_live_machine_has_a_library(slug):
    library = COACHING[slug]
    assert len(library.tips) >= TARGET and len(library.avoid) >= TARGET


def test_library_reads_like_a_person_wrote_it():
    everything = [NO_SOLUTION_COACHING]
    for library in COACHING.values():
        everything.append(Coaching(library.tips, library.avoid))
        everything.extend(library.situational.values())
    for coaching in everything:
        for text in (*coaching.tips, *coaching.avoid):
            assert not re.search(r"[—–]", text), text
            assert "|" not in text, text  # "|" separates items in the reply format


@pytest.mark.parametrize("slug", LIVE_MACHINES)
def test_typical_setup_gets_general_items(slug):
    coaching = select_coaching(slug, _facts(slug, _profile(1780)))
    assert coaching.tips == COACHING[slug].tips[:TARGET]
    assert coaching.avoid == COACHING[slug].avoid[:TARGET]


def test_short_torso_on_chest_press_gets_the_high_seat_items_first():
    facts = _facts("chest_press", _profile(1500))  # seat pinned at its highest
    assert any(f.verdict.value == "clamped_high" for f in facts)
    coaching = select_coaching("chest_press", facts)
    assert coaching.tips[0] == "Keep your shoulders pressed down, away from your ears"
    assert coaching.avoid[0] == "Shrugging up toward the handles"
    assert len(coaching.tips) == TARGET


def test_narrow_shoulders_on_shoulder_press_get_the_wide_grip_items():
    facts = _facts("shoulder_press", _profile(1750, biacromial_width_BAW_mm=320.0))
    coaching = select_coaching("shoulder_press", facts)
    assert "Bring your elbows slightly forward instead of straight out to the sides" in coaching.tips
    assert "Flaring your elbows straight out" in coaching.avoid
    assert len(coaching.tips) <= CAP and len(coaching.avoid) <= CAP


def test_gated_machine_gets_the_no_solution_set():
    injury = InjuryConstraint(
        constraint_id="t",
        joint=InjuryJoint.SHOULDER_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=15,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    facts = _facts("shoulder_press", _profile(1750), {InjuryJoint.SHOULDER_L: injury})
    assert select_coaching("shoulder_press", facts) == NO_SOLUTION_COACHING


APPROVED = Coaching(tips=("Tip one", "Tip two"), avoid=("Avoid one", "Avoid two"))


def test_enforce_keeps_a_good_rephrasing():
    reply = "WHY: Pin 3 lines you up.\nTIPS: First tip, reworded|Second tip, reworded\nAVOID: No one|No two"
    assert enforce_coaching(reply, APPROVED) == reply


def test_enforce_restores_approved_items_when_the_count_is_wrong():
    reply = "WHY: Pin 3 lines you up.\nTIPS: An invented extra|Tip one|Tip two\nAVOID: Avoid one"
    fixed = enforce_coaching(reply, APPROVED)
    assert fixed == "WHY: Pin 3 lines you up.\nTIPS: Tip one|Tip two\nAVOID: Avoid one|Avoid two"


def test_enforce_wraps_a_reply_that_ignored_the_format():
    fixed = enforce_coaching("Set the seat to pin 3.\nHave fun!", APPROVED)
    assert fixed == "WHY: Set the seat to pin 3. Have fun!\nTIPS: Tip one|Tip two\nAVOID: Avoid one|Avoid two"


def test_context_message_lists_the_approved_items():
    facts = _facts("chest_press", _profile(1780))
    coaching = select_coaching("chest_press", facts)
    message = setup_context_message(facts, coaching=coaching)
    assert "APPROVED TIPS" in message and "APPROVED AVOID" in message
    for i, tip in enumerate(coaching.tips, 1):
        assert f"{i}. {tip}" in message


def test_chat_gets_the_last_machines_notes():
    notes = machine_notes("pec_deck")
    message = chat_message_with_notes("how far back should I go?", notes, "Pec Deck (Chest Fly)")
    assert "Approved technique notes for Pec Deck (Chest Fly)" in message
    assert COACHING["pec_deck"].avoid[0] in message
    assert chat_message_with_notes("hi", None, None) == "hi"
