"""TutorUI: a Rich Live/Layout dashboard. Runs regardless of which frontend
(ConsoleInterface or TJBotInterface) is active -- it's the debugging /
observability layer, independent of how speak/listen/wave/shine are realized."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel

from tutor.lesson import LessonPlan
from tutor.stats import InferenceStats
from tutor.state import SessionState
from tutor.ui.formatting import (
    render_debug_text,
    render_evidence_panel,
    render_header,
    render_plan_table,
    render_stats_table,
)

DEBUG_LOG_MAXLEN = 200


class TutorUI:
    def __init__(
        self,
        lesson: LessonPlan,
        session: SessionState,
        stats: InferenceStats,
        *,
        provider_name: str,
        model: str,
        interface_name: str,
    ) -> None:
        self._lesson = lesson
        self._session = session
        self._stats = stats
        self._provider_name = provider_name
        self._model = model
        self._interface_name = interface_name
        self._event_log: deque[str] = deque(maxlen=DEBUG_LOG_MAXLEN)
        self._live = Live(self._render(), console=Console(), refresh_per_second=4, transient=False)

    def __enter__(self) -> "TutorUI":
        self._live.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._live.stop()

    def refresh(self) -> None:
        self._live.update(self._render())

    def log_event(self, kind: str, detail: str) -> None:
        self._event_log.append(f"[{kind}] {detail}")
        self.refresh()

    def log_debug(self, message: str) -> None:
        """Non-hardware debug notes: relevance classification, retries, raw
        evaluator JSON, errors -- anything beyond the physical action log."""
        self._event_log.append(message)
        self.refresh()

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Stop the Live render, yield control to a blocking terminal call
        (input()/print()), then resume. ConsoleInterface wraps every one of
        its methods in this so the conversation transcript and the dashboard
        never fight for the cursor."""
        self._live.stop()
        try:
            yield
        finally:
            self._live.start()
            self.refresh()

    def _render(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=1),
            Layout(name="middle", ratio=2),
            Layout(name="stats", size=8),
            Layout(name="debug", ratio=1, minimum_size=5),
        )
        layout["header"].update(
            render_header(
                self._lesson,
                self._session,
                provider_name=self._provider_name,
                model=self._model,
                interface_name=self._interface_name,
            )
        )
        layout["middle"].split_row(
            Layout(
                Panel(render_plan_table(self._lesson, self._session), title="Learning Plan"),
                name="plan",
            ),
            Layout(
                Panel(render_evidence_panel(self._lesson, self._session), title="Evidence"),
                name="evidence",
            ),
        )
        layout["stats"].update(Panel(render_stats_table(self._stats), title="LLM Inference Stats"))
        layout["debug"].update(Panel(render_debug_text(self._event_log), title="Debug / Events"))
        return layout
