"""Gather every number the paper reports, straight from the experiment outputs.

Nothing in the paper is typed by hand: build_paper.js reads only numbers.json,
and this script reads only the databases and result files. Re-run both after any
new experiment and the paper is current.

    python -m paper.collect && node paper/build_paper.js
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from experiments.analyze import cohens_kappa, gap_recovery, mcnemar

ROOT = Path(__file__).resolve().parents[1]


def q(conn, sql, *a):
    return conn.execute(sql, a).fetchall()


def arm_outcomes(db: Path, variant_filter: str | None, metric: str) -> dict:
    """Complete triples only, keyed by instance, for one judged metric."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    where = "AND i.variant = ?" if variant_filter else ""
    args = (variant_filter,) if variant_filter else ()
    try:
        rows = q(conn, f"""
            SELECT r.pr_id, r.condition, j.{metric} v FROM runs r
            JOIN judgements j ON j.run_id = r.id JOIN instances i ON i.pr_id = r.pr_id
            WHERE r.error IS NULL {where}""", *args)
    except sqlite3.OperationalError:
        return {}
    by: dict[str, dict] = {}
    for r in rows:
        by.setdefault(r["pr_id"], {})[r["condition"]] = int(r["v"] or 0)
    full = {k: v for k, v in by.items() if len(v) == 3}
    keys = sorted(full)
    return {c: [full[k][c] for k in keys] for c in ("full_plain", "stripped_plain", "stripped_clarify")} | {"n": len(keys)}


def study(db: Path) -> dict:
    if not db.exists():
        return {"available": False}
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out: dict = {"available": True}
    out["attempted"] = q(conn, "SELECT COUNT(DISTINCT pr_id) n FROM instances")[0]["n"] or \
        q(conn, "SELECT COUNT(DISTINCT pr_id) n FROM runs")[0]["n"]
    out["runs_ok"] = q(conn, "SELECT COUNT(*) n FROM runs WHERE error IS NULL")[0]["n"]
    out["runs_failed"] = q(conn, "SELECT COUNT(*) n FROM runs WHERE error IS NOT NULL")[0]["n"]
    out["complete_triples"] = len(q(conn, "SELECT pr_id FROM runs WHERE error IS NULL "
                                          "GROUP BY pr_id HAVING COUNT(DISTINCT condition)=3"))
    try:
        out["judged"] = q(conn, "SELECT COUNT(*) n FROM judgements")[0]["n"]
    except sqlite3.OperationalError:
        out["judged"] = 0

    per_cond = {}
    for c in ("full_plain", "stripped_plain", "stripped_clarify"):
        try:
            r = q(conn, """SELECT COUNT(*) n, SUM(j.intent_recovered) ir, SUM(j.false_alarm) fa,
                                  SUM(j.defect_caught) dc, AVG(r.latency_ms) ms,
                                  AVG(r.overall_confidence) conf
                           FROM runs r JOIN judgements j ON j.run_id=r.id
                           WHERE r.condition=? AND r.error IS NULL""", c)[0]
            per_cond[c] = {k: (round(r[k], 3) if isinstance(r[k], float) else r[k])
                           for k in r.keys()}
        except sqlite3.OperationalError:
            pass
    out["per_condition"] = per_cond

    ask = q(conn, """SELECT COUNT(*) n, SUM(ask) a FROM runs
                     WHERE condition='stripped_clarify' AND error IS NULL AND ask IS NOT NULL""")[0]
    out["treatment_ask_rate"] = round((ask["a"] or 0) / ask["n"], 4) if ask["n"] else None
    out["treatment_asks"] = ask["a"] or 0
    out["treatment_n"] = ask["n"]
    # Asking is not the same as being answered: an oracle refusal or an empty
    # reply leaves the treatment with no more intent than the floor had.
    out["treatment_answered"] = q(conn, """SELECT COUNT(*) n FROM runs
        WHERE condition='stripped_clarify' AND error IS NULL AND answered=1""")[0]["n"]
    out["treatment_refused"] = q(conn, """SELECT COUNT(*) n FROM clarifications
        WHERE answer LIKE 'I''m not sure%'""")[0]["n"] if out["treatment_asks"] else 0
    try:
        qs = q(conn, """SELECT c.question, c.answer, r.pr_id FROM clarifications c
                        JOIN runs r ON r.id=c.run_id""")
        out["questions"] = [dict(x) for x in qs]
    except sqlite3.OperationalError:
        out["questions"] = []

    # Where the effect can come from. The treatment can only beat the floor on an
    # instance the floor got wrong, the detector flagged, and the author answered;
    # counting each step shows which one limits the result.
    try:
        rows = q(conn, """
            SELECT r.pr_id, r.condition, r.asked, j.intent_recovered ir,
                   (SELECT c.answer FROM clarifications c WHERE c.run_id = r.id LIMIT 1) ans
            FROM runs r JOIN judgements j ON j.run_id = r.id WHERE r.error IS NULL""")
        by: dict = {}
        for r in rows:
            by.setdefault(r["pr_id"], {})[r["condition"]] = dict(r)
        trip = {k: v for k, v in by.items() if len(v) == 3}
        misses = [k for k, v in trip.items() if not v["stripped_plain"]["ir"]]
        asked_on = [k for k in misses if trip[k]["stripped_clarify"]["asked"]]

        def substantive(a):
            return bool(a) and not a.startswith("I'm not sure")

        answered_on = [k for k in asked_on if substantive(trip[k]["stripped_clarify"]["ans"])]
        recovered = [k for k in answered_on if trip[k]["stripped_clarify"]["ir"]]
        out["funnel"] = {
            "floor_misses": len(misses),
            "ceiling_also_missed": sum(1 for k in misses if not trip[k]["full_plain"]["ir"]),
            "detector_asked": len(asked_on),
            "author_answered": len(answered_on),
            "treatment_recovered": len(recovered),
            "missed_ids": sorted(misses),
            "recovered_ids": sorted(recovered),
            "asked_total": sum(1 for v in trip.values() if v["stripped_clarify"]["asked"]),
            "answered_total": sum(1 for v in trip.values()
                                  if substantive(v["stripped_clarify"]["ans"])),
        }
    except sqlite3.OperationalError:
        out["funnel"] = {}

    tests = {}
    for label, variant, metric in [("intent_all", None, "intent_recovered"),
                                   ("intent_golden", "golden", "intent_recovered"),
                                   ("intent_mutant", "mutant", "intent_recovered"),
                                   ("defect_mutant", "mutant", "defect_caught"),
                                   ("false_alarm_golden", "golden", "false_alarm")]:
        d = arm_outcomes(db, variant, metric)
        if d and d.get("n", 0) >= 2:
            m = mcnemar(d["stripped_plain"], d["stripped_clarify"])
            g = gap_recovery(d["stripped_plain"], d["stripped_clarify"], d["full_plain"])
            tests[label] = {
                "n": d["n"],
                "ceiling": g["ceiling_rate"], "floor": g["floor_rate"], "treatment": g["treatment_rate"],
                "gap_recovery": g["gap_recovery"], "gap_ci": [g["ci_low"], g["ci_high"]],
                "mcnemar_p": m.p_value, "discordant_treatment_better": m.b_only,
                "discordant_floor_better": m.a_only,
                "diff": m.difference, "diff_ci": [m.ci_low, m.ci_high],
            }
    out["tests"] = tests
    return out


def main() -> int:
    nums: dict = {}
    nums["pilot"] = study(ROOT / "data/archive/pilot_2026-09-02.db")
    nums["v2"] = study(ROOT / "data/study_v2.db")

    mut = [json.loads(l) for l in (ROOT / "data/mutants.verified.jsonl").read_text().splitlines() if l]
    nums["mutants"] = {"attempted": len(mut), "by_status": dict(Counter(m["status"] for m in mut)),
                       "operators": dict(Counter(m["mutation_op"] for m in mut if m["status"] == "verified"))}

    inst_v2 = ROOT / "data/instances.v2.jsonl"
    if inst_v2.exists():
        rows = [json.loads(l) for l in inst_v2.read_text().splitlines() if l]
        nums["v2_design"] = {
            "rows": len(rows),
            "arms": dict(Counter(f"{r['arm']}/{r['variant']}" for r in rows)),
            "repos": dict(Counter(r["repo"] for r in rows)),
            "difficulty": dict(Counter(r["difficulty"] for r in rows)),
        }
    det = {}
    for f in sorted((ROOT / "runs").glob("detector_comparison*.json")):
        for name, d in json.loads(f.read_text())["detectors"].items():
            det[name] = {k: v for k, v in d.items() if k != "decisions"}
    nums["detectors"] = det

    tests = list(ROOT.glob("tests/test_*.py"))
    import subprocess
    res = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "pytest", "-q"], cwd=ROOT,
                         capture_output=True, text=True)
    nums["tests_passing"] = res.stdout.strip().splitlines()[-1] if res.stdout else "?"
    nums["loc"] = {
        "src": sum(len(p.read_text().splitlines()) for p in (ROOT / "src").rglob("*.py")),
        "experiments": sum(len(p.read_text().splitlines()) for p in (ROOT / "experiments").glob("*.py")),
        "tests": sum(len(p.read_text().splitlines()) for p in tests),
    }
    out = ROOT / "paper/numbers.json"
    # NaN is how an undefined gap recovery comes out of the analysis (the pilot's
    # floor equalled its ceiling). It is not valid JSON, so it becomes null and the
    # paper prints "n/a" rather than a number that does not exist.
    import math

    def clean(x):
        if isinstance(x, float) and math.isnan(x):
            return None
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items()}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x

    out.write_text(json.dumps(clean(nums), indent=2, default=str, allow_nan=False))
    print(f"wrote {out}")
    print(json.dumps({k: nums[k] for k in ("mutants", "tests_passing", "loc")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
