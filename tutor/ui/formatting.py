"""Pure render helpers -- kept out of app.py so it stays purely declarative
(compose panels, don't build table rows inline)."""

from __future__ import annotations

from collections import deque

from rich.table import Table
from rich.text import Text

from tutor.lesson import LessonPlan
from tutor.stats import InferenceStats
from tutor.state import ConceptStatus, SessionState

STATUS_COLORS = {
    ConceptStatus.NOT_STARTED: "grey58",
    ConceptStatus.IN_PROGRESS: "yellow",
    ConceptStatus.PENDING_RESUME: "magenta",
    ConceptStatus.MASTERED: "green",
}

EVIDENCE_DISPLAY_LIMIT = 8
DEBUG_DISPLAY_LIMIT = 30
EXCERPT_LENGTH = 60


def render_header(
    lesson: LessonPlan,
    session: SessionState,
    *,
    provider_name: str,
    model: str,
    interface_name: str,
) -> Text:
    return Text.from_markup(
        f"[bold]{lesson.title}[/bold]  ·  provider=[cyan]{provider_name}[/cyan] "
        f"model=[cyan]{model}[/cyan]  ·  interface=[cyan]{interface_name}[/cyan]  ·  turn #{session.turn_index}"
    )


def render_plan_table(lesson: LessonPlan, session: SessionState) -> Table:
    table = Table(expand=True)
    table.add_column("Concept")
    table.add_column("Status")
    table.add_column("Criteria met")

    for concept_id in lesson.default_concept_order:
        concept = lesson.get_concept(concept_id)
        state = session.concepts[concept_id]
        color = STATUS_COLORS[state.status]
        marker = "➤ " if concept_id == session.current_concept_id else "  "
        table.add_row(
            f"{marker}{concept.title}",
            f"[{color}]{state.status.value}[/{color}]",
            f"{len(state.criteria_met)}/{len(concept.mastery_rubric)}",
        )

    if session.resume_stack:
        pending_titles = ", ".join(lesson.get_concept(cid).title for cid in session.resume_stack)
        table.caption = f"Pending resume (next → first): {pending_titles}"

    return table


def render_evidence_panel(lesson: LessonPlan, session: SessionState) -> Table:
    table = Table(expand=True)
    table.add_column("Turn")
    table.add_column("Concept")
    table.add_column("Said")
    table.add_column("Criteria met")

    all_evidence = [
        (concept_id, evidence)
        for concept_id, state in session.concepts.items()
        for evidence in state.evidence_log
    ]
    all_evidence.sort(key=lambda pair: pair[1].turn_index)
    recent = all_evidence[-EVIDENCE_DISPLAY_LIMIT:]

    if not recent:
        table.add_row("-", "-", "(no evidence recorded yet)", "-")
        return table

    for concept_id, evidence in recent:
        excerpt = evidence.student_utterance
        if len(excerpt) > EXCERPT_LENGTH:
            excerpt = excerpt[: EXCERPT_LENGTH - 1] + "…"
        table.add_row(
            str(evidence.turn_index),
            lesson.get_concept(concept_id).title,
            excerpt,
            ", ".join(evidence.criteria_met) or "-",
        )

    return table


def render_stats_table(stats: InferenceStats) -> Table:
    table = Table(expand=True)
    table.add_column("Call")
    table.add_column("Latency")
    table.add_column("In/Out tok")
    table.add_column("Cache R/W")
    table.add_column("Cost (est)")

    for call_type in ("evaluator", "tutor"):
        record = stats.last(call_type)
        if record is None:
            table.add_row(call_type, "-", "-", "-", "-")
            continue
        cache_r = record.usage.cache_read_input_tokens
        cache_w = record.usage.cache_creation_input_tokens
        cache_str = f"{cache_r or 0}/{cache_w or 0}" if cache_r is not None or cache_w is not None else "n/a"
        table.add_row(
            f"last {call_type}",
            f"{record.latency_ms:.0f} ms",
            f"{record.usage.input_tokens}/{record.usage.output_tokens}",
            cache_str,
            f"${record.estimated_cost_usd:.4f}",
        )

    table.add_row(
        "[bold]session totals[/bold]",
        f"{stats.average_latency_ms:.0f} ms avg",
        f"{stats.total_input_tokens}/{stats.total_output_tokens}",
        f"{stats.total_cache_read_tokens}/{stats.total_cache_creation_tokens}",
        f"${stats.total_estimated_cost_usd:.4f}",
    )
    return table


def render_debug_text(event_log: deque[str]) -> Text:
    lines = list(event_log)[-DEBUG_DISPLAY_LIMIT:]
    if not lines:
        return Text("(no events yet)", style="grey58")
    return Text("\n".join(lines))
