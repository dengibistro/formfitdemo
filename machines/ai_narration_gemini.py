"""AI narration layer — Gemini backend (free-tier alternative to ai_narration.py).

Same responsibility and hard boundary as `ai_narration.py` (narrate
`ExplanationFacts` in a warm trainer voice, never invent biomechanics) —
kept as a fully separate module rather than branching provider logic inside
`ai_narration.py`, so the two SDKs never mix in one file. Shared prompt/
formatting lives in `machines/narration_common.py` so both backends narrate
identically. Use this one for free-tier testing; `ai_narration.py` stays the
Claude path for anything beyond that.

Gemini's Interactions API (confirmed against the installed `google-genai`
2.10.0 SDK, not just recalled from training — this surface is newer than
the older `generate_content`/`chats.create` pattern) is server-stateful:
the SERVER holds conversation history via `previous_interaction_id`
chaining. So the only thing this module needs to persist per user is the
last interaction ID — stored in `storage.py` (Supabase), not an in-process
dict, so it survives a server restart — unlike `ai_narration.py`'s Claude
session, which must resend the full message list every call anyway.

Setup:
1. Get a free API key at aistudio.google.com (no card required) — "Get API
   key" -> "Create API key".
2. Put it in your OWN shell's environment, never in a chat message or a
   file that could be committed: `export GEMINI_API_KEY="..."`.
3. `pip install -U google-genai` (already done in this environment).

Run as `python3 -m machines.ai_narration_gemini` from the `formfit_spec/`
directory (requires `GEMINI_API_KEY` — free tier, but still a real network
call to Google).
"""

import concurrent.futures
import os

from google import genai

import storage
from machines.coaching import Coaching
from machines.explanations import ExplanationFacts
from machines.narration_common import SYSTEM_PROMPT, setup_context_message, strip_dashes

# Set GEMINI_MODEL in Render's environment to switch models without a deploy.
#
# REVISED 2026-09-28: was "gemini-3-flash-preview". Preview models get
# retired with little warning, and a real user hit minutes of hangs and
# errors on it. Google's forum reply to people whose pipelines broke on that
# preview recommends the GA models instead (gemini-3.5-flash, or
# gemini-3.1-flash-lite for cheaper; gemini-3.8-flash is the newest GA Flash
# as of 2026-09). Defaulting to a GA model, not a preview.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
# Older history, 2026-07-09: "gemini-2.5-flash" was retired from the Interactions
# API specifically (still listed by client.models.list(), but
# interactions.create() rejected it with "no longer available"). Verified
# gemini-2.5-flash-lite and gemini-3-flash-preview both worked via a direct
# interactions.create() call — but flash-lite then failed with the exact
# same "no longer available" error on the very next real test, minutes
# later, with no code change in between. That's not a real deprecation on
# that timescale — it points to the Interactions API itself (confirmed
# brand-new/beta per this file's own earlier docstring) being unstable
# about which models it'll accept from one call to the next, not a stable
# guarantee either candidate keeps working. Switched to gemini-3-flash-preview
# as the next thing to verify; if THIS also flakes, the real fix is
# probably moving off the Interactions API to the standard generate_content/
# chats.create surface (see ai_narration.py's Claude backend for the
# equivalent stable pattern), not chasing model names further.

# Hard cap on one Gemini call, enforced here rather than through the SDK:
# google-genai's own timeout option is unreliable (googleapis/python-genai#911,
# it can hand timeout=None to httpx whatever you configure), and its automatic
# retries (up to 4, backing off up to 60s) can stretch a stuck call to minutes.
# A real user sat on a spinner for ~5 minutes before a raw "Internal Server
# Error" came back (2026-09-28).
GEMINI_TIMEOUT_SECONDS = 20


class GeminiUnavailableError(Exception):
    """The Gemini call timed out or failed. The message is safe to show to
    the user; api.py turns it into a 503 the chat already knows how to
    display, instead of a raw 500 the frontend can't parse."""


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Lazily constructed so importing this module never requires an API key
    — only actually calling it does. Reads GEMINI_API_KEY/GOOGLE_API_KEY
    from the environment automatically."""
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def _call_gemini(user_id: str, user_text: str) -> str:
    # previous_interaction_id is typed `str`, not `str | None` — omit it
    # entirely on the first turn rather than passing None.
    last_interaction_id = storage.get_last_interaction_id(user_id)
    chain_kwargs = {}
    if last_interaction_id is not None:
        chain_kwargs["previous_interaction_id"] = last_interaction_id

    def _create():
        interaction = _get_client().interactions.create(
            model=MODEL,
            input=user_text,
            system_instruction=SYSTEM_PROMPT,
            **chain_kwargs,
        )
        if interaction.status != "completed":
            raise RuntimeError(f"Gemini interaction did not complete: status={interaction.status!r}")
        return interaction

    # The call runs in its own thread so the wait can be bounded. On timeout
    # the thread is abandoned, not killed (Python can't), and finishes in the
    # background; shutdown(wait=False) keeps us from blocking on it.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_create)
        try:
            interaction = future.result(timeout=GEMINI_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError as e:
            raise GeminiUnavailableError(
                "The AI trainer is taking too long to answer. Try again in a minute."
            ) from e
        except Exception as e:
            raise GeminiUnavailableError("Couldn't reach the AI trainer right now. Try again in a minute.") from e
    finally:
        pool.shutdown(wait=False)

    storage.set_last_interaction_id(user_id, interaction.id)
    return strip_dashes(interaction.output_text or "")


def narrate_setup(
    user_id: str,
    facts: list[ExplanationFacts],
    just_finished_machine: str | None = None,
    coaching: Coaching | None = None,
) -> str:
    """Narrate one or more axis results for a machine setup, continuing the
    ongoing conversation with this user. `coaching` is the approved
    tips/avoids the reply's TIPS/AVOID must rephrase."""
    return _call_gemini(user_id, setup_context_message(facts, just_finished_machine, coaching))


def chat(user_id: str, user_message: str) -> str:
    """Free-form follow-up question, in the same ongoing conversation."""
    return _call_gemini(user_id, user_message)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from datetime import date

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        raise SystemExit(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. Get a free key at "
            "aistudio.google.com, export it in your OWN shell, then re-run."
        )
    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")):
        raise SystemExit(
            "SUPABASE_URL/SUPABASE_KEY are not set — narrate_setup()/chat() now persist the "
            "interaction pointer via storage.py. Export both in your OWN shell, then re-run."
        )

    from machines.chest_press import resolve_chest_press
    from machines.explanations import build_explanation_facts
    from machines.leg_extension import resolve_leg_extension
    from machines.leg_press import CouplingConstants, LegPressFrameConstants, resolve_leg_press
    from models import AnthropometryProfile, BilateralSegment, InjuryConstraint, InjuryJoint, InjuryProvenance, InjuryTier

    def _print(label: str, reply: str) -> None:
        print(f"=== {label} ===")
        print(reply)
        print()
        assert len(reply) > 0
        assert "CLAMPED_" not in reply.upper() and "CAUSING_SEGMENT" not in reply.upper()

    petite_user = AnthropometryProfile(
        user_id="petite_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=1550,
        sitting_height_T_mm=780,
        femur=BilateralSegment(left_mm=380, right_mm=378),
        tibia=BilateralSegment(left_mm=350, right_mm=352),
        arm=BilateralSegment(left_mm=520, right_mm=515),
        biacromial_width_BAW_mm=340,
        chest_depth_Cd_mm=195,
    )
    basketball_player = AnthropometryProfile(
        user_id="basketball_player",
        captured_at=date(2026, 7, 6),
        height_H_mm=2290,
        sitting_height_T_mm=1250,
        femur=BilateralSegment(left_mm=560, right_mm=558),
        tibia=BilateralSegment(left_mm=520, right_mm=522),
        arm=BilateralSegment(left_mm=750, right_mm=745),
        biacromial_width_BAW_mm=480,
        chest_depth_Cd_mm=290,
    )

    # --- Scenario 1: IN_RANGE — petite user, no injury, Leg Extension (both axes IN_RANGE) ---
    leg_ext_result = resolve_leg_extension(petite_user)
    depth_facts = build_explanation_facts(leg_ext_result.seat_depth, machine_name="Leg Extension")
    _print("Scenario 1 — IN_RANGE (Leg Extension)", narrate_setup("user_in_range", [depth_facts]))

    # --- Scenario 2: CLAMPED_HIGH — petite user + Tier-3 shoulder injury, Chest Press ---
    left_shoulder_injury = InjuryConstraint(
        constraint_id="petite-shoulder-L",
        joint=InjuryJoint.SHOULDER_L,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=15,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 5, 1),
        review_date=date(2026, 8, 1),
    )
    chest_result = resolve_chest_press(petite_user, injuries={InjuryJoint.SHOULDER_L: left_shoulder_injury})
    seat_facts = build_explanation_facts(chest_result.seat, machine_name="Chest Press")
    handle_facts = build_explanation_facts(chest_result.handle_depth, machine_name="Chest Press")
    assert chest_result.seat.state.value == "clamped_high"  # sanity-check we're actually exercising this branch

    reply_1 = narrate_setup("demo_user", [seat_facts, handle_facts])
    _print("Scenario 2 — CLAMPED_HIGH seat + CLAMPED_LOW handle depth (Chest Press, petite)", reply_1)

    # --- Scenario 3: follow-up chat in the SAME session, testing server-side memory ---
    first_interaction_id = storage.get_last_interaction_id("demo_user")
    reply_2 = chat("demo_user", "why did my seat end up so high, remind me?")
    _print("Scenario 3 — follow-up chat (same session, memory check)", reply_2)
    assert storage.get_last_interaction_id("demo_user") != first_interaction_id  # chain advanced

    # --- Scenario 4: CLAMPED_LOW — tall basketball-player profile, Chest Press seat ---
    tall_chest_result = resolve_chest_press(basketball_player)
    tall_seat_facts = build_explanation_facts(tall_chest_result.seat, machine_name="Chest Press")
    assert tall_chest_result.seat.state.value == "clamped_low"  # sanity-check we're actually exercising this branch
    reply_4 = narrate_setup("tall_user", [tall_seat_facts])
    _print("Scenario 4 — CLAMPED_LOW seat (Chest Press, tall basketball-player profile)", reply_4)

    # --- Scenario 5: Leg Press, unfeasible geometry (NO_SOLUTION_BY_COUPLING), fresh session ---
    unfeasible_user = AnthropometryProfile(
        user_id="unfeasible_user",
        captured_at=date(2026, 7, 6),
        height_H_mm=2000,
        sitting_height_T_mm=1020,
        femur=BilateralSegment(left_mm=700, right_mm=698),
        tibia=BilateralSegment(left_mm=430, right_mm=428),
        arm=BilateralSegment(left_mm=700, right_mm=695),
        biacromial_width_BAW_mm=440,
        chest_depth_Cd_mm=260,
    )
    lumbar_injury = InjuryConstraint(
        constraint_id="severe-lumbar",
        joint=InjuryJoint.LUMBAR,
        tier=InjuryTier.TIER_3,
        candidate_severity=0.9,
        applied_severity=0.9,
        functional_limit_deg=90,
        provenance=InjuryProvenance.CLINICIAN_SET,
        onset_date=date(2026, 4, 1),
        review_date=date(2026, 7, 1),
    )
    coupling = CouplingConstants(a_ham=0.1, a_fem=0.15, fatigue_reserve_deg=3.0, m_hip_tier3=0.75)
    frame = LegPressFrameConstants(recline_hip_reduction_per_step_deg=6.0)
    leg_press_result = resolve_leg_press(
        unfeasible_user, coupling, frame, theta_hip_onset_deg=115.0, theta_knee_screen_deg=70.0,
        injuries={InjuryJoint.LUMBAR: lumbar_injury},
    )
    carriage_facts = build_explanation_facts(leg_press_result.carriage_d, machine_name="Leg Press 45°")
    assert leg_press_result.carriage_d.state.value == "no_solution_by_coupling"  # sanity-check the branch

    reply_5 = narrate_setup("another_user", [carriage_facts], just_finished_machine="Seated Row")
    _print("Scenario 5 — NO_SOLUTION_BY_COUPLING (Leg Press 45°, fresh session)", reply_5)
    assert storage.get_last_interaction_id("another_user") != storage.get_last_interaction_id("demo_user")

    print("All machines/ai_narration_gemini.py smoke tests passed.")
