"""Durable bot state: parked runs, posted reviews, webhook deliveries."""

from clarifyreview.store import db
from clarifyreview.types import (
    ClarificationExchange, ClarifyingQuestion, ClarifyingQuestions, Decision,
    DetectorName, PRContext,
)


def _decision():
    return Decision(ask=True, score=0.8, why="rules fired",
                    detector=DetectorName.HEURISTIC, threshold=0.5, cost_usd=0.01)


def _park(conn, ctx, *, now=1000.0, deadline=2000.0, pr_id="acme/app#1"):
    db.park(
        conn, pr_id=pr_id, repo="acme/app", number=1, author="alice",
        head_sha="abc", installation_id=7, comment_id=99, ctx=ctx,
        decision=_decision(), detector="heuristic", question_cost=0.002,
        now=now, deadline=deadline,
    )


def _conn(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    return db.connect(path)


def test_context_round_trip_keeps_fingerprint(tmp_path, ambiguous_ctx):
    ambiguous_ctx.clarification = ClarificationExchange(
        questions=ClarifyingQuestions(
            ambiguity_summary="guard removed",
            questions=[ClarifyingQuestion(target="a.py:1", question="why?", why_needed="w")],
        ),
        responder="github",
    )
    before = ambiguous_ctx.fingerprint()
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx)
        row = db.get_parked(conn, "acme/app#1")
    back = PRContext.model_validate_json(row["context_json"])
    assert back.fingerprint() == before
    assert back.clarification.questions.questions[0].target == "a.py:1"
    assert Decision.model_validate_json(row["decision_json"]).ask is True
    assert row["state"] == "parked" and row["installation_id"] == 7
    assert row["question_cost_usd"] == 0.002


def test_double_claim_only_one_wins(tmp_path, ambiguous_ctx):
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx)
        first = db.claim_parked(conn, "acme/app#1", now=1500.0)
        second = db.claim_parked(conn, "acme/app#1", now=1500.0)
        assert first is not None and first["state"] == "claimed"
        assert second is None
        assert db.count_parked(conn) == 0


def test_expiry_claims_only_due_rows(tmp_path, ambiguous_ctx):
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx, deadline=2000.0)
        assert db.claim_expired(conn, now=1999.0) == []
        rows = db.claim_expired(conn, now=2000.0)
        assert [r["pr_id"] for r in rows] == ["acme/app#1"]
        assert db.claim_expired(conn, now=2001.0) == []  # already claimed


def test_stale_claim_is_reclaimed(tmp_path, ambiguous_ctx):
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx, deadline=5000.0)
        assert db.claim_parked(conn, "acme/app#1", now=1000.0)
        # Not yet stale, and the deadline has not passed either.
        assert db.claim_expired(conn, now=1500.0, stale_claim_s=900) == []
        # The worker died: 900 s later someone else may take it.
        again = db.claim_expired(conn, now=1900.0, stale_claim_s=900)
        assert len(again) == 1 and again[0]["claimed_at"] == 1900.0


def test_release_counts_attempts_then_fails(tmp_path, ambiguous_ctx):
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx)
        for expected in ("parked", "parked", "failed"):
            assert db.claim_parked(conn, "acme/app#1", now=1500.0)
            assert db.release_parked(conn, "acme/app#1", "boom", max_attempts=3) == expected
        row = db.get_parked(conn, "acme/app#1")
        assert row["attempts"] == 3 and row["last_error"] == "boom"
        assert db.claim_parked(conn, "acme/app#1", now=1600.0) is None


def test_finish_and_update_context(tmp_path, ambiguous_ctx, clear_ctx):
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx)
        assert db.update_parked_context(conn, "acme/app#1", clear_ctx, "def") is True
        row = db.get_parked(conn, "acme/app#1")
        assert row["head_sha"] == "def"
        assert PRContext.model_validate_json(row["context_json"]).title == clear_ctx.title
        db.claim_parked(conn, "acme/app#1", now=1500.0)
        # A claimed row is being processed; it must not be rewritten under the worker.
        assert db.update_parked_context(conn, "acme/app#1", ambiguous_ctx, "ghi") is False
        db.finish_parked(conn, "acme/app#1")
        assert db.get_parked(conn, "acme/app#1")["state"] == "done"


def test_repark_resets_the_row(tmp_path, ambiguous_ctx):
    with _conn(tmp_path) as conn:
        _park(conn, ambiguous_ctx)
        db.claim_parked(conn, "acme/app#1", now=1500.0)
        db.release_parked(conn, "acme/app#1", "x")
        _park(conn, ambiguous_ctx, now=3000.0, deadline=4000.0)
        row = db.get_parked(conn, "acme/app#1")
        assert row["state"] == "parked" and row["attempts"] == 0
        assert row["deadline_at"] == 4000.0


def test_posted_reviews_and_deliveries(tmp_path):
    with _conn(tmp_path) as conn:
        assert db.review_posted_for(conn, "acme/app#1", "abc") is False
        db.record_posted_review(conn, "acme/app#1", "abc", 1, 5, now=1.0)
        assert db.review_posted_for(conn, "acme/app#1", "abc") is True
        assert db.review_posted_for(conn, "acme/app#1", "def") is False
        assert db.review_posted_for(conn, "acme/app#1", None) is False

        assert db.record_delivery(conn, "d1", "pull_request", "acme/app", 1, "opened",
                                  now=10.0, args_json="{}") is True
        assert db.record_delivery(conn, "d1", "pull_request", "acme/app", 1, "opened",
                                  now=11.0, args_json="{}") is False
        assert [d["delivery_id"] for d in db.pending_deliveries(conn, older_than=20.0)] == ["d1"]
        db.mark_delivery(conn, "d1", "done")
        assert db.pending_deliveries(conn, older_than=20.0) == []
        # A delivery that failed may be redelivered and retried.
        db.mark_delivery(conn, "d1", "failed")
        assert db.record_delivery(conn, "d1", "pull_request", "acme/app", 1, "opened",
                                  now=30.0, args_json="{}") is True
