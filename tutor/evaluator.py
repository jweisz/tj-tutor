"""The structured 'evaluator' LLM call: classifies the student's utterance's
relevance and judges it against the current concept's mastery rubric. One
call carries both jobs -- no separate relevance-classification call."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

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


def evaluator_result_model(lesson: LessonPlan) -> type[EvaluatorResult]:
    """A lesson-specific EvaluatorResult whose id fields are enums of the lesson's
    actual concept/criterion/misconception ids. Grammar-constrained backends then
    can't emit an invalid id at all -- small models otherwise put criterion ids in
    target_concept_id, or write things like "null" or "misconception id: x" into
    criteria_met. Instances are still EvaluatorResults, so callers don't change."""
    concept_ids = [c.id for c in lesson.concepts]
    criterion_ids = [r.id for c in lesson.concepts for r in c.mastery_rubric]
    misconception_ids = [m.id for c in lesson.concepts for m in c.misconceptions]
    base_fields = EvaluatorResult.model_fields

    def enum(ids: list[str]) -> Any:
        return Literal[tuple(ids)]  # type: ignore[valid-type]

    overrides: dict[str, Any] = {
        "target_concept_id": (
            enum(concept_ids) | None,
            Field(default=None, description=base_fields["target_concept_id"].description),
        ),
    }
    if criterion_ids:
        overrides["criteria_met"] = (
            list[enum(criterion_ids)],  # type: ignore[misc]
            Field(default_factory=list, description=base_fields["criteria_met"].description),
        )
    if misconception_ids:
        overrides["demonstrates_misconception_id"] = (
            enum(misconception_ids) | None,
            Field(default=None, description=base_fields["demonstrates_misconception_id"].description),
        )
    return create_model("EvaluatorResult", __base__=EvaluatorResult, **overrides)


EVALUATOR_PERSONA = """\
You are the evaluation module for a Socratic tutor for {audience}.
You never speak to the student and you never teach. Your only job is to read the
student's latest message and produce a structured judgment about it: which topic
it's about, and whether it provides evidence the student understands a concept.

## Step 1: relevance -- decide in this order

1. off_topic: the message is not about the ideas in any of the lesson's concepts.
   Small talk, food, pets, games, the student's day, feelings, questions about the
   tutor, and requests to do something else are all off_topic. Young children say
   things like this often, so off_topic is a common, perfectly normal judgment.
   Never stretch to connect an unrelated message to a concept.
2. Otherwise, compare the message's main idea against EVERY concept's summary
   (the current one and the others listed below) and pick the closest match:
   - current_concept: it best matches the concept currently being taught, or it
     answers the tutor's question -- including wrong answers, guesses,
     misconceptions, partial ideas, and "I don't know".
   - other_concept: its main idea clearly matches one of the OTHER concepts'
     summaries better than the current one -- even if it mentions words from
     the current concept too.

## Step 2: target_concept_id

The id of the concept the message is about, copied EXACTLY from the "concept id"
values listed below: {concept_ids}. Use the current concept's id for
current_concept, the other concept's id for other_concept, and null for
off_topic. Criterion ids and misconception ids are NOT concept ids -- never put
them in target_concept_id.

## Step 3: evidence

Be conservative about marking criteria_met -- only mark a criterion when the
student's own words clearly demonstrate the understanding, not just that the
message touched on the topic. Only use criterion ids listed under the target
concept. A student often says something partially right; partial credit belongs
in demonstrates_insight, not in criteria_met. If the message expresses one of
the known misconceptions -- even as a confident answer -- set
demonstrates_misconception_id to its id. Leave everything empty/null for
off_topic messages."""


def _render_current_concept(concept: Concept) -> str:
    lines = [
        f"## Currently teaching -- concept id: {concept.id}",
        f"Title: {concept.title}",
        f"Summary: {concept.summary}",
        "",
        "Mastery criteria (copy criterion ids EXACTLY and bare, e.g. just "
        f"{concept.mastery_rubric[0].id}):",
    ]
    for criterion in concept.mastery_rubric:
        lines.append(f"- criterion id: {criterion.id}")
        lines.append(f"  description: {criterion.description}")
        if criterion.example_phrases:
            examples = "; ".join(criterion.example_phrases)
            lines.append(f"  example phrasings that would satisfy this: {examples}")
    if concept.misconceptions:
        lines.append("")
        lines.append("Known misconceptions (copy misconception ids bare, same rule):")
        for m in concept.misconceptions:
            lines.append(f"- misconception id: {m.id}")
            lines.append(f"  description: {m.description}")
    return "\n".join(lines)


def _render_sibling_concepts(siblings: list[Concept]) -> str:
    # Sibling rubric ids are listed so a correct other_concept judgment can report
    # criteria from the right rubric instead of inventing ids.
    lines = ["## Other concepts in this lesson (only for other_concept messages)"]
    for concept in siblings:
        lines.append(f"- concept id: {concept.id}")
        lines.append(f"  title: {concept.title}")
        lines.append(f"  summary: {concept.summary}")
        criteria = "; ".join(f"{c.id} ({c.description})" for c in concept.mastery_rubric)
        lines.append(f"  criterion ids: {criteria}")
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
        EVALUATOR_PERSONA.format(
            audience=lesson.audience,
            concept_ids=", ".join(c.id for c in lesson.concepts),
        ),
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
