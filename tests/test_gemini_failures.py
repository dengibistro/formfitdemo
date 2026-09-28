"""A slow or broken Gemini call must come back fast as a readable error.

A real user sat on a spinner for ~5 minutes and then got a raw "Internal
Server Error" the chat couldn't parse (2026-09-28). No real network here:
the Gemini client and Supabase storage are both replaced with stubs.
"""

import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

import api
import machines.ai_narration_gemini as gemini
from machines.coaching import COACHING
from models import AnthropometryProfile, BilateralSegment


class _Interactions:
    def __init__(self, behaviour):
        self.behaviour = behaviour

    def create(self, **kwargs):
        return self.behaviour()


class _Client:
    def __init__(self, behaviour):
        self.interactions = _Interactions(behaviour)


def _hang():
    time.sleep(5)


def _explode():
    raise ConnectionError("network down")


@pytest.fixture
def stub_storage(monkeypatch):
    profile = AnthropometryProfile(
        user_id="tester",
        captured_at=date(2026, 9, 28),
        height_H_mm=1830,
        sitting_height_T_mm=961,
        femur=BilateralSegment(left_mm=462, right_mm=443),
        tibia=BilateralSegment(left_mm=425, right_mm=434),
        arm=BilateralSegment(left_mm=541, right_mm=531),
        biacromial_width_BAW_mm=348,
        chest_depth_Cd_mm=197,
    )
    monkeypatch.setattr(api.storage, "get_profile", lambda user_id: profile)
    monkeypatch.setattr(api.storage, "get_injuries", lambda user_id: {})
    monkeypatch.setattr(api.storage, "get_last_machine", lambda user_id: None)
    monkeypatch.setattr(api.storage, "set_last_machine", lambda user_id, machine: None)
    monkeypatch.setattr(api.storage, "log_message", lambda *a, **k: None)
    monkeypatch.setattr(gemini.storage, "get_last_interaction_id", lambda user_id: None)
    monkeypatch.setattr(gemini.storage, "set_last_interaction_id", lambda user_id, i: None)


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setattr(gemini, "GEMINI_TIMEOUT_SECONDS", 0.5)


def test_hanging_call_gives_up_quickly(monkeypatch, short_timeout, stub_storage):
    monkeypatch.setattr(gemini, "_get_client", lambda: _Client(_hang))
    started = time.monotonic()
    with pytest.raises(gemini.GeminiUnavailableError, match="taking too long"):
        gemini.chat("tester", "hi")
    assert time.monotonic() - started < 2  # didn't wait for the 5s hang


def test_failing_call_becomes_a_readable_error(monkeypatch, short_timeout, stub_storage):
    monkeypatch.setattr(gemini, "_get_client", lambda: _Client(_explode))
    with pytest.raises(gemini.GeminiUnavailableError, match="Couldn't reach"):
        gemini.chat("tester", "hi")


@pytest.mark.parametrize("behaviour", [_hang, _explode])
def test_free_chat_returns_json_503(monkeypatch, short_timeout, stub_storage, behaviour):
    """Free chat can't work without the model, so it answers with a JSON
    `detail` the chat can show, not an unparseable plain-text 500."""
    monkeypatch.setattr(gemini, "_get_client", lambda: _Client(behaviour))
    response = TestClient(api.app).post("/assistant/tester", json={"message": "what should I eat today?"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "AI trainer" in detail and "tap a machine" in detail and "(error: " in detail


@pytest.mark.parametrize("behaviour", [_hang, _explode])
def test_machine_setup_still_works_without_gemini(monkeypatch, short_timeout, stub_storage, behaviour):
    """The pins and tips don't need the model, so a setup still goes out,
    flagged so the chat can say the AI is offline."""
    monkeypatch.setattr(gemini, "_get_client", lambda: _Client(behaviour))
    response = TestClient(api.app).post("/assistant/tester", json={"message": "chest press"})
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "machine_setup" and body["ai_fallback"] is True
    assert body["ai_error"] in ("timeout", "ConnectionError")
    seat = next(f for f in body["facts"] if f["axis_name"] == "Seat height")
    assert f"WHY: Set the seat height to pin {seat['achieved_pin']}." in body["reply"]
    assert COACHING["chest_press"].tips[0] in body["reply"]  # library text, verbatim


def test_normal_setup_is_not_flagged(monkeypatch, short_timeout, stub_storage):
    class _Done:
        status = "completed"
        id = "interaction-1"
        output_text = "WHY: Pin 2 lines your shoulders up.\nTIPS: Tip a|Tip b\nAVOID: Avoid a|Avoid b"

    monkeypatch.setattr(gemini, "_get_client", lambda: _Client(lambda: _Done()))
    body = TestClient(api.app).post("/assistant/tester", json={"message": "chest press"}).json()
    assert body["ai_fallback"] is False
    assert body["reply"].startswith("WHY: Pin 2 lines your shoulders up.")


def test_stale_conversation_pointer_starts_fresh(monkeypatch, short_timeout, stub_storage):
    """A saved previous_interaction_id from an old model (or an expired one)
    must not break every message: retry once without it."""

    class _Done:
        status = "completed"
        id = "fresh-1"
        output_text = "Sure, happy to help."

    calls = []

    class _StrictInteractions:
        def create(self, **kwargs):
            calls.append("previous_interaction_id" in kwargs)
            if "previous_interaction_id" in kwargs:
                raise ValueError("unknown previous interaction")
            return _Done()

    class _StrictClient:
        interactions = _StrictInteractions()

    monkeypatch.setattr(gemini.storage, "get_last_interaction_id", lambda user_id: "old-model-interaction")
    monkeypatch.setattr(gemini, "_get_client", lambda: _StrictClient())
    assert gemini.chat("tester", "hi") == "Sure, happy to help."
    assert calls == [True, False]  # tried the old chain, then a fresh one


def test_calls_ask_for_minimal_thinking_and_a_timeout(monkeypatch, short_timeout, stub_storage):
    """Gemini 3 thinks at a high level by default, which alone was enough to
    time out every call. Every request must ask for minimal thinking and
    carry its own timeout."""

    class _Done:
        status = "completed"
        id = "i-1"
        output_text = "ok"

    seen = {}

    class _Recording:
        def create(self, **kwargs):
            seen.update(kwargs)
            return _Done()

    class _RecordingClient:
        interactions = _Recording()

    monkeypatch.setattr(gemini, "_get_client", lambda: _RecordingClient())
    gemini.chat("tester", "hi")
    assert seen["generation_config"]["thinking_level"] == "minimal"
    assert seen["timeout"] == gemini.GEMINI_TIMEOUT_SECONDS
