"""Configuration, and the model policy the whole project runs under.

Three providers are supported (Gemini, Anthropic, and local models via Ollama). The one in use is chosen by CLARIFYREVIEW_PROVIDER
and affects nothing above `llm/` - detectors, pipeline and experiment harness all
talk to the same wrapper, so switching provider changes no research code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["gemini", "anthropic", "ollama"]

# --------------------------------------------------------------- model policy
#
# One role -> one model, per provider. The review model in particular is fixed
# across every experimental condition; if it varies the ablation is confounded
# and no result from it means anything.
#
# Gemini defaults were chosen by probing a real free-tier key: the 2.5 family is
# closed to new keys, and the pro tier exhausts its free quota immediately. Never
# put a `-latest` alias here - the review model must stay fixed for the whole
# ablation, and an alias can change under you mid-study. Override any of these with
# CLARIFYREVIEW_MODEL_REVIEW, _QUESTION, _JUDGE, _ORACLE, _SAMPLING.
# Run `clarifyreview models` to list what your key can actually reach.
MODELS: dict[str, dict[str, str]] = {
    "gemini": {
        # Fixed for the whole v2 study: every condition is reviewed by this model.
        # Chosen under free-tier limits measured on 19 October 2026 - see below.
        "review": "gemini-3.5-flash-lite",
        # Question, oracle and judge run on a different model family. That keeps
        # them off the reviewer's daily quota and, for the judge, removes the
        # self-preference bias of a model scoring its own output.
        "question": "gemma-4-31b-it",
        "judge": "gemma-4-31b-it",
        "oracle": "gemma-4-31b-it",
        "sampling": "gemini-3.5-flash-lite",
    },
    "anthropic": {
        "review": "claude-opus-5",
        "question": "claude-opus-5",
        "judge": "claude-opus-5",
        # Deliberately not the review model: a weaker oracle volunteers less
        # unasked-for information, which is the leakage failure mode Study A has
        # to defend against.
        "oracle": "claude-sonnet-5",
        # `temperature` is rejected with a 400 on Opus 5, Sonnet 5 and the whole
        # 4.6+ family, so the sampling detector runs on the one current tier that
        # still accepts it. On Gemini no such workaround is needed and the
        # sampler runs on the review model itself, which is the better
        # instrument - dispersion then reflects the review model's own
        # instability rather than a different model's.
        "sampling": "claude-haiku-4-5",
    },
    # Local models, ~4 GB VRAM laptop. See docs/ollama.md for the rationale. Tags
    # are explicit (never `:latest`) so a pull cannot change the model under a
    # study; `served_model` additionally records the weights digest.
    "ollama": {
        "review": "qwen3:4b-instruct-2507-q4_K_M",
        "sampling": "qwen3:4b-instruct-2507-q4_K_M",
        # A different family from the reviewer: the judge does not score its own
        # output, and a weaker oracle volunteers less unasked-for information.
        "question": "llama3.2:3b",
        "oracle": "llama3.2:3b",
        "judge": "llama3.2:3b",
    },
}

# Measured on a free key, 19 October 2026 (Google does not publish these):
#   gemini-3.6-flash  20 requests/day.
#   gemini-3.5-flash  charged to gemini-3.6-flash's quota - the two share one
#                     allowance, so spreading roles across them spreads nothing.
#   gemini-3.7-flash, gemini-3.1-flash-lite  persistently 503 (overloaded).
# Every run records the model that actually served it (`served_model`), so the
# claim that all conditions used one reviewer is checked, not assumed.


def supports_thinking_config(model: str) -> bool:
    """Gemma rejects any thinking configuration with a 400."""
    return not model.startswith("gemma")


# Which models accept temperature / top_p / top_k. Every Gemini model does; on
# Anthropic only the older tiers do.
MODELS_ACCEPTING_TEMPERATURE = frozenset({"claude-haiku-4-5"})


def accepts_temperature(model: str) -> bool:
    """Gemini accepts sampling parameters everywhere; Anthropic does not."""
    if model.startswith(("gemini", "gemma")):
        return True
    if ":" in model:  # Ollama "name:tag" ids; local models take any sampling option
        return True
    return model in MODELS_ACCEPTING_TEMPERATURE


# USD per million tokens: (input, output). Cache reads bill at a fraction of
# input; cache writes at a premium on Anthropic and not at all on Gemini.
#
# The Gemini entries are 0.0 because the free AI Studio tier bills nothing, which
# makes them correct for a free key and wrong for a paid one. If you move to a
# paid key, put the published rates here before quoting any cost figure in the
# paper - `cost_report` in experiments/analyze.py reads straight from this table.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gemini-3.7-flash": (0.00, 0.00),
    "gemini-3.6-flash": (0.00, 0.00),
    "gemini-3.5-flash": (0.00, 0.00),
    "gemini-3.5-flash-lite": (0.00, 0.00),
    "gemini-3.1-flash-lite": (0.00, 0.00),
    "gemma-4-31b-it": (0.00, 0.00),
    # Local models cost nothing per token.
    "qwen3:4b": (0.00, 0.00),
    "qwen3:4b-instruct-2507-q4_K_M": (0.00, 0.00),
    "llama3.2:3b": (0.00, 0.00),
    "gemma3:4b": (0.00, 0.00),
    "qwen2.5-coder:3b": (0.00, 0.00),
    "qwen2.5-coder:7b": (0.00, 0.00),
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25
BATCH_MULTIPLIER = 0.5


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    batch: bool = False,
) -> float:
    """Dollar cost of one call. Logged per run so the paper can report it.

    An unknown model costs 0.0 rather than raising: a missing price should not
    take down an experiment run, and a zero total is obvious in the report.
    """
    rate_in, rate_out = PRICING.get(model, (0.0, 0.0))
    total = (
        input_tokens * rate_in
        + output_tokens * rate_out
        + cache_read_tokens * rate_in * CACHE_READ_MULTIPLIER
        + cache_write_tokens * rate_in * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000
    return total * (BATCH_MULTIPLIER if batch else 1.0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", case_sensitive=False
    )

    clarifyreview_provider: Provider = "gemini"

    gemini_api_key: str | None = None
    google_api_key: str | None = None  # the SDK's own conventional name
    anthropic_api_key: str | None = None

    # Local Ollama server. The key is only for a proxy that demands one.
    ollama_host: str = "http://127.0.0.1:11434"
    ollama_num_ctx_max: int = 16384
    ollama_num_predict_max: int = 4096
    ollama_think: Literal["off", "on", "auto"] = "off"
    ollama_keep_alive: str = "10m"
    ollama_timeout_s: float = 600
    ollama_api_key: str | None = None

    github_token: str | None = None
    github_webhook_secret: str | None = None

    # Per-role model overrides. Empty means "use the provider default".
    clarifyreview_model_review: str = ""
    clarifyreview_model_question: str = ""
    clarifyreview_model_judge: str = ""
    clarifyreview_model_oracle: str = ""
    clarifyreview_model_sampling: str = ""

    clarifyreview_db: Path = Path("data/clarifyreview.db")
    clarifyreview_detector: str = "heuristic"
    clarifyreview_clarify_timeout: int = 86400

    # Live tool, large repositories (see ingest.checkout and ingest.triage).
    clarifyreview_checkout: bool = True
    clarifyreview_checkout_dir: Path = Path("data/checkouts")
    clarifyreview_skip_globs: str = ""  # comma-separated, on top of the built-in list

    uncertainty_samples: int = 8
    # Frozen on the dev split, then committed. Never tuned on the ablation set.
    thresholds_path: Path = Path("data/thresholds.json")
    classifier_path: Path = Path("data/models/ambiguity_clf.joblib")
    # Live tool only (CLI ingest/detect/review, webhook bot). Unset means the live
    # tool uses DEFAULT_THRESHOLDS, NOT data/thresholds.json: that file was frozen
    # on a degenerate labelled set and is a study artefact. Set
    # CLARIFYREVIEW_THRESHOLDS_PATH to opt a deployment into a file you trust.
    clarifyreview_thresholds_path: Path | None = None

    # ------------------------------------------------------------- accessors

    @property
    def provider(self) -> str:
        return self.clarifyreview_provider

    def api_key(self) -> str | None:
        if self.provider == "gemini":
            return self.gemini_api_key or self.google_api_key
        if self.provider == "ollama":
            # A local server needs no key; a placeholder keeps callers that
            # require a non-empty key (cli.py) working unchanged.
            return self.ollama_api_key or "ollama"
        return self.anthropic_api_key

    def skip_globs(self) -> tuple[str, ...]:
        return tuple(g.strip() for g in self.clarifyreview_skip_globs.split(",") if g.strip())

    def model_for(self, role: str) -> str:
        """Resolve a role to a model id: explicit override, else provider default."""
        override = getattr(self, f"clarifyreview_model_{role}", "")
        if override:
            return override
        try:
            return MODELS[self.provider][role]
        except KeyError:
            raise ValueError(
                f"no model configured for role {role!r} on provider {self.provider!r}"
            ) from None


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook: drop the cached singleton so env changes take effect."""
    global _settings
    _settings = None


# Backwards-compatible role accessors. Call these rather than importing a
# constant, so a provider switch is picked up without touching call sites.
def review_model() -> str:
    return settings().model_for("review")


def question_model() -> str:
    return settings().model_for("question")


def judge_model() -> str:
    return settings().model_for("judge")


def oracle_model() -> str:
    return settings().model_for("oracle")


def sampling_model() -> str:
    return settings().model_for("sampling")
