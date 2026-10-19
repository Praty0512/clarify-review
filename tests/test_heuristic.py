from clarifyreview.detect.base import Thresholds
from clarifyreview.detect.heuristic import HeuristicDetector


def detector():
    return HeuristicDetector(thresholds=Thresholds({"heuristic": 0.5}, "test"))


def test_ambiguous_pr_triggers_a_question(ambiguous_ctx):
    d = detector().decide(ambiguous_ctx)
    assert d.ask is True
    assert d.score >= 0.5
    assert "removes_guard" in d.why


def test_clear_pr_proceeds(clear_ctx):
    d = detector().decide(clear_ctx)
    assert d.ask is False
    assert d.score < 0.5


def test_substantive_issue_damps_the_score(clear_ctx):
    """A documented PR should not be interrogated just for looking risky."""
    from clarifyreview.types import LinkedIssue

    risky = clear_ctx.model_copy(deep=True)
    risky.linked_issue = None
    undamped = detector().score(risky)[0]
    damped = detector().score(clear_ctx)[0]
    assert damped < undamped


def test_decision_carries_its_threshold(ambiguous_ctx):
    d = detector().decide(ambiguous_ctx)
    assert d.threshold == 0.5
    assert d.detector.value == "heuristic"


def test_never_ask_detector_is_the_control(ambiguous_ctx):
    from clarifyreview.detect.base import NeverAskDetector

    assert NeverAskDetector().decide(ambiguous_ctx).ask is False
