"""Supabase-backed persistence layer.

Replaces the in-memory dicts `api.py` and `machines/ai_narration_gemini.py`
used to use (`_PROFILES`/`_INJURIES`/`_LAST_MACHINE`/`_SESSIONS`) — those
reset on every process restart, which meant a friend's scanned profile
vanished the moment the server (or `--reload`) restarted. One function per
operation here, matching the exact shape of what the dicts used to do, so
the calling code barely changes.

Stores `AnthropometryProfile`/`InjuryConstraint` as JSONB blobs
(`.model_dump(mode="json")`) rather than one SQL column per field — both
models have nested types (`BilateralSegment`) and enums, and hand-mapping
every field now just means a migration dance later for no real benefit at
this scale. Reading back uses `model_validate(data, strict=False)` — the
domain models are deliberately `strict=True` (see `models.py`), but a JSONB
round-trip is exactly the same "already-typed-enough but not exactly right
Python types" situation `api.py`'s wire-format DTOs exist for (e.g. dates
survive as ISO strings) — `strict=False` on validate is Pydantic v2's
built-in way to relax just this one call, no separate DTO needed here.

Client is constructed lazily from `SUPABASE_URL`/`SUPABASE_KEY` — importing
this module never requires those env vars, only calling into it does (same
pattern as `machines/ai_narration_gemini.py`'s `_get_client()`). Export both
in your own shell before running `uvicorn`, same convention as
`GEMINI_API_KEY` — never commit them.

Required tables (run once in the Supabase SQL editor):

    create table profiles (
      user_id text primary key,
      data jsonb not null,
      updated_at timestamptz not null default now()
    );

    create table injuries (
      user_id text not null,
      joint text not null,
      data jsonb not null,
      updated_at timestamptz not null default now(),
      primary key (user_id, joint)
    );

    create table user_state (
      user_id text primary key,
      last_machine text,
      last_interaction_id text,
      updated_at timestamptz not null default now()
    );

    create table message_log (
      id bigint generated always as identity primary key,
      user_id text not null,
      role text not null,
      kind text,
      created_at timestamptz not null default now()
    );

    create table feedback (
      id bigint generated always as identity primary key,
      user_id text not null,
      machine text,
      rating text not null,
      comment text,
      created_at timestamptz not null default now()
    );
"""

import os

from supabase import Client, create_client

from models import AnthropometryProfile, InjuryConstraint, InjuryJoint

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL/SUPABASE_KEY not set — export both in your shell before running uvicorn"
            )
        _client = create_client(url, key)
    return _client


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def get_profile(user_id: str) -> AnthropometryProfile | None:
    res = _get_client().table("profiles").select("data").eq("user_id", user_id).execute()
    if not res.data:
        return None
    return AnthropometryProfile.model_validate(res.data[0]["data"], strict=False)


def save_profile(profile: AnthropometryProfile) -> None:
    _get_client().table("profiles").upsert(
        {"user_id": profile.user_id, "data": profile.model_dump(mode="json")}
    ).execute()


# ---------------------------------------------------------------------------
# Injuries
# ---------------------------------------------------------------------------


def get_injuries(user_id: str) -> dict[InjuryJoint, InjuryConstraint]:
    res = _get_client().table("injuries").select("joint, data").eq("user_id", user_id).execute()
    return {
        InjuryJoint(row["joint"]): InjuryConstraint.model_validate(row["data"], strict=False) for row in res.data
    }


def save_injury(user_id: str, injury: InjuryConstraint) -> None:
    _get_client().table("injuries").upsert(
        {"user_id": user_id, "joint": injury.joint.value, "data": injury.model_dump(mode="json")}
    ).execute()


def delete_injury(user_id: str, joint: InjuryJoint) -> None:
    _get_client().table("injuries").delete().eq("user_id", user_id).eq("joint", joint.value).execute()


# ---------------------------------------------------------------------------
# Per-user operational state (last machine, Gemini interaction pointer)
# ---------------------------------------------------------------------------


def _get_user_state(user_id: str) -> dict:
    res = _get_client().table("user_state").select("last_machine, last_interaction_id").eq(
        "user_id", user_id
    ).execute()
    return res.data[0] if res.data else {}


def get_last_machine(user_id: str) -> str | None:
    return _get_user_state(user_id).get("last_machine")


def set_last_machine(user_id: str, machine: str) -> None:
    _get_client().table("user_state").upsert({"user_id": user_id, "last_machine": machine}).execute()


def get_last_interaction_id(user_id: str) -> str | None:
    return _get_user_state(user_id).get("last_interaction_id")


def set_last_interaction_id(user_id: str, interaction_id: str) -> None:
    _get_client().table("user_state").upsert({"user_id": user_id, "last_interaction_id": interaction_id}).execute()


# ---------------------------------------------------------------------------
# Message log — counts/activity only (who's using it, how much), not a
# transcript. The actual chat thread lives client-side only, in each
# browser's own localStorage (see frontend.html) — the backend has never
# seen message text before this, and still doesn't: only who sent
# something, what kind of reply it got, and when.
# ---------------------------------------------------------------------------


def log_message(user_id: str, role: str, kind: str | None = None) -> None:
    _get_client().table("message_log").insert({"user_id": user_id, "role": role, "kind": kind}).execute()


def get_activity_summary() -> list[dict]:
    """One row per person who's ever scanned (`profiles`), with message
    counts/last-active folded in from `message_log` — the data `GET /admin`
    renders. Two small `select`s + a Python-side merge rather than a SQL
    view/RPC: this is friend-testing scale (a handful of rows), not worth
    a second migration for a GROUP BY."""
    profiles_res = _get_client().table("profiles").select("user_id, updated_at").execute()
    logs_res = _get_client().table("message_log").select("user_id, role, created_at").execute()

    stats: dict[str, dict] = {}
    for row in logs_res.data:
        entry = stats.setdefault(row["user_id"], {"messages_sent": 0, "last_active": None})
        if row["role"] == "user":
            entry["messages_sent"] += 1
        if entry["last_active"] is None or row["created_at"] > entry["last_active"]:
            entry["last_active"] = row["created_at"]

    summary = []
    for p in profiles_res.data:
        entry = stats.get(p["user_id"], {"messages_sent": 0, "last_active": None})
        summary.append(
            {
                "user_id": p["user_id"],
                "scanned_at": p["updated_at"],
                "messages_sent": entry["messages_sent"],
                "last_active": entry["last_active"],
            }
        )
    summary.sort(key=lambda r: r["last_active"] or r["scanned_at"], reverse=True)
    return summary


# ---------------------------------------------------------------------------
# Feedback — thumbs up/down per bot reply, optional comment on a thumbs-down.
# Deliberately not linked to a specific `message_log` row: the frontend
# never gave messages a durable ID (they're plain DOM bubbles, see
# frontend.html), and for friend-testing scale "which machine, up or down,
# what they typed" is enough signal without that plumbing.
# ---------------------------------------------------------------------------


def log_feedback(user_id: str, rating: str, machine: str | None = None, comment: str | None = None) -> None:
    _get_client().table("feedback").insert(
        {"user_id": user_id, "rating": rating, "machine": machine, "comment": comment}
    ).execute()


def get_feedback_summary() -> dict:
    """Up/down counts plus the comments people actually bothered to type —
    `GET /admin` shows both: the count is a quick pulse-check, the comments
    are where the actual "not helpful" reasons live."""
    res = _get_client().table("feedback").select("user_id, machine, rating, comment, created_at").execute()
    up = sum(1 for r in res.data if r["rating"] == "up")
    down = sum(1 for r in res.data if r["rating"] == "down")
    comments = [r for r in res.data if r["comment"]]
    comments.sort(key=lambda r: r["created_at"], reverse=True)
    return {"up": up, "down": down, "comments": comments}
