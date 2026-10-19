"""The two backends, exercised end to end against stub SDK clients.

No network and no key. These assert the request each backend builds and that a
schema-validated object comes back, which is what would otherwise only be found
out by spending money.
"""

from dataclasses import dataclass

import pytest

from clarifyreview.llm.base import MissingAPIKey, Usage
from clarifyreview.llm.client import LLM
from clarifyreview.llm.providers.gemini_backend import GeminiBackend
from clarifyreview.types import ReviewFinding, ReviewOutput


REVIEW = ReviewOutput(
    intent_summary="moves validation upstream",
    overall_confidence=0.9,
    verdict="approve",
    findings=[ReviewFinding(file="a.py", line=1, severity="minor", category="style",
                            claim="c", evidence="e", suggested_fix="none",
                            confidence=0.5)],
)


@dataclass
class FakeUsage:
    prompt_token_count: int = 12_000
    cached_content_token_count: int = 9_000
    candidates_token_count: int = 800
    thoughts_token_count: int = 200


class FakeResponse:
    def __init__(self, parsed=None, text=""):
        self.parsed = parsed
        self.text = text
        self.usage_metadata = FakeUsage()


class FakeModels:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def list(self):
        class M:
            def __init__(self, n): self.name, self.supported_actions = n, ["generateContent"]
        return [M("models/gemini-3.6-flash"), M("models/gemini-3.5-flash")]


class FakeGenAIClient:
    def __init__(self, response):
        self.models = FakeModels(response)


def backend(response):
    return GeminiBackend(client=FakeGenAIClient(response))


# ------------------------------------------------------------------ gemini

def test_structured_returns_a_validated_object():
    b = backend(FakeResponse(parsed=REVIEW))
    result = b.structured(model="gemini-3.6-flash", schema=ReviewOutput,
                          system="sys", cached_context="ctx", instruction="go",
                          max_tokens=4096, thinking=True, temperature=None)
    assert isinstance(result.value, ReviewOutput)
    assert result.value.verdict == "approve"


def test_structured_requests_json_against_the_schema():
    b = backend(FakeResponse(parsed=REVIEW))
    b.structured(model="gemini-3.6-flash", schema=ReviewOutput, system="sys",
                 cached_context="ctx", instruction="go", max_tokens=4096,
                 thinking=True, temperature=None)
    cfg = b._client.models.calls[0]["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema is ReviewOutput
    assert cfg.system_instruction == "sys"


def test_cached_context_is_sent_before_the_instruction():
    """Implicit caching only helps if the stable part leads the request."""
    b = backend(FakeResponse(parsed=REVIEW))
    b.structured(model="gemini-3.6-flash", schema=ReviewOutput, system="s",
                 cached_context="THE-CONTEXT", instruction="THE-INSTRUCTION",
                 max_tokens=100, thinking=True, temperature=None)
    assert b._client.models.calls[0]["contents"] == ["THE-CONTEXT", "THE-INSTRUCTION"]


def test_unparseable_response_raises_with_the_raw_text():
    b = backend(FakeResponse(parsed=None, text="not json at all"))
    with pytest.raises(ValueError, match="not json at all"):
        b.structured(model="gemini-3.6-flash", schema=ReviewOutput, system="s",
                     cached_context="c", instruction="i", max_tokens=100,
                     thinking=True, temperature=None)


def test_usage_separates_cached_from_fresh_input():
    """prompt_token_count includes the cached portion; billing them together
    would hide the whole point of the cache."""
    b = backend(FakeResponse(parsed=REVIEW))
    u = b.structured(model="gemini-3.6-flash", schema=ReviewOutput, system="s",
                     cached_context="c", instruction="i", max_tokens=100,
                     thinking=True, temperature=None).usage
    assert u.cache_read_tokens == 9_000
    assert u.input_tokens == 3_000            # 12,000 prompt - 9,000 cached
    assert u.output_tokens == 1_000           # 800 candidates + 200 thoughts
    assert u.calls == 1


def test_text_returns_stripped_output():
    b = backend(FakeResponse(text="  an intent hypothesis  "))
    assert b.text(model="gemini-3.6-flash", system="s", cached_context="c",
                  instruction="i", max_tokens=100, thinking=False,
                  temperature=1.0).value == "an intent hypothesis"


def test_list_models_strips_the_models_prefix():
    assert backend(FakeResponse()).list_models() == ["gemini-3.5-flash", "gemini-3.6-flash"]


def test_missing_key_raises_actionable_error(monkeypatch):
    from clarifyreview import config

    config.reset_settings()
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config.Settings, "api_key", lambda self: None)
    try:
        with pytest.raises(MissingAPIKey, match="aistudio.google.com"):
            GeminiBackend()
    finally:
        config.reset_settings()


# ------------------------------------------------------------------- facade

def test_llm_accumulates_usage_across_calls():
    llm = LLM(backend=backend(FakeResponse(text="x")))
    for _ in range(3):
        llm.text(model="gemini-3.6-flash", system="s", cached_context="c",
                 instruction="i")
    assert llm.total.calls == 3
    assert llm.total.cache_read_tokens == 27_000


def test_llm_reports_its_provider():
    assert LLM(backend=backend(FakeResponse(text="x"))).provider == "gemini"


def test_usage_add_is_field_wise():
    a, b = Usage(input_tokens=1, calls=1), Usage(input_tokens=2, calls=1)
    a.add(b)
    assert (a.input_tokens, a.calls) == (3, 2)


# ------------------------------------------------------- transient failures

class FlakyModels(FakeModels):
    """Fails with `exc` for the first `fail_times` calls, then succeeds."""

    def __init__(self, response, exc, fail_times):
        super().__init__(response)
        self.exc = exc
        self.fail_times = fail_times
        self.attempts = 0

    def generate_content(self, **kwargs):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise self.exc
        return super().generate_content(**kwargs)


def _err(cls, code):
    """Build a real SDK error without going near the network.

    The SDK's errors take (code, response_json, response); passing the JSON
    shape the API actually returns keeps this honest rather than a stand-in.
    """
    from google.genai import errors

    return getattr(errors, cls)(
        code, {"error": {"code": code, "message": f"{code} simulated"}}, None)


def _flaky_backend(exc, fail_times, monkeypatch):
    b = GeminiBackend(client=FakeGenAIClient(FakeResponse(text="ok")))
    b._client.models = FlakyModels(FakeResponse(text="ok"), exc, fail_times)
    monkeypatch.setattr("time.sleep", lambda _s: None)   # no real backoff in tests
    return b


def test_retries_a_transient_503_and_succeeds(monkeypatch):
    """A single 503 must not lose an ablation instance."""
    b = _flaky_backend(_err("ServerError", 503), 2, monkeypatch)
    assert b.text(model="gemini-3.6-flash", system="s", cached_context="c",
                  instruction="i").value == "ok"
    assert b._client.models.attempts == 3


def test_retries_a_429_rate_limit(monkeypatch):
    b = _flaky_backend(_err("ClientError", 429), 1, monkeypatch)
    assert b.text(model="gemini-3.6-flash", system="s", cached_context="c",
                  instruction="i").value == "ok"
    assert b._client.models.attempts == 2


def test_gives_up_after_max_attempts(monkeypatch):
    from google.genai import errors

    b = _flaky_backend(_err("ServerError", 503), 99, monkeypatch)
    with pytest.raises(errors.ServerError):
        b.text(model="gemini-3.6-flash", system="s", cached_context="c", instruction="i")
    assert b._client.models.attempts == GeminiBackend.MAX_ATTEMPTS


def test_does_not_retry_a_request_level_error(monkeypatch):
    """A 400 or 404 is our fault - a bad argument, or a model this key cannot
    reach. Retrying wastes quota and delays the real error."""
    from google.genai import errors

    b = _flaky_backend(_err("ClientError", 404), 99, monkeypatch)
    with pytest.raises(errors.ClientError):
        b.text(model="gemini-3.6-flash", system="s", cached_context="c", instruction="i")
    assert b._client.models.attempts == 1


def _quota_err(quota_id):
    from google.genai import errors

    return errors.ClientError(429, {"error": {
        "code": 429, "message": "quota exceeded",
        "details": [{"violations": [{"quotaId": quota_id}]}]}}, None)


def test_per_minute_rate_limit_is_retried(monkeypatch):
    b = GeminiBackend(client=FakeGenAIClient(FakeResponse(text="ok")))
    b._client.models = FlakyModels(
        FakeResponse(text="ok"),
        _quota_err("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"), 1)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    assert b.text(model="gemini-3.6-flash", system="s", cached_context="c",
                  instruction="i").value == "ok"
    assert b._client.models.attempts == 2


def test_per_day_quota_is_not_retried(monkeypatch):
    """Each retry spends another request against the very quota that is
    exhausted, turning one refusal into five."""
    from google.genai import errors

    b = GeminiBackend(client=FakeGenAIClient(FakeResponse(text="ok")))
    b._client.models = FlakyModels(
        FakeResponse(text="ok"),
        _quota_err("GenerateRequestsPerDayPerProjectPerModel-FreeTier"), 99)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(errors.ClientError):
        b.text(model="gemini-3.6-flash", system="s", cached_context="c", instruction="i")
    assert b._client.models.attempts == 1


def test_gemma_is_never_sent_a_thinking_config():
    """Gemma rejects any thinking configuration with a 400."""
    assert "thinking_config" not in GeminiBackend._sampling("gemma-4-31b-it", thinking=False,
                                                            temperature=None)
    assert "thinking_config" in GeminiBackend._sampling("gemini-3.5-flash-lite", thinking=False,
                                                        temperature=None)


def test_usage_records_the_model_that_actually_served_the_request():
    """Providers can alias one model to another; the run must record which
    model really answered so 'one reviewer for every condition' is checkable."""
    resp = FakeResponse(text="ok")
    resp.model_version = "gemini-3.5-flash-lite-002"
    b = backend(resp)
    u = b.text(model="gemini-3.5-flash-lite", system="s", cached_context="c",
               instruction="i").usage
    assert u.served_model == "gemini-3.5-flash-lite-002"
