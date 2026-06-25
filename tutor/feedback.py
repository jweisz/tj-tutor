"""Maps evaluator/orchestrator signals to physical TJBot feedback. Fired by
deterministic Python logic, never by asking the LLM "should I shine now" --
the dialogue is fully LLM-driven, the robot control is not."""

from __future__ import annotations

from tutor.evaluator import EvaluatorResult
from tutor.interface import TutorInterface

MASTERY_COLOR = "gold"
MISCONCEPTION_COLOR = "orange"
MISCONCEPTION_PULSE_SECONDS = 0.8
INSIGHT_COLOR = "#33CC66"  # soft green
INSIGHT_PULSE_SECONDS = 0.6


def apply_feedback(
    evaluator_result: EvaluatorResult,
    *,
    just_mastered: bool,
    interface: TutorInterface,
) -> None:
    """At most one physical reaction per turn, in priority order. Silence on
    an ordinary turn is meaningful too -- it avoids feedback fatigue from
    flashing on every single exchange."""
    if just_mastered:
        interface.shine(MASTERY_COLOR)
        interface.wave()
        return

    if evaluator_result.demonstrates_misconception_id is not None:
        interface.pulse(MISCONCEPTION_COLOR, MISCONCEPTION_PULSE_SECONDS)
        return

    if evaluator_result.demonstrates_insight:
        interface.pulse(INSIGHT_COLOR, INSIGHT_PULSE_SECONDS)
