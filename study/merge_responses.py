"""Un-blind returned Study B responses into one analysis-ready CSV.

Inputs may be files, directories (every *.csv inside) or glob patterns, so the
command works the same in cmd, PowerShell and bash. The default is the folder the
returned files are meant to be dropped into.

    python -m study.merge_responses study/responses --out runs/study_b.csv
    python -m experiments.analyze --study-b runs/study_b.csv --out runs/study_b_report.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
from pathlib import Path

from .assign import clarify_is_a, item_ids

OUT_FIELDS = ["participant", "years", "pr_id", "condition", "usefulness", "trust",
              "would_act", "why"]


def expand(inputs: list[str]) -> list[Path]:
    """Files named directly, *.csv inside directories, and glob matches, de-duplicated."""
    found: list[Path] = []
    for spec in inputs:
        p = Path(spec)
        if p.is_dir():
            found.extend(sorted(p.glob("*.csv")))
        elif p.is_file():
            found.append(p)
        else:
            found.extend(Path(m) for m in sorted(glob.glob(spec)) if Path(m).is_file())
    seen, out = set(), []
    for p in found:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def merge(inputs: list[str], out: Path, html: Path | None = None) -> dict:
    """Merge and un-blind responses; returns counts.

    A participant who downloads twice (autosave makes this likely) produces
    duplicate (participant, item, label) rows; the row from the most recently
    modified file wins and the number dropped is reported. Rows with a blank
    usefulness or trust rating are skipped. Items not in `html` are counted in
    `unknown_items` (stale page or wrong file) but still merged.
    """
    files = sorted(expand(inputs), key=lambda p: (os.path.getmtime(p), str(p)))
    known = set(item_ids(html)) if html and Path(html).exists() else None

    latest: dict[tuple, dict] = {}
    n_in = 0
    for f in files:
        with f.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if not (r.get("usefulness") and r.get("trust")):
                    continue
                n_in += 1
                participant = r["participant"].strip()
                a_is_clarify = clarify_is_a(participant, r["item"])
                is_clarify = (r["label"] == "A") == a_is_clarify
                latest[(participant.lower(), r["item"], r["label"])] = {
                    "participant": participant, "years": r["years"], "pr_id": r["item"],
                    "condition": "stripped_clarify" if is_clarify else "stripped_plain",
                    "usefulness": r["usefulness"], "trust": r["trust"],
                    "would_act": r["would_act"], "why": r["why"],
                }
    rows = list(latest.values())
    unknown = sorted({r["pr_id"] for r in rows if known is not None and r["pr_id"] not in known})

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return {
        "files": [str(f) for f in files],
        "ratings": len(rows),
        "participants": len({r["participant"].lower() for r in rows}),
        "duplicates_dropped": n_in - len(rows),
        "unknown_items": unknown,
        "out": str(out),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", default=["study/responses"],
                    help="files, directories or glob patterns (default: study/responses)")
    ap.add_argument("--out", default="runs/study_b.csv")
    ap.add_argument("--html", default="study/study.html")
    args = ap.parse_args(argv)

    res = merge(args.files, Path(args.out), Path(args.html))
    if not res["files"]:
        print("no response files found in", " ".join(args.files))
        return 1
    if res["duplicates_dropped"]:
        print(f"dropped {res['duplicates_dropped']} duplicate rows (kept the latest file's)")
    if res["unknown_items"]:
        print(f"warning: {len(res['unknown_items'])} item ids are not in {args.html}: "
              f"{', '.join(res['unknown_items'][:5])}")
    print(f"{res['ratings']} ratings from {res['participants']} participants -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
