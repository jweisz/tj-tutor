"""TutorUI: fixed header panels + scrolling color-coded chat transcript.

Uses ANSI scroll-region control to split the terminal: Learning Plan, Evidence,
and Stats panels are pinned to the top N lines via absolute cursor positioning;
the chat transcript (TJBot speech, student responses, debug events) flows and
scrolls naturally below like a normal terminal.
"""

from __future__ import annotations

import io
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from tutor.lesson import LessonPlan
from tutor.stats import InferenceStats
from tutor.state import SessionState
from tutor.ui.formatting import (
    render_evidence_panel,
    render_header,
    render_plan_table,
    render_stats_table,
)


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
        self._console = Console(highlight=False)
        self._header_height: int = 0

    def __enter__(self) -> "TutorUI":
        self._init_terminal()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._reset_terminal()

    def refresh(self) -> None:
        self._redraw_header()

    def reset(self, session: SessionState, stats: InferenceStats) -> None:
        """Swap in a fresh session and stats for a replay without restarting the terminal."""
        self._session = session
        self._stats = stats
        self._redraw_header()

    def log_event(self, kind: str, detail: str) -> None:
        """Print a color-coded line in the scrolling chat area."""
        if kind == "speak":
            self._print_chat(f"\n[bold cyan]TJBot:[/bold cyan] {detail}")
        elif kind in ("wave", "shine", "pulse"):
            self._print_chat(f"[dim italic]* {kind}: {detail} *[/dim italic]")
        else:
            self._print_chat(f"[dim]{kind}: {detail}[/dim]")

    def log_debug(self, message: str) -> None:
        self._print_chat(f"[italic steel_blue1]{message}[/italic steel_blue1]")

    def prompt_user(self) -> str:
        """Show a styled input prompt in the chat area and return the response."""
        self._anchor_chat_cursor()
        return self._console.input("\n[bold green]You:[/bold green] ").strip()

    @contextmanager
    def paused(self) -> Iterator[None]:
        yield  # no Live to stop/start; the chat area is always active

    # ── private ─────────────────────────────────────────────────────────────

    def _anchor_chat_cursor(self) -> None:
        """Move cursor to the bottom of the scroll region before chat output.

        Without this, the cursor can end up anywhere in the scroll region
        (e.g. mid-screen after input() returns), which causes subsequent \n
        characters to move the cursor down without scrolling — eventually the
        cursor escapes the scroll region into the header area.
        """
        sys.stdout.write(f"\033[{shutil.get_terminal_size().lines};1H")
        sys.stdout.flush()

    def _print_chat(self, markup: str) -> None:
        """Anchor to the bottom of the scroll region, then print markup."""
        self._anchor_chat_cursor()
        self._console.print(markup)

    def _render_header_lines(self) -> list[str]:
        term = shutil.get_terminal_size()
        buf = io.StringIO()
        cap = Console(
            file=buf,
            width=term.columns,
            highlight=False,
            force_terminal=True,
            color_system="truecolor",
        )
        cap.print(
            render_header(
                self._lesson,
                self._session,
                provider_name=self._provider_name,
                model=self._model,
                interface_name=self._interface_name,
            )
        )
        side_by_side = Table.grid(expand=True)
        side_by_side.add_column(ratio=1)
        side_by_side.add_column(ratio=1)
        side_by_side.add_row(
            Panel(render_plan_table(self._lesson, self._session), title="Learning Plan"),
            Panel(render_evidence_panel(self._lesson, self._session), title="Evidence"),
        )
        cap.print(side_by_side)
        cap.print(Panel(render_stats_table(self._stats), title="LLM Inference Stats"))
        return buf.getvalue().splitlines()

    def _redraw_header(self) -> None:
        """Overwrite the fixed header region without disturbing the chat below."""
        lines = self._render_header_lines()
        term = shutil.get_terminal_size()
        new_height = len(lines)

        parts = ["\033[?25l"]  # hide cursor during draw to prevent flicker
        for i, line in enumerate(lines):
            parts.append(f"\033[{i + 1};1H\033[2K{line}")  # position, clear, write
        # Always re-set the scroll region (handles terminal resize and height changes).
        scroll_top = new_height + 1
        parts.append(f"\033[{scroll_top};{term.lines}r")
        parts.append(f"\033[{term.lines};1H")  # leave cursor at bottom of chat area
        parts.append("\033[?25h")
        sys.stdout.write("".join(parts))
        sys.stdout.flush()
        self._header_height = new_height

    def _init_terminal(self) -> None:
        sys.stdout.write("\033[2J\033[H")  # clear screen, cursor to top-left
        sys.stdout.flush()
        self._redraw_header()  # sets scroll region + moves cursor to bottom

    def _reset_terminal(self) -> None:
        sys.stdout.write("\033[r")     # reset scroll region (full terminal)
        sys.stdout.write("\033[?25h")  # ensure cursor visible
        sys.stdout.flush()
