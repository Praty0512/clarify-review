"""Detector (a): dispersion across N independent readings of the same PR.

The idea is that if the model's own account of *what this PR is trying to do*
changes from sample to sample, the PR is ambiguous - not merely that the decoder
is noisy. Two variants, because the obvious implementation is not available:

  (a1) SamplingUncertaintyDetector - the classical self-consistency framing.
       `temperature` is rejected with a 400 on Opus 5, Sonnet 5 and the whole
       4.6+ family, so this runs on claude-haiku-4-5, the current tier that still
       accepts sampling parameters.

  (a2) PerturbationUncertaintyDetector - holds the model fixed at the review
       model and perturbs the *prompt* instead: reorder hunks, re-frame the
       question, vary which context is presented first. Arguably the better
       instrument, since it measures whether the PR's intent is stable under how
       you look at it rather than whether the sampler is noisy.

Both embed one-sentence intent hypotheses rather than whole reviews. Embedding a
full review measures prose style; embedding a single claim about intent measures
intent.
"""

from __future__ import annotations

import math
import random
from typing import Protocol

import numpy as np

from ..config import review_model, sampling_model
from ..types import DetectorName, PRContext
from .base import BaseDetector

INTENT_SYSTEM = (
    "You read pull requests and state, in exactly one sentence, what the change is "
    "trying to accomplish. State the most likely intent directly. Do not hedge, do "
    "not list alternatives, do not explain your reasoning. One sentence, nothing else."
)
INTENT_INSTRUCTION = "In one sentence: what is this pull request trying to do?"

# (a2) prompt perturbations. Each asks the same question from a different angle;
# a PR with clear intent survives all of them with the same answer.
PERTURBATIONS: tuple[str, ...] = (
    "In one sentence: what is this pull request trying to do?",
    "In one sentence: what problem was the author most likely fixing here?",
    "In one sentence: describe the author's intent behind this change.",
    "A teammate asks what this PR is for. Answer in one sentence.",
    "In one sentence: what would the linked issue for this PR have said?",
    "In one sentence: summarise the purpose of this diff.",
    "In one sentence: why was this change made?",
    "In one sentence: what behaviour of the system does this change alter, and why?",
)


# ------------------------------------------------------------------ embedding


class Embedder(Protocol):
    def encode(self, sentences: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Preferred. Requires the `embed` extra."""

    def __init__(self, model: str = "all-mpnet-base-v2") -> None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        self._m = SentenceTransformer(model)

    def encode(self, sentences: list[str]) -> np.ndarray:
        return np.asarray(self._m.encode(sentences, normalize_embeddings=True))


class TfidfEmbedder:
    """Fallback with no extra dependency beyond scikit-learn.

    Fitting the vectoriser on the N sentences themselves is fine here: the only
    quantity that matters is their dispersion *relative to each other*, and this
    is never used to compare across pull requests.
    """

    def encode(self, sentences: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1
        )
        try:
            m = vec.fit_transform(sentences).toarray()
        except ValueError:  # every sentence was empty or pure stopwords
            return np.zeros((len(sentences), 1))
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return m / norms


def default_embedder() -> Embedder:
    try:
        return SentenceTransformerEmbedder()
    except Exception:
        return TfidfEmbedder()


# ------------------------------------------------------------------ measures


def mean_pairwise_distance(vectors: np.ndarray) -> float:
    """Mean cosine distance over all pairs. 0 = every sample agreed."""
    n = len(vectors)
    if n < 2:
        return 0.0
    sims = vectors @ vectors.T
    iu = np.triu_indices(n, k=1)
    return float(np.clip(1.0 - sims[iu], 0.0, 2.0).mean())


def semantic_entropy(vectors: np.ndarray, distance_threshold: float = 0.35) -> float:
    """Entropy over semantic-equivalence clusters, normalised to [0,1].

    Clustering first is what separates 'the model said the same thing eight
    different ways' from 'the model gave eight different answers'. Normalising by
    log(n) keeps the score comparable across different sample counts.
    """
    n = len(vectors)
    if n < 2:
        return 0.0
    from sklearn.cluster import AgglomerativeClustering

    labels = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    ).fit_predict(vectors)

    _, counts = np.unique(labels, return_counts=True)
    p = counts / counts.sum()
    h = -float((p * np.log(p)).sum())
    return h / math.log(n) if n > 1 else 0.0


# ----------------------------------------------------------------- detectors


class _UncertaintyBase(BaseDetector):
    """Shared scoring; subclasses only differ in how they generate the N samples."""

    def __init__(self, llm=None, n: int = 8, embedder: Embedder | None = None, thresholds=None):
        super().__init__(thresholds)
        self._llm = llm
        self.n = n
        self._embedder = embedder

    @property
    def llm(self):
        if self._llm is None:
            from ..llm.client import LLM

            self._llm = LLM()
        return self._llm

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = default_embedder()
        return self._embedder

    def _hypotheses(self, ctx: PRContext) -> tuple[list[str], float]:
        raise NotImplementedError

    def score(self, ctx: PRContext) -> tuple[float, str, dict]:
        hypotheses, cost = self._hypotheses(ctx)
        cleaned = [h.strip() for h in hypotheses if h and h.strip()]
        if len(cleaned) < 2:
            return (
                0.0,
                "too few usable samples to measure dispersion",
                {"cost_usd": cost, "hypotheses": cleaned},
            )

        vectors = self.embedder.encode(cleaned)
        dispersion = mean_pairwise_distance(vectors)
        entropy = semantic_entropy(vectors)

        # Both signals, evenly weighted: dispersion catches gradual drift,
        # entropy catches a clean split into two incompatible readings.
        score = float(np.clip(0.5 * dispersion + 0.5 * entropy, 0.0, 1.0))
        why = (
            f"{len(cleaned)} intent hypotheses: mean pairwise distance "
            f"{dispersion:.2f}, semantic entropy {entropy:.2f}"
        )
        return (
            score,
            why,
            {
                "cost_usd": cost,
                "dispersion": round(dispersion, 4),
                "entropy": round(entropy, 4),
                "hypotheses": cleaned,
            },
        )


class SamplingUncertaintyDetector(_UncertaintyBase):
    """(a1) N samples at temperature 1.0 on the one tier that still allows it."""

    name = DetectorName.SAMPLING

    def __init__(self, *args, model: str | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._model = model

    @property
    def model(self) -> str:
        return self._model or sampling_model()

    def _hypotheses(self, ctx: PRContext) -> tuple[list[str], float]:
        rendered = ctx.render()
        out: list[str] = []
        cost = 0.0
        for _ in range(self.n):
            res = self.llm.text(
                model=self.model,
                system=INTENT_SYSTEM,
                cached_context=rendered,  # identical prefix -> cache hit from #2 on
                instruction=INTENT_INSTRUCTION,
                max_tokens=200,
                thinking=False,
                temperature=1.0,
            )
            out.append(res.value)
            cost += res.usage.cost_usd
        return out, cost


class PerturbationUncertaintyDetector(_UncertaintyBase):
    """(a2) One model, K framings of the same question.

    The PR context is also lightly shuffled per sample: hunk order within the
    rendered diff is permuted under a seed derived from the PR id, so the
    perturbation is reproducible but not identical across samples.
    """

    name = DetectorName.PERTURBATION

    def __init__(self, *args, model: str | None = None, shuffle_hunks: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self._model = model
        self.shuffle_hunks = shuffle_hunks

    @property
    def model(self) -> str:
        return self._model or review_model()

    def _hypotheses(self, ctx: PRContext) -> tuple[list[str], float]:
        out: list[str] = []
        cost = 0.0
        prompts = list(PERTURBATIONS)[: self.n]
        if len(prompts) < self.n:  # more samples than framings: cycle
            prompts = [PERTURBATIONS[i % len(PERTURBATIONS)] for i in range(self.n)]

        for i, instruction in enumerate(prompts):
            rendered = (
                self._shuffled(ctx, seed=f"{ctx.pr_id}:{i}")
                if self.shuffle_hunks
                else ctx.render()
            )
            res = self.llm.text(
                model=self.model,
                system=INTENT_SYSTEM,
                cached_context=rendered,
                instruction=instruction,
                max_tokens=200,
                thinking=False,
            )
            out.append(res.value)
            cost += res.usage.cost_usd
        return out, cost

    @staticmethod
    def _shuffled(ctx: PRContext, seed: str) -> str:
        """Permute hunk order deterministically. Same seed, same permutation."""
        if len(ctx.hunks) < 2:
            return ctx.render()
        rng = random.Random(seed)
        order = list(range(len(ctx.hunks)))
        rng.shuffle(order)
        clone = ctx.model_copy(deep=True)
        clone.hunks = [ctx.hunks[i] for i in order]
        clone.diff = "\n".join(h.body for h in clone.hunks)
        return clone.render()
