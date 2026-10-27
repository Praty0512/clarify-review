"""The four stages, wired.

One entry point for every caller: the GitHub bot, the CLI, and the ablation
runner all come through `Pipeline.run`. The three experimental conditions differ
only in which detector is installed and whether a responder is present - not in
which code path executes. That is deliberate and load-bearing: if the baseline
had its own function, the ablation would be comparing two programs rather than
one program with one stage switched off.
"""

from __future__ import annotations

import logging
import time

from .clarify.loop import ClarificationLoop, Responder
from .detect.base import BaseDetector, NeverAskDetector
from .review.generator import ReviewGenerator
from .types import Decision, DetectorName, PRContext, ReviewRun

log = logging.getLogger(__name__)

# The three conditions of Study A.
CONDITION_FULL_PLAIN = "full_plain"  # ceiling: full context, single pass
CONDITION_STRIPPED_PLAIN = "stripped_plain"  # floor: context stripped, single pass
CONDITION_STRIPPED_CLARIFY = "stripped_clarify"  # treatment
# Production runs from the GitHub bot. Never a Study A condition, so a live run can
# not leak into the ablation's analysis tables.
CONDITION_GITHUB_LIVE = "github_live"


def live_condition(condition: str, live: bool) -> str:
    """The condition a run is logged under. `clarifyreview review --repo --pr` runs the
    treatment pipeline on a real PR (the same code path as the bot), so it is logged as
    `github_live`, the bot's label, rather than as the Study A treatment. The pipeline
    itself is unchanged; only the label differs, and `run_matrix` never calls this."""
    return CONDITION_GITHUB_LIVE if live else condition


class Pipeline:
    def __init__(
        self,
        detector: BaseDetector | None = None,
        responder: Responder | None = None,
        generator: ReviewGenerator | None = None,
        condition: str = CONDITION_STRIPPED_CLARIFY,
    ) -> None:
        self.detector = detector or NeverAskDetector()
        self.responder = responder
        self.generator = generator or ReviewGenerator()
        self.condition = condition

    @classmethod
    def plain(cls, condition: str, generator: ReviewGenerator | None = None) -> Pipeline:
        """The single-pass control. Stage 2 always says proceed; Stage 3 never runs."""
        return cls(
            detector=NeverAskDetector(), responder=None, generator=generator,
            condition=condition,
        )

    def run(self, ctx: PRContext, *, decision: Decision | None = None) -> ReviewRun:
        """Run the stages. `decision` lets a caller that already ran Stage 2 (the
        live bot, which must decide before it can post a question) hand the result
        in instead of paying for the detector a second time."""
        started = time.monotonic()
        run = ReviewRun(
            pr_id=ctx.pr_id,
            condition=self.condition,
            detector=decision.detector if decision is not None
            else getattr(self.detector, "name", None),
            context_fingerprint=ctx.fingerprint(),
        )

        try:
            # Stage 2 - the branch.
            supplied = decision is not None
            if decision is None:
                decision = self.detector.decide(ctx)
            run.decision = decision
            run.cost_usd += decision.cost_usd

            # Stage 3 - only when Stage 2 said ask and someone can answer.
            if decision.ask and supplied and ctx.clarification is not None:
                # A resumed run: the question was asked and the answer (or the
                # timeout) is already on the context.
                run.clarification = ctx.clarification
            elif decision.ask and self.responder is not None:
                loop = ClarificationLoop(self.responder)
                exchange, cost = loop.run(ctx)
                run.clarification = exchange
                run.cost_usd += cost
                log.info(
                    "%s: asked %d question(s), answered=%s",
                    ctx.pr_id,
                    len(exchange.questions.questions),
                    exchange.answered,
                )
            elif decision.ask:
                log.info("%s: detector said ask, but no responder is installed", ctx.pr_id)

            # Stage 4 - the review. Always runs.
            review, meta = self.generator.generate(ctx)
            run.review = review
            run.model = meta["model"]
            run.input_tokens = meta["input_tokens"]
            run.output_tokens = meta["output_tokens"]
            run.cache_read_tokens = meta["cache_read_tokens"]
            run.cost_usd += meta["cost_usd"]
            # Stage 3 mutates the context, so re-fingerprint what was reviewed.
            run.context_fingerprint = meta["context_fingerprint"]

        except Exception as exc:  # noqa: BLE001 - a failed PR must not kill a batch
            log.exception("%s failed", ctx.pr_id)
            run.error = f"{type(exc).__name__}: {exc}"

        run.latency_ms = int((time.monotonic() - started) * 1000)
        return run


def build_condition(
    condition: str,
    detector_name: str | DetectorName = DetectorName.HEURISTIC,
    responder: Responder | None = None,
    generator: ReviewGenerator | None = None,
    **detector_kwargs,
) -> Pipeline:
    """Construct the pipeline for one experimental condition."""
    from . import detect

    if condition in (CONDITION_FULL_PLAIN, CONDITION_STRIPPED_PLAIN):
        return Pipeline.plain(condition, generator=generator)
    if condition == CONDITION_STRIPPED_CLARIFY:
        if responder is None:
            raise ValueError(
                "the treatment condition needs a responder; pass an OracleResponder "
                "for the benchmark or a GitHubResponder in production"
            )
        return Pipeline(
            detector=detect.build(detector_name, **detector_kwargs),
            responder=responder,
            generator=generator,
            condition=condition,
        )
    raise ValueError(f"unknown condition: {condition}")
