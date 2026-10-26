"""Heuristic suggestions to help ADJUDICATE labelling disagreements.

This never touches the labelling sheet and never writes a human column. It writes
a separate file keyed by pr_id. Open it only after both annotators have finished:
seeing a suggestion first would anchor them. It is a weak aid for the rows the two
annotators disagree on, not a label and not ground truth.

In the code-only view the sheet shows, three heuristic rules fire on every row
(no linked issue, generic commit message, no test alongside), so they carry no
information here and are left out of the evidence.

    python -m experiments.prelabel
    python -m experiments.prelabel --evidence-only
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from clarifyreview.detect.base import Thresholds
from clarifyreview.detect.features import _GUARD_CALL, _GUARD_SHAPE, _SENSITIVE, extract
from clarifyreview.detect.heuristic import HeuristicDetector
from clarifyreview.ingest import from_raw

CONSTANT_IN_CODE_ONLY_VIEW = frozenset({"no_linked_issue", "generic_commit_msg", "no_test_alongside"})
SUGGESTION_FIELDS = ["pr_id", "repo", "suggested_label", "heuristic_score", "evidence_rules",
                     "files_touched", "lines_added", "lines_removed", "deletion_ratio",
                     "changed_symbols", "removed_guard_lines", "sensitive_terms", "note"]
NOTE = "heuristic aid for adjudication only - not a label"

README = """\
labelling_suggestions.csv - read this first

Do NOT open labelling_suggestions.csv until BOTH annotators have finished
labelling. Seeing a suggestion first would anchor your judgement.

Use it only for the rows where the two annotators disagree, to help the person
adjudicating. The suggestion is a hand-set rule heuristic run on its default
thresholds. It is weak (it was never validated against human labels), it is not a
label, and it must not be copied into annotator_1, annotator_2 or adjudicated.
The adjudicator still decides each disagreement by reading the code.

suggested_label: 1 = the heuristic would ask (unclear), 0 = clear.
evidence_rules: rules that fired, excluding the three that fire on every row of the
code-only view (no_linked_issue, generic_commit_msg, no_test_alongside).
"""


def _label_sensitive(text: str) -> list[str]:
    seen: list[str] = []
    for m in _SENSITIVE.finditer(text):
        t = m.group(0).lower()
        if t not in seen:
            seen.append(t)
        if len(seen) == 5:
            break
    return seen


def suggest_row(pr_id: str, repo: str, code_change: str, thresholds: Thresholds | None = None,
                evidence_only: bool = False) -> dict:
    thresholds = thresholds or Thresholds.load(None)
    ctx = from_raw(pr_id=pr_id, diff=code_change, repo=repo)
    det = HeuristicDetector(thresholds)
    score, _why, extra = det.score(ctx)
    f = extract(ctx)
    evidence = sorted(r for r, w in extra["fired"].items()
                      if r not in CONSTANT_IN_CODE_ONLY_VIEW and w > 0)
    removed = [ln for h in ctx.hunks for ln in h.removed]
    guards = [ln.strip() for ln in removed if _GUARD_CALL.search(ln) or _GUARD_SHAPE.search(ln)][:3]
    n_add = sum(len(h.added) for h in ctx.hunks)
    sensitive_text = "\n".join(ln for h in ctx.hunks for ln in (*h.added, *h.removed))
    ask = score >= thresholds.for_(det.name)
    return {
        "pr_id": pr_id, "repo": repo,
        "suggested_label": "" if evidence_only else ("1" if ask else "0"),
        "heuristic_score": "" if evidence_only else f"{score:.4f}",
        "evidence_rules": ";".join(evidence),
        "files_touched": len(ctx.files_touched),
        "lines_added": n_add, "lines_removed": len(removed),
        "deletion_ratio": f"{f['deletion_ratio']:.3f}",
        "changed_symbols": len(ctx.changed_symbols),
        "removed_guard_lines": " || ".join(guards),
        "sensitive_terms": ";".join(_label_sensitive(sensitive_text)),
        "note": NOTE,
    }


def write_suggestions(sheet: Path, out: Path, evidence_only: bool = False) -> int:
    sheet, out = Path(sheet), Path(out)
    if out.resolve() == sheet.resolve():
        raise ValueError("refusing to write suggestions over the labelling sheet")
    csv.field_size_limit(10**8)
    from experiments.label_tool import _read_rows

    rows = _read_rows(sheet)
    out.parent.mkdir(parents=True, exist_ok=True)
    thresholds = Thresholds.load(None)          # defaults, never data/thresholds.json
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SUGGESTION_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(suggest_row(r["pr_id"], r.get("repo", ""), r["code_change"],
                                   thresholds, evidence_only))
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="runs/labelling_sheet.csv")
    ap.add_argument("--out", default="runs/labelling_suggestions.csv")
    ap.add_argument("--evidence-only", action="store_true",
                    help="drop the suggested label and score; keep only the evidence columns")
    args = ap.parse_args(argv)
    sheet, out = Path(args.sheet), Path(args.out)
    if out.resolve() == sheet.resolve():
        print("--out must not be the labelling sheet", file=sys.stderr)
        return 2
    n = write_suggestions(sheet, out, args.evidence_only)
    readme = out.with_name(re.sub(r"\.csv$", "", out.name) + ".README.txt")
    readme.write_text(README, encoding="utf-8")
    print(f"wrote {n} suggestions to {out}\nread-me: {readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
