"""End-to-end pipeline tests with a stub LLM - no API calls, no key needed.

These are the tests that matter most for the ablation: they assert that the
control and treatment conditions differ in exactly one thing.
"""

import pytest

from clarifyreview.clarify.loop import ClarificationLoop, NullResponder
from clarifyreview.detect.base import NeverAskDetector, Thresholds
from clarifyreview.detect.heuristic import HeuristicDetector
from clarifyreview.pipeline import (
    CONDITION_FULL_PLAIN,
    CONDITION_STRIPPED_CLARIFY,
    Pipeline,
)
from clarifyreview.types import (
    ClarifyingQuestion,
    ClarifyingQuestions,
    ReviewFinding,
    ReviewOutput,
)


class StubGenerator:
    """Records what it was asked to review."""

    def __init__(self):
        self.seen_contexts = []

    def generate(self, ctx):
        self.seen_contexts.append(ctx.render())
        return (
            ReviewOutput(
                intent_summary="removes a null check",
                overall_confidence=0.8,
                verdict="comment",
                findings=[
                    ReviewFinding(
                        file="app/auth.py", line=12, severity="major",
                        category="correctness", claim="guard removed",
                        evidence="the null check is gone", suggested_fix="restore it",
                        confidence=0.7,
                    )
                ],
            ),
            {"model": "stub", "input_tokens": 100, "output_tokens": 50,
             "cache_read_tokens": 0, "cost_usd": 0.001, "latency_ms": 1,
             "context_fingerprint": ctx.fingerprint()},
        )


class StubQuestions:
    def generate(self, ctx):
        return (
            ClarifyingQuestions(
                ambiguity_summary="a guard disappeared with no stated reason",
                questions=[ClarifyingQuestion(
                    target="app/auth.py:12",
                    question="Was this check moved elsewhere?",
                    why_needed="decides whether this is a bug or a refactor",
                )],
            ),
            0.002,
        )


class AnsweringResponder:
    name = "test"

    def __init__(self, answer="Moved to the API gateway."):
        self.answer = answer
        self.asked = []

    def ask(self, ctx, questions):
        self.asked.append(questions)
        return self.answer


def test_control_condition_never_asks(ambiguous_ctx):
    gen = StubGenerator()
    run = Pipeline.plain(CONDITION_FULL_PLAIN, generator=gen).run(ambiguous_ctx)
    assert run.decision.ask is False
    assert run.clarification is None
    assert run.review.verdict == "comment"


def test_treatment_asks_and_conditions_the_review(ambiguous_ctx):
    gen = StubGenerator()
    responder = AnsweringResponder()
    pipeline = Pipeline(
        detector=HeuristicDetector(thresholds=Thresholds({"heuristic": 0.4}, "test")),
        responder=responder,
        generator=gen,
        condition=CONDITION_STRIPPED_CLARIFY,
    )
    pipeline_loop = ClarificationLoop(responder, question_generator=StubQuestions())
    # Inject the stub question generator through the loop the pipeline builds.
    import clarifyreview.pipeline as pipeline_mod
    original = pipeline_mod.ClarificationLoop
    pipeline_mod.ClarificationLoop = lambda r: pipeline_loop
    try:
        run = pipeline.run(ambiguous_ctx)
    finally:
        pipeline_mod.ClarificationLoop = original

    assert run.decision.ask is True
    assert run.clarification.answered is True
    assert len(responder.asked) == 1
    # The answer reached the reviewer.
    assert "Moved to the API gateway." in gen.seen_contexts[0]


def test_timeout_falls_through_to_a_flagged_review(ambiguous_ctx):
    loop = ClarificationLoop(NullResponder(), question_generator=StubQuestions())
    exchange, cost = loop.run(ambiguous_ctx)
    assert exchange.answered is False
    assert exchange.timed_out is True
    # The reviewer is told, rather than silently reviewing as if nothing happened.
    assert "NOT answered" in ambiguous_ctx.render()


def test_conditions_differ_only_in_stage_2_and_3(ambiguous_ctx):
    """The claim the whole ablation rests on."""
    from experiments.strip import strip_context

    stripped, _ = strip_context(ambiguous_ctx)
    plain_gen, clarify_gen = StubGenerator(), StubGenerator()

    Pipeline.plain("stripped_plain", generator=plain_gen).run(stripped.model_copy(deep=True))

    responder = AnsweringResponder()
    pipeline = Pipeline(
        detector=NeverAskDetector(), responder=responder, generator=clarify_gen,
        condition=CONDITION_STRIPPED_CLARIFY,
    )
    pipeline.run(stripped.model_copy(deep=True))

    # With the detector saying proceed, the two conditions must be identical.
    assert plain_gen.seen_contexts[0] == clarify_gen.seen_contexts[0]


def test_a_failing_stage_does_not_kill_the_run(ambiguous_ctx):
    class Exploding:
        def generate(self, ctx):
            raise RuntimeError("model unavailable")

    run = Pipeline.plain(CONDITION_FULL_PLAIN, generator=Exploding()).run(ambiguous_ctx)
    assert run.error is not None
    assert "RuntimeError" in run.error
    assert run.review is None


def test_treatment_condition_requires_a_responder():
    from clarifyreview.pipeline import build_condition

    with pytest.raises(ValueError, match="responder"):
        build_condition(CONDITION_STRIPPED_CLARIFY, responder=None)


def test_a_supplied_decision_skips_stage_2(ambiguous_ctx):
    """The live bot decides before it can post a question; the pipeline must not
    pay for the detector a second time."""
    from clarifyreview.pipeline import CONDITION_GITHUB_LIVE
    from clarifyreview.types import Decision, DetectorName

    class CountingDetector(NeverAskDetector):
        calls = 0

        def decide(self, ctx):
            type(self).calls += 1
            return super().decide(ctx)

    decision = Decision(ask=False, score=0.1, why="precomputed", cost_usd=0.5,
                        detector=DetectorName.SAMPLING, threshold=0.35)
    gen = StubGenerator()
    pipeline = Pipeline(detector=CountingDetector(), generator=gen,
                        condition=CONDITION_GITHUB_LIVE)
    run = pipeline.run(ambiguous_ctx, decision=decision)

    assert CountingDetector.calls == 0
    assert run.decision is decision
    assert run.detector is DetectorName.SAMPLING
    assert run.condition == "github_live"
    assert run.cost_usd == pytest.approx(0.5 + 0.001)


def test_a_resumed_run_keeps_the_exchange_already_on_the_context(ambiguous_ctx):
    from clarifyreview.types import (
        ClarificationExchange, Decision, DetectorName,
    )

    ambiguous_ctx.clarification = ClarificationExchange(
        questions=StubQuestions().generate(ambiguous_ctx)[0],
        answer="Moved to the gateway.", answered=True, responder="github",
    )
    decision = Decision(ask=True, score=0.9, why="x", detector=DetectorName.HEURISTIC,
                        threshold=0.5)
    gen = StubGenerator()
    responder = AnsweringResponder()
    run = Pipeline(responder=responder, generator=gen).run(ambiguous_ctx, decision=decision)

    assert run.clarification is ambiguous_ctx.clarification
    assert responder.asked == []  # not asked a second time
    assert "Moved to the gateway." in gen.seen_contexts[0]


def test_render_is_byte_identical_without_a_marker_and_prefixed_with_one():
    from clarifyreview.review.render import QUESTION_MARKER, render_questions, render_review
    from clarifyreview.types import ClarificationExchange

    review = StubGenerator().generate(__import__("types").SimpleNamespace(
        render=lambda: "", fingerprint=lambda: ""))[0]
    plain = render_review(review, detector_note="n")
    assert render_review(review, detector_note="n", marker=None) == plain
    assert render_review(review, detector_note="n", marker="<!-- m -->") == "<!-- m -->\n" + plain

    exchange = ClarificationExchange(questions=StubQuestions().generate(None)[0])
    q = render_questions(exchange)
    assert render_questions(exchange, marker=QUESTION_MARKER) == QUESTION_MARKER + "\n" + q
