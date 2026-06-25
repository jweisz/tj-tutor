"""Lesson plan schema — the single source of truth used by both the runtime
loader and the bootstrap script's validation."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class HintLevel(BaseModel):
    level: int
    hint_text: str  # guidance for the tutor LLM, not a verbatim script


class MasteryCriterion(BaseModel):
    id: str
    description: str
    example_phrases: list[str] = Field(default_factory=list)


class Misconception(BaseModel):
    id: str
    description: str
    correction_hook: str


class CrossLink(BaseModel):
    concept_id: str
    # Reused for both natural transitions and pending-resume nudges.
    transition_hint: str


class Concept(BaseModel):
    id: str
    # Free-form category label (e.g. "space", "fractions", "the French Revolution")
    # -- organizational/display context only, never branched on in code.
    domain: str
    title: str
    summary: str
    hook_question: str
    teaching_strategy: str
    misconceptions: list[Misconception] = Field(default_factory=list)
    mastery_rubric: list[MasteryCriterion]
    hint_ladder: list[HintLevel]
    celebration_cue: str
    relates_to: list[CrossLink] = Field(default_factory=list)

    def get_misconception(self, misconception_id: str) -> Misconception | None:
        return next((m for m in self.misconceptions if m.id == misconception_id), None)

    def get_cross_link(self, concept_id: str) -> CrossLink | None:
        return next((c for c in self.relates_to if c.concept_id == concept_id), None)

    def hint_for_level(self, level: int) -> HintLevel | None:
        if not self.hint_ladder:
            return None
        clamped = max(0, min(level, len(self.hint_ladder) - 1))
        return self.hint_ladder[clamped]


class LessonPlan(BaseModel):
    id: str
    title: str
    audience: str
    default_concept_order: list[str]
    concepts: list[Concept]
    wrap_up_message: str

    def get_concept(self, concept_id: str) -> Concept:
        for concept in self.concepts:
            if concept.id == concept_id:
                return concept
        raise KeyError(
            f"lesson {self.id!r} has no concept with id {concept_id!r}; "
            f"known ids: {[c.id for c in self.concepts]}"
        )

    @model_validator(mode="after")
    def _check_cross_references(self) -> "LessonPlan":
        known_ids = {c.id for c in self.concepts}
        for concept_id in self.default_concept_order:
            if concept_id not in known_ids:
                raise ValueError(
                    f"default_concept_order references unknown concept id {concept_id!r}"
                )
        for concept in self.concepts:
            for link in concept.relates_to:
                if link.concept_id not in known_ids:
                    raise ValueError(
                        f"concept {concept.id!r} has relates_to entry pointing at "
                        f"unknown concept id {link.concept_id!r}"
                    )
        return self


class ConceptSeed(BaseModel):
    """Lightweight authoring input: just enough for an LLM to expand into a
    full Concept. See scripts/bootstrap_lesson.py."""

    id: str
    domain: str
    title: str
    summary: str
    relates_to_ids: list[str] = Field(default_factory=list)


class LessonSeed(BaseModel):
    id: str
    title: str
    audience: str
    wrap_up_message: str
    concepts: list[ConceptSeed]

    @model_validator(mode="after")
    def _check_relates_to_ids(self) -> "LessonSeed":
        known_ids = {c.id for c in self.concepts}
        for concept in self.concepts:
            for related_id in concept.relates_to_ids:
                if related_id not in known_ids:
                    raise ValueError(
                        f"seed concept {concept.id!r} has relates_to_ids entry pointing "
                        f"at unknown concept id {related_id!r}"
                    )
        return self
