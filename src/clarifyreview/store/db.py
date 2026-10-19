"""The experiment log.

Plain `sqlite3`, no ORM. The log *is* the raw data for Study A, so its schema is
part of the method and should be readable in the paper's appendix without knowing
anything about an ORM's conventions. Every run - production or benchmark - lands
here, which means instrumentation is not a separate effort later.

Full JSON blobs are stored alongside the flattened columns. The columns make
analysis queries easy; the blobs mean a question nobody thought to ask in August
is still answerable in December.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..types import ReviewRun

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    pr_id               TEXT    NOT NULL,
    condition           TEXT    NOT NULL,
    detector            TEXT,
    context_fingerprint TEXT,

    -- stage 2
    ask                 INTEGER,
    ambiguity_score     REAL,
    threshold           REAL,
    detector_why        TEXT,

    -- stage 3
    asked               INTEGER NOT NULL DEFAULT 0,
    answered            INTEGER NOT NULL DEFAULT 0,
    timed_out           INTEGER NOT NULL DEFAULT 0,
    responder           TEXT,
    round_trip_s        REAL,

    -- stage 4
    verdict             TEXT,
    intent_summary      TEXT,
    n_findings          INTEGER,
    flagged_defect      INTEGER,
    overall_confidence  REAL,

    -- accounting
    model               TEXT,
    input_tokens        INTEGER DEFAULT 0,
    output_tokens       INTEGER DEFAULT 0,
    cache_read_tokens   INTEGER DEFAULT 0,
    cost_usd            REAL    DEFAULT 0,
    latency_ms          INTEGER DEFAULT 0,
    error               TEXT,

    payload             TEXT NOT NULL   -- the whole ReviewRun, for later questions
);

CREATE TABLE IF NOT EXISTS findings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    file        TEXT,
    line        INTEGER,
    severity    TEXT,
    category    TEXT,
    claim       TEXT,
    evidence    TEXT,
    suggested_fix TEXT,
    confidence  REAL
);

CREATE TABLE IF NOT EXISTS clarifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    target      TEXT,
    question    TEXT,
    why_needed  TEXT,
    answer      TEXT
);

-- Study A ground truth, filled in by experiments/build_dataset.py and mutate.py.
CREATE TABLE IF NOT EXISTS instances (
    pr_id           TEXT PRIMARY KEY,
    source          TEXT,          -- e.g. 'swebench_verified'
    repo            TEXT,
    base_commit     TEXT,
    variant         TEXT,          -- 'golden' | 'mutant'
    has_defect      INTEGER,       -- ground truth: 1 for verified mutants
    mutation_op     TEXT,
    mutation_target TEXT,
    problem_statement TEXT,        -- withheld from the stripped conditions
    original_commit_msg TEXT,      -- withheld; the oracle's only other input
    tests_verified  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runs_pr        ON runs(pr_id);
CREATE INDEX IF NOT EXISTS idx_runs_condition ON runs(condition);
CREATE INDEX IF NOT EXISTS idx_findings_run   ON findings(run_id);
"""


@contextmanager
def connect(path: Path, autocommit_each: bool = False) -> Iterator[sqlite3.Connection]:
    """Open the experiment log.

    `autocommit_each` commits after every statement rather than once at the end.
    Long runs want it: a hundred-instance ablation is hours of API calls, and
    holding one transaction across all of them means a crash, an interrupt or a
    dead laptop battery at instance ninety loses every result already paid for.
    Short-lived callers keep the single-transaction default.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # A busy timeout rather than the default 5 s: the judge, the runner and an
    # analysis query can legitimately share the log, and "database is locked"
    # once killed a judge pass part-way through.
    conn = sqlite3.connect(path, timeout=60,
                           isolation_level=None if autocommit_each else "")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


def record_run(conn: sqlite3.Connection, run: ReviewRun) -> int:
    d = run.decision
    c = run.clarification
    r = run.review

    cur = conn.execute(
        """
        INSERT INTO runs (
            pr_id, condition, detector, context_fingerprint,
            ask, ambiguity_score, threshold, detector_why,
            asked, answered, timed_out, responder, round_trip_s,
            verdict, intent_summary, n_findings, flagged_defect, overall_confidence,
            model, input_tokens, output_tokens, cache_read_tokens,
            cost_usd, latency_ms, error, payload
        ) VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?,?,?, ?,?,?,?, ?,?,?,?)
        """,
        (
            run.pr_id,
            run.condition,
            run.detector.value if run.detector else None,
            run.context_fingerprint,
            int(d.ask) if d else None,
            d.score if d else None,
            d.threshold if d else None,
            d.why if d else None,
            int(c is not None),
            int(bool(c and c.answered)),
            int(bool(c and c.timed_out)),
            c.responder if c else None,
            c.round_trip_s if c else None,
            r.verdict if r else None,
            r.intent_summary if r else None,
            len(r.findings) if r else None,
            int(r.flagged_a_defect) if r else None,
            r.overall_confidence if r else None,
            run.model,
            run.input_tokens,
            run.output_tokens,
            run.cache_read_tokens,
            run.cost_usd,
            run.latency_ms,
            run.error,
            run.to_json(),
        ),
    )
    run_id = int(cur.lastrowid)

    if r:
        conn.executemany(
            """INSERT INTO findings
               (run_id, file, line, severity, category, claim, evidence,
                suggested_fix, confidence)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, f.file, f.line, f.severity, f.category,
                    f.claim, f.evidence, f.suggested_fix, f.confidence,
                )
                for f in r.findings
            ],
        )

    if c:
        conn.executemany(
            """INSERT INTO clarifications (run_id, target, question, why_needed, answer)
               VALUES (?,?,?,?,?)""",
            [
                (run_id, q.target, q.question, q.why_needed, c.answer)
                for q in c.questions.questions
            ],
        )

    return run_id


def upsert_instance(conn: sqlite3.Connection, **fields) -> None:
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "pr_id")
    conn.execute(
        f"INSERT INTO instances ({cols}) VALUES ({marks}) "
        f"ON CONFLICT(pr_id) DO UPDATE SET {updates}",
        tuple(fields.values()),
    )


def load_runs(conn: sqlite3.Connection, condition: str | None = None) -> list[dict]:
    sql = "SELECT * FROM runs WHERE error IS NULL"
    args: tuple = ()
    if condition:
        sql += " AND condition = ?"
        args = (condition,)
    return [dict(row) for row in conn.execute(sql, args)]


def load_payload(row: dict) -> dict:
    return json.loads(row["payload"])
