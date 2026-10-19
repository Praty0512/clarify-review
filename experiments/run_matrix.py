"""Study A: the 2 x 3 ablation runner.

Two patch variants (golden, mutant) crossed with three conditions:

    full_plain        full context, single pass      -> the ceiling
    stripped_plain    intent removed, single pass    -> the floor
    stripped_clarify  intent removed, ClarifyReview  -> the treatment

Every cell runs the same `Pipeline` over the same `PRContext`. The floor and the
treatment see byte-identical code and differ only in whether Stage 2 and Stage 3
executed - which is the one comparison the whole study rests on, so the runner
asserts it rather than trusting it.

    python -m experiments.run_matrix --instances data/instances.jsonl --limit 100
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from clarifyreview.config import settings
from clarifyreview.ingest import from_raw
from clarifyreview.pipeline import (
    CONDITION_FULL_PLAIN,
    CONDITION_STRIPPED_CLARIFY,
    CONDITION_STRIPPED_PLAIN,
    Pipeline,
    build_condition,
)
from clarifyreview.store import db
from clarifyreview.types import LinkedIssue, PRContext, ReviewRun

from .oracle import Oracle, OracleResponder
from .strip import Withheld, is_properly_stripped, strip_context

log = logging.getLogger("run_matrix")

CONDITIONS = (CONDITION_FULL_PLAIN, CONDITION_STRIPPED_PLAIN, CONDITION_STRIPPED_CLARIFY)


@dataclass
class Instance:
    """One row of the benchmark. Built by build_dataset.py + mutate.py."""

    pr_id: str
    repo: str
    variant: str  # "golden" | "mutant"
    has_defect: bool
    diff: str
    problem_statement: str
    commit_messages: list[str]
    issue_title: str = ""
    issue_number: int = 0
    pr_body: str = ""
    base_commit: str = ""
    mutation_op: str = ""
    mutation_target: str = ""
    repo_root: str = ""

    @classmethod
    def from_json(cls, line: str) -> Instance:
        data = json.loads(line)
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def context(self) -> PRContext:
        issue = (
            LinkedIssue(
                number=self.issue_number,
                title=self.issue_title,
                body=self.problem_statement,
            )
            if self.problem_statement.strip()
            else None
        )
        return from_raw(
            pr_id=self.pr_id,
            diff=self.diff,
            repo=self.repo,
            title=self.issue_title or "",
            body=self.pr_body,
            commit_messages=self.commit_messages,
            linked_issue=issue,
            repo_root=Path(self.repo_root) if self.repo_root else None,
        )


def run_instance(
    inst: Instance,
    detector_name: str,
    oracle: Oracle,
    conditions: tuple[str, ...] = CONDITIONS,
) -> list[ReviewRun]:
    """All three conditions for one instance."""
    full = inst.context()
    stripped, withheld = strip_context(full)

    if not is_properly_stripped(stripped):
        raise AssertionError(f"{inst.pr_id}: stripping left intent behind")
    if stripped.diff != full.diff:
        raise AssertionError(
            f"{inst.pr_id}: stripping changed the diff; the conditions would not be "
            f"comparable"
        )

    runs: list[ReviewRun] = []

    if CONDITION_FULL_PLAIN in conditions:
        runs.append(Pipeline.plain(CONDITION_FULL_PLAIN).run(full.model_copy(deep=True)))

    if CONDITION_STRIPPED_PLAIN in conditions:
        runs.append(
            Pipeline.plain(CONDITION_STRIPPED_PLAIN).run(stripped.model_copy(deep=True))
        )

    if CONDITION_STRIPPED_CLARIFY in conditions:
        pipeline = build_condition(
            CONDITION_STRIPPED_CLARIFY,
            detector_name=detector_name,
            responder=OracleResponder(oracle, withheld),
        )
        runs.append(pipeline.run(stripped.model_copy(deep=True)))

    return runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Study A: the 2 x 3 ablation")
    ap.add_argument("--instances", default="data/instances.jsonl")
    ap.add_argument("--db", default=None)
    ap.add_argument("--detector", default="heuristic",
                    choices=["heuristic", "classifier", "sampling", "perturbation"])
    ap.add_argument("--limit", type=int, default=0, help="0 means all")
    ap.add_argument("--conditions", nargs="*", default=list(CONDITIONS))
    ap.add_argument("--dry-run", action="store_true",
                    help="build and validate contexts without calling the API")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    path = Path(args.instances)
    if not path.exists():
        log.error("no instance file at %s - run experiments/build_dataset.py first", path)
        return 1

    instances = [Instance.from_json(line) for line in path.read_text().splitlines() if line.strip()]
    if args.limit:
        instances = instances[: args.limit]
    log.info("%d instances, detector=%s, conditions=%s",
             len(instances), args.detector, ", ".join(args.conditions))

    if args.dry_run:
        return _dry_run(instances)

    db_path = Path(args.db) if args.db else settings().clarifyreview_db
    db.init(db_path)
    oracle = Oracle()

    total_cost = 0.0
    failures = 0
    # Commit as we go: the run is hours long, and a failure part-way through
    # must not discard the instances already paid for.
    with db.connect(db_path, autocommit_each=True) as conn:
        for i, inst in enumerate(instances, start=1):
            try:
                runs = run_instance(inst, args.detector, oracle, tuple(args.conditions))
            except Exception:
                log.exception("%s failed entirely", inst.pr_id)
                failures += 1
                continue

            db.upsert_instance(
                conn,
                pr_id=inst.pr_id,
                source="swebench_verified",
                repo=inst.repo,
                base_commit=inst.base_commit,
                variant=inst.variant,
                has_defect=int(inst.has_defect),
                mutation_op=inst.mutation_op,
                mutation_target=inst.mutation_target,
                problem_statement=inst.problem_statement,
                original_commit_msg="\n".join(inst.commit_messages),
                tests_verified=int(inst.variant == "mutant"),
            )
            for run in runs:
                db.record_run(conn, run)
                total_cost += run.cost_usd
                if run.error:
                    failures += 1

            log.info(
                "[%d/%d] %s (%s): %s | running cost $%.2f",
                i, len(instances), inst.pr_id, inst.variant,
                "  ".join(
                    f"{r.condition}={'err' if r.error else (r.review.verdict if r.review else '?')}"
                    for r in runs
                ),
                total_cost + oracle.cost_usd,
            )

    log.info("done. %d failures. total cost $%.2f (oracle $%.2f)",
             failures, total_cost + oracle.cost_usd, oracle.cost_usd)
    log.info("now run: python -m experiments.judge --db %s", db_path)
    return 0


def _dry_run(instances: list[Instance]) -> int:
    """Validate the manipulation without spending anything.

    Worth running over the full set before every real run: it catches a stripping
    leak or a malformed diff in seconds rather than after $50 of API calls.
    """
    bad = 0
    for inst in instances:
        try:
            full = inst.context()
            stripped, withheld = strip_context(full)
            assert is_properly_stripped(stripped), "strip left intent behind"
            assert stripped.diff == full.diff, "strip changed the diff"
            assert full.fingerprint() != stripped.fingerprint(), "strip changed nothing"
            if withheld.is_empty():
                log.warning("%s: nothing withheld, the oracle will have no answer",
                            inst.pr_id)
        except AssertionError as exc:
            log.error("%s: %s", inst.pr_id, exc)
            bad += 1
    log.info("dry run: %d/%d instances valid", len(instances) - bad, len(instances))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
