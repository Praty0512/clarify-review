from clarifyreview.store import db
from clarifyreview.types import (
    ClarificationExchange, ClarifyingQuestion, ClarifyingQuestions, Decision,
    DetectorName, ReviewFinding, ReviewOutput, ReviewRun,
)


def _run():
    qs = ClarifyingQuestions(
        ambiguity_summary="unclear",
        questions=[ClarifyingQuestion(target="a.py:1", question="why?", why_needed="w")],
    )
    return ReviewRun(
        pr_id="acme/app#1",
        condition="stripped_clarify",
        detector=DetectorName.HEURISTIC,
        decision=Decision(ask=True, score=0.7, why="rules fired",
                          detector=DetectorName.HEURISTIC, threshold=0.5),
        clarification=ClarificationExchange(questions=qs, answer="moved", answered=True),
        review=ReviewOutput(
            intent_summary="moves validation upstream",
            overall_confidence=0.9, verdict="approve",
            findings=[ReviewFinding(file="a.py", line=1, severity="minor",
                                    category="style", claim="c", evidence="e",
                                    suggested_fix="none", confidence=0.5)],
        ),
        model="stub", cost_usd=0.01, input_tokens=10, output_tokens=5,
    )


def test_roundtrip(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    with db.connect(path) as conn:
        run_id = db.record_run(conn, _run())
        assert run_id > 0

    with db.connect(path) as conn:
        rows = db.load_runs(conn, condition="stripped_clarify")
        assert len(rows) == 1
        row = rows[0]
        assert row["ask"] == 1 and row["answered"] == 1
        assert row["verdict"] == "approve"
        assert row["flagged_defect"] == 0   # a style nit is not a defect claim
        assert db.load_payload(row)["review"]["intent_summary"].startswith("moves")

        assert conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM clarifications").fetchone()[0] == 1


def test_instances_upsert_is_idempotent(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    with db.connect(path) as conn:
        db.upsert_instance(conn, pr_id="x::golden", variant="golden", has_defect=0)
        db.upsert_instance(conn, pr_id="x::golden", variant="golden", has_defect=1)
        rows = conn.execute("SELECT has_defect FROM instances").fetchall()
    assert len(rows) == 1 and rows[0]["has_defect"] == 1


def test_errored_runs_are_excluded_from_analysis_queries(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    run = _run()
    run.error = "boom"
    with db.connect(path) as conn:
        db.record_run(conn, run)
    with db.connect(path) as conn:
        assert db.load_runs(conn) == []


def test_autocommit_persists_before_the_context_closes(tmp_path):
    """A hundred-instance ablation is hours of API calls. Holding one
    transaction across all of them means a crash at instance ninety discards
    every result already paid for."""
    path = tmp_path / "t.db"
    db.init(path)
    with db.connect(path, autocommit_each=True) as conn:
        db.record_run(conn, _run())
        # A second, independent connection must already see it.
        with db.connect(path) as other:
            assert len(db.load_runs(other)) == 1


def test_default_connection_still_batches_into_one_transaction(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    with db.connect(path) as conn:
        db.record_run(conn, _run())
        with db.connect(path) as other:
            assert db.load_runs(other) == []   # not yet visible
    with db.connect(path) as after:
        assert len(db.load_runs(after)) == 1   # visible once committed
