"""Anthropic Claude backend."""

from __future__ import annotations

import time
from typing import Any, Literal

import anthropic
from anthropic.types import MessageParam, TextBlockParam
from dotenv import load_dotenv

from tutor.llm.base import (
    LLMResponse,
    Message,
    ModelT,
    ProviderError,
    StructuredOutputError,
    TokenUsage,
)

DEFAULT_MODEL = "claude-sonnet-4-6"


class AnthropicProvider:
    name: Literal["anthropic"] = "anthropic"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        effort: Literal["low", "medium", "high"] = "low",
    ) -> None:
        self._model = model
        self._effort = effort
        # Populate os.environ from a local .env file, if present, without
        # clobbering a real shell-exported ANTHROPIC_API_KEY (load_dotenv's
        # default: existing env vars win). No api_key kwarg below -- the SDK
        # reads ANTHROPIC_API_KEY from the environment itself.
        load_dotenv()
        self._client = anthropic.Anthropic()

    @property
    def model(self) -> str:
        return self._model

    def complete_text(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 512,
    ) -> LLMResponse:
        start = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                system=self._system_blocks(system),
                messages=self._api_messages(messages),
                max_tokens=max_tokens,
                output_config={"effort": self._effort},
            )
        except anthropic.APIError as exc:
            raise ProviderError(f"Anthropic API error: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        text = next((block.text for block in response.content if block.type == "text"), "")
        return LLMResponse(
            text=text,
            parsed=None,
            usage=self._usage_from(response.usage),
            latency_ms=latency_ms,
            model=response.model,
            provider_name="anthropic",
            raw=response.model_dump(mode="json"),
        )

    def complete_structured(
        self,
        system: str,
        messages: list[Message],
        *,
        response_model: type[ModelT],
        max_tokens: int = 512,
    ) -> LLMResponse:
        start = time.monotonic()
        try:
            response = self._client.messages.parse(
                model=self._model,
                system=self._system_blocks(system),
                messages=self._api_messages(messages),
                max_tokens=max_tokens,
                output_format=response_model,
                output_config={"effort": self._effort},
            )
        except anthropic.APIError as exc:
            raise ProviderError(f"Anthropic API error: {exc}") from exc
        latency_ms = (time.monotonic() - start) * 1000

        parsed = response.parsed_output
        if parsed is None:
            raise StructuredOutputError(
                f"Anthropic response did not contain a parsed {response_model.__name__} "
                f"(stop_reason={response.stop_reason!r})"
            )

        text = next((block.text for block in response.content if block.type == "text"), "")
        return LLMResponse(
            text=text,
            parsed=parsed,
            usage=self._usage_from(response.usage),
            latency_ms=latency_ms,
            model=response.model,
            provider_name="anthropic",
            raw=response.model_dump(mode="json"),
        )

    @staticmethod
    def _system_blocks(system: str) -> list[TextBlockParam]:
        # The system prompt is large and static for the whole session (persona +
        # full lesson content) -- an ideal caching candidate.
        return [TextBlockParam(type="text", text=system, cache_control={"type": "ephemeral"})]

    @staticmethod
    def _api_messages(messages: list[Message]) -> list[MessageParam]:
        # Roll the cache breakpoint forward onto whatever is currently the last
        # message being sent. Earlier breakpoints (from prior turns' requests)
        # remain valid read points server-side without us re-marking them here --
        # see shared/prompt-caching.md's multi-turn pattern.
        if not messages:
            return []
        api_messages: list[MessageParam] = [
            MessageParam(role=m["role"], content=m["content"]) for m in messages[:-1]  # type: ignore[typeddict-item]
        ]
        last = messages[-1]
        api_messages.append(
            MessageParam(
                role=last["role"],  # type: ignore[typeddict-item]
                content=[
                    TextBlockParam(
                        type="text",
                        text=last["content"],
                        cache_control={"type": "ephemeral"},
                    )
                ],
            )
        )
        return api_messages

    @staticmethod
    def _usage_from(usage: Any) -> TokenUsage:
        return TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
        )
