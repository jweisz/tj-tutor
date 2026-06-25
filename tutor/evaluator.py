"""The structured 'evaluator' LLM call: classifies the student's utterance's
relevance and judges it against the current concept's mastery rubric. One
call carries both jobs -- no separate relevance-classification call."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from tutor.lesson import Concept, LessonPlan
from tutor.llm.base import Message
from tutor.state import Relevance, SessionState

HISTORY_TURNS_FOR_EVALUATOR = 0  # rubric judgment is about the latest utterance alone --
# verified empirically that even one prior message measurably degrades small local
# models' criteria_met extraction (history adds noise this narrow task doesn't need;
# the system prompt already carries the full rubric + concept context every turn).


class EvaluatorResult(BaseModel):
    relevance: Relevance = Field(
        description=(
            "current_concept if the utterance is about the concept currently being taught; "
            "other_concept if it is clearly about a DIFFERENT one of the listed target concepts; "
            "off_topic if it isn't substantively about any of the target concepts at all."
        )
    )
    target_concept_id: str | None = Field(
        default=None,
        description=(
            "The id of the concept this utterance bears on. Required (non-null) when relevance "
            "is current_concept or other_concept. Must be null when relevance is off_topic."
        ),
    )
    criteria_met: list[str] = Field(
        default_factory=list,
        description=(
            "Mastery-criterion ids (from target_concept_id's rubric) that this utterance, on its "
            "own, provides clear evidence the student has grasped. Leave empty if none apply yet -- "
            "do not guess generously."
        ),
    )
    demonstrates_misconception_id: str | None = Field(
        default=None,
        description="The id of a known misconception this utterance reveals, or null if none.",
    )
    demonstrates_insight: bool = Field(
        default=False,
        description=(
            "True if this single utterance shows a notable spark of understanding worth "
            "acknowledging, even if it doesn't fully satisfy a rubric criterion yet."
        ),
    )
    confidence: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="Your own confidence in this judgment.",
    )


EVALUATOR_PERSONA = """\
You are the evaluation module for a Socratic tutor for {audience}.
You never speak to the student and you never teach. Your only job is to read the
student's latest message and produce a structured judgment about it: which topic
it's about, and whether it provides evidence the student understands the concept
currently being taught.

Be conservative about marking criteria_met -- only mark a criterion when the
student's own words clearly demonstrate the understanding, not just that the
question touched on the topic. A student often says something partially right;
partial credit belongs in demonstrates_insight, not in criteria_met.

IMPORTANT rule for target_concept_id: read the student's message and decide
which ONE of the listed concepts it is actually about, by content -- do not
default to whichever concept happens to be "currently teaching" just because
it's listed first or described in more detail. If the message is clearly
about one of the "other" concepts instead, you MUST set relevance to
other_concept AND set target_concept_id to that other concept's exact id
(never leave target_concept_id null when relevance is other_concept)."""


def _render_current_concept(concept: Concept) -> str:
    lines = [
        f"## Currently teaching: {concept.title} (id: {concept.id})",
        f"Summary: {concept.summary}",
        "",
        "Mastery rubric (the only criteria you may report as met -- copy these id values",
        "EXACTLY and bare, with no quotes and no 'id=' prefix, e.g. just light_takes_time):",
    ]
    for criterion in concept.mastery_rubric:
        lines.append(f'- criterion_id: "{criterion.id}"')
        lines.append(f"  description: {criterion.description}")
        if criterion.example_phrases:
            examples = "; ".join(criterion.example_phrases)
            lines.append(f"  example phrasings that would satisfy this: {examples}")
    if concept.misconceptions:
        lines.append("")
        lines.append("Known misconceptions for this concept (copy misconception_id bare, same rule):")
        for m in concept.misconceptions:
            lines.append(f'- misconception_id: "{m.id}"')
            lines.append(f"  description: {m.description}")
    return "\n".join(lines)


def _render_sibling_concepts(siblings: list[Concept]) -> str:
    lines = [
        "## Other target concepts in this lesson (for relevance classification only -- copy "
        "concept_id values EXACTLY and bare, with no quotes):"
    ]
    for concept in siblings:
        lines.append(f'- concept_id: "{concept.id}", title: "{concept.title}": {concept.summary}')
    return "\n".join(lines)


def build_evaluator_messages(
    lesson: LessonPlan,
    session: SessionState,
    student_utterance: str,
) -> tuple[str, list[Message]]:
    current = lesson.get_concept(session.current_concept_id)
    siblings = [c for c in lesson.concepts if c.id != current.id]

    # The last tutor question is essential context for interpreting short or
    # fragmented student answers.  Without it, "a longer ago past" is opaque;
    # with it, the evaluator knows it's a direct correct answer to "do farther
    # stars show a more recent or longer-ago past?" and can credit the criterion.
    last_tutor_q = next(
        (m["content"] for m in reversed(session.transcript) if m["role"] == "assistant"),
        None,
    )

    sections = [
        EVALUATOR_PERSONA.format(audience=lesson.audience),
        _render_current_concept(current),
        _render_sibling_concepts(siblings),
    ]
    if last_tutor_q:
        sections.append(
            "## What the tutor just asked (what the student is directly responding to)\n"
            f"{last_tutor_q}\n\n"
            "Short or fragment answers must be judged in this context. If the fragment is a "
            "direct, correct answer to the question above, credit the relevant criterion -- "
            "e.g. 'a longer ago past' as an answer to 'do farther stars show a more recent "
            "or longer-ago past?' clearly demonstrates distance_means_older_light."
        )

    system = "\n\n".join(sections)
    messages: list[Message] = [{"role": "user", "content": student_utterance}]
    return system, messages
