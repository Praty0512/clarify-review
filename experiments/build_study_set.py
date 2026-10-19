"""Compose the v2 study set.

Two arms, both drawn from SWE-bench Verified:

  mutant arm   instances whose injected defect was execution-verified by
               verify_mutants.py. Each contributes a golden row AND a mutant row,
               so defect detection and false alarms are measured on the same
               underlying change.
  golden arm   further golden patches from other repositories, selected by
               SWE-bench's own `difficulty` annotation, hardest first.

Why difficulty: the pilot showed randomly sampled golden patches are mostly
self-documenting. Harder fixes are larger and less likely to state their own
purpose. Crucially, `difficulty` was assigned by SWE-bench's annotators, not by
this project's detector, so selecting on it cannot bias the detector comparison.
Pilot instances are excluded so the v2 results are independent of v1.

    python -m experiments.build_study_set --golden 12 --mutants 12
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from pathlib import Path

from .build_dataset import to_rows
from .mutate import Mutant
from .strip import strip_context, is_properly_stripped

log = logging.getLogger("build_study_set")
ROOT = Path(__file__).resolve().parents[1]
DIFFICULTY_ORDER = [">4 hours", "1-4 hours", "15 min - 1 hour", "<15 min fix"]


def usable_after_stripping(row: dict) -> bool:
    """A row is usable when v2 stripping leaves real code and no prose."""
    from .run_matrix import Instance, _same_code
    inst = Instance.from_json(json.dumps(row))
    full = inst.context()
    stripped, _ = strip_context(full, level="prose")
    return is_properly_stripped(stripped, level="prose") and _same_code(full.diff, stripped.diff)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=int, default=12, help="golden-arm instances")
    ap.add_argument("--mutants", type=int, default=12, help="mutant-arm instances")
    ap.add_argument("--verified", default="data/mutants.verified.jsonl")
    ap.add_argument("--exclude", default="data/archive/instances.pilot.jsonl")
    ap.add_argument("--out", default="data/instances.v2.jsonl")
    ap.add_argument("--seed", type=int, default=20261019)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from datasets import load_dataset
    rows = {r["instance_id"]: dict(r)
            for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")}

    excluded = set()
    if Path(args.exclude).exists():
        excluded = {json.loads(l)["pr_id"].split("::")[0]
                    for l in Path(args.exclude).read_text().splitlines() if l}

    out_rows: list[dict] = []

    # ---- mutant arm
    verified = []
    if Path(args.verified).exists():
        verified = [json.loads(l) for l in Path(args.verified).read_text().splitlines() if l]
        verified = [v for v in verified if v.get("status") == "verified"
                    and v["instance_id"] not in excluded]
    mutant_ids = []
    for v in verified:
        if len(mutant_ids) >= args.mutants:
            break
        inst = rows[v["instance_id"]]
        mutant = Mutant(op=v["mutation_op"], target_line=v["mutation_target"],
                        mutated_line=v["mutated_line"], file="", diff=v["mutant_diff"],
                        verified=True)
        pair = to_rows(inst, mutant)
        if all(usable_after_stripping(r) for r in pair):
            for r in pair:
                r["arm"] = "mutant"
                r["difficulty"] = inst["difficulty"]
                r["tests_verified"] = r["variant"] == "mutant"
            out_rows.extend(pair)
            mutant_ids.append(v["instance_id"])
    log.info("mutant arm: %d instances (%d rows)", len(mutant_ids), 2 * len(mutant_ids))

    # ---- golden arm, hardest first, round-robin across repositories
    rng = random.Random(args.seed)
    taken = set(mutant_ids) | excluded
    pool = [r for r in rows.values()
            if r["instance_id"] not in taken and r["repo"] != "sympy/sympy"]
    golden: list[dict] = []
    for level in DIFFICULTY_ORDER:
        tier = [r for r in pool if r["difficulty"] == level]
        rng.shuffle(tier)
        by_repo: dict[str, list[dict]] = {}
        for r in tier:
            by_repo.setdefault(r["repo"], []).append(r)
        while len(golden) < args.golden and any(by_repo.values()):
            for repo in sorted(by_repo):
                if by_repo[repo] and len(golden) < args.golden:
                    cand = by_repo[repo].pop()
                    row = to_rows(cand, None)[0]
                    if usable_after_stripping(row):
                        row["arm"] = "golden"
                        row["difficulty"] = cand["difficulty"]
                        golden.append(row)
        if len(golden) >= args.golden:
            break
    out_rows.extend(golden)
    log.info("golden arm: %d instances", len(golden))

    Path(args.out).write_text("\n".join(json.dumps(r, sort_keys=True) for r in out_rows) + "\n")
    from collections import Counter
    log.info("wrote %d rows to %s | difficulty: %s", len(out_rows), args.out,
             dict(Counter(r["difficulty"] for r in out_rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
