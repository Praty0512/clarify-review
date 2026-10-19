"""Build the Study B page: a blind, paired comparison of two reviews per PR.

For each selected pull request the participant sees the issue, the code change,
and two reviews labelled only "A" and "B" - one from the single-pass reviewer,
one from ClarifyReview including any question it asked and the answer it got.
They rate usefulness and trust (1-5), say whether they would act on it, and why.

The page is a single static HTML file. Responses never leave the participant's
machine until they press "Download responses" and send the CSV back. No answer
key is embedded: A/B assignment is recomputed from the participant id.

    python -m study.build_study --db data/study_v2.db --n 16
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent


def review_block(payload: dict) -> dict:
    review = payload.get("review") or {}
    clar = payload.get("clarification")
    exchange = None
    if clar:
        exchange = {
            "questions": [q["question"] for q in clar["questions"]["questions"]],
            "answer": clar.get("answer") or "(no answer received)",
        }
    return {
        "summary": review.get("intent_summary", ""),
        "verdict": review.get("verdict", ""),
        "findings": [
            {"sev": f["severity"], "cat": f["category"], "where": f"{f['file']}:{f.get('line') or ''}",
             "claim": f["claim"], "fix": f["suggested_fix"]}
            for f in review.get("findings", [])
        ],
        "exchange": exchange,
    }


def select_items(db_path: Path, n: int) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pairs = conn.execute("""
        SELECT p.pr_id, i.problem_statement, i.variant, p.payload AS plain, c.payload AS clarify
        FROM runs p
        JOIN runs c ON c.pr_id = p.pr_id AND c.condition = 'stripped_clarify' AND c.error IS NULL
        JOIN instances i ON i.pr_id = p.pr_id
        WHERE p.condition = 'stripped_plain' AND p.error IS NULL
        ORDER BY p.pr_id
    """).fetchall()
    # Prefer items where ClarifyReview actually asked, since those are the ones
    # where the two reviews can differ; fill the rest with the others.
    asked = [r for r in pairs if json.loads(r["clarify"]).get("clarification")]
    rest = [r for r in pairs if not json.loads(r["clarify"]).get("clarification")]
    chosen = (asked + rest)[:n]
    items = []
    for r in chosen:
        plain, clar = json.loads(r["plain"]), json.loads(r["clarify"])
        items.append({
            "id": r["pr_id"],
            "issue": (r["problem_statement"] or "")[:1500],
            "diff": json.loads(r["clarify"]).get("context_diff") or "",
            "plain": review_block(plain),
            "clarify": review_block(clar),
        })
    return items


def attach_diffs(items: list[dict], instances_path: Path) -> None:
    if not instances_path.exists():
        return
    diffs = {}
    for line in instances_path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            diffs[row["pr_id"]] = row["diff"]
    for it in items:
        it["diff"] = diffs.get(it["id"], it["diff"])[:6000]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/study_v2.db")
    ap.add_argument("--instances", default="data/instances.v2.jsonl")
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--out", default="study/study.html")
    args = ap.parse_args(argv)

    items = select_items(Path(args.db), args.n)
    attach_diffs(items, Path(args.instances))
    if not items:
        print("no complete stripped_plain/stripped_clarify pairs in", args.db)
        return 1
    page = (HERE / "template.html").read_text()
    page = page.replace("/*ITEMS*/[]", json.dumps(items))
    Path(args.out).write_text(page)
    print(f"wrote {args.out} with {len(items)} items "
          f"({sum(1 for i in items if i['clarify']['exchange'])} where a question was asked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
