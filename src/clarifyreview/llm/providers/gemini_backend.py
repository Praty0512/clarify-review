"""Google Gemini backend.

Two things differ from the Anthropic backend and both are worth knowing:

Sampling. Gemini accepts `temperature` on every model, so the sampling detector
runs on the same model that writes the reviews. That is a better instrument than
the Anthropic path allows - dispersion across samples then reflects the review
model's own instability rather than a different, weaker model's.

Caching. There is no inline cache breakpoint to set. Gemini's 2.5 models apply
implicit caching to repeated prefixes automatically, so `cached_context` is
simply placed first in the request and the hit rate is read back from
`usage_metadata.cached_content_token_count`. The saving is still measured, it is
just not something the caller asks for. Explicit `client.caches` objects exist
but carry a minimum size that a ~12K-token pull request context may not reach.
"""

from __future__ import annotations

import logging
import time

from pydantic import BaseModel

from ...config import cost_usd, settings, supports_thinking_config
from ..base import Backend, MissingAPIKey, Result, Usage

log = logging.getLogger(__name__)

KEY_HELP = (
    "No Gemini API key found.\n"
    "  Get a free key at https://aistudio.google.com/apikey\n"
    "  then either:  export GEMINI_API_KEY=...\n"
    "  or add GEMINI_API_KEY=... to your .env file."
)


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self, client=None) -> None:
        self._client = client
        if client is None:
            key = settings().api_key()
            if not key:
                raise MissingAPIKey(KEY_HELP)
            from google import genai

            self._client = genai.Client(api_key=key)

    # ------------------------------------------------------------ core calls

    def structured(self, *, model, schema: type[BaseModel], system, cached_context,
                   instruction, max_tokens=8192, thinking=True, temperature=None):
        from google.genai import types

        started = time.monotonic()
        response = self._call(
            model=model,
            contents=[cached_context, instruction],
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                response_schema=schema,
                **self._sampling(model, thinking, temperature),
            ),
        )
        usage = self._usage(model, response, started)
        parsed = response.parsed
        if parsed is None:
            parsed = self._recover_json(response.text or "", schema)
        if parsed is None:
            raise ValueError(
                f"{model} returned no parseable output for {schema.__name__}. "
                f"Raw text: {(response.text or '')[:300]!r}"
            )
        return Result(value=parsed, usage=usage)

    def text(self, *, model, system, cached_context, instruction,
             max_tokens=4000, thinking=False, temperature=None):
        from google.genai import types

        started = time.monotonic()
        response = self._call(
            model=model,
            contents=[cached_context, instruction],
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                **self._sampling(model, thinking, temperature),
            ),
        )
        usage = self._usage(model, response, started)
        return Result(value=(response.text or "").strip(), usage=usage)

    @staticmethod
    def _recover_json(text: str, schema: type[BaseModel]):
        """Parse a schema object the SDK declined to.

        Gemma honours the requested schema but sometimes wraps the object in
        whitespace, a code fence or a trailing remark, and the SDK's parser then
        returns nothing. Decoding the first JSON object in the text and
        validating it against the same schema recovers it without loosening the
        contract: anything that does not validate is still rejected.
        """
        import json

        from pydantic import ValidationError

        start = text.find("{")
        if start < 0:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(text[start:])
            return schema.model_validate(obj)
        except (json.JSONDecodeError, ValidationError):
            return None

    def list_models(self) -> list[str]:
        out = []
        for m in self._client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                out.append((m.name or "").replace("models/", ""))
        return sorted(out)

    # -------------------------------------------------------------- internals

    @staticmethod
    def _sampling(model: str, thinking: bool, temperature: float | None) -> dict:
        from google.genai import types

        cfg: dict = {}
        if temperature is not None:
            cfg["temperature"] = temperature
        if not thinking and supports_thinking_config(model):
            # Gemini models think by default, and the sampling detector does not
            # want that: reasoning before a one-sentence answer suppresses exactly
            # the variation being measured.
            #
            # `thinking_budget=0` is the 2.5-era way to turn it off and is
            # rejected outright by the 3.5+ family (400 INVALID_ARGUMENT), which a
            # stub client cannot catch. `thinking_level` is the current control
            # and is accepted by both, so it is what we send.
            cfg["thinking_config"] = types.ThinkingConfig(thinking_level="low")
        return cfg

    # A 600-call ablation run against a busy free tier will meet transient
    # failures. Without retries a single 503 loses that instance, and enough of
    # them make the run unusable; with them the run merely takes longer.
    MAX_ATTEMPTS = 5
    BASE_BACKOFF_S = 4.0

    @staticmethod
    def _is_daily_quota(exc) -> bool:
        """Distinguish a per-day cap from a per-minute rate limit.

        The API names the exhausted quota in the error body, e.g.
        `GenerateRequestsPerDayPerProjectPerModel-FreeTier`. Only the per-minute
        kind is worth waiting out.
        """
        blob = str(getattr(exc, "details", "") or "") + str(exc)
        lowered = blob.lower()
        return "perday" in lowered or "per day" in lowered

    def _call(self, **kwargs):
        """Retry transient failures; fail fast on anything the request caused."""
        import random

        from google.genai import errors

        last: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                return self._client.models.generate_content(**kwargs)
            except errors.ClientError as exc:
                code = getattr(exc, "code", None)
                if code != 429:
                    # 400, 404 and friends are our fault: a bad argument or a
                    # model this key cannot reach. Retrying cannot help.
                    log.error("Gemini client error %s: %s", code or "?", exc)
                    raise
                if self._is_daily_quota(exc):
                    # Not every 429 is transient. A per-day free-tier cap will
                    # not clear within any backoff we could sit through, and
                    # each retry spends another request against the very quota
                    # that is exhausted - turning one refusal into five.
                    log.error("daily free-tier quota exhausted for this model; "
                              "not retrying. Switch model or wait for the reset.")
                    raise
                last = exc
                log.warning("rate limited (attempt %d/%d); request rate too high",
                            attempt, self.MAX_ATTEMPTS)
            except errors.ServerError as exc:
                last = exc
                log.warning("Gemini unavailable (attempt %d/%d): %s",
                            attempt, self.MAX_ATTEMPTS, getattr(exc, "code", "?"))

            if attempt < self.MAX_ATTEMPTS:
                # Exponential backoff with jitter, so a batch of parallel runs
                # does not retry in lockstep and re-create the spike.
                delay = self.BASE_BACKOFF_S * (2 ** (attempt - 1))
                time.sleep(delay * (0.5 + random.random()))

        log.error("giving up after %d attempts", self.MAX_ATTEMPTS)
        raise last  # type: ignore[misc]

    @staticmethod
    def _usage(model: str, response, started: float) -> Usage:
        u = response.usage_metadata
        prompt = getattr(u, "prompt_token_count", 0) or 0
        cached = getattr(u, "cached_content_token_count", 0) or 0
        # Thinking tokens bill as output but are reported separately.
        out = (getattr(u, "candidates_token_count", 0) or 0) + (
            getattr(u, "thoughts_token_count", 0) or 0)
        # prompt_token_count includes the cached portion; bill them separately so
        # the implicit-cache saving shows up in the cost report.
        fresh = max(prompt - cached, 0)
        return Usage(
            input_tokens=fresh,
            output_tokens=out,
            cache_read_tokens=cached,
            cache_write_tokens=0,  # Gemini does not bill implicit cache writes
            cost_usd=cost_usd(model, input_tokens=fresh, output_tokens=out,
                              cache_read_tokens=cached),
            calls=1,
            latency_ms=int((time.monotonic() - started) * 1000),
            served_model=getattr(response, "model_version", None) or model,
        )
