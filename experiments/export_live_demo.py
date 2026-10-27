"""Export the live GitHub demonstration to a committed snapshot, data/live_demo.json.

The runs live in data/clarifyreview.db, which is gitignored (it also holds personal
experiment logs). This script reads it read-only and writes only the facts the
deliverables quote, so paper/collect.py can cite them without the database.

    python -m experiments.export_live_demo [--pr 1 --pr 2] [--db ...] [--out ...]

For each PR the run exported is the latest run that was answered (else the latest run).
For a PR that also has an unanswered run, that run's intent and confidence are kept as a
"without answer" comparison. Facts that exist only in logs (retries) are read from
runs/bot_live.log when that file is present and left out otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "Praty0512/clarifyreview-sandbox"
DEFAULT_PRS = (1, 2)
BOT_LOG = ROOT / "runs" / "bot_live.log"
MODEL_RE = re.compile(r"/models/([\w.\-]+):generateContent")
ATTEMPT_RE = re.compile(r"Gemini unavailable \(attempt (\d+)/(\d+)\): (\d+)")


def entry_point(condition: str, parked: bool) -> str:
    """The bot parks a run while it waits for the author; the CLI blocks instead."""
    return "webhook_bot" if parked else "cli_post"


def log_models(path: Path) -> list[str]:
    """Distinct model names called, in order of first use, from a provider log."""
    seen: list[str] = []
    for m in MODEL_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def log_facts(path: Path) -> dict:
    """Retry facts that only the bot log records. Empty when the log is absent."""
    if not path.exists():
        return {}
    errs = [m.group(3) for m in ATTEMPT_RE.finditer(path.read_text(encoding="utf-8",
                                                                    errors="replace"))]
    return {"provider_retries": len(errs), "provider_retry_statuses": sorted(set(errs))}


def _run_row(conn, run: sqlite3.Row, parked: bool, models: list[str]) -> dict:
    payload = json.loads(run["payload"] or "{}")
    cl = conn.execute("SELECT * FROM clarifications WHERE run_id=?", (run["id"],)).fetchone()
    findings = [
        {"severity": f["severity"], "category": f["category"], "file": f["file"],
         "line": f["line"], "message": f["claim"], "suggested_fix": f["suggested_fix"]}
        for f in conn.execute("SELECT * FROM findings WHERE run_id=? ORDER BY id", (run["id"],))]
    question_model = next((m for m in models if m != run["model"]), None)
    return {
        "run_id": run["id"],
        "entry_point": entry_point(run["condition"], parked),
        "condition": run["condition"],
        "detector": run["detector"],
        "score": run["ambiguity_score"],
        "threshold": run["threshold"],
        "asked": bool(run["asked"]),
        "answered": bool(run["answered"]),
        "timed_out": bool(run["timed_out"]),
        "question": cl["question"] if cl else None,
        "question_target": cl["target"] if cl else None,
        "answer": cl["answer"] if cl else None,
        "answer_round_trip_s": run["round_trip_s"],
        "verdict": run["verdict"],
        "findings": findings,
        "flagged_defect": bool(run["flagged_defect"]),
        "intent_summary": run["intent_summary"],
        "overall_confidence": run["overall_confidence"],
        "reviewer_model": run["model"],
        "question_model": question_model,
        "created_at": run["created_at"],
        "latency_ms": run["latency_ms"],
        "cost_usd": run["cost_usd"],
        "input_tokens": run["input_tokens"],
        "output_tokens": run["output_tokens"],
        "payload_has_review": "review" in payload,
    }


def export(db: Path, prs=DEFAULT_PRS, bot_log: Path = BOT_LOG,
           pr1_log: Path | None = ROOT / "runs" / "live_review_sandbox_pr1_post.log") -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out_prs = []
    for n in prs:
        pr_id = f"{REPO}#{n}"
        runs = conn.execute("SELECT * FROM runs WHERE pr_id=? AND error IS NULL ORDER BY id",
                            (pr_id,)).fetchall()
        if not runs:
            raise SystemExit(f"no successful run for {pr_id} in {db}")
        answered = [r for r in runs if r["answered"]]
        main = (answered or runs)[-1]
        parked = conn.execute("SELECT 1 FROM parked_runs WHERE pr_id=?", (pr_id,)).fetchone()
        is_bot = bool(parked)
        log = bot_log if is_bot else pr1_log
        models = log_models(log) if log and log.exists() else []
        rec = {"pr_id": pr_id, "pr_number": n, "url": f"https://github.com/{REPO}/pull/{n}",
               "run": _run_row(conn, main, is_bot, models)}
        before = [r for r in runs if not r["answered"] and r["asked"] and r["id"] < main["id"]]
        if before:
            b = before[-1]
            rec["without_answer"] = {
                "run_id": b["id"], "intent_summary": b["intent_summary"],
                "overall_confidence": b["overall_confidence"], "verdict": b["verdict"],
                "timed_out": bool(b["timed_out"])}
        if is_bot:
            facts = log_facts(bot_log)
            deliveries = conn.execute(
                "SELECT event, args_json FROM webhook_deliveries WHERE repo=? AND number=?",
                (REPO, n)).fetchall()
            own = sum(1 for d in deliveries if '"body": "<!-- clarifyreview:' in d["args_json"])
            facts["webhook_deliveries"] = len(deliveries)
            facts["own_comment_deliveries"] = own
            facts["runs_for_pr"] = len(runs)
            rec["facts"] = facts
        out_prs.append(rec)
    conn.close()
    return {"repo": REPO, "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "note": "Demonstration on two constructed PRs in the authors' own sandbox "
                    "repository; not an evaluation.",
            "prs": out_prs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pr", type=int, action="append", help="PR number (repeatable)")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "clarifyreview.db")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "live_demo.json")
    args = ap.parse_args(argv)
    data = export(args.db, tuple(args.pr or DEFAULT_PRS))
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"wrote {args.out}: {len(data['prs'])} PRs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
