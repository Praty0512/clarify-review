"""Build the Study A instance file from SWE-bench Verified.

Verified, not the full set: the full set contains instances whose issue text is
under-specified even for a human, which would contaminate the ambiguity
manipulation - those instances are ambiguous in the *full-context* condition too,
so they cannot serve as a ceiling.

Each SWE-bench instance yields up to two rows:

    golden  the accepted patch, known-good      -> flagged defects are false alarms
    mutant  the patch with an injected defect   -> a missed defect is a miss

A mutant is only emitted if `--verify` confirmed the repository's FAIL_TO_PASS
tests fail on it. Without `--verify` the mutants are written with
`tests_verified=false` and are usable for a pilot but not for a reported result.

    python -m experiments.build_dataset --limit 100 --out data/instances.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

from .mutate import Mutant, SubprocessTestRunner, candidate_mutants, verify_mutant

log = logging.getLogger("build_dataset")

DATASET = "princeton-nlp/SWE-bench_Verified"


def load_swebench(split: str = "test", limit: int = 0) -> list[dict]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "SWE-bench loading needs the `bench` extra: pip install -e '.[bench]'"
        ) from exc

    ds = load_dataset(DATASET, split=split)
    rows = [dict(r) for r in ds]
    log.info("loaded %d instances from %s", len(rows), DATASET)
    return rows[:limit] if limit else rows


def stratify_by_repo(rows: list[dict], n: int, seed: int = 20260831) -> list[dict]:
    """Sample evenly across repositories.

    Without this, a handful of large repos dominate: SWE-bench is not uniform
    across its twelve projects, and a result driven by one codebase's conventions
    is not a result about pull request review.
    """
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)

    rng = random.Random(seed)
    repos = sorted(by_repo)
    per_repo = max(1, n // len(repos))
    picked: list[dict] = []
    for repo in repos:
        pool = sorted(by_repo[repo], key=lambda r: r["instance_id"])
        picked.extend(rng.sample(pool, min(per_repo, len(pool))))

    # Top up deterministically if rounding left us short.
    if len(picked) < n:
        remaining = [r for r in rows if r not in picked]
        remaining.sort(key=lambda r: r["instance_id"])
        picked.extend(remaining[: n - len(picked)])
    return sorted(picked[:n], key=lambda r: r["instance_id"])


def to_rows(
    instance: dict,
    mutant: Mutant | None,
    repo_root: str = "",
) -> list[dict]:
    """One SWE-bench instance -> one or two instance-file rows."""
    base = {
        "repo": instance["repo"],
        "problem_statement": instance.get("problem_statement", ""),
        "issue_title": (instance.get("problem_statement", "") or "").splitlines()[:1][0][:200]
        if instance.get("problem_statement")
        else "",
        "issue_number": 0,
        "pr_body": "",
        "commit_messages": [f"Fix: {instance['instance_id']}"],
        "base_commit": instance.get("base_commit", ""),
        "repo_root": repo_root,
    }

    rows = [
        {
            **base,
            "pr_id": f"{instance['instance_id']}::golden",
            "variant": "golden",
            "has_defect": False,
            "diff": instance["patch"],
            "mutation_op": "",
            "mutation_target": "",
        }
    ]
    if mutant is not None:
        rows.append(
            {
                **base,
                "pr_id": f"{instance['instance_id']}::mutant",
                "variant": "mutant",
                "has_defect": True,
                "diff": mutant.diff,
                "mutation_op": mutant.op,
                "mutation_target": mutant.target_line.strip()[:200],
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="instances to sample")
    ap.add_argument("--out", default="data/instances.jsonl")
    ap.add_argument("--seed", type=int, default=20260831)
    ap.add_argument(
        "--verify",
        action="store_true",
        help="run each candidate mutant against the repo's FAIL_TO_PASS tests. "
             "Needs a prepared checkout per instance; see --checkouts.",
    )
    ap.add_argument("--checkouts", help="directory of per-instance checkouts at base_commit")
    ap.add_argument("--golden-only", action="store_true", help="skip mutation entirely")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    rows = load_swebench()
    picked = stratify_by_repo(rows, args.limit, seed=args.seed)
    log.info("sampled %d instances across %d repos",
             len(picked), len({r["repo"] for r in picked}))

    runner = SubprocessTestRunner()
    out_rows: list[dict] = []
    no_mutant = 0

    for inst in picked:
        mutant = None
        if not args.golden_only:
            candidates = candidate_mutants(inst["patch"])
            if not candidates:
                no_mutant += 1
            elif not args.verify:
                # Unverified: usable for a pilot, not for a reported number.
                mutant = candidates[0]
            else:
                checkout = Path(args.checkouts or "") / inst["instance_id"]
                fail_to_pass = json.loads(inst.get("FAIL_TO_PASS") or "[]")
                for cand in candidates:
                    if not checkout.exists():
                        log.warning("no checkout at %s; cannot verify", checkout)
                        break
                    if verify_mutant(cand, checkout, fail_to_pass, runner):
                        mutant = cand
                        break
                if mutant is None:
                    no_mutant += 1

        repo_root = str(Path(args.checkouts) / inst["instance_id"]) if args.checkouts else ""
        out_rows.extend(to_rows(inst, mutant, repo_root=repo_root))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    log.info("wrote %d rows to %s (%d instances yielded no usable mutant)",
             len(out_rows), out, no_mutant)
    if no_mutant > len(picked) // 3:
        log.warning(
            "mutation yield is low (%d/%d dropped). Widen the operator set in "
            "mutate.py before reporting, or the mutant cell will be underpowered.",
            no_mutant, len(picked),
        )
    if not args.verify:
        log.warning("mutants are UNVERIFIED. Re-run with --verify --checkouts before "
                    "reporting any defect-detection number.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
