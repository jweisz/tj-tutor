"""LM Studio backend, via its OpenAI-compatible /v1 API. Works the same against
the desktop app and llmster (LM Studio's headless daemon, e.g. on a Raspberry
Pi) -- both serve the identical API, so only the host differs. Like Ollama,
small local models are less reliable at structured output, so
complete_structured does exactly one repair retry before giving up."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Literal

import openai
from dotenv import load_dotenv
from pydantic import ValidationError

from tutor.llm.base import (
    LLMResponse,
    Message,
    ModelT,
    ProviderError,
    StructuredOutputError,
    TokenUsage,
)

DEFAULT_MODEL = None  # None -> use whichever model LM Studio lists first (see _resolve_model)
DEFAULT_HOST = "http://localhost:1234"

Reasoning = Literal["none", "low", "medium", "high"]
# Reasoning models (e.g. Gemma 4, Qwen3) spend completion tokens on hidden
# reasoning_content before writing any answer -- with only the caller's
# max_tokens they can exhaust it and return an empty reply. When reasoning is
# on, give them this much extra room.
REASONING_TOKEN_ALLOWANCE = 2048

# Reasoning models (e.g. Qwen3) can leak their chain of thought into `content`
# if LM Studio's "separate reasoning_content" server setting is off -- strip it
# so TJBot never reads its thinking out loud.
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LMStudioProvider:
    name: Literal["lmstudio"] = "lmstudio"

    def __init__(
        self,
        model: str | None = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        reasoning: Reasoning = "none",
    ) -> None:
        # "none" by default: a spoken tutor turn can't afford the extra latency,
        # and reasoning_effort="none" is what actually disables thinking in LM
        # Studio (it's ignored by non-reasoning models).
        self._reasoning = reasoning
        # LM Studio auth is off by default; when it's enabled (Server Settings >
        # Require Authentication), the token is sent as a Bearer header. The
        # OpenAI SDK insists on *some* api_key, so fall back to a placeholder.
        load_dotenv()
        self._client = openai.OpenAI(
            base_url=host.rstrip("/") + "/v1",
            api_key=os.environ.get("LM_API_TOKEN") or "lm-studio",
        )
        self._model = model or self._resolve_model()

    @property
    def model(self) -> str:
        return self._model

    def _resolve_model(self) -> str:
        try:
            models = self._client.models.list().data
        except openai.APIError as exc:
            raise ProviderError(f"Could not reach LM Studio to list models: {exc}") from exc
        # Embedding models can't chat; skip them.
        chat_models = [m.id for m in models if "embed" not in m.id.lower()]
        if not chat_models:
            raise ProviderError(
                "LM Studio has no chat models available -- download one (e.g. `lms get`) "
                "or set lmstudio_model in recipe.toml"
            )
        return chat_models[0]

    def complete_text(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = 512,
    ) -> LLMResponse:
        response, latency_ms = self._chat(self._chat_messages(system, messages), max_tokens)
        return self._to_llm_response(response, latency_ms, parsed=None)

    def complete_structured(
        self,
        system: str,
        messages: list[Message],
        *,
        response_model: type[ModelT],
        max_tokens: int = 512,
    ) -> LLMResponse:
        # LM Studio only supports the json_schema response format (not json_object).
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": response_model.__name__,
                "strict": True,
                "schema": response_model.model_json_schema(),
            },
        }
        chat_messages = self._chat_messages(system, messages)

        response, latency_ms = self._chat(chat_messages, max_tokens, response_format)
        parsed, error = self._parse(response, response_model)
        if parsed is None:
            chat_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your last response didn't match the required JSON schema: {error}. "
                        "Try again, respond with ONLY valid JSON matching the schema."
                    ),
                }
            )
            response, latency_ms = self._chat(chat_messages, max_tokens, response_format)
            parsed, error = self._parse(response, response_model)

        if parsed is None:
            raise StructuredOutputError(
                f"LM Studio model {self._model!r} failed to produce valid {response_model.__name__} "
                f"JSON after one repair retry: {error}"
            )
        return self._to_llm_response(response, latency_ms, parsed=parsed)

    @staticmethod
    def _chat_messages(system: str, messages: list[Message]) -> list[dict[str, str]]:
        # Some chat templates (e.g. Gemma's) reject a conversation with no user
        # turn, so give the opening turn a stub one, as the Anthropic provider does.
        transcript = messages or [{"role": "user", "content": "Begin."}]
        return [{"role": "system", "content": system}, *transcript]

    def _chat(
        self,
        chat_messages: list[dict[str, str]],
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[Any, float]:
        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=chat_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens if self._reasoning == "none" else max_tokens + REASONING_TOKEN_ALLOWANCE,
                reasoning_effort=self._reasoning,
                response_format=response_format or openai.omit,  # type: ignore[arg-type]
            )
        except openai.APIError as exc:
            raise ProviderError(f"LM Studio request failed: {exc}") from exc
        return response, (time.monotonic() - start) * 1000

    @staticmethod
    def _content(response: Any) -> str:
        return _THINK_RE.sub("", response.choices[0].message.content or "").strip()

    def _parse(self, response: Any, response_model: type[ModelT]) -> tuple[ModelT | None, str | None]:
        try:
            return response_model.model_validate(json.loads(self._content(response))), None
        except (json.JSONDecodeError, ValidationError) as exc:
            return None, str(exc)

    def _to_llm_response(self, response: Any, latency_ms: float, parsed: Any) -> LLMResponse:
        usage = response.usage
        return LLMResponse(
            text=self._content(response),
            parsed=parsed,
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            latency_ms=latency_ms,
            model=response.model or self._model,
            provider_name="lmstudio",
            raw=response.model_dump(mode="json"),
        )
