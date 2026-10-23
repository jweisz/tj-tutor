#!/usr/bin/env python3
"""Regression suite for the structured evaluator call: runs a fixed set of
student utterances through build_evaluator_messages + the lesson-specific
EvaluatorResult schema against any provider, and scores the result the way the
orchestrator would act on it. Use it to compare models, or to check that an
evaluator prompt change doesn't regress small local models.

The cases are written for lessons/space_basics.yaml, with the tutor having
just asked the first concept's hook question."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor.evaluator import build_evaluator_messages, evaluator_result_model  # noqa: E402
from tutor.lesson import LessonPlan  # noqa: E402
from tutor.lesson_loader import load_lesson  # noqa: E402
from tutor.llm.factory import ProviderConfig, build_provider  # noqa: E402
from tutor.state import SessionState  # noqa: E402

LESSON_PATH = Path(__file__).resolve().parent.parent / "lessons" / "space_basics.yaml"
LOOKING_BACK, STARS, YEAR = "looking_back_in_time", "stars_are_suns", "a_year_is_an_orbit"
CURRENT, OTHER, OFF = "current_concept", "other_concept", "off_topic"

# (utterance, acceptable (relevance, target) routes, expected misconception).
# Expected misconception: None = must not report a wrong one; "any" = no
# expectation; an id = must report exactly that one.
CASES: list[tuple[str, set[tuple[str, str | None]], str | None]] = [
    ("because light is faster than sound!", {(CURRENT, LOOKING_BACK)}, None),
    ("the light has to travel to us first", {(CURRENT, LOOKING_BACK)}, None),
    ("light is super fast", {(CURRENT, LOOKING_BACK)}, "any"),
    ("so the star might not even be there anymore?", {(CURRENT, LOOKING_BACK)}, None),
    ("you see it right when it happens", {(CURRENT, LOOKING_BACK)}, "instant_seeing"),
    ("I don't know", {(CURRENT, LOOKING_BACK), (OFF, None)}, None),
    ("thunder is really loud and scary", {(CURRENT, LOOKING_BACK), (OFF, None)}, "any"),
    ("I like pizza", {(OFF, None)}, None),
    ("my dog is named Max", {(OFF, None)}, None),
    ("can we play a game instead?", {(OFF, None)}, None),
    ("what's your favorite color?", {(OFF, None)}, None),
    ("I had soup for lunch today", {(OFF, None)}, None),
    ("are stars like our sun but really far away?", {(OTHER, STARS)}, "any"),
    ("stars only look tiny because they are so far", {(OTHER, STARS)}, None),
    ("is the sun a star?", {(OTHER, STARS)}, "any"),
    ("how long does it take earth to go around the sun?", {(OTHER, YEAR)}, None),
    ("a year is one lap around the sun", {(OTHER, YEAR)}, None),
    ("does saturn have birthdays too?", {(OTHER, YEAR), (OFF, None)}, "any"),
]


def run_case(provider, lesson: LessonPlan, case) -> tuple[bool, str, float]:
    utterance, acceptable, expected_misconception = case
    session = SessionState.new(lesson)
    session.transcript.append({"role": "assistant", "content": lesson.get_concept(LOOKING_BACK).hook_question})
    system, messages = build_evaluator_messages(lesson, session, utterance)

    start = time.monotonic()
    try:
        result = provider.complete_structured(
            system, messages, response_model=evaluator_result_model(lesson)
        ).parsed
    except Exception as exc:  # noqa: BLE001 -- any failure is a failed case
        return False, f"ERROR {str(exc)[:100]}", time.monotonic() - start
    elapsed = time.monotonic() - start

    # Score what the orchestrator would *do*: it routes on target_concept_id,
    # fills in the current id when omitted, and treats unknown ids as off_topic.
    target = result.target_concept_id if result.relevance.value != OFF else None
    if result.relevance.value == CURRENT and target is None:
        target = LOOKING_BACK
    concept_ids = {c.id for c in lesson.concepts}
    if target not in concept_ids:
        route: tuple[str, str | None] = (OFF, None)
    else:
        route = (CURRENT if target == LOOKING_BACK else OTHER, target)

    problems = []
    if route not in acceptable:
        problems.append(f"route={route[0]}/{route[1]}")
    rubric = {r.id for r in lesson.get_concept(target).mastery_rubric} if target in concept_ids else set()
    if wrong := [c for c in result.criteria_met if c not in rubric]:
        problems.append(f"criteria not in target rubric: {wrong}")
    misconception = result.demonstrates_misconception_id
    if expected_misconception not in (None, "any") and misconception != expected_misconception:
        problems.append(f"missed misconception {expected_misconception} (got {misconception})")
    if expected_misconception is None and misconception is not None:
        problems.append(f"spurious misconception {misconception}")

    detail = (
        f"{result.relevance.value}/{result.target_concept_id} -> {route[0]}/{route[1]} "
        f"criteria={result.criteria_met} misconception={misconception}"
    )
    if problems:
        detail += "  <-- " + "; ".join(problems)
    return not problems, detail, elapsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the evaluator prompt against a fixed set of utterances.")
    parser.add_argument("--provider", choices=["anthropic", "ollama", "lmstudio"], required=True)
    parser.add_argument("--model", required=True, help="model name/key (provider-specific)")
    parser.add_argument("--host", default=None, help="server URL for ollama/lmstudio (default: localhost)")
    parser.add_argument("--repeats", type=int, default=1, help="run the suite N times (local models vary run to run)")
    parser.add_argument("--verbose", action="store_true", help="print passing cases too")
    args = parser.parse_args(argv)

    config = ProviderConfig(kind=args.provider, model=args.model)
    if args.host is not None:
        config.ollama_host = config.lmstudio_host = args.host
    provider = build_provider(config)
    lesson = load_lesson(LESSON_PATH)

    # Local servers handle one request at a time; the API can take several.
    workers = 6 if args.provider == "anthropic" else 1
    passed = total = 0
    latencies: list[float] = []
    for _ in range(args.repeats):
        with ThreadPoolExecutor(workers) as pool:
            results = pool.map(lambda case: run_case(provider, lesson, case), CASES)
            for case, (ok, detail, elapsed) in zip(CASES, results):
                total += 1
                passed += ok
                latencies.append(elapsed)
                if args.verbose or not ok:
                    print(f"{'PASS' if ok else 'FAIL'} {elapsed:5.1f}s  {case[0][:48]:48} {detail}")

    # The median hides the first call's model-load time on local servers.
    print(
        f"\n{args.provider}/{args.model}: {passed}/{total} passed ({100 * passed / total:.0f}%), "
        f"median latency {statistics.median(latencies):.1f}s"
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
