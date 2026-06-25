"""argparse entry point. Parses --lesson/--interface, wires everything
together, and runs the session. LLM provider/model/effort/host are
recipe.toml-only -- see tutor/config.py."""

from __future__ import annotations

import argparse
import sys

from tutor.config import AppConfig, load_app_config
from tutor.interface import ConsoleInterface, TJBotInterface, TutorInterface
from tutor.lesson_loader import LessonLoadError, load_lesson
from tutor.llm.factory import build_provider
from tutor.orchestrator import Orchestrator
from tutor.state import SessionState
from tutor.stats import InferenceStats
from tutor.ui.app import TutorUI


_NO_WORDS = {"no", "nope", "nah", "stop", "quit", "done", "finish", "finished", "end", "bye", "goodbye"}
_YES_WORDS = {"y", "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "alright",
              "please", "again", "restart", "want", "like", "would", "love", "more", "let's"}


def _wants_replay(answer: str) -> bool:
    """True if the answer expresses a desire to replay. No-words take priority over yes-words."""
    words = set(answer.lower().split())
    if words & _NO_WORDS:
        return False
    return bool(words & _YES_WORDS)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tj-tutor",
        description="A Socratic dialogue tutor for TJBot, driven entirely by LLM calls.",
    )
    parser.add_argument("--lesson", help="path to a lesson plan YAML file")
    parser.add_argument(
        "--interface",
        choices=["console", "tjbot"],
        help="which frontend to use -- console (default, runs on this Mac) or tjbot (real hardware)",
    )
    return parser.parse_args(argv)


def _apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    data = config.model_dump()
    if args.lesson is not None:
        data["lesson_path"] = args.lesson
    if args.interface is not None:
        data["interface"] = args.interface
    return AppConfig.model_validate(data)


def build_interface(config: AppConfig, ui: TutorUI) -> TutorInterface:
    if config.interface == "console":
        return ConsoleInterface(ui)
    if config.interface == "tjbot":
        return TJBotInterface(listen_timeout_secs=config.listen_reprompt_secs)
    raise ValueError(f"unknown interface: {config.interface!r}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = _apply_cli_overrides(load_app_config(), args)

    try:
        lesson = load_lesson(config.lesson_path)
    except LessonLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    session = SessionState.new(lesson)
    stats = InferenceStats()
    # One provider instance, reused for both the evaluator and tutor calls --
    # LLMProvider is stateless aside from its constructor config.
    provider = build_provider(config.provider)

    ui = TutorUI(
        lesson,
        session,
        stats,
        provider_name=provider.name,
        model=provider.model,
        interface_name=config.interface,
    )
    interface = build_interface(config, ui)

    orchestrator = Orchestrator(
        lesson,
        session,
        evaluator_provider=provider,
        tutor_provider=provider,
        interface=interface,
        stats=stats,
        ui=ui,
        thinking_delay_secs=config.thinking_delay_secs,
    )

    with ui:
        while True:
            orchestrator.run_session()

            interface.speak(
                "Would you like to go through the lesson again? Say yes to restart or no to finish."
            )
            answer = interface.listen()
            if not _wants_replay(answer):
                interface.speak("Thanks for learning with TJBot today! Goodbye!")
                break

            # Replay: fresh session and stats, same lesson/provider/interface/terminal.
            session = SessionState.new(lesson)
            stats = InferenceStats()
            ui.reset(session, stats)
            orchestrator = Orchestrator(
                lesson,
                session,
                evaluator_provider=provider,
                tutor_provider=provider,
                interface=interface,
                stats=stats,
                ui=ui,
                thinking_delay_secs=config.thinking_delay_secs,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
