"""Loads and validates a lesson plan YAML file against the LessonPlan schema."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from tutor.lesson import LessonPlan


class LessonLoadError(Exception):
    pass


def load_lesson(path: str | Path) -> LessonPlan:
    lesson_path = Path(path)
    if not lesson_path.exists():
        raise LessonLoadError(f"lesson file not found: {lesson_path}")

    try:
        raw = yaml.safe_load(lesson_path.read_text())
    except yaml.YAMLError as exc:
        raise LessonLoadError(f"failed to parse {lesson_path} as YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise LessonLoadError(f"{lesson_path} did not parse to a YAML mapping at the top level")

    try:
        return LessonPlan.model_validate(raw)
    except ValidationError as exc:
        raise LessonLoadError(f"{lesson_path} does not match the lesson plan schema:\n{exc}") from exc
