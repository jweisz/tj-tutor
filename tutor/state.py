"""Session/concept state mutated every turn. Distinct from tutor/lesson.py
(static content loaded from YAML) because the two have different lifecycles
and consumers -- the bootstrap script needs lesson.py only, never this module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from tutor.lesson import LessonPlan


class ConceptStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PENDING_RESUME = "pending_resume"
    MASTERED = "mastered"


class Relevance(StrEnum):
    CURRENT_CONCEPT = "current_concept"
    OTHER_CONCEPT = "other_concept"
    OFF_TOPIC = "off_topic"


@dataclass
class Evidence:
    turn_index: int
    student_utterance: str
    criteria_met: list[str]
    notes: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ConceptState:
    concept_id: str
    status: ConceptStatus = ConceptStatus.NOT_STARTED
    criteria_met: set[str] = field(default_factory=set)
    evidence_log: list[Evidence] = field(default_factory=list)
    hint_level: int = 0
    stuck_turn_count: int = 0


@dataclass
class SessionState:
    lesson_id: str
    concepts: dict[str, ConceptState]
    current_concept_id: str
    resume_stack: list[str] = field(default_factory=list)
    turn_index: int = 0
    session_complete: bool = False
    # Full message history, shared across both LLM call types for conversation
    # context / cache continuity. Each entry: {"role": "user"|"assistant", "content": str}.
    transcript: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls, lesson: LessonPlan) -> "SessionState":
        if not lesson.default_concept_order:
            raise ValueError(f"lesson {lesson.id!r} has an empty default_concept_order")
        concepts = {concept.id: ConceptState(concept_id=concept.id) for concept in lesson.concepts}
        first_id = lesson.default_concept_order[0]
        concepts[first_id].status = ConceptStatus.IN_PROGRESS
        return cls(lesson_id=lesson.id, concepts=concepts, current_concept_id=first_id)

    @property
    def current(self) -> ConceptState:
        return self.concepts[self.current_concept_id]

    def push_resume(self, concept_id: str) -> None:
        if concept_id not in self.resume_stack:
            self.resume_stack.append(concept_id)
        self.concepts[concept_id].status = ConceptStatus.PENDING_RESUME

    def pop_resume(self) -> str | None:
        if not self.resume_stack:
            return None
        return self.resume_stack.pop()

    def next_unmastered_in_default_order(self, default_concept_order: list[str]) -> str | None:
        for concept_id in default_concept_order:
            if self.concepts[concept_id].status != ConceptStatus.MASTERED:
                return concept_id
        return None
