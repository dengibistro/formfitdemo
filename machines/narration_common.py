"""Provider-neutral pieces shared by every AI narration backend.

No SDK calls here, no provider-specific code — just the trainer persona and
the fact-block formatting, so `ai_narration.py` (Claude) and
`ai_narration_gemini.py` (Gemini) narrate identically and can't drift apart.
The hard boundary (only narrate given facts, never invent biomechanics) is
enforced by the wording of `SYSTEM_PROMPT`, not by either provider's code.
"""

import re

from machines.coaching import Coaching
from machines.explanations import ExplanationFacts

# Plain-language statement of which physical extreme a clamp verdict landed
# on. The model has no reliable way to infer this from a raw pin number —
# pin 1 is the machine's HIGHEST setting on an Inverted axis (e.g. Chest
# Press seat) but the LOWEST on a Direct one. Observed failure mode without
# this: the model guessed "pin 1 = lowest" and got the direction backwards.
_EXTREME_BY_VERDICT = {
    "clamped_low": "this IS the machine's MINIMUM available setting for this axis",
    "clamped_high": "this IS the machine's MAXIMUM available setting for this axis",
    "clamped_by_coupling": "this is the safest achievable compromise given a coupled hip/knee constraint, not a simple min/max clamp",
}

SYSTEM_PROMPT = """\
You are FormFit's in-app personal trainer. You chat with a user one exercise \
at a time, like a coach texting a client. You are not a form that spits out \
numbers.

For each machine setup you get a block of STRUCTURED FACTS (not prose) with \
exactly what the engine computed: which machine, which axis, the verdict, \
which body measurement drove the result, how far the achieved position is \
from the ideal one, which pin was set, and what that axis is there to protect.

Hard rules:
1. Only state facts that are in the data. Never invent or guess a joint \
angle, a measurement, or a biomechanical claim you weren't given. If the \
facts don't explain something, say so plainly instead of filling the gap.
2. For an "in_range" verdict: confirm it briefly.
3. For a "clamped_low", "clamped_high" or "clamped_by_coupling" verdict: \
explain why, using the specific body measurement and gap you were given. Say \
which position was set as the best option. Frame it as the machine's limit for their proportions, never as \
something wrong with their body.
4. For a "no_solution" or "no_solution_by_coupling" verdict: be honest that \
this machine can't be set up safely for them right now. Say the machine \
doesn't fit their build for this exercise, not that they don't fit. Don't \
name a specific alternative machine. Just say a substitute is worth asking a \
coach about.
5. Keep replies short. A few sentences, like a text message.
6. If the user just finished another machine, you can mention it, but you \
don't have to, and never open the same way twice in a row. Mix it up: \
sometimes lead with it ("Nice work on Shoulder Press. Now Chest Press:"), \
sometimes work it in ("Since you're coming off Shoulder Press, here's Chest \
Press."), sometimes a quick aside ("Chest Press next, let's get you set \
up."), and sometimes skip it and go straight to the setup. If your last few \
replies started with "Nice work on...", pick something else.
7. Never repeat raw field names or codes like "CLAMPED_HIGH" or \
"causing_segment". Put them in plain words.
7b. If a fact block has an "alternative pin" line, give both pins and \
include its "cue for the user" so they can check which one fits in person. \
Any "cue for the user" line has to appear in your WHY line. It's a \
concrete instruction from the engine, not optional.
8. The pin number alone does NOT tell you whether it's the machine's high or \
low end, because different machines number their holes in opposite \
directions. Only trust the explicit "this IS the machine's MAXIMUM/MINIMUM" \
line and the "gap" line for direction. Never say "furthest", "closest", \
"highest" or "lowest" based on the pin number by itself.
9. This format is ONLY for narrating a fresh block of STRUCTURED FACTS (a \
new machine setup). Ordinary follow-up questions with no facts block get a \
normal conversational answer. For a facts-narration reply, use EXACTLY these \
three lines, with nothing before, between or after them and no other \
headings:
WHY: <your explanation in a friendly trainer voice, covering every axis you \
were given. A couple of sentences is fine, but keep it on this one line (no \
line breaks inside it). No technique advice here, that's what TIPS is for>
TIPS: <approved tip 1>|<approved tip 2>
AVOID: <approved avoid 1>|<approved avoid 2>
TIPS and AVOID come ONLY from the "APPROVED TIPS" and "APPROVED AVOID" \
lists in the message: the same number of items, in the same order, each one \
rephrased in your own words with exactly the same meaning. Don't add, drop, \
merge, soften or extend any item. Separate items with "|".
10. Write like a real person texting. Never use em dashes or en dashes \
between words; use a period, a comma or a colon instead. Skip filler like \
"Great question", "Absolutely", "Let's dive in" or "I hope this helps". \
Plain words, short sentences.
11. Technique and safety advice ONLY comes from approved notes: the \
approved tips and avoids you were given in this conversation, or \
"approved technique notes" attached to a message. In follow-up chat, if a \
question about technique, sets, reps, weight or exercise choice isn't \
covered by those notes, say honestly that it's a good one for a coach and \
don't answer it yourself. If they mention pain or an injury, tell them to \
stop that exercise and check with a coach.
"""


# Spaced em/en dash between words (" — ", " – "). Number ranges like "2–3"
# have no spaces around the dash, so they're left alone.
_SPACED_DASH = re.compile(r"\s+[—–]\s+")


def strip_dashes(text: str) -> str:
    """Safety net for model replies: rule 10 asks for no dashes, but models
    slip. Swaps a spaced dash for a comma, which reads naturally in almost
    every case and doesn't look machine-written."""
    return _SPACED_DASH.sub(", ", text)


def facts_to_context_block(facts: ExplanationFacts) -> str:
    """Render one ExplanationFacts as a compact, labeled fact block —
    grounding data for the model, not a sentence it should copy verbatim.

    Deliberately spells out direction in plain language (which extreme was
    hit, which way the gap runs) instead of handing the model a bare pin
    number and a signed "residual" — those require inferring this axis's
    Direct/Inverted numbering convention, which the model has no way to
    know and was observed getting backwards (see _EXTREME_BY_VERDICT).
    """
    lines = [
        f"machine: {facts.machine_name or 'unknown'}",
        f"axis: {facts.axis_name}",
        f"verdict: {facts.verdict.value}",
    ]
    if facts.purpose_description:
        lines.append(f"this axis protects: {facts.purpose_description}")
    if facts.causing_segment:
        lines.append(f"driven by body measurement: {facts.causing_segment}")

    extreme = _EXTREME_BY_VERDICT.get(facts.verdict.value)
    if extreme and facts.achieved_pin is None:
        # Fixed hardware (e.g. Shoulder Press grip): nothing to set, so no "maximum setting".
        lines.append("this part is FIXED and can't be adjusted; the gap below is how far it is from ideal for this body")
    elif extreme:
        lines.append(extreme)

    if facts.residual_mm is not None:
        magnitude = abs(facts.residual_mm)
        if facts.residual_mm > 0.05:
            gap = f"the numerically ideal value was actually SMALLER than what got set, by {magnitude:.1f}mm"
        elif facts.residual_mm < -0.05:
            gap = f"the numerically ideal value was actually LARGER than what got set, by {magnitude:.1f}mm"
        else:
            gap = "the achieved position matches the ideal value almost exactly"
        lines.append(f"gap: {gap}")

    if facts.achieved_pin is not None:
        lines.append(
            f"set to pin: {facts.achieved_pin} (do not infer high/low from this number alone, see the line above)"
        )
    if facts.alternative_pin is not None:
        lines.append(
            f"alternative pin: {facts.alternative_pin} (the scan can't fully separate these two. "
            "Give the set pin first, the alternative second)"
        )
    if facts.achieved_coordinate_mm is not None:
        lines.append(f"achieved coordinate: {facts.achieved_coordinate_mm:.1f}mm")
    lines.append(f"confidence: {facts.confidence.value}")
    if facts.user_cue:
        lines.append(f"cue for the user (must be passed on, in your own words): {facts.user_cue}")
    return "\n".join(lines)


def setup_context_message(
    facts: list[ExplanationFacts],
    just_finished_machine: str | None = None,
    coaching: Coaching | None = None,
) -> str:
    """The full user-turn text for narrating one or more axis results,
    shared verbatim by both provider backends. `coaching` is the approved
    tips/avoids for TIPS and AVOID (machines/coaching.py's select_coaching)."""
    parts = []
    if just_finished_machine:
        parts.append(f"The user just finished: {just_finished_machine}.")
    parts.append("New machine setup facts:")
    for f in facts:
        parts.append("---\n" + facts_to_context_block(f))
    if coaching is not None:
        parts.append("---\nAPPROVED TIPS (rephrase each, same meaning, same order):")
        parts.extend(f"{i}. {t}" for i, t in enumerate(coaching.tips, 1))
        parts.append("APPROVED AVOID (rephrase each, same meaning, same order):")
        parts.extend(f"{i}. {a}" for i, a in enumerate(coaching.avoid, 1))
    return "\n".join(parts)


def chat_message_with_notes(user_message: str, notes: str | None, machine_label: str | None) -> str:
    """Free-form chat turn with the approved technique notes for the user's
    last machine attached, so the model answers technique questions from
    them (prompt rule 11) instead of from its own knowledge."""
    if not notes:
        return user_message
    return f"(Approved technique notes for {machine_label}:\n{notes})\n\nUser: {user_message}"


_LINE = re.compile(r"^(WHY|TIPS|AVOID):\s*(.*)$", re.M)


def enforce_coaching(reply: str, coaching: Coaching) -> str:
    """Make sure a setup reply's TIPS/AVOID are the approved ones. The model
    is asked to rephrase them; if it returns the wrong number of items or
    drops the lines, the approved text goes in verbatim instead. A reply
    that ignored the WHY/TIPS/AVOID format entirely becomes the WHY line."""
    found = {m.group(1): m.group(2).strip() for m in _LINE.finditer(reply)}
    why = found.get("WHY") or " ".join(reply.split())

    def items(key: str) -> list[str]:
        return [x.strip() for x in found.get(key, "").split("|") if x.strip()]

    tips = items("TIPS")
    avoid = items("AVOID")
    if len(tips) != len(coaching.tips):
        tips = list(coaching.tips)
    if len(avoid) != len(coaching.avoid):
        avoid = list(coaching.avoid)
    return f"WHY: {why}\nTIPS: {'|'.join(tips)}\nAVOID: {'|'.join(avoid)}"
