"""FormFit HTTP API — thin FastAPI layer over the biomechanics engine.

Wraps the already-verified `resolve_*` machine functions and the Gemini
narration backend (`machines/ai_narration_gemini.py`) so a browser frontend
can talk to this over plain HTTP. Per project decision, the engine stays
Python and is hosted as its own persistent process (Railway/Render/Fly) —
this file is that process's entrypoint, not a rewrite of anything.

No biomechanics happens here — this module only stores per-user state,
dispatches to the right `resolve_*` function, and turns the resulting
`ExplanationFacts` into a chat reply. Run with:

    uvicorn api:app --reload

Per-user state (profiles, injuries, last machine, Gemini interaction
pointer) is Supabase-backed — see `storage.py`. Requires `SUPABASE_URL`/
`SUPABASE_KEY` exported in the shell `uvicorn` runs from (never committed),
same convention as `GEMINI_API_KEY`.
"""

import dataclasses
import html
import os
import secrets
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import storage
from machines.ai_narration_gemini import GeminiUnavailableError, narrate_setup
from machines.ai_narration_gemini import chat as gemini_chat
from machines.chest_press import resolve_chest_press
from machines.coaching import COACHING, machine_notes, select_coaching
from machines.common import AxisResolution
from machines.explanations import ExplanationFacts, build_explanation_facts
from machines.lat_pulldown import LatPulldownFrameConstants, resolve_lat_pulldown
from machines.narration_common import chat_message_with_notes, enforce_coaching, fallback_narration
from machines.leg_curl import LegCurlFrameConstants, resolve_leg_curl
from machines.leg_extension import resolve_leg_extension
from machines.leg_press import CouplingConstants, LegPressFrameConstants, resolve_leg_press
from machines.pec_deck import resolve_pec_deck
from machines.seated_row import SeatedRowFrameConstants, resolve_seated_row
from machines.shoulder_press import resolve_shoulder_press
from models import (
    AnthropometryProfile,
    FeasibilityState,
    InjuryConstraint,
    InjuryJoint,
    InjuryProvenance,
    InjuryTier,
    MachineName,
)

# ---------------------------------------------------------------------------
# Wire-format request DTOs.
#
# models.py's domain records (AnthropometryProfile, InjuryConstraint) use
# `strict=True` deliberately (see models.py) — but strict mode rejects the
# ISO date *strings* JSON is forced to carry (there's no JSON date type),
# since strict mode only allows already-correctly-typed values, not string
# coercion. These DTOs are plain (non-strict) Pydantic models that mirror
# the wire shape; FastAPI's normal (lax) parsing turns date strings into
# real `date` objects here, which then satisfy the domain model's strict
# constructor untouched — no loosening of models.py itself.
# ---------------------------------------------------------------------------


class _BilateralSegmentIn(BaseModel):
    left_mm: float | None = None
    right_mm: float | None = None
    single_sided: bool = False


class _ScanSigmaIn(BaseModel):
    sigma_T_mm: float | None = None
    sigma_F_mm: float | None = None
    sigma_Ti_mm: float | None = None
    sigma_A_mm: float | None = None
    sigma_BAW_mm: float | None = None
    sigma_Cd_mm: float | None = None


class ProfileIn(BaseModel):
    user_id: str
    captured_at: date
    height_H_mm: float
    sitting_height_T_mm: float
    femur: _BilateralSegmentIn
    tibia: _BilateralSegmentIn
    arm: _BilateralSegmentIn
    biacromial_width_BAW_mm: float
    chest_depth_Cd_mm: float
    scan_sigma_mm: _ScanSigmaIn | None = None  # absent from older scanner builds -> engine defaults


class InjuryIn(BaseModel):
    constraint_id: str
    joint: InjuryJoint
    tier: InjuryTier
    candidate_severity: float
    applied_severity: float
    functional_limit_deg: float
    provenance: InjuryProvenance
    onset_date: date
    review_date: date
    pain_free_counter: int = 0
    last_pain_report_date: date | None = None

app = FastAPI(title="FormFit API")

# Kept even though scan.html is now served by this same process (below) —
# still useful when testing scan.html off a separate quick static server.
# Wide open is fine for solo/friend-testing; tighten to specific origins
# before any real deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serves scan/scan.html (and its .mjs modules) directly from this same
# process — one process, one port, one ngrok tunnel, no CORS needed in the
# common case. Matches the "one process serves everything" architecture
# decision in PRODUCT_ROADMAP_NOTES.md (originally written with
# frontend.html in mind; scan.html gets the same treatment now that it
# exists). Mounted by absolute path so it works regardless of the cwd
# uvicorn was launched from.
app.mount("/scan", StaticFiles(directory=Path(__file__).parent / "scan"), name="scan")

# No local /machine_photos static mount — those photos (Matrix's own, from
# their official site) live in Supabase Storage instead (public
# "machine-photos" bucket, see upload_machine_photos.py and frontend.html's
# MACHINE_PHOTOS), served straight from Supabase's CDN to the browser, not
# through this server at all. Keeps them out of the public GitHub repo
# without needing this process to know anything about them.

# ---------------------------------------------------------------------------
# Frame constants — properties of the physical machines in a gym, not user
# input, so they're wired here once rather than sent per-request. None of
# these numbers are fixed by the spec (see each module's own docstring) —
# these are the same illustrative values each machine's own smoke test uses.
# Replace with calibrated per-gym data once available.
# ---------------------------------------------------------------------------
_LAT_PULLDOWN_FRAME = LatPulldownFrameConstants(
    thigh_pad_leg_length_coefficient=0.20,
    seat_pan_height_mm=450.0,
    overhead_reach_tolerance_mm=60.0,
)
_SEATED_ROW_FRAME = SeatedRowFrameConstants(y_target_mm=1180.0)
_LEG_CURL_FRAME = LegCurlFrameConstants(ankle_pad_offset_mm=20.0)
_LEG_PRESS_FRAME = LegPressFrameConstants(recline_hip_reduction_per_step_deg=6.0)
_LEG_PRESS_COUPLING = CouplingConstants(a_ham=0.1, a_fem=0.15, fatigue_reserve_deg=3.0, m_hip_tier3=0.75)

# Per-user state (profiles, injuries, last-machine) is Supabase-backed —
# see storage.py. No more in-memory dicts here: those reset on every
# process restart, which meant a friend's scanned profile vanished the
# moment the server (or `--reload`) restarted.


class LegPressExtras(BaseModel):
    """Per-user functional-screen inputs Leg Press needs beyond the scan
    profile — these vary per user/session, unlike the frame constants above."""

    theta_hip_onset_deg: float
    theta_knee_screen_deg: float
    hamstring_tightness: float = 0.0


class ChatMessage(BaseModel):
    message: str


class SetupResponse(BaseModel):
    machine: str
    facts: list[ExplanationFacts]
    narration: str
    ai_fallback: bool = False  # True when Gemini was down and the reply was built without it


def _normalize_user_id(user_id: str) -> str:
    """Trim + lowercase every user_id at every entry point (path params and
    the POST /profiles body alike) so "Alex" and "alex " are always the
    same lookup key — this MVP's only identity mechanism is a self-typed
    name, no accounts, so two people typing the same name in different
    casing/whitespace must still collide predictably rather than silently
    creating two "different" profiles. The normalized form is also what
    gets stored as AnthropometryProfile.user_id itself (not just the dict
    key), so there's exactly one canonical form, never a mismatch between
    how a profile is stored vs. looked up."""
    return user_id.strip().lower()


def _require_profile(user_id: str) -> AnthropometryProfile:
    profile = storage.get_profile(_normalize_user_id(user_id))
    if profile is None:
        raise HTTPException(404, "no profile for this user_id — POST /profiles first")
    return profile


# Scans captured before this date used the old scan/measurements.mjs formulas
# (T measured ear-to-hip, and a calibration that inflated every segment by
# ~12%) — their numbers put nearly everyone on the top seat hole. They can't
# be converted after the fact (the raw landmarks aren't stored), so those
# users are asked to scan again instead of being served wrong setups.
SCAN_FORMULA_FIXED_ON = date(2026, 9, 28)


def _needs_rescan(profile: AnthropometryProfile) -> bool:
    return profile.captured_at < SCAN_FORMULA_FIXED_ON


_RESCAN_REPLY = (
    "Heads up: we've improved the scan, and your old measurements would give you the "
    "wrong seat settings. Redo your scan (takes about a minute) and I'll set you up properly."
)


@app.get("/profiles/{user_id}/exists")
def profile_exists(user_id: str) -> dict:
    """Cheap existence check for the frontend's "we found a profile named X
    — is this you?" step (Phase 2 chat product plan) — avoids needing to
    catch/parse a 404 from GET /profiles/{user_id} just to answer a yes/no
    question, and never leaks the profile's actual data in the process."""
    profile = storage.get_profile(_normalize_user_id(user_id))
    return {
        "exists": profile is not None,
        "needs_rescan": profile is not None and _needs_rescan(profile),
    }


def _is_informative(facts: ExplanationFacts) -> bool:
    """False for fixed hardware the engine has no data on yet (no pin, no
    coordinate, nothing flagged) — e.g. Chest Press's handle depth. Showing
    those as a "—" row or narrating them as "in range, low confidence" was
    pure noise."""
    return not (
        facts.achieved_pin is None
        and facts.achieved_coordinate_mm is None
        and facts.verdict is FeasibilityState.IN_RANGE
    )


def _extract_facts(resolution: object, machine_label: str) -> list[ExplanationFacts]:
    """Pull every AxisResolution field off a machine's result dataclass and
    turn each into ExplanationFacts — generic over all 8 machines instead of
    hardcoding each one's field names. Uninformative fixed-hardware axes are
    dropped (see `_is_informative`)."""
    facts = []
    for field in dataclasses.fields(resolution):
        value = getattr(resolution, field.name)
        if isinstance(value, AxisResolution):
            axis_facts = build_explanation_facts(value, machine_name=machine_label)
            if _is_informative(axis_facts):
                facts.append(axis_facts)
    return facts


# machine slug -> (MachineName, resolver taking (profile, injuries, leg_press_extras))
_MACHINE_RESOLVERS = {
    "chest_press": (
        MachineName.CHEST_PRESS,
        lambda profile, injuries, extras: resolve_chest_press(profile, injuries),
    ),
    "shoulder_press": (
        MachineName.SHOULDER_PRESS,
        lambda profile, injuries, extras: resolve_shoulder_press(profile, injuries),
    ),
    "lat_pulldown": (
        MachineName.LAT_PULLDOWN,
        lambda profile, injuries, extras: resolve_lat_pulldown(profile, _LAT_PULLDOWN_FRAME, injuries),
    ),
    "pec_deck": (
        MachineName.PEC_DECK,
        lambda profile, injuries, extras: resolve_pec_deck(profile, injuries),
    ),
    "seated_row": (
        MachineName.SEATED_ROW,
        lambda profile, injuries, extras: resolve_seated_row(profile, _SEATED_ROW_FRAME, injuries),
    ),
    "leg_extension": (
        MachineName.LEG_EXTENSION,
        lambda profile, injuries, extras: resolve_leg_extension(profile, injuries),
    ),
    "leg_curl": (
        MachineName.SEATED_LEG_CURL,
        lambda profile, injuries, extras: resolve_leg_curl(profile, _LEG_CURL_FRAME, injuries),
    ),
    "leg_press": (
        MachineName.LEG_PRESS_45,
        lambda profile, injuries, extras: resolve_leg_press(
            profile,
            _LEG_PRESS_COUPLING,
            _LEG_PRESS_FRAME,
            theta_hip_onset_deg=extras.theta_hip_onset_deg,
            theta_knee_screen_deg=extras.theta_knee_screen_deg,
            injuries=injuries,
            hamstring_tightness=extras.hamstring_tightness,
        ),
    ),
}


# MachineName value (what storage.get_last_machine returns) -> slug.
_SLUG_BY_MACHINE_NAME = {machine_enum.value: slug for slug, (machine_enum, _) in _MACHINE_RESOLVERS.items()}


def _narrate(user_id: str, machine: str, facts: list[ExplanationFacts]) -> tuple[str, str | None]:
    """(reply, ai_error) for a setup, with the approved tips/avoids for
    this machine and result (machines/coaching.py). The model only rephrases
    them; enforce_coaching puts the approved text back if it doesn't.

    If Gemini is down, the setup still goes out: the engine's pins and the
    library tips don't need the model, only the wording does. ai_error (None
    when the model answered) tells the chat to say so, and why."""
    coaching = select_coaching(machine, facts) if machine in COACHING else None
    try:
        narration = narrate_setup(
            user_id, facts, just_finished_machine=storage.get_last_machine(user_id), coaching=coaching
        )
    except GeminiUnavailableError as e:
        return fallback_narration(facts, coaching), e.code
    return (enforce_coaching(narration, coaching) if coaching else narration), None


def _chat(user_id: str, message: str) -> str:
    """Free-form chat, with the approved technique notes for the user's last
    machine attached (prompt rule 11: technique advice only from those)."""
    last_machine = storage.get_last_machine(user_id)
    notes = machine_notes(_SLUG_BY_MACHINE_NAME.get(last_machine, "")) if last_machine else None
    try:
        return gemini_chat(user_id, chat_message_with_notes(message, notes, last_machine))
    except GeminiUnavailableError as e:
        # A 503 with a JSON `detail`, which the chat shows as "Something went
        # wrong: ...", instead of an unhandled 500 it can't parse.
        raise HTTPException(
            503, f"{e} Try again in a minute. Machine setups still work, just tap a machine. (error: {e.code})"
        ) from e


@app.post("/profiles")
def create_profile(payload: ProfileIn) -> AnthropometryProfile:
    """Submit (or overwrite) a user's anthropometry profile — the body-scan
    output, until a real scan pipeline exists to produce it."""
    data = payload.model_dump()
    data["user_id"] = _normalize_user_id(data["user_id"])
    profile = AnthropometryProfile(**data)
    storage.save_profile(profile)
    return profile


@app.get("/profiles/{user_id}")
def get_profile(user_id: str) -> AnthropometryProfile:
    return _require_profile(user_id)


@app.post("/profiles/{user_id}/injuries")
def add_injury(user_id: str, payload: InjuryIn) -> list[InjuryConstraint]:
    user_id = _normalize_user_id(user_id)
    _require_profile(user_id)
    injury = InjuryConstraint(**payload.model_dump())
    storage.save_injury(user_id, injury)
    return list(storage.get_injuries(user_id).values())


@app.delete("/profiles/{user_id}/injuries/{joint}")
def remove_injury(user_id: str, joint: InjuryJoint) -> list[InjuryConstraint]:
    user_id = _normalize_user_id(user_id)
    _require_profile(user_id)
    storage.delete_injury(user_id, joint)
    return list(storage.get_injuries(user_id).values())


@app.get("/machines")
def list_machines() -> list[str]:
    return list(_MACHINE_RESOLVERS.keys())


# ---------------------------------------------------------------------------
# Zone 1 (chat product plan, see PRODUCT_ROADMAP_NOTES.md): a single
# assistant endpoint the chat UI calls for every message, so the frontend
# never has to decide "is this a machine-setup request or small talk" —
# that decision belongs server-side, next to the narration logic it feeds.
#
# Deliberately keyword-based, not an LLM call, for deciding *which machine*
# (or whether it's a machine question at all): same discipline as the rest
# of this project — the LLM's job is phrasing an already-computed result,
# never deciding facts or, here, even routing. A dumb substring match is
# good enough for a friend-testing MVP and is free/instant/fully
# predictable. Only falls through to the real LLM (`gemini_chat`) for
# genuine free-form conversation with no machine match at all.
# ---------------------------------------------------------------------------

_MACHINE_SPECIFIC_TRIGGERS: dict[str, list[str]] = {
    "chest_press": ["chest press", "chestpress", "bench press"],
    "shoulder_press": ["shoulder press", "shoulderpress", "overhead press", "shoulders"],
    "lat_pulldown": ["lat pulldown", "lat pull down", "pulldown", "pull down", "lats"],
    "pec_deck": ["pec deck", "pec dec", "pecdeck", "chest fly", "flyes", "fly machine", "butterfly"],
    "seated_row": ["seated row", "cable row", "row machine", "rowing"],
    "leg_extension": ["leg extension", "quad extension", "quads"],
    "leg_curl": ["leg curl", "leg curls", "hamstring curl"],
    "leg_press": ["leg press", "legpress"],
}

# Only consulted if NO specific phrase above matched anything. Bare "chest"
# really is ambiguous between chest_press and pec_deck — but "chest press"
# and "chest fly" are already unambiguous specific phrases above, and must
# resolve to exactly one machine without ever reaching this fallback. (Real
# bug caught before it shipped: originally "chest" was mixed directly into
# _MACHINE_SPECIFIC_TRIGGERS's own lists, so tapping the "Chest Press"
# equipment chip — whose label is the literal string "Chest Press" — also
# matched pec_deck's bare "chest" trigger, wrongly asking the user to
# clarify something they'd already stated unambiguously.)
_MACHINE_AMBIGUOUS_FALLBACK_TRIGGERS: dict[str, list[str]] = {
    "chest_press": ["chest"],
    "pec_deck": ["chest"],
}


def detect_machine_intent(message: str) -> list[str]:
    """Every machine slug whose trigger phrase appears in `message`
    (case-insensitive substring match). Specific phrases are checked first
    and, if any match, are returned immediately — the ambiguous "chest"
    fallback is only ever consulted when nothing specific matched at all,
    so an unambiguous phrase like "chest press" can never accidentally
    trip the chest_press/pec_deck clarification."""
    lowered = message.lower()
    specific = [slug for slug, triggers in _MACHINE_SPECIFIC_TRIGGERS.items() if any(t in lowered for t in triggers)]
    if specific:
        return specific
    return [slug for slug, triggers in _MACHINE_AMBIGUOUS_FALLBACK_TRIGGERS.items() if any(t in lowered for t in triggers)]


class AssistantMessage(BaseModel):
    message: str


class AssistantReply(BaseModel):
    kind: str  # "machine_setup" | "clarify" | "unsupported_machine" | "chat" | "rescan"
    reply: str
    machine: str | None = None
    facts: list[ExplanationFacts] | None = None
    # True when Gemini was down and this setup was built from the engine and
    # the tip library alone; the chat shows a note so it's obvious.
    ai_fallback: bool = False
    ai_error: str | None = None  # short code for why ("timeout", "429"), shown in that note



# Machines gated out of the live assistant this round (2026-08 field audit).
# `leg_press` was already gated (needs an unbuilt mobility screen); `leg_curl`
# and `leg_extension` join it now — `leg_curl` because it turned out to be a
# structurally different (prone, not seated) machine with zero real
# measurements yet, and `leg_extension` because this round's scope is
# deliberately limited to the machines with confirmed real data (see
# leg_extension.md's own note — nothing is confirmed wrong there, it's just
# out of scope this round). Same pattern for all three: still listed in
# `GET /machines`/routable via triggers, just answered with a fixed
# "not supported yet" reply here rather than computed and served.
_UNSUPPORTED_MACHINES: dict[str, str] = {
    "leg_press": (
        "Leg press isn't ready yet. It needs a quick mobility check we haven't built. "
        "Ask me about another machine!"
    ),
    "leg_curl": (
        "Leg curl isn't ready yet, we're re-measuring it after a hardware change. "
        "Ask me about another machine!"
    ),
    "leg_extension": (
        "Leg extension isn't ready yet. Ask me about another machine!"
    ),
    # 2026-09-28 population sweep: the fixed-bar reach check told nearly
    # everyone under ~190cm the machine doesn't fit them (the bar is meant to
    # be reached up to / half-standing, not at seated arm's length), and the
    # thigh-pad axis is still in the pre-audit reference frame (see
    # lat_pulldown.py). Gated until both are re-modeled.
    "lat_pulldown": (
        "Lat pulldown isn't ready yet, we're still measuring it. Ask me about another machine!"
    ),
    # 2026-09-28 population sweep: y_target_mm (api.py's _SEATED_ROW_FRAME) was
    # never measured on-site, and the illustrative 1180mm put everyone under
    # ~190cm on the top seat hole. Gated until it's measured.
    "seated_row": (
        "Seated row isn't ready yet, we're still measuring it. Ask me about another machine!"
    ),
}


@app.post("/assistant/{user_id}")
def assistant_message(user_id: str, body: AssistantMessage) -> AssistantReply:
    """The one endpoint the chat UI talks to. Figures out whether the
    message is about a specific machine (compute + narrate it for real),
    ambiguous (ask which one), an unsupported machine this round (see
    `_UNSUPPORTED_MACHINES`), or neither (ordinary free-form chat)."""
    user_id = _normalize_user_id(user_id)
    profile = _require_profile(user_id)
    storage.log_message(user_id, "user")
    if _needs_rescan(profile):
        storage.log_message(user_id, "bot", kind="rescan")
        return AssistantReply(kind="rescan", reply=_RESCAN_REPLY)
    matches = detect_machine_intent(body.message)

    if len(matches) == 1:
        machine = matches[0]
        if machine in _UNSUPPORTED_MACHINES:
            storage.log_message(user_id, "bot", kind="unsupported_machine")
            return AssistantReply(
                kind="unsupported_machine",
                machine=machine,
                reply=_UNSUPPORTED_MACHINES[machine],
            )
        machine_enum, resolver = _MACHINE_RESOLVERS[machine]
        injuries = storage.get_injuries(user_id)
        resolution = resolver(profile, injuries, None)
        facts = _extract_facts(resolution, machine_enum.value)
        narration, ai_error = _narrate(user_id, machine, facts)
        storage.set_last_machine(user_id, machine_enum.value)
        storage.log_message(user_id, "bot", kind="machine_setup_fallback" if ai_error else "machine_setup")
        return AssistantReply(
            kind="machine_setup",
            reply=narration,
            machine=machine,
            facts=facts,
            ai_fallback=ai_error is not None,
            ai_error=ai_error,
        )

    if len(matches) > 1:
        friendly = " or ".join(m.replace("_", " ") for m in matches)
        storage.log_message(user_id, "bot", kind="clarify")
        return AssistantReply(
            kind="clarify",
            reply=f"Which one did you mean, {friendly}?",
        )

    reply = _chat(user_id, body.message)
    storage.log_message(user_id, "bot", kind="chat")
    return AssistantReply(kind="chat", reply=reply)


class FeedbackIn(BaseModel):
    rating: str  # "up" | "down"
    machine: str | None = None
    comment: str | None = None


@app.post("/feedback/{user_id}")
def submit_feedback(user_id: str, body: FeedbackIn) -> dict:
    """One 👍/👎 (optionally with a comment, only ever offered on 👎 in the
    UI) per bot reply — see frontend.html's `attachFeedbackUI`. Not tied to
    a specific message/row (see storage.py's own note on `log_feedback`)."""
    if body.rating not in ("up", "down"):
        raise HTTPException(422, "rating must be 'up' or 'down'")
    storage.log_feedback(_normalize_user_id(user_id), body.rating, machine=body.machine, comment=body.comment)
    return {"ok": True}


@app.post("/setup/{user_id}/{machine}")
def setup_machine(
    user_id: str,
    machine: str,
    leg_press_extras: LegPressExtras | None = None,
) -> SetupResponse:
    """Resolve one machine's setup for this user and narrate it. Facts are
    computed by the deterministic engine only; the LLM's job is phrasing."""
    user_id = _normalize_user_id(user_id)
    profile = _require_profile(user_id)
    if machine not in _MACHINE_RESOLVERS:
        raise HTTPException(404, f"unknown machine {machine!r} — see GET /machines")
    if machine == "leg_press" and leg_press_extras is None:
        raise HTTPException(
            422, "leg_press requires theta_hip_onset_deg/theta_knee_screen_deg in the request body"
        )

    machine_enum, resolver = _MACHINE_RESOLVERS[machine]
    injuries = storage.get_injuries(user_id)
    resolution = resolver(profile, injuries, leg_press_extras)

    facts = _extract_facts(resolution, machine_enum.value)
    narration, ai_error = _narrate(user_id, machine, facts)
    storage.set_last_machine(user_id, machine_enum.value)

    return SetupResponse(
        machine=machine_enum.value, facts=facts, narration=narration, ai_fallback=ai_error is not None
    )


@app.post("/chat/{user_id}")
def chat_endpoint(user_id: str, body: ChatMessage) -> dict:
    """Free-form follow-up question, same ongoing narration session."""
    user_id = _normalize_user_id(user_id)
    _require_profile(user_id)
    return {"reply": _chat(user_id, body.message)}


# ---------------------------------------------------------------------------
# Frontend — serves the single self-contained HTML file once it exists in
# this directory, so the whole product is one process/one deploy. No build
# step: the frontend is plain React-via-CDN + in-browser Babel JSX.
# ---------------------------------------------------------------------------
_FRONTEND_FILE = Path(__file__).parent / "frontend.html"


@app.get("/")
def serve_frontend() -> FileResponse:
    if not _FRONTEND_FILE.exists():
        raise HTTPException(404, "frontend.html not present yet — API-only for now")
    # No explicit Cache-Control here meant Safari (specifically — other
    # browsers weren't reproducing this) was heuristically caching this
    # single-page app's HTML+inline-script and silently serving a stale
    # version on reload during active development, while a browser with no
    # prior cache for this origin always fetched fresh — "works in one
    # browser, broken in another on the same phone" was the tell.
    # no-cache (NOT no-store) forces revalidation on every load rather than
    # disabling caching outright — a 304 still short-circuits the body.
    return FileResponse(_FRONTEND_FILE, headers={"Cache-Control": "no-cache, must-revalidate"})


def _format_ts(ts: str | None) -> str:
    if ts is None:
        return "—"
    return ts.replace("T", " ")[:19]  # ISO string from Supabase -> "YYYY-MM-DD HH:MM:SS", drop the rest


def _relative_time(ts: str | None) -> str:
    """"3m ago"/"2h ago"-style — nicer to scan at a glance than a raw
    timestamp for "who's active right now"-type questions, the actual
    point of this page."""
    if ts is None:
        return "never"
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    return f"{int(hours // 24)}d ago"


# Cycled per-row so avatars aren't all one flat colour — purely decorative,
# same HSL family as the rest of the app's palette (frontend.html/scan.html).
_AVATAR_HUES = (217, 262, 172, 25, 330)

_admin_security = HTTPBasic()


def _require_admin(credentials: HTTPBasicCredentials = Depends(_admin_security)) -> None:
    """Gates /admin behind HTTP Basic auth — this page shows real friends'
    names/activity/feedback, and going from "private ngrok link" to a
    public GitHub repo + a permanent cloud URL means the exact path is no
    longer secret by obscurity. Credentials come from ADMIN_USER/
    ADMIN_PASSWORD env vars, same "export in your own shell, never commit"
    convention as GEMINI_API_KEY/SUPABASE_KEY — fails loud (500, not a
    silent open door) if they're not set. `secrets.compare_digest` avoids a
    timing side-channel on the comparison."""
    admin_user = os.environ.get("ADMIN_USER")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_user or not admin_password:
        raise HTTPException(500, "ADMIN_USER/ADMIN_PASSWORD not set — export both in your shell before running uvicorn")
    valid = secrets.compare_digest(credentials.username, admin_user) and secrets.compare_digest(
        credentials.password, admin_password
    )
    if not valid:
        raise HTTPException(401, "Invalid admin credentials", headers={"WWW-Authenticate": "Basic"})


@app.get("/admin", response_class=HTMLResponse)
def admin_activity(_admin: None = Depends(_require_admin)) -> str:
    """HTML activity dashboard — who's scanned, how many messages they've
    sent, when they were last active. Built so the user can just open this
    URL themselves instead of asking in chat every time (see storage.py's
    `get_activity_summary`). Styled to match the rest of the app (same
    Inter/Barlow Condensed + HSL token palette as frontend.html/scan.html)
    rather than a bare unstyled table. Not authenticated — same "wide open,
    fine for friend-testing, tighten before any real deploy" convention as
    the CORS middleware above; don't share this URL beyond the people you'd
    already trust with the fact that you're testing this."""
    rows = storage.get_activity_summary()
    total_users = len(rows)
    total_messages = sum(r["messages_sent"] for r in rows)
    active_today = sum(1 for r in rows if r["last_active"] and _relative_time(r["last_active"]).endswith(("m ago", "h ago", "just now")))

    feedback = storage.get_feedback_summary()

    def _row_html(r: dict, i: int) -> str:
        # user_id is escaped explicitly — api.py's own validation
        # (SAFE_NAME_PATTERN) only exists client-side in frontend.html; a
        # direct POST /profiles call could put anything in this column,
        # and it'd land straight in this page's HTML otherwise.
        name = html.escape(r["user_id"])
        initial = html.escape(r["user_id"][:1].upper())
        hue = _AVATAR_HUES[i % len(_AVATAR_HUES)]
        badge_class = "pill-active" if r["messages_sent"] > 0 else "pill-idle"
        return f"""<tr>
      <td><div class="user-cell"><span class="avatar" style="background:hsl({hue} 85% 94%);color:hsl({hue} 70% 38%)">{initial}</span><span class="user-name">{name}</span></div></td>
      <td class="muted">{_format_ts(r['scanned_at'])}</td>
      <td><span class="pill {badge_class}">{r['messages_sent']}</span></td>
      <td class="muted">{_relative_time(r['last_active'])}</td>
    </tr>"""

    body_rows = "".join(_row_html(r, i) for i, r in enumerate(rows))
    if not body_rows:
        body_rows = '<tr><td colspan="4" class="empty">No one has scanned yet — send the link around 👀</td></tr>'

    def _comment_html(c: dict) -> str:
        icon = "👍" if c["rating"] == "up" else "👎"
        machine_label = html.escape(c["machine"]) if c["machine"] else "general chat"
        return f"""<div class="comment-card">
      <div class="comment-top"><span>{icon}</span><span class="comment-machine">{machine_label}</span>
        <span class="comment-meta">{html.escape(c['user_id'])} · {_relative_time(c['created_at'])}</span></div>
      <p class="comment-text">{html.escape(c['comment'])}</p>
    </div>"""

    comment_html = "".join(_comment_html(c) for c in feedback["comments"])
    if not comment_html:
        comment_html = '<p class="empty" style="padding: 16px 0;">No comments left yet.</p>'

    return f"""<!doctype html>
<html><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" />
<title>FormFit — Activity</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
  :root {{
    --background: 0 0% 100%; --foreground: 220 13% 18%; --card: 220 14% 96%;
    --card-elevated: 220 14% 93%; --primary: 217 91% 60%; --primary-dark: 217 91% 52%;
    --muted-foreground: 220 9% 46%; --border: 220 13% 91%; --dark-navy: 222 24% 14%; --radius: 1rem;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Inter, -apple-system, system-ui, sans-serif; margin: 0;
    background: hsl(var(--background)); color: hsl(var(--foreground));
    padding: 28px 16px 60px; display: flex; justify-content: center;
  }}
  .wrap {{ width: 100%; max-width: 720px; }}
  .header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 22px; }}
  .logo {{
    width: 40px; height: 40px; border-radius: 11px; background: hsl(var(--dark-navy));
    color: white; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;
  }}
  h1 {{ font-family: "Barlow Condensed", Inter, sans-serif; font-size: 24px; font-weight: 700; text-transform: uppercase; margin: 0; }}
  .sub {{ color: hsl(var(--muted-foreground)); font-size: 13px; margin: 2px 0 0; }}

  .stats {{ display: flex; gap: 10px; margin-bottom: 20px; }}
  .stat-card {{
    flex: 1; background: hsl(var(--card)); border: 1px solid hsl(var(--border));
    border-radius: var(--radius); padding: 14px 16px;
  }}
  .stat-value {{ font-family: "Barlow Condensed", Inter, sans-serif; font-size: 30px; font-weight: 700; color: hsl(var(--primary-dark)); line-height: 1; }}
  .stat-label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: hsl(var(--muted-foreground)); margin-top: 5px; font-weight: 600; }}

  table {{
    width: 100%; border-collapse: collapse; background: white; border: 1px solid hsl(var(--border));
    border-radius: var(--radius); overflow: hidden; box-shadow: 0 2px 12px -4px hsl(231 80% 30% / .1);
  }}
  th, td {{ text-align: left; padding: 12px 16px; font-size: 14px; border-bottom: 1px solid hsl(var(--border)); }}
  th {{ background: hsl(var(--card)); font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: hsl(var(--muted-foreground)); font-weight: 700; }}
  tr:last-child td {{ border-bottom: none; }}
  .muted {{ color: hsl(var(--muted-foreground)); font-size: 13px; }}

  .user-cell {{ display: flex; align-items: center; gap: 10px; }}
  .avatar {{
    width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 13px; font-weight: 700; flex-shrink: 0;
  }}
  .user-name {{ font-weight: 600; }}

  .pill {{ display: inline-block; min-width: 24px; text-align: center; padding: 3px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
  .pill-active {{ background: hsl(var(--primary) / .14); color: hsl(var(--primary-dark)); }}
  .pill-idle {{ background: hsl(var(--card-elevated)); color: hsl(var(--muted-foreground)); }}

  .empty {{ text-align: center; color: hsl(var(--muted-foreground)); padding: 32px; }}

  .section-heading {{ font-family: "Barlow Condensed", Inter, sans-serif; font-size: 16px; font-weight: 700; text-transform: uppercase; margin: 28px 0 10px; }}
  .comment-card {{
    background: white; border: 1px solid hsl(var(--border)); border-radius: 12px;
    padding: 12px 14px; margin-bottom: 8px;
  }}
  .comment-top {{ display: flex; align-items: center; gap: 8px; font-size: 12px; }}
  .comment-machine {{ font-weight: 700; text-transform: uppercase; letter-spacing: .02em; font-size: 11px; color: hsl(var(--primary-dark)); }}
  .comment-meta {{ margin-left: auto; color: hsl(var(--muted-foreground)); }}
  .comment-text {{ margin: 6px 0 0; font-size: 14px; line-height: 1.4; }}

  .live-dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: hsl(142 71% 45%); margin-right: 5px; animation: livePulse 1.6s ease-in-out infinite; }}
  @keyframes livePulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
</style></head>
<body>
<div class="wrap" id="wrap">
  <div class="header">
    <div class="logo">💪</div>
    <div>
      <h1>Activity</h1>
      <p class="sub"><span class="live-dot"></span>Live — updates automatically every few seconds.</p>
    </div>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="stat-value">{total_users}</div><div class="stat-label">Scanned</div></div>
    <div class="stat-card"><div class="stat-value">{total_messages}</div><div class="stat-label">Messages sent</div></div>
    <div class="stat-card"><div class="stat-value">{active_today}</div><div class="stat-label">Active today</div></div>
  </div>

  <table>
    <thead><tr><th>User</th><th>Scanned</th><th>Messages</th><th>Last active</th></tr></thead>
    <tbody>{body_rows}</tbody>
  </table>

  <div class="section-heading">Feedback</div>
  <div class="stats">
    <div class="stat-card"><div class="stat-value">👍 {feedback['up']}</div><div class="stat-label">Helpful</div></div>
    <div class="stat-card"><div class="stat-value">👎 {feedback['down']}</div><div class="stat-label">Not helpful</div></div>
  </div>
  {comment_html}
</div>
<script>
  // Polling, not a Supabase Realtime subscription — a real subscription
  // would need the anon key shipped to the browser and would go through
  // Row Level Security, which is deliberately off on these tables (see
  // storage.py's docstring) since only this trusted backend touches them
  // today. Re-fetching this same page every few seconds and swapping the
  // #wrap contents gets the "feels live" result without reopening that
  // decision. relative "Xm ago" times mean this needs to re-render even
  // when the underlying data hasn't changed, so no dirty-check — cheap at
  // this scale (a handful of DB rows).
  async function refreshActivity() {{
    try {{
      const res = await fetch(location.pathname, {{ cache: "no-store" }});
      const html = await res.text();
      const next = new DOMParser().parseFromString(html, "text/html").getElementById("wrap");
      if (next) document.getElementById("wrap").innerHTML = next.innerHTML;
    }} catch (err) {{
      // Transient network hiccup — leave the last-known table showing
      // rather than blanking the page; the next tick tries again.
    }}
  }}
  setInterval(refreshActivity, 4000);
</script>
</body></html>"""
