"""argparse entry point. Parses --interface (console|tjbot) plus the other
overrides, wires everything together, and runs the session."""

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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tj-tutor",
        description="A Socratic dialogue tutor for TJBot, driven entirely by LLM calls.",
    )
    parser.add_argument("--lesson", help="path to a lesson plan YAML file")
    parser.add_argument("--provider", choices=["anthropic", "ollama"], help="LLM backend")
    parser.add_argument("--model", help="model name (provider-specific)")
    parser.add_argument("--effort", choices=["low", "medium", "high"], help="Anthropic effort level")
    parser.add_argument(
        "--interface",
        choices=["console", "tjbot"],
        help="which frontend to use -- console (default, runs on this Mac) or tjbot (real hardware)",
    )
    parser.add_argument("--ollama-host", help="Ollama server base URL")
    return parser.parse_args(argv)


def _apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> AppConfig:
    data = config.model_dump()
    if args.lesson is not None:
        data["lesson_path"] = args.lesson
    if args.interface is not None:
        data["interface"] = args.interface
    if args.provider is not None:
        data["provider"]["kind"] = args.provider
    if args.model is not None:
        data["provider"]["model"] = args.model
    if args.effort is not None:
        data["provider"]["effort"] = args.effort
    if args.ollama_host is not None:
        data["provider"]["ollama_host"] = args.ollama_host
    return AppConfig.model_validate(data)


def build_interface(config: AppConfig, ui: TutorUI) -> TutorInterface:
    if config.interface == "console":
        return ConsoleInterface(ui)
    if config.interface == "tjbot":
        return TJBotInterface()
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
    )

    with ui:
        orchestrator.run_session()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
