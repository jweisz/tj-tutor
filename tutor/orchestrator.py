"""The per-turn algorithm. Holds a TutorInterface and never branches on which
concrete frontend it is -- business logic stays self-contained."""

from __future__ import annotations

from tutor.evaluator import EvaluatorResult, build_evaluator_messages
from tutor.feedback import apply_feedback
from tutor.interface import TutorInterface
from tutor.lesson import LessonPlan
from tutor.llm.base import LLMProvider, ProviderError
from tutor.state import ConceptStatus, Evidence, Relevance, SessionState
from tutor.stats import InferenceStats
from tutor.tutor_speech import TUTOR_PERSONA, TutorSpeechContext, build_tutor_messages
from tutor.ui.app import TutorUI

EMPTY_INPUT_REPROMPT = "Sorry, I didn't catch that -- can you say that again?"
TUTOR_FAILURE_FALLBACK = "Hmm, my brain glitched for a second there. Can you say that again?"
STUCK_TURNS_BEFORE_HINT_BUMP = 2


class Orchestrator:
    def __init__(
        self,
        lesson: LessonPlan,
        session: SessionState,
        *,
        evaluator_provider: LLMProvider,
        tutor_provider: LLMProvider,
        interface: TutorInterface,
        stats: InferenceStats,
        ui: TutorUI,
    ) -> None:
        self.lesson = lesson
        self.session = session
        self.evaluator_provider = evaluator_provider
        self.tutor_provider = tutor_provider
        self.interface = interface
        self.stats = stats
        self.ui = ui

    def run_session(self) -> None:
        self._run_opening()
        while not self.session.session_complete:
            self.run_turn()
        self.ui.log_debug("[orchestrator] session complete")

    def _run_opening(self) -> None:
        """Speak an introductory greeting + the first concept's hook question
        before ever listening -- a cold session shouldn't wait for the student
        to speak first."""
        current = self.lesson.get_concept(self.session.current_concept_id)
        system = "\n\n".join(
            [
                TUTOR_PERSONA.format(audience=self.lesson.audience),
                "## Starting the lesson\n"
                f"Greet the student warmly, introduce yourself as TJBot, and briefly say you're "
                f"going to explore {self.lesson.title} together. Then ask this opening question "
                f"to kick things off: {current.hook_question}",
            ]
        )
        response = self.tutor_provider.complete_text(system, [])
        self.stats.record("tutor", response)
        self.interface.speak(response.text)
        self.session.transcript.append({"role": "assistant", "content": response.text})
        self.ui.refresh()

    def run_turn(self) -> None:
        # 1. Listen
        utterance = self.interface.listen()
        if not utterance.strip():
            self.interface.speak(EMPTY_INPUT_REPROMPT)
            return

        # 2. Evaluate (LLM call #1, structured)
        result = self._evaluate(utterance)

        # 3. Branch on relevance + 4. Check mastery
        just_mastered = False
        resuming_transition_hint: str | None = None
        if result.relevance != Relevance.OFF_TOPIC and result.target_concept_id in self.session.concepts:
            self._apply_relevance_branch(result)
            just_mastered, resuming_transition_hint = self._check_mastery()
        else:
            if result.relevance != Relevance.OFF_TOPIC:
                self.ui.log_debug(
                    f"[orchestrator] evaluator gave relevance={result.relevance.value} but "
                    f"target_concept_id={result.target_concept_id!r} is not a known concept; "
                    "treating this turn as off_topic"
                )
                result = EvaluatorResult(relevance=Relevance.OFF_TOPIC, confidence="low")

        # 5. Generate tutor reply (LLM call #2, free text)
        context = TutorSpeechContext(
            just_mastered=just_mastered,
            resuming_transition_hint=resuming_transition_hint,
            session_complete=self.session.session_complete,
        )
        reply_text = self._generate_reply(utterance, result, context)

        # 7. Speak, then physically react (6: misconception/mastery/insight feedback)
        self.interface.speak(reply_text)
        apply_feedback(result, just_mastered=just_mastered, interface=self.interface)

        # 8. Append transcript, advance turn, refresh UI
        self.session.transcript.append({"role": "user", "content": utterance})
        self.session.transcript.append({"role": "assistant", "content": reply_text})
        self.session.turn_index += 1
        self.ui.refresh()

    def _evaluate(self, utterance: str) -> EvaluatorResult:
        system, messages = build_evaluator_messages(self.lesson, self.session, utterance)
        try:
            response = self.evaluator_provider.complete_structured(
                system, messages, response_model=EvaluatorResult
            )
        except ProviderError as exc:
            self.ui.log_debug(f"[evaluator] FAILED, falling back to off_topic: {exc}")
            return EvaluatorResult(relevance=Relevance.OFF_TOPIC, confidence="low")

        result = response.parsed
        assert isinstance(result, EvaluatorResult)
        self.stats.record("evaluator", response)

        # Small/local models reliably signal relevance="current_concept" but often
        # omit target_concept_id, treating "current" as self-evident rather than
        # re-stating the id. We already know what "current" means -- fill it in
        # rather than discarding a turn the model otherwise judged correctly.
        if result.relevance == Relevance.CURRENT_CONCEPT and result.target_concept_id is None:
            result.target_concept_id = self.session.current_concept_id

        self.ui.log_debug(
            f"[evaluator] relevance={result.relevance.value} target={result.target_concept_id} "
            f"criteria_met={result.criteria_met} misconception={result.demonstrates_misconception_id} "
            f"insight={result.demonstrates_insight} confidence={result.confidence}"
        )
        return result

    def _apply_relevance_branch(self, result: EvaluatorResult) -> None:
        target_id = result.target_concept_id
        assert target_id is not None
        if target_id != self.session.current_concept_id:
            # Case (b): the student raised a different target concept -- switch.
            current_state = self.session.current
            if current_state.status != ConceptStatus.MASTERED:
                self.session.push_resume(self.session.current_concept_id)
            if target_id in self.session.resume_stack:
                self.session.resume_stack.remove(target_id)
            self.session.current_concept_id = target_id
            self.ui.log_debug(
                f"[orchestrator] switching current concept -> {target_id!r} "
                f"(resume stack: {self.session.resume_stack})"
            )

        target_state = self.session.current
        if target_state.status in (ConceptStatus.NOT_STARTED, ConceptStatus.PENDING_RESUME):
            target_state.status = ConceptStatus.IN_PROGRESS

        self._apply_evidence(result)

    def _apply_evidence(self, result: EvaluatorResult) -> None:
        state = self.session.current
        newly_met = [c for c in result.criteria_met if c not in state.criteria_met]
        state.criteria_met.update(result.criteria_met)

        student_utterance = self.session.transcript[-1]["content"] if self.session.transcript else ""
        state.evidence_log.append(
            Evidence(
                turn_index=self.session.turn_index,
                student_utterance=student_utterance,
                criteria_met=newly_met,
                notes=f"confidence={result.confidence}",
            )
        )

        if newly_met:
            state.stuck_turn_count = 0
        else:
            state.stuck_turn_count += 1
            if state.stuck_turn_count >= STUCK_TURNS_BEFORE_HINT_BUMP:
                concept = self.lesson.get_concept(state.concept_id)
                state.hint_level = min(state.hint_level + 1, len(concept.hint_ladder) - 1)

    def _check_mastery(self) -> tuple[bool, str | None]:
        current = self.lesson.get_concept(self.session.current_concept_id)
        state = self.session.current
        required_ids = {c.id for c in current.mastery_rubric}

        if state.status == ConceptStatus.MASTERED or not required_ids <= state.criteria_met:
            return False, None

        state.status = ConceptStatus.MASTERED
        self.ui.log_debug(f"[orchestrator] concept mastered: {current.id!r}")

        next_id = self.session.pop_resume()
        resumed_from_stack = next_id is not None
        if next_id is None:
            next_id = self.session.next_unmastered_in_default_order(self.lesson.default_concept_order)

        if next_id is None:
            self.session.session_complete = True
            self.ui.log_debug("[orchestrator] all concepts mastered -- session complete")
            return True, None

        resuming_transition_hint: str | None = None
        if resumed_from_stack:
            link = current.get_cross_link(next_id)
            resuming_transition_hint = (
                link.transition_hint
                if link
                else f"Let's go back to something we talked about earlier: "
                f"{self.lesson.get_concept(next_id).title}."
            )

        self.session.current_concept_id = next_id
        next_state = self.session.concepts[next_id]
        if next_state.status != ConceptStatus.MASTERED:
            next_state.status = ConceptStatus.IN_PROGRESS

        return True, resuming_transition_hint

    def _generate_reply(
        self,
        utterance: str,
        result: EvaluatorResult,
        context: TutorSpeechContext,
    ) -> str:
        system, messages = build_tutor_messages(self.lesson, self.session, utterance, result, context)
        try:
            response = self.tutor_provider.complete_text(system, messages)
        except ProviderError as exc:
            self.ui.log_debug(f"[tutor] FAILED: {exc}")
            return self.lesson.wrap_up_message if context.session_complete else TUTOR_FAILURE_FALLBACK

        self.stats.record("tutor", response)
        return response.text
