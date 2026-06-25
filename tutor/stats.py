"""Accumulates per-call LLM inference stats (latency, tokens, cache, cost) for
the dashboard's stats panel and debug panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from tutor.llm.base import LLMResponse, TokenUsage

CallType = Literal["evaluator", "tutor"]

# USD per 1M tokens, (input, output). Unknown/local models default to $0 --
# Ollama is free/local, and an unrecognized Anthropic model just won't show a
# cost estimate rather than guessing wrong.
PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


@dataclass
class CallRecord:
    call_type: CallType
    provider_name: str
    model: str
    latency_ms: float
    usage: TokenUsage
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def estimated_cost_usd(self) -> float:
        prices = PRICING_PER_MTOK.get(self.model)
        if prices is None:
            return 0.0
        input_price, output_price = prices
        cost = self.usage.input_tokens * input_price
        cost += self.usage.output_tokens * output_price
        if self.usage.cache_creation_input_tokens:
            cost += self.usage.cache_creation_input_tokens * input_price * CACHE_WRITE_MULTIPLIER
        if self.usage.cache_read_input_tokens:
            cost += self.usage.cache_read_input_tokens * input_price * CACHE_READ_MULTIPLIER
        return cost / 1_000_000


@dataclass
class InferenceStats:
    records: list[CallRecord] = field(default_factory=list)

    def record(self, call_type: CallType, response: LLMResponse) -> CallRecord:
        rec = CallRecord(
            call_type=call_type,
            provider_name=response.provider_name,
            model=response.model,
            latency_ms=response.latency_ms,
            usage=response.usage,
        )
        self.records.append(rec)
        return rec

    def last(self, call_type: CallType) -> CallRecord | None:
        for rec in reversed(self.records):
            if rec.call_type == call_type:
                return rec
        return None

    @property
    def total_calls(self) -> int:
        return len(self.records)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.usage.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.usage.output_tokens for r in self.records)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(r.usage.cache_read_input_tokens or 0 for r in self.records)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(r.usage.cache_creation_input_tokens or 0 for r in self.records)

    @property
    def total_estimated_cost_usd(self) -> float:
        return sum(r.estimated_cost_usd for r in self.records)

    @property
    def average_latency_ms(self) -> float:
        if not self.records:
            return 0.0
        return sum(r.latency_ms for r in self.records) / len(self.records)
