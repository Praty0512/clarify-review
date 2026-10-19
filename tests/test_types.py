from clarifyreview.types import ReviewFinding, ReviewOutput


def _finding(**kw):
    base = dict(file="a.py", line=1, severity="major", category="correctness",
                claim="c", evidence="e", suggested_fix="none", confidence=0.9)
    base.update(kw)
    return ReviewFinding(**base)


def test_flagged_defect_only_counts_real_assertions():
    assert ReviewOutput(intent_summary="s", overall_confidence=0.9, verdict="comment",
                        findings=[_finding()]).flagged_a_defect
    assert not ReviewOutput(
        intent_summary="s", overall_confidence=0.9, verdict="comment",
        findings=[_finding(severity="nit", category="style")]
    ).flagged_a_defect
    assert not ReviewOutput(intent_summary="s", overall_confidence=0.9,
                            verdict="approve").flagged_a_defect


def test_render_is_deterministic(ambiguous_ctx):
    assert ambiguous_ctx.render() == ambiguous_ctx.render()
    assert ambiguous_ctx.fingerprint() == ambiguous_ctx.fingerprint()


def test_render_changes_when_intent_is_removed(ambiguous_ctx, clear_ctx):
    assert ambiguous_ctx.fingerprint() != clear_ctx.fingerprint()


def test_symbol_order_does_not_depend_on_insertion_order(ambiguous_ctx):
    shuffled = ambiguous_ctx.model_copy(deep=True)
    shuffled.changed_symbols = list(reversed(shuffled.changed_symbols))
    assert shuffled.render() == ambiguous_ctx.render()


def test_clarification_renders_answered_and_unanswered_differently():
    from clarifyreview.types import (
        ClarificationExchange, ClarifyingQuestion, ClarifyingQuestions,
    )

    qs = ClarifyingQuestions(
        ambiguity_summary="unclear",
        questions=[ClarifyingQuestion(target="a.py:1", question="why?", why_needed="w")],
    )
    answered = ClarificationExchange(questions=qs, answer="moved upstream", answered=True)
    timed_out = ClarificationExchange(questions=qs, timed_out=True)
    assert "authoritative" in answered.render()
    assert "NOT answered" in timed_out.render()
