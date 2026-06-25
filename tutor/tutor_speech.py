"""Builds the prompt for the free-form 'tutor speech' LLM call -- the actual
words TJBot will say. No JSON constraint here; this call is pure natural
language so even small local models stay fluent and in character."""

from __future__ import annotations

from dataclasses import dataclass

from tutor.evaluator import EvaluatorResult
from tutor.lesson import Concept, LessonPlan
from tutor.llm.base import Message
from tutor.state import Relevance, SessionState

HISTORY_TURNS_FOR_TUTOR = 8  # ~4 exchanges, for natural conversational continuity

TUTOR_PERSONA = """\
You are TJBot, a friendly, curious robot tutor teaching {audience} through
spoken conversation. You speak out loud -- your reply is read aloud by a
text-to-speech engine, so:
- Write the way you'd actually talk to {audience}: short sentences, warm and
  playful tone, no markdown, no bullet points, no asterisks.
- Ask ONE guiding question at a time. Never lecture in long paragraphs.
- NEVER just tell the student the answer outright. Lead them toward the "aha
  moment" with questions, relatable analogies, and encouragement -- the goal is
  for THEM to figure it out, even if it takes a few tries.
- Keep each reply short: 1-3 sentences, almost always ending in a question
  unless you are celebrating mastery or wrapping up the whole session."""


def _render_concept_context(concept: Concept, hint_text: str | None) -> str:
    lines = [
        f"## Current concept: {concept.title} (id: {concept.id})",
        f"The 'aha moment' you are steering the student toward: {concept.summary}",
        f"Teaching guidance: {concept.teaching_strategy}",
        f"Opening hook question (use near the start of this concept): {concept.hook_question}",
    ]
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

    sections = [persona, _render_concept_context(current, hint_text)]

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
                f"Address it kindly, without making them feel wrong, using guidance like: "
                f"{misconception.correction_hook}"
            )

    if evaluator_result.relevance == Relevance.OFF_TOPIC:
        sections.append(
            "## Off-topic remark\n"
            "What the student just said isn't about the concept you're teaching. Briefly and "
            "warmly acknowledge it in a sentence (tangents matter!), then steer the "
            "conversation back to the current concept with a question."
        )

    system = "\n\n".join(sections)
    history = session.transcript[-HISTORY_TURNS_FOR_TUTOR:]
    return system, [*history, {"role": "user", "content": student_utterance}]
