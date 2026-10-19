"""Provider-agnostic types and the backend contract.

Everything above `llm/` sees only `LLM.structured()` and `LLM.text()`, so a
backend is the entire surface a new provider has to implement. Keeping the
contract this narrow is what makes swapping providers a one-file change rather
than a refactor of the detectors and the experiment harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    """Accumulated across a run so cost per condition is a reported number."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    latency_ms: int = 0
    # The model that actually answered, as reported by the provider. It can
    # differ from the one requested when a provider aliases models.
    served_model: str | None = None

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cost_usd += other.cost_usd
        self.calls += other.calls
        self.latency_ms += other.latency_ms


@dataclass
class Result(Generic[T]):
    value: T
    usage: Usage = field(default_factory=Usage)


class Backend(Protocol):
    """What a provider must implement. Two methods, one shape."""

    name: str

    def structured(self, *, model: str, schema: type[T], system: str,
                   cached_context: str, instruction: str, max_tokens: int,
                   thinking: bool, temperature: float | None) -> Result: ...

    def text(self, *, model: str, system: str, cached_context: str,
             instruction: str, max_tokens: int, thinking: bool,
             temperature: float | None) -> Result: ...

    def list_models(self) -> list[str]:
        """Model ids this key can reach. Used by `clarifyreview models`."""


class MissingAPIKey(RuntimeError):
    """Raised with actionable text rather than an SDK-level failure."""
