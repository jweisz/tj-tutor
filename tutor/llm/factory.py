"""Single construction point for LLMProvider instances, reused by both the
runtime (tutor/cli.py) and the bootstrap script."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from tutor.llm.anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT_MODEL
from tutor.llm.anthropic_provider import AnthropicProvider
from tutor.llm.base import LLMProvider
from tutor.llm.ollama_provider import DEFAULT_HOST as OLLAMA_DEFAULT_HOST
from tutor.llm.ollama_provider import DEFAULT_MODEL as OLLAMA_DEFAULT_MODEL
from tutor.llm.ollama_provider import OllamaProvider


class ProviderConfig(BaseModel):
    kind: Literal["anthropic", "ollama"] = "ollama"
    model: str | None = None  # None -> provider-specific default
    effort: Literal["low", "medium", "high"] = "low"  # anthropic only
    ollama_host: str = OLLAMA_DEFAULT_HOST


def build_provider(config: ProviderConfig) -> LLMProvider:
    if config.kind == "anthropic":
        return AnthropicProvider(model=config.model or ANTHROPIC_DEFAULT_MODEL, effort=config.effort)
    if config.kind == "ollama":
        return OllamaProvider(model=config.model or OLLAMA_DEFAULT_MODEL, host=config.ollama_host)
    raise ValueError(f"unknown provider kind: {config.kind!r}")
