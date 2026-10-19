"""Anthropic Claude backend.

Kept working alongside Gemini so the project is not trading one lock-in for
another, and so the two providers can be compared if that ever becomes
interesting for the paper.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel

from ...config import accepts_temperature, cost_usd, settings
from ..base import Backend, MissingAPIKey, Result, Usage

log = logging.getLogger(__name__)

KEY_HELP = (
    "No Anthropic API key found.\n"
    "  export ANTHROPIC_API_KEY=sk-ant-...\n"
    "  or add ANTHROPIC_API_KEY=... to your .env file."
)


class AnthropicBackend(Backend):
    name = "anthropic"

    def __init__(self, client=None) -> None:
        self._client = client
        if client is None:
            key = settings().api_key()
            if not key:
                raise MissingAPIKey(KEY_HELP)
            import anthropic

            self._client = anthropic.Anthropic(api_key=key)

    # ------------------------------------------------------------ core calls

    def structured(self, *, model, schema: type[BaseModel], system, cached_context,
                   instruction, max_tokens=16000, thinking=True, temperature=None):
        started = time.monotonic()
        response = self._call(
            self._client.messages.parse,
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[self._user(cached_context, instruction)],
            output_format=schema,
            **self._params(model, thinking, temperature),
        )
        usage = self._usage(model, response, started)
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(f"{model} returned no parseable output for {schema.__name__}")
        return Result(value=parsed, usage=usage)

    def text(self, *, model, system, cached_context, instruction,
             max_tokens=4000, thinking=False, temperature=None):
        started = time.monotonic()
        response = self._call(
            self._client.messages.create,
            model=model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[self._user(cached_context, instruction)],
            **self._params(model, thinking, temperature),
        )
        usage = self._usage(model, response, started)
        text = "".join(b.text for b in response.content if b.type == "text")
        return Result(value=text.strip(), usage=usage)

    def list_models(self) -> list[str]:
        return sorted(m.id for m in self._client.models.list(limit=100))

    # -------------------------------------------------------------- internals

    @staticmethod
    def _user(cached_context: str, instruction: str) -> dict:
        """The cache breakpoint sits between the stable context and the varying
        instruction, so repeated sampling over one pull request pays for the
        prefix once."""
        return {
            "role": "user",
            "content": [
                {"type": "text", "text": cached_context,
                 "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": instruction},
            ],
        }

    @staticmethod
    def _params(model: str, thinking: bool, temperature: float | None) -> dict:
        params: dict = {}
        if thinking:
            params["thinking"] = {"type": "adaptive"}
        if temperature is not None:
            if not accepts_temperature(model):
                # Opus 5 / Sonnet 5 / the 4.6+ family reject temperature with a
                # 400. Failing loudly beats silently dropping it - a sampling
                # detector that is secretly deterministic would produce a
                # meaningless dispersion score.
                raise ValueError(
                    f"{model} does not accept `temperature`. Use the configured "
                    f"sampling model, switch to the Gemini provider, or use the "
                    f"perturbation detector, which varies the prompt instead."
                )
            params["temperature"] = temperature
            params.pop("thinking", None)  # sampling wants raw decoder variation
        return params

    @staticmethod
    def _call(fn, **kwargs):
        import anthropic

        try:
            return fn(**kwargs)
        except anthropic.NotFoundError:
            raise
        except anthropic.RateLimitError:
            log.warning("rate limited; SDK retries exhausted")
            raise
        except anthropic.APIStatusError as exc:
            log.error("API error %s: %s", exc.status_code, exc.message)
            raise
        except anthropic.APIConnectionError:
            log.error("could not reach the API")
            raise

    @staticmethod
    def _usage(model: str, response, started: float) -> Usage:
        u = response.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        return Usage(
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            cost_usd=cost_usd(model, input_tokens=u.input_tokens,
                              output_tokens=u.output_tokens,
                              cache_read_tokens=cache_read,
                              cache_write_tokens=cache_write),
            calls=1,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
