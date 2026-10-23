#!/usr/bin/env python3
"""Expands a lightweight lesson seed (id/domain/title/summary per concept)
into a full lesson plan YAML via one structured LLM call per concept. This is
an offline authoring tool, separate from the conversational runtime -- it
reuses tutor.llm.factory so the same provider code path is exercised, but
talks to neither recipe.toml nor the runtime's AppConfig."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tutor.lesson import (  # noqa: E402
    Concept,
    CrossLink,
    HintLevel,
    LessonPlan,
    LessonSeed,
    MasteryCriterion,
    Misconception,
)
from tutor.llm.base import ProviderError, StructuredOutputError  # noqa: E402
from tutor.llm.factory import ProviderConfig, build_provider  # noqa: E402
from tutor.stats import InferenceStats  # noqa: E402

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"


class ConceptExpansion(BaseModel):
    """Only the fields we want the LLM to generate. id/domain/title/summary
    come from the seed verbatim, so the model can't drift them."""

    hook_question: str = Field(description="The opening Socratic question that kicks off this concept.")
    teaching_strategy: str = Field(
        description=(
            "Paragraph of guidance for a tutor LLM: which analogies to use, how to pace the "
            "conversation, and explicitly what NOT to just state outright."
        )
    )
    misconceptions: list[Misconception] = Field(
        default_factory=list,
        description="1-2 common misconceptions a learner might have about this concept.",
    )
    mastery_rubric: list[MasteryCriterion] = Field(
        description="2-3 criteria that, together, constitute genuinely understanding the concept."
    )
    hint_ladder: list[HintLevel] = Field(
        description="2-3 increasingly direct hints to use if the learner gets stuck."
    )
    celebration_cue: str = Field(
        description="Guidance text (not a fixed phrase) for how the tutor should celebrate mastery."
    )
    relates_to_transitions: list[str] = Field(
        description=(
            "One transition-hint sentence per entry in relates_to_ids, IN THE SAME ORDER, bridging "
            "from this concept toward that related concept."
        )
    )


BOOTSTRAP_PERSONA = """\
You are a curriculum designer creating Socratic-dialogue tutoring content for a
tutoring robot (TJBot). The audience is {audience}.

Core design principle: every concept must require an "aha moment" -- the learner
must reason their way to the insight through guided questions and relatable
analogies, never be told the answer outright. teaching_strategy must describe
HOW to lead the learner there, and must explicitly note what must NOT just be
stated as a fact.

Keep all language appropriate for {audience}: clear wording and concrete,
relatable analogies suited to that audience, no unnecessary jargon."""


def render_concept_prompt(seed_concept, other_concepts: list, audience: str) -> tuple[str, str]:
    siblings_text = "\n".join(
        f"- id={c.id!r}, title={c.title!r}: {c.summary}" for c in other_concepts
    )
    related_text = ", ".join(seed_concept.relates_to_ids) or "(none)"

    system = BOOTSTRAP_PERSONA.format(audience=audience)
    user = "\n\n".join(
        [
            f"## Concept to expand\nid: {seed_concept.id}\ndomain: {seed_concept.domain}\n"
            f"title: {seed_concept.title}\nsummary: {seed_concept.summary}",
            f"## Other concepts in this lesson (for cross-link context only)\n{siblings_text or '(none)'}",
            f"## relates_to_ids for this concept, in order\n{related_text}\n"
            "Produce exactly one relates_to_transitions entry per id above, in the same order.",
        ]
    )
    return system, user


def expand_concept(provider, seed_concept, other_concepts: list, audience: str, stats: InferenceStats) -> Concept:
    system, user = render_concept_prompt(seed_concept, other_concepts, audience)
    response = provider.complete_structured(
        system,
        [{"role": "user", "content": user}],
        response_model=ConceptExpansion,
        max_tokens=2048,
    )
    stats.record("tutor", response)
    expansion = response.parsed
    assert isinstance(expansion, ConceptExpansion)

    if len(expansion.relates_to_transitions) != len(seed_concept.relates_to_ids):
        raise StructuredOutputError(
            f"concept {seed_concept.id!r}: expected {len(seed_concept.relates_to_ids)} "
            f"relates_to_transitions (one per relates_to_id), got "
            f"{len(expansion.relates_to_transitions)}"
        )

    relates_to = [
        CrossLink(concept_id=concept_id, transition_hint=hint)
        for concept_id, hint in zip(seed_concept.relates_to_ids, expansion.relates_to_transitions)
    ]

    concept = Concept(
        id=seed_concept.id,
        domain=seed_concept.domain,
        title=seed_concept.title,
        summary=seed_concept.summary,
        hook_question=expansion.hook_question,
        teaching_strategy=expansion.teaching_strategy,
        misconceptions=expansion.misconceptions,
        mastery_rubric=expansion.mastery_rubric,
        hint_ladder=expansion.hint_ladder,
        celebration_cue=expansion.celebration_cue,
        relates_to=relates_to,
    )
    # Belt-and-suspenders: re-validate the assembled Concept on its own.
    return Concept.model_validate(concept.model_dump())


def build_lesson(seed: LessonSeed, provider, stats: InferenceStats, only: str | None) -> LessonPlan:
    concepts: list[Concept] = []
    for seed_concept in seed.concepts:
        others = [c for c in seed.concepts if c.id != seed_concept.id]
        if only is not None and seed_concept.id != only:
            continue
        print(f"  expanding concept {seed_concept.id!r}...")
        concepts.append(expand_concept(provider, seed_concept, others, seed.audience, stats))

    plan = LessonPlan(
        id=seed.id,
        title=seed.title,
        audience=seed.audience,
        default_concept_order=[c.id for c in seed.concepts],
        concepts=concepts,
        wrap_up_message=seed.wrap_up_message,
    )
    return LessonPlan.model_validate(plan.model_dump())


def regenerate_one(existing: LessonPlan, seed: LessonSeed, concept_id: str, provider, stats: InferenceStats) -> LessonPlan:
    seed_concept = next((c for c in seed.concepts if c.id == concept_id), None)
    if seed_concept is None:
        raise SystemExit(f"--only {concept_id!r} is not in the seed file")
    others = [c for c in seed.concepts if c.id != concept_id]
    print(f"  regenerating concept {concept_id!r}...")
    new_concept = expand_concept(provider, seed_concept, others, seed.audience, stats)

    new_concepts = [new_concept if c.id == concept_id else c for c in existing.concepts]
    plan = existing.model_copy(update={"concepts": new_concepts})
    return LessonPlan.model_validate(plan.model_dump())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expand a lesson seed into a full lesson plan YAML.")
    parser.add_argument("--seed", required=True, help="path to a *.seed.yaml file")
    parser.add_argument("--out", required=True, help="output path for the generated lesson YAML")
    parser.add_argument("--provider", choices=["anthropic", "ollama", "lmstudio"], default="anthropic")
    parser.add_argument("--model", default=None, help="model override (provider-specific)")
    parser.add_argument("--host", default=None, help="server URL for ollama/lmstudio (default: localhost)")
    parser.add_argument("--force", action="store_true", help="overwrite --out if it already exists")
    parser.add_argument("--only", default=None, help="regenerate a single concept id in place")
    args = parser.parse_args(argv)

    seed_path = Path(args.seed)
    out_path = Path(args.out)

    try:
        seed = LessonSeed.model_validate(yaml.safe_load(seed_path.read_text()))
    except (yaml.YAMLError, ValidationError) as exc:
        print(f"error: seed file {seed_path} is invalid: {exc}", file=sys.stderr)
        return 1

    model = args.model
    if model is None and args.provider == "anthropic":
        model = DEFAULT_ANTHROPIC_MODEL
    provider_config = ProviderConfig(kind=args.provider, model=model)
    if args.host is not None:
        provider_config.ollama_host = provider_config.lmstudio_host = args.host
    provider = build_provider(provider_config)
    stats = InferenceStats()

    try:
        if args.only:
            if not out_path.exists():
                print(f"error: --only requires --out ({out_path}) to already exist", file=sys.stderr)
                return 1
            existing = LessonPlan.model_validate(yaml.safe_load(out_path.read_text()))
            plan = regenerate_one(existing, seed, args.only, provider, stats)
        else:
            if out_path.exists() and not args.force:
                print(f"error: {out_path} already exists (use --force to overwrite)", file=sys.stderr)
                return 1
            plan = build_lesson(seed, provider, stats, only=None)
    except (ProviderError, StructuredOutputError) as exc:
        print(f"error: lesson generation failed: {exc}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False, default_flow_style=False, width=100))

    total_criteria = sum(len(c.mastery_rubric) for c in plan.concepts)
    print(f"\nWrote {out_path} -- {len(plan.concepts)} concepts, {total_criteria} mastery criteria total")
    print(
        f"LLM calls: {stats.total_calls}, tokens in/out: "
        f"{stats.total_input_tokens}/{stats.total_output_tokens}, "
        f"est. cost: ${stats.total_estimated_cost_usd:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
