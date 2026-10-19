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
    strip_level: str = "prose",
) -> list[ReviewRun]:
    """All three conditions for one instance.

    The floor and the treatment always receive the same stripped context; that
    is the comparison the study rests on. At strip level "issue" the stripped
    diff is also byte-identical to the full one. At "prose" it differs from the
    full diff only by the comments and docstrings the patch added - never by a
    line of code - which `_same_code` asserts.
    """
    full = inst.context()
    stripped, withheld = strip_context(full, level=strip_level)

    if not is_properly_stripped(stripped, level=strip_level):
        raise AssertionError(f"{inst.pr_id}: stripping left intent behind")
    if strip_level == "issue" and stripped.diff != full.diff:
        raise AssertionError(
            f"{inst.pr_id}: stripping changed the diff; the conditions would not be "
            f"comparable"
        )
    if strip_level == "prose" and not _same_code(full.diff, stripped.diff):
        raise AssertionError(f"{inst.pr_id}: prose stripping altered a line of code")

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


def _same_code(full_diff: str, stripped_diff: str) -> bool:
    """True when the two diffs add the same code once comments are removed."""
    from .strip import _strip_trailing_comment

    def code(diff: str) -> list[str]:
        from clarifyreview.ingest.diff import parse_unified_diff
        lines = []
        for h in parse_unified_diff(diff):
            for a in h.added:
                c = _strip_trailing_comment(a).rstrip()
                if c.strip() and not c.strip().startswith("#"):
                    lines.append(c)
        return lines

    stripped_code = code(stripped_diff)
    # Every surviving added line must be code that was in the full diff.
    full_code = code(full_diff)
    return all(line in full_code for line in stripped_code) and len(stripped_code) > 0


def _completed(db_path: Path, conditions: tuple[str, ...] = CONDITIONS) -> set[str]:
    """Instances that already have all requested conditions recorded cleanly."""
    if not db_path.exists():
        return set()
    import sqlite3
    conn = sqlite3.connect(db_path)
    marks = ",".join("?" for _ in conditions)
    try:
        rows = conn.execute(
            f"SELECT pr_id FROM runs WHERE error IS NULL AND condition IN ({marks}) "
            f"GROUP BY pr_id HAVING COUNT(DISTINCT condition) = ?",
            (*conditions, len(conditions))).fetchall()
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()
    return {r[0] for r in rows}


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
    ap.add_argument("--strip-level", default="prose", choices=["issue", "prose"],
                    help="issue = v1 (pilot); prose = v2, also strips added comments "
                         "and docstrings")
    ap.add_argument("--resume", action="store_true",
                    help="skip instances already complete in --db; failed attempts "
                         "for an instance are cleared and retried")
    ap.add_argument("--only", nargs="*", default=None, metavar="PR_ID",
                    help="restrict the run to these instance ids")
    ap.add_argument("--redo", action="store_true",
                    help="with --only: discard the requested conditions for those "
                         "instances and run them again (e.g. after an oracle fix)")
    ap.add_argument("--stop-on-quota", action="store_true", default=True,
                    help="stop the run at the first exhausted daily quota rather than "
                         "recording a failure for every remaining instance")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    path = Path(args.instances)
    if not path.exists():
        log.error("no instance file at %s - run experiments/build_dataset.py first", path)
        return 1

    instances = [Instance.from_json(line) for line in path.read_text().splitlines() if line.strip()]
    if args.only:
        wanted = set(args.only)
        instances = [i for i in instances if i.pr_id in wanted]
        missing = wanted - {i.pr_id for i in instances}
        if missing:
            log.error("not in %s: %s", path, ", ".join(sorted(missing)))
            return 1
    if args.limit:
        instances = instances[: args.limit]
    log.info("%d instances, detector=%s, conditions=%s",
             len(instances), args.detector, ", ".join(args.conditions))

    if args.dry_run:
        return _dry_run(instances, args.strip_level)

    db_path = Path(args.db) if args.db else settings().clarifyreview_db
    db.init(db_path)
    oracle = Oracle()

    conditions = tuple(args.conditions)
    if args.redo and not args.only:
        log.error("--redo needs --only; refusing to discard a whole run")
        return 1
    if args.resume or args.redo:
        done = set() if args.redo else _completed(db_path, conditions)
        before = len(instances)
        instances = [i for i in instances if i.pr_id not in done]
        log.info("resume: %d already complete, %d remaining", before - len(instances),
                 len(instances))
        # Partial attempts are discarded so the paired comparison never mixes a
        # condition from one day with a retried condition from another. Only the
        # requested conditions are touched: redoing the treatment after an oracle
        # fix must leave the floor and ceiling it is compared against intact.
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=60)
        conn.execute("PRAGMA foreign_keys = ON")
        marks = ",".join("?" for _ in conditions)
        for inst in instances:
            conn.execute(f"DELETE FROM runs WHERE pr_id = ? AND condition IN ({marks})",
                         (inst.pr_id, *conditions))
        conn.commit()
        conn.close()

    total_cost = 0.0
    failures = 0
    # Commit as we go: the run is hours long, and a failure part-way through
    # must not discard the instances already paid for.
    with db.connect(db_path, autocommit_each=True) as conn:
        for i, inst in enumerate(instances, start=1):
            try:
                runs = run_instance(inst, args.detector, oracle, conditions,
                                    strip_level=args.strip_level)
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
            quota_hit = any(r.error and "PerDay" in r.error for r in runs)
            if quota_hit and args.stop_on_quota:
                # Do not record a half-finished instance; --resume will redo it.
                log.warning("daily quota exhausted at %s; stopping. Re-run with "
                            "--resume after the reset.", inst.pr_id)
                break

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


def _dry_run(instances: list[Instance], strip_level: str = "prose") -> int:
    """Validate the manipulation without spending anything.

    Worth running over the full set before every real run: it catches a stripping
    leak or a malformed diff in seconds rather than after $50 of API calls.
    """
    bad = 0
    for inst in instances:
        try:
            full = inst.context()
            stripped, withheld = strip_context(full, level=strip_level)
            assert is_properly_stripped(stripped, level=strip_level), \
                "strip left intent behind"
            if strip_level == "issue":
                assert stripped.diff == full.diff, "strip changed the diff"
            else:
                assert _same_code(full.diff, stripped.diff), "strip altered code"
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
