"""Defect injection, so the ablation has true positives.

A SWE-bench golden patch is the accepted fix. Reviewing it produces no true
positives at all - every defect a reviewer reports on a correct patch is a false
alarm. That is a useful measurement, but it is half a confusion matrix.

This module produces the other half: plausible defective variants of the golden
patch. A mutant is only kept if the repository's own FAIL_TO_PASS tests fail on
it, which makes "there is a bug here" execution-verified ground truth rather than
a judgement call.

Mutations are applied only to lines the golden patch *added*. Mutating untouched
code elsewhere in the file would produce a defect the diff does not contain, and
a reviewer that missed it would be marked wrong for no reason.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from clarifyreview.ingest.diff import parse_unified_diff


@dataclass
class Mutant:
    op: str
    target_line: str
    mutated_line: str
    file: str
    diff: str
    verified: bool = False

    @property
    def description(self) -> str:
        return f"{self.op} in {self.file}: {self.target_line.strip()!r} -> {self.mutated_line.strip()!r}"


# --------------------------------------------------------------- operators
#
# Each returns the mutated line, or None if it does not apply. Ordered from most
# to least likely to produce a genuine behavioural defect rather than a no-op.

def _invert_comparison(line: str) -> str | None:
    swaps = [("==", "!="), ("!=", "=="), (" <= ", " < "), (" >= ", " > "),
             (" < ", " <= "), (" > ", " >= ")]
    for a, b in swaps:
        if a in line:
            return line.replace(a, b, 1)
    return None


def _negate_condition(line: str) -> str | None:
    m = re.match(r"^(\s*)(if|while|elif)\s+(?!not\s)(.+?):\s*$", line)
    if m:
        return f"{m.group(1)}{m.group(2)} not ({m.group(3)}):"
    m = re.match(r"^(\s*)(if|while|elif)\s+not\s+(.+?):\s*$", line)
    if m:
        return f"{m.group(1)}{m.group(2)} {m.group(3)}:"
    return None


def _swap_boolean_op(line: str) -> str | None:
    if " and " in line:
        return line.replace(" and ", " or ", 1)
    if " or " in line:
        return line.replace(" or ", " and ", 1)
    return None


def _off_by_one(line: str) -> str | None:
    m = re.search(r"([\w\)\]]\s*)([+-])(\s*)1\b", line)
    if m:
        flipped = "-" if m.group(2) == "+" else "+"
        return line[: m.start(2)] + flipped + line[m.end(2) :]
    m = re.search(r"\brange\((\w+)\)", line)
    if m:
        return line[: m.start(1)] + f"{m.group(1)} - 1" + line[m.end(1) :]
    return None


def _flip_constant(line: str) -> str | None:
    for a, b in (("True", "False"), ("False", "True")):
        if re.search(rf"\b{a}\b", line):
            return re.sub(rf"\b{a}\b", b, line, count=1)
    m = re.search(r"=\s*(0|1)\b", line)
    if m:
        return line[: m.start(1)] + ("1" if m.group(1) == "0" else "0") + line[m.end(1) :]
    return None


def _drop_guard(line: str) -> str | None:
    """Turn a raising guard into a no-op, keeping the file syntactically valid."""
    m = re.match(r"^(\s*)(raise\s+\w+.*|return\s+(None|False)\s*)$", line)
    if m:
        return f"{m.group(1)}pass"
    return None


OPERATORS: dict[str, Callable[[str], str | None]] = {
    "invert_comparison": _invert_comparison,
    "negate_condition": _negate_condition,
    "swap_boolean_op": _swap_boolean_op,
    "off_by_one": _off_by_one,
    "drop_guard": _drop_guard,
    "flip_constant": _flip_constant,
}


# ---------------------------------------------------------------- generation


def added_lines(patch: str) -> list[tuple[str, str]]:
    """(file, line) for every line the patch adds. The mutation surface."""
    out: list[tuple[str, str]] = []
    for hunk in parse_unified_diff(patch):
        for line in hunk.added:
            if line.strip() and not line.lstrip().startswith("#"):
                out.append((hunk.file, line))
    return out


def candidate_mutants(patch: str, max_per_op: int = 2) -> list[Mutant]:
    """Every mutation this patch admits, unverified.

    Ordered by operator so the caller verifies the most defect-likely first and
    can stop after one succeeds - test verification is the expensive step.
    """
    mutants: list[Mutant] = []
    for op_name, op in OPERATORS.items():
        made = 0
        for file, line in added_lines(patch):
            if made >= max_per_op:
                break
            mutated = op(line)
            if mutated is None or mutated == line:
                continue
            new_patch = _rewrite_patch_line(patch, line, mutated)
            if new_patch is None:
                continue
            mutants.append(
                Mutant(
                    op=op_name,
                    target_line=line,
                    mutated_line=mutated,
                    file=file,
                    diff=new_patch,
                )
            )
            made += 1
    return mutants


def _rewrite_patch_line(patch: str, original: str, mutated: str) -> str | None:
    """Replace one added line inside the patch text itself.

    Only the first occurrence is replaced, and only on an added (`+`) line, so a
    string that also appears as context or in a removed line is untouched.
    """
    out: list[str] = []
    done = False
    for line in patch.splitlines():
        if not done and line.startswith("+") and line[1:] == original:
            out.append("+" + mutated)
            done = True
        else:
            out.append(line)
    return "\n".join(out) + "\n" if done else None


def apply_patch_to_tree(repo_root: Path, patch: str) -> bool:
    """Apply a patch to a checkout with `git apply`. Returns success."""
    import subprocess

    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=repo_root,
        input=patch.encode(),
        capture_output=True,
    )
    return proc.returncode == 0


# -------------------------------------------------------------- verification


class TestRunner(Protocol):
    def run(self, repo_root: Path, tests: list[str]) -> bool:
        """True if every named test passes."""


class SubprocessTestRunner:
    """Runs pytest in a prepared checkout.

    Adequate for repositories whose test suite runs in the ambient environment.
    For SWE-bench proper, use the official Docker harness - each instance pins its
    own dependency set, and running them against one shared environment produces
    failures that have nothing to do with the mutation.
    """

    def __init__(self, timeout_s: int = 900) -> None:
        self.timeout_s = timeout_s

    def run(self, repo_root: Path, tests: list[str]) -> bool:
        import subprocess

        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", "-x", "-q", *tests],
                cwd=repo_root,
                capture_output=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return False
        return proc.returncode == 0


def verify_mutant(
    mutant: Mutant,
    repo_root: Path,
    fail_to_pass: list[str],
    runner: TestRunner,
) -> bool:
    """A mutant is valid when the tests the golden patch fixes fail on it.

    The caller is responsible for handing over a clean checkout at the base
    commit; this function applies the mutant patch to it and does not clean up,
    because the runner needs the tree in that state.
    """
    if not fail_to_pass:
        return False
    if not apply_patch_to_tree(repo_root, mutant.diff):
        return False
    passed = runner.run(repo_root, fail_to_pass)
    mutant.verified = not passed  # the mutant must BREAK the fixed tests
    return mutant.verified


def unified_diff(before: str, after: str, path: str) -> str:
    """Helper for building a patch from two file versions."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
