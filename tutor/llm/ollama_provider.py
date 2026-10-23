"""Local Ollama backend. Small (2-4B param) models are noticeably less
reliable at strict structured output than cloud models, so complete_structured
does exactly one repair retry before giving up."""

from __future__ import annotations

import json
from typing import Literal

import ollama
from pydantic import ValidationError

from tutor.llm.base import (
    REASONING_TOKEN_ALLOWANCE,
    LLMResponse,
    Message,
    ModelT,
    ProviderError,
    Reasoning,
    StructuredOutputError,
    TokenUsage,
)

DEFAULT_MODEL = "gemma4:e2b"  # Gemma 4 was the best local model on scripts/eval_evaluator.py
# (README: "Evaluator test results"); E2B is the size that fits on a Raspberry Pi.
DEFAULT_HOST = "http://localhost:11434"


class OllamaProvider:
    name: Literal["ollama"] = "ollama"

    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST, reasoning: Reasoning = "none") -> None:
        self._model = model
        # "none" by default, as for LM Studio: thinking adds far too much
        # latency to a spoken tutor turn.
        self._think: bool | Literal["low", "medium", "high"] = False if reasoning == "none" else reasoning
        self._client = ollama.Client(host=host)

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
        chat_messages = [{"role": "system", "content": system}, *messages]
        try:
            response = self._client.chat(
                model=self._model,
                messages=chat_messages,
                think=self._think,
                options={"num_predict": self._num_predict(max_tokens)},
            )
        except Exception as exc:  # noqa: BLE001 -- ollama raises plain/HTTP errors, not a typed hierarchy
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        return LLMResponse(
            text=response.message.content or "",
            parsed=None,
            usage=self._usage_from(response),
            latency_ms=self._latency_ms(response),
            model=response.model or self._model,
            provider_name="ollama",
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
        schema = response_model.model_json_schema()
        chat_messages: list[dict[str, str]] = [{"role": "system", "content": system}, *messages]

        response, parsed, error = self._try_structured(chat_messages, schema, response_model, max_tokens)
        if parsed is None:
            assert error is not None
            chat_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your last response didn't match the required JSON schema: {error}. "
                        "Try again, respond with ONLY valid JSON matching the schema."
                    ),
                }
            )
            response, parsed, error = self._try_structured(chat_messages, schema, response_model, max_tokens)

        if parsed is None:
            raise StructuredOutputError(
                f"Ollama model {self._model!r} failed to produce valid {response_model.__name__} "
                f"JSON after one repair retry: {error}"
            )
        assert response is not None  # always set alongside parsed in _try_structured

        return LLMResponse(
            text=response.message.content or "",
            parsed=parsed,
            usage=self._usage_from(response),
            latency_ms=self._latency_ms(response),
            model=response.model or self._model,
            provider_name="ollama",
            raw=response.model_dump(mode="json"),
        )

    def _try_structured(
        self,
        chat_messages: list[dict[str, str]],
        schema: dict,
        response_model: type[ModelT],
        max_tokens: int,
    ) -> tuple[ollama.ChatResponse | None, ModelT | None, str | None]:
        try:
            response = self._client.chat(
                model=self._model,
                messages=chat_messages,
                format=schema,
                think=self._think,
                options={"num_predict": self._num_predict(max_tokens)},
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        content = response.message.content or ""
        try:
            raw = json.loads(content)
            parsed = response_model.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            return response, None, str(exc)
        return response, parsed, None

    def _num_predict(self, max_tokens: int) -> int:
        return max_tokens if self._think is False else max_tokens + REASONING_TOKEN_ALLOWANCE

    @staticmethod
    def _latency_ms(response: ollama.ChatResponse) -> float:
        # eval_duration is model-inference time only (excludes load_duration),
        # which is the more meaningful "how long did the model take to think"
        # number for the stats panel.
        if response.eval_duration is not None:
            return response.eval_duration / 1e6
        return 0.0

    @staticmethod
    def _usage_from(response: ollama.ChatResponse) -> TokenUsage:
        return TokenUsage(
            input_tokens=response.prompt_eval_count or 0,
            output_tokens=response.eval_count or 0,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
        )
