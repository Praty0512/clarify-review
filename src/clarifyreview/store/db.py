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

-- Live bot state. Everything below survives a restart; times are unix epoch seconds.
CREATE TABLE IF NOT EXISTS parked_runs (
    pr_id               TEXT PRIMARY KEY,
    repo                TEXT NOT NULL,
    number              INTEGER NOT NULL,
    author              TEXT,
    head_sha            TEXT,
    installation_id     INTEGER,
    question_comment_id INTEGER,
    context_json        TEXT NOT NULL,
    decision_json       TEXT NOT NULL,
    detector            TEXT,
    question_cost_usd   REAL DEFAULT 0,
    created_at          REAL NOT NULL,
    deadline_at         REAL NOT NULL,
    state               TEXT NOT NULL DEFAULT 'parked',  -- parked|claimed|done|cancelled|failed
    claimed_at          REAL,
    attempts            INTEGER DEFAULT 0,
    last_error          TEXT
);
CREATE INDEX IF NOT EXISTS idx_parked_due ON parked_runs(state, deadline_at);

CREATE TABLE IF NOT EXISTS posted_reviews (
    pr_id       TEXT,
    head_sha    TEXT,
    run_id      INTEGER,
    comment_id  INTEGER,
    created_at  REAL,
    PRIMARY KEY (pr_id, head_sha)
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    event       TEXT,
    repo        TEXT,
    number      INTEGER,
    action      TEXT,
    received_at REAL,
    status      TEXT,            -- received|done|failed
    args_json   TEXT             -- handler call, so a crash mid-handling can be replayed
);
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


# ----------------------------------------------------------- live bot state
#
# Every mutating helper commits before returning. The bot runs several short
# connections concurrently (webhook handlers, the sweeper), and a transaction left
# open until the connection closes would hold SQLite's single write lock for the
# length of an LLM call.


def park(
    conn: sqlite3.Connection,
    *,
    pr_id: str,
    repo: str,
    number: int,
    author: str | None,
    head_sha: str | None,
    installation_id: int | None,
    comment_id: int | None,
    ctx,
    decision,
    detector: str | None,
    question_cost: float,
    now: float,
    deadline: float,
) -> None:
    """Record a run waiting for the author. Upserts: re-parking resets the row."""
    conn.execute(
        """
        INSERT INTO parked_runs (
            pr_id, repo, number, author, head_sha, installation_id,
            question_comment_id, context_json, decision_json, detector,
            question_cost_usd, created_at, deadline_at, state
        ) VALUES (?,?,?,?,?,?, ?,?,?,?, ?,?,?, 'parked')
        ON CONFLICT(pr_id) DO UPDATE SET
            repo=excluded.repo, number=excluded.number, author=excluded.author,
            head_sha=excluded.head_sha, installation_id=excluded.installation_id,
            question_comment_id=excluded.question_comment_id,
            context_json=excluded.context_json, decision_json=excluded.decision_json,
            detector=excluded.detector, question_cost_usd=excluded.question_cost_usd,
            created_at=excluded.created_at, deadline_at=excluded.deadline_at,
            state='parked', claimed_at=NULL, attempts=0, last_error=NULL
        """,
        (
            pr_id, repo, number, author, head_sha, installation_id, comment_id,
            ctx.model_dump_json(), decision.model_dump_json(), detector,
            float(question_cost or 0.0), now, deadline,
        ),
    )
    conn.commit()


def get_parked(conn: sqlite3.Connection, pr_id: str) -> dict | None:
    """The row in whatever state it is in; callers look at `state`."""
    row = conn.execute("SELECT * FROM parked_runs WHERE pr_id = ?", (pr_id,)).fetchone()
    return dict(row) if row else None


def claim_parked(conn: sqlite3.Connection, pr_id: str, now: float) -> dict | None:
    """Take a parked run for processing. Exactly one caller wins: the UPDATE is a
    single atomic statement, and only the winner sees rowcount == 1."""
    cur = conn.execute(
        "UPDATE parked_runs SET state='claimed', claimed_at=? "
        "WHERE pr_id=? AND state='parked'",
        (now, pr_id),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    return get_parked(conn, pr_id)


def claim_expired(
    conn: sqlite3.Connection, now: float, limit: int = 20, stale_claim_s: float = 900.0
) -> list[dict]:
    """Claim runs whose deadline has passed, plus runs claimed long ago by a worker
    that evidently died."""
    ids = [
        r["pr_id"]
        for r in conn.execute(
            "SELECT pr_id FROM parked_runs "
            "WHERE (state='parked' AND deadline_at <= ?) "
            "   OR (state='claimed' AND claimed_at <= ?) "
            "ORDER BY deadline_at LIMIT ?",
            (now, now - stale_claim_s, limit),
        )
    ]
    claimed: list[dict] = []
    for pr_id in ids:
        cur = conn.execute(
            "UPDATE parked_runs SET state='claimed', claimed_at=? "
            "WHERE pr_id=? AND ((state='parked' AND deadline_at <= ?) "
            "                OR (state='claimed' AND claimed_at <= ?))",
            (now, pr_id, now, now - stale_claim_s),
        )
        conn.commit()
        if cur.rowcount == 1:
            row = get_parked(conn, pr_id)
            if row:
                claimed.append(row)
    return claimed


def release_parked(
    conn: sqlite3.Connection, pr_id: str, error: str, max_attempts: int = 3
) -> str:
    """Give a claimed run back after a failure. After `max_attempts` it is marked
    failed instead of being retried forever. Returns the new state."""
    conn.execute(
        "UPDATE parked_runs SET attempts = COALESCE(attempts, 0) + 1, last_error = ?, "
        "claimed_at = NULL, "
        "state = CASE WHEN COALESCE(attempts, 0) + 1 >= ? THEN 'failed' ELSE 'parked' END "
        "WHERE pr_id = ? AND state = 'claimed'",
        (error[:500], max_attempts, pr_id),
    )
    conn.commit()
    row = get_parked(conn, pr_id)
    return row["state"] if row else "missing"


def finish_parked(conn: sqlite3.Connection, pr_id: str, state: str = "done") -> None:
    conn.execute("UPDATE parked_runs SET state = ? WHERE pr_id = ?", (state, pr_id))
    conn.commit()


def update_parked_context(conn: sqlite3.Connection, pr_id: str, ctx, head_sha: str | None) -> bool:
    """A push while parked: keep waiting, but review the newest code. Only touches a
    row still waiting - never one a worker has claimed."""
    cur = conn.execute(
        "UPDATE parked_runs SET context_json = ?, head_sha = ? "
        "WHERE pr_id = ? AND state = 'parked'",
        (ctx.model_dump_json(), head_sha, pr_id),
    )
    conn.commit()
    return cur.rowcount == 1


def count_parked(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) FROM parked_runs WHERE state='parked'").fetchone()[0]
    )


def record_posted_review(
    conn: sqlite3.Connection,
    pr_id: str,
    head_sha: str,
    run_id: int | None,
    comment_id: int | None,
    now: float,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO posted_reviews (pr_id, head_sha, run_id, comment_id, created_at) "
        "VALUES (?,?,?,?,?)",
        (pr_id, head_sha, run_id, comment_id, now),
    )
    conn.commit()


def review_posted_for(conn: sqlite3.Connection, pr_id: str, head_sha: str | None) -> bool:
    if not head_sha:
        return False
    return (
        conn.execute(
            "SELECT 1 FROM posted_reviews WHERE pr_id=? AND head_sha=?", (pr_id, head_sha)
        ).fetchone()
        is not None
    )


def record_delivery(
    conn: sqlite3.Connection,
    delivery_id: str,
    event: str,
    repo: str | None,
    number: int | None,
    action: str | None,
    now: float,
    args_json: str | None = None,
) -> bool:
    """False if this delivery id was already seen (GitHub redelivers on request and
    on timeouts)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO webhook_deliveries "
        "(delivery_id, event, repo, number, action, received_at, status, args_json) "
        "VALUES (?,?,?,?,?,?, 'received', ?)",
        (delivery_id, event, repo, number, action, now, args_json),
    )
    if cur.rowcount != 1:
        # A redelivery of one that failed is a retry, not a duplicate.
        cur = conn.execute(
            "UPDATE webhook_deliveries SET status='received', received_at=?, args_json=? "
            "WHERE delivery_id=? AND status='failed'",
            (now, args_json, delivery_id),
        )
    conn.commit()
    return cur.rowcount == 1


def mark_delivery(conn: sqlite3.Connection, delivery_id: str, status: str) -> None:
    conn.execute(
        "UPDATE webhook_deliveries SET status = ? WHERE delivery_id = ?", (status, delivery_id)
    )
    conn.commit()


def pending_deliveries(conn: sqlite3.Connection, older_than: float) -> list[dict]:
    """Deliveries accepted but never finished - the process died mid-handler."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM webhook_deliveries WHERE status='received' AND received_at <= ? "
            "AND args_json IS NOT NULL ORDER BY received_at",
            (older_than,),
        )
    ]
