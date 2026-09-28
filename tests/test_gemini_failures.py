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


@pytest.mark.parametrize("message", ["chest press", "what should I eat today?"])
@pytest.mark.parametrize("behaviour", [_hang, _explode])
def test_assistant_returns_json_503(monkeypatch, short_timeout, stub_storage, message, behaviour):
    """Both paths into Gemini (a machine setup and free chat) answer with a
    JSON `detail` the chat can show, not an unparseable plain-text 500."""
    monkeypatch.setattr(gemini, "_get_client", lambda: _Client(behaviour))
    response = TestClient(api.app).post("/assistant/tester", json={"message": message})
    assert response.status_code == 503
    assert "AI trainer" in response.json()["detail"]
