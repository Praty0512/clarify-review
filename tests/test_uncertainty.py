"""Dispersion measures, with a stub LLM."""

import numpy as np

from clarifyreview.detect.base import Thresholds
from clarifyreview.detect.uncertainty import (
    PerturbationUncertaintyDetector, SamplingUncertaintyDetector, TfidfEmbedder,
    mean_pairwise_distance, semantic_entropy,
)
from clarifyreview.llm.client import Result, Usage


class StubLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def text(self, **kwargs):
        self.calls.append(kwargs)
        value = self.replies[(len(self.calls) - 1) % len(self.replies)]
        return Result(value=value, usage=Usage(cost_usd=0.0001, calls=1))


AGREEING = ["It removes a redundant null check on the user email."] * 8
DISAGREEING = [
    "It removes a null check on the user email.",
    "It adds pagination to the search endpoint.",
    "It upgrades the logging library to version three.",
    "It fixes a race condition in the cache eviction path.",
    "It renames a private helper function.",
    "It disables TLS verification for internal requests.",
    "It reformats the file with a new line length.",
    "It changes the database connection pool size.",
]


def _detector(cls, replies):
    return cls(
        llm=StubLLM(replies), n=8, embedder=TfidfEmbedder(),
        thresholds=Thresholds({"sampling": 0.35, "perturbation": 0.35}, "test"),
    )


def test_agreement_means_low_ambiguity(ambiguous_ctx):
    d = _detector(SamplingUncertaintyDetector, AGREEING)
    decision = d.decide(ambiguous_ctx)
    assert decision.score < 0.2
    assert decision.ask is False


def test_disagreement_means_high_ambiguity(ambiguous_ctx):
    d = _detector(SamplingUncertaintyDetector, DISAGREEING)
    decision = d.decide(ambiguous_ctx)
    assert decision.score > 0.35
    assert decision.ask is True


def test_sampling_detector_uses_temperature(ambiguous_ctx):
    d = _detector(SamplingUncertaintyDetector, AGREEING)
    d.decide(ambiguous_ctx)
    assert all(c["temperature"] == 1.0 for c in d._llm.calls)
    assert len(d._llm.calls) == 8


def test_sampling_reuses_an_identical_prefix_so_the_cache_can_hit(ambiguous_ctx):
    d = _detector(SamplingUncertaintyDetector, AGREEING)
    d.decide(ambiguous_ctx)
    prefixes = {c["cached_context"] for c in d._llm.calls}
    assert len(prefixes) == 1


def test_perturbation_detector_varies_the_prompt_not_the_temperature(ambiguous_ctx):
    d = _detector(PerturbationUncertaintyDetector, AGREEING)
    d.decide(ambiguous_ctx)
    assert all("temperature" not in c for c in d._llm.calls)
    assert len({c["instruction"] for c in d._llm.calls}) == 8


def test_perturbation_shuffle_is_reproducible(ambiguous_ctx):
    a = PerturbationUncertaintyDetector._shuffled(ambiguous_ctx, seed="s")
    b = PerturbationUncertaintyDetector._shuffled(ambiguous_ctx, seed="s")
    assert a == b


def test_dispersion_measures_behave():
    identical = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]])
    orthogonal = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]])
    assert mean_pairwise_distance(identical) == 0.0
    assert mean_pairwise_distance(orthogonal) > 0.9
    assert semantic_entropy(identical) == 0.0
    assert semantic_entropy(orthogonal) > 0.9


def test_too_few_samples_is_not_an_error(ambiguous_ctx):
    d = _detector(SamplingUncertaintyDetector, [""])
    decision = d.decide(ambiguous_ctx)
    assert decision.ask is False
    assert "too few" in decision.why
