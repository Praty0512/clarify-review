"""Un-blind returned Study B responses into one analysis-ready CSV.

    python -m study.merge_responses responses/*.csv --out runs/study_b.csv
    python -m experiments.analyze --study-b runs/study_b.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .assign import clarify_is_a


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default="runs/study_b.csv")
    args = ap.parse_args(argv)

    out_rows = []
    for f in args.files:
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if not (r["usefulness"] and r["trust"]):
                continue
            a_is_clarify = clarify_is_a(r["participant"], r["item"])
            is_clarify = (r["label"] == "A") == a_is_clarify
            out_rows.append({
                "participant": r["participant"], "years": r["years"], "pr_id": r["item"],
                "condition": "stripped_clarify" if is_clarify else "stripped_plain",
                "usefulness": r["usefulness"], "trust": r["trust"],
                "would_act": r["would_act"], "why": r["why"],
            })
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]) if out_rows else ["participant"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"{len(out_rows)} ratings from {len({r['participant'] for r in out_rows})} "
          f"participants -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
