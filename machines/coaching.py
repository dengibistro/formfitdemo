"""Approved technique tips and things to avoid, per machine.

The narrator (Gemini) only rephrases these. It never writes its own
technique advice, same rule as the rest of the engine: the LLM phrases,
it doesn't decide. Where biomechanics comes in is *selection*: situational
items are keyed by what the engine found (a seat pinned at its limit, a
fixed grip that's too wide or narrow for this body, a machine that can't be
set up safely), and those go first.

General items are standard technique for each exercise. Worth a review by a
trainer before any wider rollout.

Every live machine (api.py's _MACHINE_RESOLVERS minus _UNSUPPORTED_MACHINES)
needs an entry; tests/test_coaching.py enforces that, so ungating a machine
means writing its tips first.
"""

from dataclasses import dataclass, field

from machines.explanations import ExplanationFacts
from models import AxisPurpose, FeasibilityState

SEAT = AxisPurpose.SEAT_HEIGHT_SHOULDER_ALIGNMENT
GRIP = AxisPurpose.GRIP_WIDTH_SHOULDER_ABDUCTION
HIGH = FeasibilityState.CLAMPED_HIGH
LOW = FeasibilityState.CLAMPED_LOW

_NO_SOLUTION_STATES = (FeasibilityState.NO_SOLUTION, FeasibilityState.NO_SOLUTION_BY_COUPLING)

# How many of each the user sees: situational items first, general ones fill
# up to TARGET. Situational items can push it to CAP, never further.
TARGET = 2
CAP = 3


@dataclass(frozen=True)
class Coaching:
    tips: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()


@dataclass(frozen=True)
class MachineCoaching:
    tips: tuple[str, ...]
    avoid: tuple[str, ...]
    situational: dict[tuple[AxisPurpose, FeasibilityState], Coaching] = field(default_factory=dict)


# Seat clamped_high: the seat is already at its highest and the handles still
# sit above the shoulders (short torso). clamped_low: seat at its lowest and
# the handles sit below the shoulders (tall torso). See common.resolve_congruence_seat.
COACHING: dict[str, MachineCoaching] = {
    "chest_press": MachineCoaching(
        tips=(
            "Squeeze your shoulder blades together and keep them down against the pad before you press",
            "Keep your wrists straight, in line with your forearms",
            "Push straight out and breathe out as you press",
            "Keep your feet flat and your back on the pad the whole set",
        ),
        avoid=(
            "Locking your elbows hard at the end",
            "Letting your shoulders roll forward off the pad",
            "Letting the handles come back so far you feel it in the front of your shoulders",
            "Arching your lower back off the pad to move more weight",
        ),
        situational={
            (SEAT, HIGH): Coaching(
                tips=("Keep your shoulders pressed down, away from your ears",),
                avoid=("Shrugging up toward the handles",),
            ),
            (SEAT, LOW): Coaching(
                tips=("Keep your elbows a little below shoulder height as you press",),
                avoid=("Letting your elbows flare up above the handles",),
            ),
        },
    ),
    "shoulder_press": MachineCoaching(
        tips=(
            "Brace your core and keep your back flat on the pad",
            "Keep your wrists stacked over your elbows",
            "Breathe out as you press up",
            "Lower until the handles are about shoulder height",
        ),
        avoid=(
            "Arching your lower back to get the weight up",
            "Shrugging your shoulders toward your ears",
            "Snapping into a hard lockout at the top",
            "Letting the weight drop fast on the way down",
        ),
        situational={
            (GRIP, HIGH): Coaching(
                tips=("Bring your elbows slightly forward instead of straight out to the sides",),
                avoid=("Flaring your elbows straight out",),
            ),
            (GRIP, LOW): Coaching(
                tips=("Keep your elbows slightly in front of you",),
                avoid=("Pushing through a pinch in your shoulders. Stop a bit higher instead",),
            ),
            (SEAT, LOW): Coaching(avoid=("Letting the handles sink well below your shoulders at the bottom",)),
            (SEAT, HIGH): Coaching(avoid=("Lifting your hips off the seat to reach the handles",)),
        },
    ),
    "pec_deck": MachineCoaching(
        tips=(
            "Keep a slight bend in your elbows and hold it the whole set",
            "Bring the handles together in a wide arc, like hugging a big tree",
            "Keep your back and head on the pad, chest up",
            "Take about two seconds on the way back",
        ),
        avoid=(
            "Letting the handles pull your arms back further than feels comfortable in your chest",
            "Bending your elbows more to push the weight",
            "Letting your shoulders roll forward as the handles meet",
            "Letting the stack slam between reps",
        ),
        situational={
            (SEAT, HIGH): Coaching(
                tips=("Keep your shoulders down and your upper arms about level with them",),
                avoid=("Shrugging up toward the handles",),
            ),
            (SEAT, LOW): Coaching(
                tips=("Keep your upper arms about level with your shoulders, not higher",),
                avoid=("Letting your elbows ride up above your shoulders",),
            ),
        },
    ),
}

# Any fact the engine can't set up safely replaces the machine's own list.
NO_SOLUTION_COACHING = Coaching(
    tips=("Ask a coach for another exercise that works the same muscles",),
    avoid=("Forcing a machine that doesn't fit you or causes pain",),
)


def _fill(chosen: list[str], general: tuple[str, ...]) -> tuple[str, ...]:
    out = list(dict.fromkeys(chosen))[:CAP]
    for item in general:
        if len(out) >= TARGET:
            break
        if item not in out:
            out.append(item)
    return tuple(out)


def select_coaching(machine_slug: str, facts: list[ExplanationFacts]) -> Coaching:
    """The tips and avoids to show for this setup: situational items matching
    the engine's result first, general ones after."""
    if any(f.verdict in _NO_SOLUTION_STATES for f in facts):
        return NO_SOLUTION_COACHING
    library = COACHING[machine_slug]
    tips: list[str] = []
    avoid: list[str] = []
    for f in facts:
        situational = library.situational.get((f.purpose, f.verdict))
        if situational:
            tips.extend(situational.tips)
            avoid.extend(situational.avoid)
    return Coaching(tips=_fill(tips, library.tips), avoid=_fill(avoid, library.avoid))


def machine_notes(machine_slug: str) -> str | None:
    """The whole general library for one machine, for free-form chat about it."""
    library = COACHING.get(machine_slug)
    if library is None:
        return None
    return "\n".join(
        ["Technique tips:", *(f"- {t}" for t in library.tips), "Things to avoid:", *(f"- {a}" for a in library.avoid)]
    )
