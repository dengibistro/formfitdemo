"""AI narration layer — turns ExplanationFacts into a conversational trainer reply.

This is the layer discussed and deliberately deferred until the deterministic
facts existed: it reads `machines/explanations.py`'s `ExplanationFacts`
(structured, tone-agnostic data — verdict, causing segment, residual,
achieved pin, what the axis protects) and narrates it via the Claude API in
a warm, coach-like voice, holding an ongoing conversation with one user
across machines.

Hard boundary: this layer must not compute or reinvent biomechanics. Every
claim it makes has to trace back to a field on `ExplanationFacts` — its job
is phrasing, not reasoning about joints and angles. That split is why
`explanations.py` exists as a separate module: the facts are the source of
truth, this is just the narrator.

Explicitly out of scope for now (per project decisions):
- Tone system (bro/pro/care) — lives in a different, not-yet-built part of
  the project. This ships one neutral-but-warm default voice.
- Substitute-machine redirects — dropped; NO_SOLUTION is narrated honestly
  without inventing a specific alternative machine.
- Persistence — conversation history is in-memory only, keyed by user_id,
  scoped to this process's lifetime. No database yet (explicit MVP scope:
  prove the chat experience works before adding one).
- Voice/streaming UI — this returns plain text; a future frontend can stream
  it however it likes.

Run as `python3 -m machines.ai_narration` from the `formfit_spec/` directory
(requires `ANTHROPIC_API_KEY` in the environment — this smoke test makes
real, billed API calls).
"""

import anthropic

from machines.explanations import ExplanationFacts
from machines.narration_common import SYSTEM_PROMPT, setup_context_message

MODEL = "claude-opus-4-8"

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazily constructed so importing this module never requires an API key
    — only actually calling it does."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


class ChatSession:
    """In-memory conversation history for one user. No persistence — lives
    only for this process's lifetime (see module docstring)."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})


_SESSIONS: dict[str, ChatSession] = {}


def get_session(user_id: str) -> ChatSession:
    if user_id not in _SESSIONS:
        _SESSIONS[user_id] = ChatSession()
    return _SESSIONS[user_id]


def _call_claude(session: ChatSession) -> str:
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        # Narrating already-computed facts in a short chat reply is a short,
        # scoped, latency-sensitive task, not an intelligence-heavy one —
        # "low" effort fits per the model's own guidance. Model choice
        # itself stays Opus regardless (not a quality downgrade).
        output_config={"effort": "low"},
        messages=session.messages,
    )
    return next((block.text for block in response.content if block.type == "text"), "")


def narrate_setup(
    user_id: str,
    facts: list[ExplanationFacts],
    just_finished_machine: str | None = None,
) -> str:
    """Narrate one or more axis results for a machine setup, continuing the
    ongoing conversation with this user."""
    session = get_session(user_id)
    session.add_user(setup_context_message(facts, just_finished_machine))
    reply = _call_claude(session)
    session.add_assistant(reply)
    return reply


def chat(user_id: str, user_message: str) -> str:
    """Free-form follow-up question, in the same ongoing conversation."""
    session = get_session(user_id)
    session.add_user(user_message)
    reply = _call_claude(session)
    session.add_assistant(reply)
    return reply


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    from datetime import date

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. This smoke test makes real, billed API "
            "calls — set the key first (see README/Console), then re-run."
        )

    from machines.chest_press import resolve_chest_press
    from machines.explanations import build_explanation_facts
    from machines.leg_press import CouplingConstants, LegPressFrameConstants, resolve_leg_press
    from models import AnthropometryProfile, BilateralSegment, InjuryConstraint, InjuryJoint, InjuryProvenance, InjuryTier

    # --- Scenario 1: Chest Press, petite user with a Tier-3 shoulder injury (CLAMPED) ---
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

    reply_1 = narrate_setup("demo_user", [seat_facts, handle_facts])
    print("=== Chest Press setup narration ===")
    print(reply_1)
    assert len(reply_1) > 0
    # No raw jargon codes (underscored verdict/field names) should leak into the narration.
    assert "CLAMPED_" not in reply_1.upper() and "CAUSING_SEGMENT" not in reply_1.upper()

    # --- Scenario 2: follow-up chat in the SAME session, testing memory ---
    reply_2 = chat("demo_user", "why did my seat end up so high, remind me?")
    print("\n=== Follow-up chat (same session) ===")
    print(reply_2)
    assert len(reply_2) > 0
    assert len(get_session("demo_user").messages) == 4  # 2 user turns + 2 assistant turns

    # --- Scenario 3: Leg Press, unfeasible geometry (NO_SOLUTION_BY_COUPLING) ---
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

    # New user_id -> fresh session, no cross-talk with demo_user's history.
    reply_3 = narrate_setup("another_user", [carriage_facts], just_finished_machine="Seated Row")
    print("\n=== Leg Press NO_SOLUTION narration (fresh session) ===")
    print(reply_3)
    assert len(reply_3) > 0
    assert len(get_session("another_user").messages) == 2

    print("\nAll machines/ai_narration.py smoke tests passed.")
