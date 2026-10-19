"""Human labelling for the classifier detector, and agreement for any two raters.

  sheet   write a labelling sheet of real SWE-bench PRs, shown as the detector
          sees them in the study: code change only, no issue, no description,
          comments and docstrings removed. Each annotator fills their column
          with 1 (intent unclear - a reviewer should ask) or 0 (clear enough).

  agree   Cohen's kappa between any two columns of a CSV, plus the confusion
          table. With --to-jsonl, rows both annotators agree on (or that have an
          `adjudicated` value) become the classifier's training file.

Used for two things in this project: the 300-PR labelling pass that trains
detector (b), and validating the LLM judge against both team members.

    python -m experiments.label_tool sheet --n 300
    python -m experiments.label_tool agree runs/labelling_sheet.csv \\
        --a annotator_1 --b annotator_2 --to-jsonl data/labelled_prs.jsonl
    python -m experiments.label_tool agree runs/judge_validation_sample.csv \\
        --a human_intent_recovered --b judge_intent_recovered
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

CODEBOOK = """\
CODEBOOK - label each pull request 1 or 0, independently, without discussing.
You see only the code change. There is no issue text and no description.

1 = UNCLEAR. A careful reviewer would need to ask the author before judging
    whether this change is correct. Typical signs: it removes or weakens a check,
    changes behaviour with no visible reason, could plausibly be either a fix or a
    regression, or alters a public interface without saying why.
0 = CLEAR. The purpose can be read off the code itself with reasonable
    confidence, even if you would still have review comments about it.

Label the INTENT, not the quality. A clear change can still be wrong.
When genuinely torn, choose 1 and say why in your notes column.
"""


def cmd_sheet(args) -> int:
    from datasets import load_dataset

    from .strip import strip_prose_from_diff

    exclude = set()
    for f in args.exclude:
        if Path(f).exists():
            exclude |= {json.loads(l)["pr_id"].split("::")[0]
                        for l in Path(f).read_text().splitlines() if l.strip()}
    rows = [dict(r) for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
            if r["instance_id"] not in exclude]
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    rows = rows[: args.n]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["pr_id", "repo", "code_change", "annotator_1", "annotator_2",
                    "adjudicated", "notes"])
        for r in rows:
            w.writerow([r["instance_id"], r["repo"],
                        strip_prose_from_diff(r["patch"])[:30000], "", "", "", ""])
    Path(out.with_suffix(".codebook.txt")).write_text(CODEBOOK)
    print(f"wrote {len(rows)} PRs to {out}\ncodebook: {out.with_suffix('.codebook.txt')}")
    print(f"excluded {len(exclude)} instances used in the ablation")
    return 0


def kappa(a: list[str], b: list[str]) -> tuple[float, dict]:
    pairs = [(x, y) for x, y in zip(a, b) if x != "" and y != ""]
    n = len(pairs)
    if n == 0:
        return float("nan"), {}
    cats = sorted({x for x, _ in pairs} | {y for _, y in pairs})
    table = {(x, y): sum(1 for p in pairs if p == (x, y)) for x in cats for y in cats}
    po = sum(table[(c, c)] for c in cats) / n
    pe = sum((sum(1 for x, _ in pairs if x == c) / n) * (sum(1 for _, y in pairs if y == c) / n)
             for c in cats)
    k = 1.0 if pe == 1 else (po - pe) / (1 - pe)
    return k, {"n": n, "observed_agreement": round(po, 4), "kappa": round(k, 4),
               "table": {f"{x}|{y}": v for (x, y), v in table.items()}}


def interpret(k: float) -> str:
    # Landis and Koch (1977), the conventional reading of kappa.
    for bound, word in [(0.0, "poor"), (0.2, "slight"), (0.4, "fair"), (0.6, "moderate"),
                        (0.8, "substantial"), (1.01, "almost perfect")]:
        if k < bound:
            return word
    return "almost perfect"


def cmd_agree(args) -> int:
    rows = list(csv.DictReader(open(args.csv, encoding="utf-8")))
    norm = lambda v: str(v).strip().split(".")[0]          # "1.0" -> "1"
    a = [norm(r.get(args.a, "")) for r in rows]
    b = [norm(r.get(args.b, "")) for r in rows]
    k, info = kappa(a, b)
    if not info:
        print("no rows have both columns filled")
        return 1
    print(json.dumps(info, indent=2))
    print(f"Cohen's kappa = {k:.3f} ({interpret(k)} agreement, n={info['n']})")

    if args.to_jsonl:
        from datasets import load_dataset
        patches = {r["instance_id"]: r["patch"]
                   for r in load_dataset("princeton-nlp/SWE-bench_Verified", split="test")}
        kept = 0
        with open(args.to_jsonl, "w", encoding="utf-8") as fh:
            for r, x, y in zip(rows, a, b):
                adj = norm(r.get("adjudicated", ""))
                label = adj if adj in ("0", "1") else (x if x == y and x in ("0", "1") else None)
                if label is None or r["pr_id"] not in patches:
                    continue
                fh.write(json.dumps({
                    "pr_id": r["pr_id"], "repo": r.get("repo", ""),
                    "diff": patches[r["pr_id"]], "title": "", "body": "",
                    "commit_messages": [], "issue_body": "", "label": int(label),
                }) + "\n")
                kept += 1
        print(f"wrote {kept} labelled PRs to {args.to_jsonl} "
              f"(agreed or adjudicated; disagreements without adjudication dropped)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--n", type=int, default=300)
    s.add_argument("--out", default="runs/labelling_sheet.csv")
    s.add_argument("--seed", type=int, default=20261019)
    s.add_argument("--exclude", nargs="*",
                   default=["data/instances.v2.jsonl", "data/archive/instances.pilot.jsonl"])
    s.set_defaults(func=cmd_sheet)
    g = sub.add_parser("agree")
    g.add_argument("csv")
    g.add_argument("--a", required=True)
    g.add_argument("--b", required=True)
    g.add_argument("--to-jsonl")
    g.set_defaults(func=cmd_agree)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
