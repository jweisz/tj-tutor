"""Provider-agnostic LLM interface. Both AnthropicProvider and OllamaProvider
implement this Protocol (as does LMStudioProvider) so the orchestrator/evaluator/tutor_speech modules
never need to know which backend is active."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)

Message = dict[str, str]  # {"role": "user" | "assistant", "content": str}


class ProviderError(Exception):
    """Raised for any unrecoverable provider-side failure (network, auth, etc.)."""


class StructuredOutputError(ProviderError):
    """Raised when complete_structured() cannot produce a value matching the
    requested schema, even after any provider-internal retry. Callers must
    treat this as an explicit failure signal, never silently get back None."""


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    # Anthropic only; None (not 0) means "not applicable for this provider".
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass
class LLMResponse:
    text: str
    parsed: BaseModel | None
    usage: TokenUsage
    latency_ms: float
    model: str
    provider_name: Literal["anthropic", "ollama", "lmstudio"]
    raw: dict[str, Any]


class LLMProvider(Protocol):
    @property
    def name(self) -> Literal["anthropic", "ollama", "lmstudio"]: ...

    @property
    def model(self) -> str: ...

    def complete_text(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 512,
    ) -> LLMResponse: ...

    def complete_structured(
        self,
        system: str,
        messages: list[Message],
        *,
        response_model: type[ModelT],
        max_tokens: int = 512,
    ) -> LLMResponse: ...
