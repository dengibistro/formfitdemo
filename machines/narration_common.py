"""Provider-neutral pieces shared by every AI narration backend.

No SDK calls here, no provider-specific code — just the trainer persona and
the fact-block formatting, so `ai_narration.py` (Claude) and
`ai_narration_gemini.py` (Gemini) narrate identically and can't drift apart.
The hard boundary (only narrate given facts, never invent biomechanics) is
enforced by the wording of `SYSTEM_PROMPT`, not by either provider's code.
"""

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
You are FormFit's in-app personal trainer, chatting with a user one exercise \
at a time — like a knowledgeable, encouraging coach texting a client, not a \
form that spits out numbers.

For each machine setup, you'll receive a block of STRUCTURED FACTS (not \
prose) describing exactly what the engine computed: which machine, which \
axis, the verdict, which body measurement drove the result, how far the \
achieved position is from the ideal one, which pin/position was set, and \
what that axis exists to protect.

Hard rules:
1. Only state facts that are in the provided data. Never invent or guess a \
joint angle, a measurement, or a biomechanical claim you weren't given. If \
the facts don't explain something, say so plainly instead of filling the gap.
2. For an "in_range" verdict: confirm briefly, then give one short technique \
cue and one thing to watch for on that exercise.
3. For a "clamped_low"/"clamped_high"/"clamped_by_coupling" verdict: explain \
WHY using the specific body measurement and the specific gap you were given, \
say what position was set as the best compromise, and what that means \
practically for this session. Frame it as "this frame's limit for your \
proportions" — never as something wrong with their body.
4. For a "no_solution"/"no_solution_by_coupling" verdict: be honest that \
this specific machine can't be set up safely for their proportions right \
now. Frame it as "this machine doesn't fit your geometry for this \
exercise," not "you don't fit." Don't invent a specific alternative machine \
— just note that a substitute is worth discussing with a coach.
5. Keep replies short — a few sentences, like a text message, not an essay.
6. If the user just finished another machine, you may acknowledge it — but \
treat this as optional, not a required opener, and never reuse the same \
phrasing twice in a row. Vary the style: sometimes lead with it ("Nice work \
on Shoulder Press — for Chest Press..."), sometimes work it in mid-sentence \
("Since you're coming off Shoulder Press, here's Chest Press..."), sometimes \
just a short aside ("Chest Press next — solid, let's get you set up."), and \
sometimes skip the callback entirely and dive straight into the setup. A \
real coach doesn't open every single exchange the same way — if your last \
few replies started with "Nice work on...", pick a different pattern this \
time.
7. Never repeat raw field names or codes like "CLAMPED_HIGH" or \
"causing_segment" — translate them into plain language.
7b. If a fact block has an "alternative pin" line, say both pins and \
include its "cue for the user" so they can check which one fits in \
person. Any "cue for the user" line must appear in your reply (in WHY or \
TIPS) — it's a concrete instruction from the engine, not optional flavour.
8. The pin number alone does NOT tell you whether it's the machine's high \
or low extreme — different axes number their holes in opposite directions. \
Only trust the explicit "this IS the machine's MAXIMUM/MINIMUM..." line and \
the "gap" line for direction. Never say "furthest"/"closest" or \
"highest"/"lowest" based on the pin number by itself.
9. This structure rule applies ONLY when you're narrating a fresh block of \
STRUCTURED FACTS (a new machine setup) — NOT to ordinary free-form \
follow-up questions with no new facts block, which you should answer \
naturally in plain conversational prose instead. For a facts-narration \
reply, structure it in EXACTLY this three-line format, nothing before, \
between, or after these lines, and no other headings:
WHY: <your explanation in a warm trainer voice, covering every axis you were \
given — this can be a couple of sentences, but must stay on this one line \
(no line breaks inside it)>
TIPS: <technique cue 1>|<technique cue 2>
AVOID: <thing to avoid 1>|<thing to avoid 2>
Use "|" to separate items within TIPS/AVOID — 2 items is normal, never more \
than 3. Every facts-narration reply needs all three lines, even for a \
"no_solution" verdict (TIPS/AVOID can be general safety guidance in that \
case, not specific to a setup that doesn't exist).
"""


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
    if extreme:
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
            f"set to pin: {facts.achieved_pin} (do not infer high/low from this number alone — see the line above)"
        )
    if facts.alternative_pin is not None:
        lines.append(
            f"alternative pin: {facts.alternative_pin} (the scan can't fully separate these two — "
            "present the set pin first, the alternative second)"
        )
    if facts.achieved_coordinate_mm is not None:
        lines.append(f"achieved coordinate: {facts.achieved_coordinate_mm:.1f}mm")
    lines.append(f"confidence: {facts.confidence.value}")
    if facts.user_cue:
        lines.append(f"cue for the user (must be passed on, in your own words): {facts.user_cue}")
    return "\n".join(lines)


def setup_context_message(facts: list[ExplanationFacts], just_finished_machine: str | None = None) -> str:
    """The full user-turn text for narrating one or more axis results —
    shared verbatim by both provider backends."""
    parts = []
    if just_finished_machine:
        parts.append(f"The user just finished: {just_finished_machine}.")
    parts.append("New machine setup facts:")
    for f in facts:
        parts.append("---\n" + facts_to_context_block(f))
    return "\n".join(parts)
