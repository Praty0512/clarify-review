"""Execution-verified defects for the mutant arm.

A mutant becomes ground truth only when the repository's own tests say so:

  1. check out the base commit, apply the benchmark's test patch;
  2. apply the golden patch and run FAIL_TO_PASS - every test must PASS.
     This proves the environment can run them; without it, a failing mutant
     could just be a broken environment;
  3. reset, apply the test patch and the mutant instead - the tests must FAIL.

The SWE-bench Docker harness does this for every repository but needs far more
disk than was available, so this runs pure-Python repositories (sympy first)
against a local Python 3.9 environment. The criterion is the same; only the
isolation differs, and the report records which mechanism verified each mutant.

    python -m experiments.verify_mutants --repo sympy/sympy --limit 40
"""

from __future__ import annotations

import argparse
import json
import logging
import shlex
import subprocess
import time
from pathlib import Path

from .mutate import candidate_mutants

log = logging.getLogger("verify_mutants")

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / ".bench"
PY39 = BENCH / "py39" / "bin" / "python"


def sh(cmd: list[str] | str, cwd: Path, timeout: int = 600, stdin: str | None = None):
    return subprocess.run(
        cmd if isinstance(cmd, list) else shlex.split(cmd),
        cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout,
    )


def reset(repo: Path, commit: str) -> bool:
    sh(["git", "reset", "-q", "--hard"], repo)
    sh(["git", "clean", "-q", "-fdx"], repo)
    return sh(["git", "checkout", "-q", "-f", commit], repo, timeout=900).returncode == 0


def apply(repo: Path, patch: str) -> bool:
    return sh(["git", "apply", "--whitespace=nowarn", "-"], repo, stdin=patch).returncode == 0


def test_files(test_patch: str) -> list[str]:
    return sorted({line[6:] for line in test_patch.splitlines()
                   if line.startswith("+++ b/") and line.endswith(".py")})


def run_tests(repo: Path, files: list[str], names: list[str], timeout: int) -> tuple[bool, str]:
    """True when every named test passes. Test names are function names."""
    bare = sorted({n.split("::")[-1].split("[")[0].strip() for n in names if n.strip()})
    expr = " or ".join(bare)
    cmd = [str(PY39), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x",
           "--no-header", "-rN", *files, "-k", expr]
    try:
        proc = sh(cmd, repo, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
    # "no tests ran" (exit 5) must not count as a pass: it means the selection
    # matched nothing, which proves nothing about the patch.
    return proc.returncode == 0, tail[0][:160]


def verify_instance(inst: dict, repo: Path, timeout: int) -> dict:
    out = {"instance_id": inst["instance_id"], "repo": inst["repo"], "status": None}
    names = json.loads(inst["FAIL_TO_PASS"] or "[]")
    files = test_files(inst["test_patch"])
    if not names or not files:
        out["status"] = "no_fail_to_pass_tests"
        return out
    candidates = candidate_mutants(inst["patch"])
    if not candidates:
        out["status"] = "no_mutation_applies"
        return out

    t0 = time.monotonic()
    if not (reset(repo, inst["base_commit"]) and apply(repo, inst["test_patch"])
            and apply(repo, inst["patch"])):
        out["status"] = "golden_patch_did_not_apply"
        return out
    ok, tail = run_tests(repo, files, names, timeout)
    out["golden_tests"] = tail
    if not ok:
        out["status"] = "environment_cannot_run_tests"   # golden must pass first
        return out

    for cand in candidates:
        if not (reset(repo, inst["base_commit"]) and apply(repo, inst["test_patch"])
                and apply(repo, cand.diff)):
            continue
        passed, tail = run_tests(repo, files, names, timeout)
        if not passed:
            out.update(status="verified", mutation_op=cand.op,
                       mutation_target=cand.target_line.strip()[:200],
                       mutated_line=cand.mutated_line.strip()[:200],
                       mutant_diff=cand.diff, mutant_tests=tail,
                       verified_by="local-py3.9-pytest",
                       seconds=round(time.monotonic() - t0, 1))
            return out
    out["status"] = "every_mutant_survived"          # tests could not see the change
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="sympy/sympy")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--out", default="data/mutants.verified.jsonl")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from datasets import load_dataset
    rows = [dict(r) for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
            if r["repo"] == args.repo]
    rows.sort(key=lambda r: r["instance_id"])
    repo_dir = BENCH / "repos" / args.repo.split("/")[1]

    out_path = ROOT / args.out
    done = set()
    if out_path.exists():
        done = {json.loads(l)["instance_id"] for l in out_path.read_text().splitlines() if l}
    todo = [r for r in rows if r["instance_id"] not in done][: args.limit]
    log.info("%d %s instances, %d already processed, %d to do",
             len(rows), args.repo, len(done), len(todo))

    tally: dict[str, int] = {}
    with out_path.open("a") as fh:
        for i, inst in enumerate(todo, 1):
            try:
                res = verify_instance(inst, repo_dir, args.timeout)
            except Exception as exc:  # noqa: BLE001 - one instance must not stop the run
                res = {"instance_id": inst["instance_id"], "repo": inst["repo"],
                       "status": f"error: {type(exc).__name__}"}
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            tally[res["status"]] = tally.get(res["status"], 0) + 1
            log.info("[%d/%d] %s -> %s", i, len(todo), inst["instance_id"], res["status"])
    reset(repo_dir, "HEAD")
    log.info("summary: %s", tally)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
