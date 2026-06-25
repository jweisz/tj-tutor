"""Builds the prompt for the free-form 'tutor speech' LLM call -- the actual
words TJBot will say. No JSON constraint here; this call is pure natural
language so even small local models stay fluent and in character."""

from __future__ import annotations

from dataclasses import dataclass

from tutor.evaluator import EvaluatorResult
from tutor.lesson import Concept, LessonPlan
from tutor.llm.base import Message
from tutor.state import ConceptState, Relevance, SessionState

HISTORY_TURNS_FOR_TUTOR = 8  # ~4 exchanges, for natural conversational continuity

TUTOR_PERSONA = """\
You are TJBot, a friendly, curious robot tutor teaching {audience} through
spoken conversation. You speak out loud -- your reply is read aloud by a
text-to-speech engine, so:
- Write the way you'd actually talk to {audience}: short sentences, warm and
  playful tone, no markdown, no bullet points, no asterisks.
- NEVER just tell the student the answer outright, and never recite the "aha
  moment" back to them in your own words either -- that's the same thing
  wearing a disguise. A question that already contains the conclusion, where
  a one-word "yes" just confirms it ("So does that mean light takes time to
  reach us?", "Does it make sense that we're seeing the star's past?"), is
  ALSO the same violation wearing a question mark -- the student supplied
  nothing, you did all the reasoning. Lead them toward the aha moment with
  questions, relatable analogies, and encouragement, so THEY are the one who
  supplies the key idea in their own words, even if it takes a few tries.
- Before you explain anything, ask what THEY think and why. Their theory --
  right, wrong, or half-formed -- is the most useful thing they can give you,
  because it tells you exactly what to nudge next. Respond to the specific
  words they used: build on the part they got right, and gently push on the
  part that's off, rather than replacing their idea wholesale with your own
  explanation.
- Never end a turn with a comprehension check that can only be confirmed, not
  failed -- "Does that make sense?", "Do you understand?", "Right?", or any
  question whose only sensible answer is "yes" to a conclusion you just handed
  them. Ask something that requires them to supply the missing piece, restate
  it in their own words, or apply it to a new case.
- Don't re-explain or restate ground you've already covered together in this
  conversation. Treat what they've already told you as established, and move
  the conversation forward from there.
- Ask ONE question at a time. Never lecture in long paragraphs.
- Keep each reply short: 1-3 sentences, almost always ending in a question
  unless you are celebrating mastery or wrapping up the whole session.

As a worked example of the difference (note: this is about ice and trays, a
different topic from anything you're actually teaching -- just copying its
shape, never its words, no matter what the real topic is):
- BAD: "It's because metal pulls heat out of the ice much faster than wood
  does, so it melts sooner on the metal tray. Does that make sense?" (hands
  them the answer, then asks a question they can't get wrong)
- ALSO BAD: "So since metal pulls heat away faster than wood, does that mean
  the ice melts quicker on the metal tray?" (same answer, just hidden inside a
  question whose only sensible reply is "yes")
- GOOD: "Huh, interesting that they melt at different speeds! What do you
  think is different about the two trays that could be doing that?" (asks for
  their theory instead of supplying one)"""


def _render_concept_context(concept: Concept, state: ConceptState, hint_text: str | None) -> str:
    lines = [
        f"## Current concept: {concept.title} (id: {concept.id})",
        "This is the 'aha moment' you are steering the student toward -- for your own grounding "
        f"only, never say this sentence or a paraphrase of it out loud: {concept.summary}",
        f"Teaching guidance: {concept.teaching_strategy}",
    ]

    met = [c.description for c in concept.mastery_rubric if c.id in state.criteria_met]
    missing = [c.description for c in concept.mastery_rubric if c.id not in state.criteria_met]
    if met:
        lines.append(
            "Already established in their own words this conversation (don't re-teach these, "
            "build on them): " + "; ".join(met)
        )
    if missing:
        lines.append(
            "Still missing -- aim your next question at getting them to reason their way to one "
            "of these specifically: " + "; ".join(missing)
        )

    if not state.evidence_log:
        lines.append(
            f"Opening hook question (this concept hasn't started yet, ask this now): "
            f"{concept.hook_question}"
        )

    if hint_text:
        lines.append(
            f"The student seems stuck. Lean on this hint, without stating the answer outright: {hint_text}"
        )
    return "\n".join(lines)


@dataclass
class TutorSpeechContext:
    """Orchestration flags computed in Orchestrator.run_turn() steps 4-6,
    describing anything special that happened this turn beyond ordinary
    rubric progress."""

    just_mastered: bool = False
    resuming_transition_hint: str | None = None
    session_complete: bool = False


def build_tutor_messages(
    lesson: LessonPlan,
    session: SessionState,
    student_utterance: str,
    evaluator_result: EvaluatorResult,
    context: TutorSpeechContext,
) -> tuple[str, list[Message]]:
    persona = TUTOR_PERSONA.format(audience=lesson.audience)

    if context.session_complete:
        system = "\n\n".join(
            [
                persona,
                "## Session complete",
                f"The student has now mastered all {len(lesson.concepts)} concepts in this lesson. "
                "Deliver this closing message warmly, in your own words, weaving in genuine pride "
                "at what they figured out:",
                lesson.wrap_up_message,
            ]
        )
        history = session.transcript[-HISTORY_TURNS_FOR_TUTOR:]
        return system, [*history, {"role": "user", "content": student_utterance}]

    current = lesson.get_concept(session.current_concept_id)
    state = session.current

    hint_text = None
    if state.stuck_turn_count >= 2:
        hint = current.hint_for_level(state.hint_level)
        hint_text = hint.hint_text if hint else None

    sections = [persona, _render_concept_context(current, state, hint_text)]

    if context.just_mastered:
        sections.append(
            "## Celebrate!\n"
            f"The student just demonstrated they understand this concept. Celebrate warmly and "
            f"specifically, in the spirit of: {current.celebration_cue}"
        )

    if context.resuming_transition_hint:
        sections.append(
            "## Nudge back to an earlier topic\n"
            "Before moving on, gently bring the student back to something they raised earlier but "
            f"didn't finish, using guidance like: {context.resuming_transition_hint}"
        )

    misconception_id = evaluator_result.demonstrates_misconception_id
    if misconception_id:
        misconception = current.get_misconception(misconception_id)
        if misconception:
            sections.append(
                "## Gently correct a misconception\n"
                f"The student's answer suggests this misunderstanding: {misconception.description}. "
                "Don't correct it by stating the right fact -- ask a question that helps them notice "
                f"the gap themselves, without making them feel wrong, in the spirit of: "
                f"{misconception.correction_hook}"
            )

    if evaluator_result.relevance == Relevance.OFF_TOPIC:
        sections.append(
            "## Off-topic remark\n"
            "What the student just said isn't about the concept you're teaching. Briefly and "
            "warmly acknowledge it in a sentence (tangents matter!), then ask a question that "
            "picks the conversation back up from wherever you left off on the current concept -- "
            "don't restart it from scratch."
        )

    system = "\n\n".join(sections)
    history = session.transcript[-HISTORY_TURNS_FOR_TUTOR:]
    return system, [*history, {"role": "user", "content": student_utterance}]
