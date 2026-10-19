"""Provider policy: the rules that would otherwise surface as a 400 mid-run."""

import pytest

from clarifyreview.config import (
    MODELS, accepts_temperature, cost_usd, judge_model, oracle_model,
    review_model, sampling_model, settings,
)
from clarifyreview.llm.providers.anthropic_backend import AnthropicBackend
from clarifyreview.llm.providers.gemini_backend import GeminiBackend


# ------------------------------------------------------------ temperature

def test_gemini_accepts_temperature_everywhere():
    for model in MODELS["gemini"].values():
        assert accepts_temperature(model), model


def test_anthropic_frontier_models_reject_temperature():
    assert not accepts_temperature("claude-opus-5")
    assert not accepts_temperature("claude-sonnet-5")
    assert accepts_temperature("claude-haiku-4-5")


def test_anthropic_backend_refuses_temperature_it_cannot_send():
    with pytest.raises(ValueError, match="does not accept"):
        AnthropicBackend._params("claude-opus-5", thinking=False, temperature=1.0)


def test_anthropic_backend_passes_temperature_where_supported():
    params = AnthropicBackend._params("claude-haiku-4-5", thinking=False, temperature=1.0)
    assert params["temperature"] == 1.0
    assert "thinking" not in params  # sampling wants raw decoder variation


def test_gemini_backend_sends_temperature_and_disables_thinking_for_sampling():
    cfg = GeminiBackend._sampling("gemini-3.6-flash", thinking=False, temperature=1.0)
    assert cfg["temperature"] == 1.0
    # Reasoning before a one-sentence answer suppresses the variation being measured.
    assert str(cfg["thinking_config"].thinking_level.value).lower() == "low"


def test_thinking_is_disabled_by_level_not_budget():
    """`thinking_budget=0` is rejected with a 400 on the 3.5+ family. A stub
    client cannot catch that, so the contract is pinned here instead."""
    cfg = GeminiBackend._sampling("gemini-3.6-flash", thinking=False, temperature=None)
    assert cfg["thinking_config"].thinking_budget is None
    assert str(cfg["thinking_config"].thinking_level.value).lower() == "low"


def test_gemini_backend_leaves_thinking_on_by_default():
    assert "thinking_config" not in GeminiBackend._sampling(
        "gemini-3.6-flash", thinking=True, temperature=None)


def test_no_latest_alias_is_used_as_a_default():
    """An alias can change model under a running study, which would silently
    break the requirement that the review model is fixed across conditions."""
    for provider, roles in MODELS.items():
        for role, model in roles.items():
            assert not model.endswith("-latest"), f"{provider}.{role} = {model}"


def test_anthropic_adaptive_thinking_is_the_default_shape():
    assert AnthropicBackend._params("claude-opus-5", thinking=True, temperature=None) == {
        "thinking": {"type": "adaptive"}
    }


# ----------------------------------------------------------- role resolution

def test_roles_resolve_for_the_active_provider():
    cfg = settings()
    assert review_model() == MODELS[cfg.provider]["review"]
    assert sampling_model() == MODELS[cfg.provider]["sampling"]
    assert judge_model() == MODELS[cfg.provider]["judge"]
    assert oracle_model() == MODELS[cfg.provider]["oracle"]


def test_gemini_samples_on_the_review_model():
    """No workaround is needed on Gemini, so dispersion reflects the review
    model's own instability rather than a weaker model's."""
    assert MODELS["gemini"]["sampling"] == MODELS["gemini"]["review"]


def test_anthropic_needs_a_separate_sampling_model():
    assert MODELS["anthropic"]["sampling"] != MODELS["anthropic"]["review"]
    assert accepts_temperature(MODELS["anthropic"]["sampling"])


def test_oracle_is_never_the_review_model_on_anthropic():
    """A weaker oracle volunteers less unasked-for information."""
    assert MODELS["anthropic"]["oracle"] != MODELS["anthropic"]["review"]


def test_every_role_has_a_model_on_every_provider():
    roles = {"review", "question", "judge", "oracle", "sampling"}
    for provider, models in MODELS.items():
        assert set(models) == roles, provider


def test_model_override_wins_over_provider_default(monkeypatch):
    from clarifyreview import config

    config.reset_settings()
    monkeypatch.setenv("CLARIFYREVIEW_MODEL_REVIEW", "gemini-2.5-pro")
    try:
        assert config.settings().model_for("review") == "gemini-2.5-pro"
    finally:
        monkeypatch.delenv("CLARIFYREVIEW_MODEL_REVIEW", raising=False)
        config.reset_settings()


# ------------------------------------------------------------------- costs

def test_cache_reads_are_an_order_of_magnitude_cheaper():
    fresh = cost_usd("claude-opus-5", input_tokens=12_000)
    cached = cost_usd("claude-opus-5", cache_read_tokens=12_000)
    assert cached == pytest.approx(fresh * 0.1)


def test_batch_halves_the_bill():
    assert cost_usd("claude-opus-5", input_tokens=1000, batch=True) == pytest.approx(
        cost_usd("claude-opus-5", input_tokens=1000) / 2)


def test_gemini_free_tier_costs_nothing():
    assert cost_usd("gemini-2.5-flash", input_tokens=50_000, output_tokens=5_000) == 0.0


def test_unknown_model_costs_zero_rather_than_raising():
    """A missing price must not take down an experiment run."""
    assert cost_usd("some-future-model", input_tokens=1000) == 0.0
