"""Scoring reviews against ground truth.

Three questions per review, all of them checklist-shaped rather than similarity-
shaped. Lexical overlap with a reference review would measure prose; what Study A
needs to know is whether the correct *problem* was identified.

    intent_recovered   did the review's intent_summary match what the issue said?
    defect_caught      (mutants only) did it flag the injected defect?
    false_alarm        (golden only) did it assert a defect in correct code?

The judge is an LLM, which is a known weak point in automated code-review
evaluation. `--sample-for-humans` writes a stratified sample to CSV for both team
members to score independently; report that agreement before reporting anything
the judge concluded alone.

    python -m experiments.judge --db data/clarifyreview.db
    python -m experiments.judge --db data/clarifyreview.db --sample-for-humans 60
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
from pathlib import Path

from pydantic import BaseModel, Field

from clarifyreview.config import judge_model, settings
from clarifyreview.store import db

log = logging.getLogger("judge")

SYSTEM = """\
You score a code review against known ground truth. You are strict, and you \
explain each score in one sentence.

You are given: the problem the pull request was actually addressing, whether a \
defect was deliberately injected into the patch (and if so, what and where), and \
the review that was produced.

`intent_recovered` is true when the review's summary of what the change is for \
matches the real problem. Different wording is fine; a different problem is not. \
A vague summary that could describe any change is not a match.

`defect_caught` is true only when a defect was injected AND the review reports a \
blocking or major correctness/security/performance finding that identifies that \
specific defect. A finding that is merely near the right line does not count. \
When no defect was injected, set this false.

`false_alarm` is true when NO defect was injected AND the review nonetheless \
asserts a blocking or major correctness/security/performance problem. Style, \
maintainability, and nit-level comments are never false alarms - suggesting an \
improvement to correct code is legitimate reviewing.\
"""


class JudgeVerdict(BaseModel):
    intent_recovered: bool
    intent_reason: str = Field(description="One sentence.")
    defect_caught: bool
    defect_reason: str = Field(description="One sentence.")
    false_alarm: bool
    false_alarm_reason: str = Field(description="One sentence.")


def build_judge_context(run_row: dict, instance_row: dict) -> str:
    payload = json.loads(run_row["payload"])
    review = payload.get("review") or {}
    findings = review.get("findings", [])

    defect = (
        f"A defect WAS injected: operator `{instance_row['mutation_op']}` applied to "
        f"`{instance_row['mutation_target']}`."
        if instance_row["has_defect"]
        else "No defect was injected. This patch is the accepted fix and is correct."
    )

    rendered_findings = (
        "\n".join(
            f"- [{f['severity']}/{f['category']}] {f['file']}:{f.get('line') or '?'} "
            f"{f['claim']} (confidence {f['confidence']})"
            for f in findings
        )
        or "(no findings reported)"
    )

    return (
        f"## Ground truth\n"
        f"The pull request was addressing:\n{instance_row['problem_statement']}\n\n"
        f"{defect}\n\n"
        f"## The review under test\n"
        f"Intent summary: {review.get('intent_summary', '(none)')}\n"
        f"Verdict: {review.get('verdict', '(none)')}\n"
        f"Overall confidence: {review.get('overall_confidence', '?')}\n"
        f"Findings:\n{rendered_findings}\n"
    )


def score_all(db_path: Path, model: str | None = None, limit: int = 0) -> dict:
    from clarifyreview.llm.client import LLM

    llm = LLM()
    model = model or judge_model()
    scored = 0
    cost = 0.0

    # Same reasoning as the runner: judging a full ablation is hundreds of
    # calls, and a failure part-way through must not discard the scores
    # already paid for.
    with db.connect(db_path, autocommit_each=True) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS judgements (
                run_id            INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                intent_recovered  INTEGER,
                defect_caught     INTEGER,
                false_alarm       INTEGER,
                intent_reason     TEXT,
                defect_reason     TEXT,
                false_alarm_reason TEXT,
                judge_model       TEXT
            );
            """
        )
        rows = conn.execute(
            """
            SELECT r.*, i.has_defect, i.mutation_op, i.mutation_target,
                   i.problem_statement
            FROM runs r
            JOIN instances i ON i.pr_id = r.pr_id
            LEFT JOIN judgements j ON j.run_id = r.id
            WHERE r.error IS NULL AND j.run_id IS NULL
            """
        ).fetchall()

        if limit:
            rows = rows[:limit]
        log.info("%d reviews to judge", len(rows))

        for row in rows:
            d = dict(row)
            try:
                result = llm.structured(
                    model=model,
                    schema=JudgeVerdict,
                    system=SYSTEM,
                    cached_context=build_judge_context(d, d),
                    instruction="Score this review against the ground truth.",
                    max_tokens=2000,
                    thinking=True,
                )
            except Exception:
                log.exception("judging run %s failed", d["id"])
                continue

            v = result.value
            cost += result.usage.cost_usd
            conn.execute(
                """INSERT OR REPLACE INTO judgements
                   (run_id, intent_recovered, defect_caught, false_alarm,
                    intent_reason, defect_reason, false_alarm_reason, judge_model)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    d["id"], int(v.intent_recovered), int(v.defect_caught),
                    int(v.false_alarm), v.intent_reason, v.defect_reason,
                    v.false_alarm_reason, model,
                ),
            )
            scored += 1
            if scored % 25 == 0:
                log.info("judged %d/%d, $%.2f", scored, len(rows), cost)

    return {"scored": scored, "cost_usd": round(cost, 4)}


def sample_for_humans(db_path: Path, n: int, out: Path, seed: int = 20260831) -> int:
    """Stratified sample for the judge-validation pass.

    Stratifying by condition and variant matters: an unstratified sample at n=60
    can easily under-represent the treatment cell, and agreement on the cell that
    carries the result is the number worth reporting.
    """
    with db.connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """
                SELECT r.id, r.pr_id, r.condition, i.variant, i.has_defect,
                       i.problem_statement, r.intent_summary, r.verdict,
                       r.n_findings, r.flagged_defect, j.intent_recovered,
                       j.defect_caught, j.false_alarm
                FROM runs r
                JOIN instances i ON i.pr_id = r.pr_id
                LEFT JOIN judgements j ON j.run_id = r.id
                WHERE r.error IS NULL
                """
            )
        ]

    strata: dict[tuple, list[dict]] = {}
    for row in rows:
        strata.setdefault((row["condition"], row["variant"]), []).append(row)

    rng = random.Random(seed)
    per = max(1, n // max(len(strata), 1))
    sample: list[dict] = []
    for key in sorted(strata):
        pool = strata[key]
        sample.extend(rng.sample(pool, min(per, len(pool))))

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        # Blank human columns; the judge's own scores are deliberately last so a
        # scorer who fills this left to right has not seen them first.
        fieldnames = [
            "run_id", "pr_id", "condition", "variant", "has_defect",
            "problem_statement", "intent_summary", "verdict", "n_findings",
            "human_intent_recovered", "human_defect_caught", "human_false_alarm",
            "judge_intent_recovered", "judge_defect_caught", "judge_false_alarm",
        ]
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for row in sample:
            w.writerow(
                {
                    "run_id": row["id"],
                    "pr_id": row["pr_id"],
                    "condition": row["condition"],
                    "variant": row["variant"],
                    "has_defect": row["has_defect"],
                    "problem_statement": (row["problem_statement"] or "")[:400],
                    "intent_summary": row["intent_summary"],
                    "verdict": row["verdict"],
                    "n_findings": row["n_findings"],
                    "human_intent_recovered": "",
                    "human_defect_caught": "",
                    "human_false_alarm": "",
                    "judge_intent_recovered": row["intent_recovered"],
                    "judge_defect_caught": row["defect_caught"],
                    "judge_false_alarm": row["false_alarm"],
                }
            )
    return len(sample)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sample-for-humans", type=int, default=0)
    ap.add_argument("--out", default="runs/judge_validation_sample.csv")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    db_path = Path(args.db) if args.db else settings().clarifyreview_db

    if args.sample_for_humans:
        n = sample_for_humans(db_path, args.sample_for_humans, Path(args.out))
        print(f"wrote {n} rows to {args.out}")
        print("Copy it once per scorer (e.g. runs/judge_yashika.csv, runs/judge_pratyaksh.csv),")
        print("fill the human_* columns independently with 1/0, then run:")
        print("  python -m experiments.analyze --judge-agreement runs/judge_*.csv")
        return 0

    stats = score_all(db_path, limit=args.limit)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
