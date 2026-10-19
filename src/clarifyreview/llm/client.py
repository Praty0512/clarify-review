"""The one place this project talks to a model provider.

Everything else calls `LLM.structured()` or `LLM.text()`. Centralising it buys
three things the experiment needs: token and cost accounting on every call
(logged per run, reported in the paper), a single place where provider quirks
live, and one seam at which the provider can be swapped without touching a line
of research code.

`cached_context` and `instruction` are separate arguments on purpose. The context
is the large, stable part (the rendered pull request); the instruction is the
small, varying part. Anthropic puts an explicit cache breakpoint between them;
Gemini caches repeated prefixes implicitly. Either way the detector's eight
samples over one pull request should pay for the prefix roughly once, and the
hit rate is recorded so that assumption is checkable rather than assumed.
"""

from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from ..config import settings
from .base import Backend, MissingAPIKey, Result, Usage

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

__all__ = ["LLM", "BatchJob", "Result", "Usage", "MissingAPIKey"]


class LLM:
    """Thin, opinionated, provider-agnostic wrapper. Not a framework."""

    def __init__(self, backend: Backend | None = None, provider: str | None = None):
        if backend is None:
            from .providers import build_backend

            backend = build_backend(provider)
        self.backend = backend
        self.total = Usage()

    @property
    def provider(self) -> str:
        return self.backend.name

    def structured(
        self,
        *,
        model: str,
        schema: type[T],
        system: str,
        cached_context: str,
        instruction: str,
        max_tokens: int = 8192,
        thinking: bool = True,
        temperature: float | None = None,
    ) -> Result[T]:
        """A schema-validated response."""
        result = self.backend.structured(
            model=model, schema=schema, system=system,
            cached_context=cached_context, instruction=instruction,
            max_tokens=max_tokens, thinking=thinking, temperature=temperature,
        )
        self.total.add(result.usage)
        return result

    def text(
        self,
        *,
        model: str,
        system: str,
        cached_context: str,
        instruction: str,
        max_tokens: int = 4000,
        thinking: bool = False,
        temperature: float | None = None,
    ) -> Result[str]:
        """Free-text response. Used for intent hypotheses and oracle replies."""
        result = self.backend.text(
            model=model, system=system, cached_context=cached_context,
            instruction=instruction, max_tokens=max_tokens, thinking=thinking,
            temperature=temperature,
        )
        self.total.add(result.usage)
        return result

    def list_models(self) -> list[str]:
        return self.backend.list_models()


# ------------------------------------------------------------------- batching


class BatchJob:
    """Offline half-price batching. Anthropic only, for now.

    The ablation runner does not use this - it runs synchronously so that a
    failure is visible immediately rather than an hour later. It is kept because
    a full run at scale is the obvious place to want it, and because dropping the
    Anthropic path entirely would make the provider comparison impossible.
    """

    def __init__(self, client=None) -> None:
        if settings().provider != "anthropic":
            raise NotImplementedError(
                "BatchJob currently supports the Anthropic provider only. On "
                "Gemini, run the ablation synchronously (experiments/run_matrix.py "
                "already does), or set CLARIFYREVIEW_PROVIDER=anthropic."
            )
        import anthropic

        key = settings().api_key()
        self._client = client or (
            anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        )
        self._requests: list = []

    def add(self, custom_id: str, **params) -> None:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        self._requests.append(
            Request(custom_id=custom_id, params=MessageCreateParamsNonStreaming(**params))
        )

    def __len__(self) -> int:
        return len(self._requests)

    def submit(self) -> str:
        batch = self._client.messages.batches.create(requests=self._requests)
        log.info("submitted batch %s with %d requests", batch.id, len(self._requests))
        self._requests = []
        return batch.id

    def wait(self, batch_id: str, poll_s: int = 30, timeout_s: int = 86400) -> None:
        import time

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            batch = self._client.messages.batches.retrieve(batch_id)
            if batch.processing_status == "ended":
                log.info("batch %s ended: %d succeeded, %d errored", batch_id,
                         batch.request_counts.succeeded, batch.request_counts.errored)
                return
            time.sleep(poll_s)
        raise TimeoutError(f"batch {batch_id} did not finish within {timeout_s}s")

    def results(self, batch_id: str) -> dict[str, object]:
        out: dict[str, object] = {}
        for item in self._client.messages.batches.results(batch_id):
            if item.result.type == "succeeded":
                out[item.custom_id] = item.result.message
            else:
                log.warning("batch item %s: %s", item.custom_id, item.result.type)
                out[item.custom_id] = None
        return out
