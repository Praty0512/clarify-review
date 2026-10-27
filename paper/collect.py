"""Gather every number the paper reports, straight from the experiment outputs.

Nothing in the paper is typed by hand: build_paper.js reads only numbers.json,
and this script reads only the databases and result files. Re-run both after any
new experiment and the paper is current.

    python -m paper.collect && node paper/build_paper.js
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from experiments.analyze import cohens_kappa, gap_recovery, mcnemar
from experiments.external_judge import API_LABEL, compare as compare_judges, judged_copy

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
    finally:
        conn.close()  # an open handle blocks deleting a temporary copy on Windows
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
    conn.close()
    return out


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


_JUDGE_METRICS = ("intent_recovered", "defect_caught", "false_alarm")


def _judge_yes_rates(root: Path) -> dict:
    """Share of the validation sample each side marked 1, per metric.

    Joins every blind human copy to the reference sample (which holds the judge's
    answers) on run_id; only rows a human actually scored count.
    """
    import csv

    ref_path = root / "runs/judge_validation_sample.csv"
    files = sorted((root / "runs/judge_validation").glob("*.csv"))
    if not ref_path.exists() or not files:
        return {}
    with ref_path.open(encoding="utf-8-sig", newline="") as fh:
        ref = {r["run_id"]: r for r in csv.DictReader(fh)}
    out: dict = {}
    for m in _JUDGE_METRICS:
        human, judge = [], []
        for f in files:
            with f.open(encoding="utf-8-sig", newline="") as fh:
                for r in csv.DictReader(fh):
                    h = (r.get(f"human_{m}") or "").strip()
                    j = (ref.get(r.get("run_id"), {}).get(f"judge_{m}") or "").strip()
                    if h in ("0", "1") and j in ("0", "1"):
                        human.append(int(h))
                        judge.append(int(j))
        if human:
            out[m] = {"human_yes_rate": sum(human) / len(human),
                      "judge_yes_rate": sum(judge) / len(judge), "n_pairs": len(human)}
    return out


def human_results(root: Path = ROOT) -> dict:
    """What the human steps produced, read only from their own result files.

    Every section carries "available". It is False whenever the file is missing or
    empty, and build_paper.js then prints exactly what it printed before the human
    steps existed. Nothing here is estimated, defaulted or filled in.

    Keys consumed by build_paper.js:
      labelling:  available, n, kappa, observed_agreement, reading, n_disagree,
                  n_adjudicated, n_written, diff_source
      thresholds: available, values (frozen thresholds), dev_sweep, n_labels, n_ambiguous
      judge_validation: available, scorers, n_scorers,
                  metrics {metric: {n (max over scorers), kappa_mean, kappas, n_per_scorer}},
                  human_vs_judge, human_vs_human
      study_b:    available, participants, usefulness, trust, would_act
    """
    root = Path(root)
    out: dict = {}

    rep = _load_json(root / "runs/labelling_agreement.json")
    if isinstance(rep, dict) and rep.get("n") and rep.get("n_disagree_unadjudicated", 0) == 0:
        out["labelling"] = {"available": True} | {
            k: rep.get(k) for k in ("n", "kappa", "observed_agreement", "reading", "n_rows",
                                    "n_disagree", "n_adjudicated", "n_written", "diff_source")}
        # Who settled the disagreements. When it was not the annotators themselves the
        # paper must say so; the log is written by whoever adjudicated.
        log = _load_json(root / "runs/labelling/adjudication_log.json")
        if isinstance(log, dict) and log.get("adjudicator"):
            out["labelling"]["adjudicated_by"] = log["adjudicator"]
            out["labelling"]["n_adjudicated_by_ai"] = (
                log.get("n_adjudicated") if "AI" in log["adjudicator"] else 0)
    else:
        out["labelling"] = {"available": False}

    sweep = _load_json(root / "runs/threshold_sweep.json")
    frozen = _load_json(root / "data/thresholds.json")
    if isinstance(sweep, dict) and sweep.get("n_labels"):
        out["thresholds"] = {"available": True,
                             "values": sweep.get("thresholds") or frozen,
                             "dev_sweep": sweep.get("dev_sweep"),
                             "n_labels": sweep.get("n_labels"),
                             "n_ambiguous": sweep.get("n_ambiguous"),
                             "train": sweep.get("train"), "dev": sweep.get("dev")}
    else:
        out["thresholds"] = {"available": False}

    ja = _load_json(root / "runs/judge_agreement.json")
    if isinstance(ja, dict) and ja.get("human_vs_judge"):
        metrics = {}
        for m in _JUDGE_METRICS:
            per = [v.get(m) or {} for v in ja["human_vs_judge"].values()]
            per = [d for d in per if d.get("n")]
            if per:
                ks = [d["kappa"] for d in per if d.get("kappa") is not None
                      and not (isinstance(d["kappa"], float) and math.isnan(d["kappa"]))]
                metrics[m] = {"n": max(d["n"] for d in per),
                              "n_per_scorer": [d["n"] for d in per],
                              "kappas": ks,
                              "kappa_mean": (sum(ks) / len(ks)) if ks else None}
        # Mean percent agreement per metric, and how often humans and the judge said
        # "yes" on the same rows: kappa alone misleads when one answer dominates.
        for m in metrics:
            pa = [v.get(m, {}).get("percent_agreement") for v in ja["human_vs_judge"].values()]
            pa = [x for x in pa if x is not None]
            metrics[m]["percent_agreement_mean"] = sum(pa) / len(pa) if pa else None
        rates = _judge_yes_rates(root)
        for m, r in rates.items():
            if m in metrics:
                metrics[m].update(r)
        out["judge_validation"] = {
            "available": bool(metrics), "scorers": ja.get("scorers", []),
            "n_scorers": len(ja.get("scorers", [])), "metrics": metrics,
            "human_vs_judge": ja["human_vs_judge"],
            "human_vs_human": ja.get("human_vs_human", {})}
    else:
        out["judge_validation"] = {"available": False}

    sb = _load_json(root / "runs/study_b_report.json")
    if isinstance(sb, dict) and sb.get("participants") and (sb.get("usefulness") or {}).get("n"):
        out["study_b"] = {"available": True} | {
            k: sb.get(k) for k in ("participants", "usefulness", "trust", "would_act", "ratings")}
    else:
        out["study_b"] = {"available": False}
    return out


# --------------------------------------------------- v3 and judge calibration
#
# Everything below is AI-vs-AI. None of it is a human result and none of it may
# be written to runs/judge_agreement.json or nums["human"]: judgeSentence() in the
# paper builder would then claim human validation.

AGENT_LABEL = "claude-sonnet-agent"
GEMINI_LABEL = "gemini-web"


def study_with_judge(db: Path, label: str) -> dict:
    """study() on a temporary copy of `db` whose judgements are `label`'s scores."""
    if not Path(db).exists():
        return {"available": False}
    with judged_copy(Path(db), label) as tmp:
        return study(tmp)


def _ro_conn(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(db).resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _judge_models(db: Path, label: str) -> list[str]:
    """Model names recorded for a judge label ('api' = the judgements table)."""
    conn = _ro_conn(db)
    try:
        if label == API_LABEL:
            rows = q(conn, "SELECT DISTINCT judge_model m FROM judgements")
        else:
            rows = q(conn, "SELECT DISTINCT judge_model m FROM external_judgements "
                           "WHERE judge_label=?", label)
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()
    return sorted(r["m"] for r in rows if r["m"])


def _one_model(db: Path, label: str) -> str | None:
    ms = _judge_models(db, label)
    return ms[0] if len(ms) == 1 else (" / ".join(ms) if ms else None)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def design_from_instances(path: Path) -> tuple[dict, list[dict]]:
    rows = _read_jsonl(path)
    return {
        "rows": len(rows),
        "arms": dict(Counter(f"{r['arm']}/{r['variant']}" for r in rows)),
        "repos": dict(Counter(r["repo"] for r in rows)),
        "difficulty": dict(Counter(r["difficulty"] for r in rows)),
    }, rows


def v3_design(root: Path, verified_mutants: int | None) -> dict:
    p3, p2 = root / "data/instances.v3.jsonl", root / "data/instances.v2.jsonl"
    if not p3.exists():
        return {"available": False}
    design, rows = design_from_instances(p3)
    ids3 = {r["pr_id"] for r in rows}
    out = {"available": True} | design
    if p2.exists():
        ids2 = {r["pr_id"] for r in _read_jsonl(p2)}
        out["v2_subset"] = ids2 <= ids3
        out["n_new_rows"] = len(ids3 - ids2)
        out["v2_rows"] = len(ids2)
    mut_rows = [r for r in rows if r["variant"] == "mutant"]
    out["mutants_used"] = len(mut_rows)
    out["mutants_verified_total"] = verified_mutants
    out["all_verified_mutants_used"] = (verified_mutants == len(mut_rows)
                                        if verified_mutants is not None else None)
    # golden-only rows: instances whose arm is "golden" (no mutant sibling).
    solo = [r for r in rows if r["arm"] == "golden"]
    out["golden_only_rows"] = len(solo)
    out["golden_only_repos"] = len({r["repo"] for r in solo})
    out["golden_only_repos_not_in_mutants"] = len(
        {r["repo"] for r in solo} - {r["repo"] for r in mut_rows})
    return out


def question_oracle_model(root: Path, v3_ids: set[str], v2_ids: set[str]) -> dict:
    """The question/oracle model is not stored per DB row; runs/oracle_log.jsonl
    records it per answer. Only entries for instances that exist in v3 alone are
    used, so a v2 entry cannot be mistaken for a v3 one."""
    log = root / "runs/oracle_log.jsonl"
    if not log.exists():
        return {"model": None, "n_logged": 0, "per_row_in_db": False}
    models: Counter = Counter()
    for r in _read_jsonl(log):
        if r.get("pr_id") in v3_ids and r.get("pr_id") not in v2_ids:
            models[r.get("model")] += 1
    named = [m for m in models if m]
    return {"model": named[0] if len(named) == 1 else None,
            "models_seen": {str(k): v for k, v in models.items()},
            "n_logged": sum(models.values()), "per_row_in_db": False}


def v3_setup(db: Path, root: Path) -> dict:
    if not Path(db).exists():
        return {"available": False}
    conn = _ro_conn(db)
    try:
        r = q(conn, """SELECT model, detector, threshold, COUNT(*) n,
                              SUM(error IS NOT NULL) failed,
                              MIN(created_at) t0, MAX(created_at) t1
                       FROM runs GROUP BY model, detector, threshold""")
    finally:
        conn.close()
    top = max(r, key=lambda x: x["n"])
    full = top["model"]
    t0 = min(x["t0"] for x in r)
    t1 = max(x["t1"] for x in r)
    inst3 = {x["pr_id"] for x in _read_jsonl(root / "data/instances.v3.jsonl")}
    inst2 = {x["pr_id"] for x in _read_jsonl(root / "data/instances.v2.jsonl")}
    oracle = question_oracle_model(root, inst3, inst2)
    return {
        "available": True,
        "reviewer_model": full,
        "reviewer_model_name": full.split("@")[0] if full else None,
        "single_reviewer_model": len(r) == 1,
        "detector": top["detector"],
        "threshold": top["threshold"],
        "runs": sum(x["n"] for x in r),
        "runs_failed": sum(x["failed"] or 0 for x in r),
        # "<name>@<digest>" is how the Ollama backend records the model it served.
        "backend": "ollama" if full and "@" in full else None,
        "wall_minutes": round((datetime.fromisoformat(t1) - datetime.fromisoformat(t0))
                              .total_seconds() / 60),
        "started": t0, "finished": t1,
        "question_oracle": oracle,
        "question_oracle_model": oracle["model"],
    }


def v2_tokens(db: Path) -> dict:
    if not Path(db).exists():
        return {"available": False}
    conn = _ro_conn(db)
    try:
        r = q(conn, """SELECT COUNT(*) n, SUM(input_tokens) i, SUM(output_tokens) o,
                              SUM(cache_read_tokens) c FROM runs WHERE error IS NULL""")[0]
        asked = q(conn, """SELECT COUNT(*) n, AVG(latency_ms) m FROM runs
                           WHERE error IS NULL AND asked = 1""")[0]
        cond = {x["condition"]: {"input": x["i"], "output": x["o"], "cache_read": x["c"]}
                for x in q(conn, """SELECT condition, SUM(input_tokens) i,
                    SUM(output_tokens) o, SUM(cache_read_tokens) c
                    FROM runs WHERE error IS NULL GROUP BY condition""")}
    finally:
        conn.close()
    return {"available": True, "runs": r["n"], "input": r["i"] or 0, "output": r["o"] or 0,
            "cache_read": r["c"] or 0, "by_condition": cond,
            "asked_runs": asked["n"],
            "asked_mean_latency_s": round(asked["m"] / 1000, 1) if asked["m"] else None}


def _pair(db: Path, a: str, b: str) -> dict:
    res = compare_judges(Path(db), a, b)
    return {"a": a, "b": b, "n_shared_runs": res["n_shared_runs"]} | dict(res["fields"])


def three_way_intent(db: Path, labels: tuple[str, str, str]) -> dict:
    """Runs scored by all three judges, and how many of them they agree on (intent)."""
    from experiments.external_judge import load_judge

    conn = _ro_conn(db)
    try:
        sets = [load_judge(conn, lab)[0] for lab in labels]
    finally:
        conn.close()
    shared = sorted(set.intersection(*[set(s) for s in sets]))
    agree = sum(1 for i in shared
                if len({int(s[i]["intent_recovered"]) for s in sets}) == 1)
    return {"n": len(shared), "all_agree": agree}


def judges_block(root: Path) -> dict:
    v2x = root / "data/study_v2_external.db"
    v3 = root / "data/study_v3_ollama.db"
    out: dict = {"available": v2x.exists() and v3.exists()}
    if not out["available"]:
        return out
    out["models"] = {"api_v2": _one_model(v2x, API_LABEL),
                     "agent": _one_model(v2x, AGENT_LABEL),
                     "gemini_web": _one_model(v2x, GEMINI_LABEL),
                     "api_v3": _one_model(v3, API_LABEL)}
    out["v2_pairs"] = {"api_vs_agent": _pair(v2x, API_LABEL, AGENT_LABEL),
                       "gemini_vs_agent": _pair(v2x, GEMINI_LABEL, AGENT_LABEL),
                       "gemini_vs_api": _pair(v2x, GEMINI_LABEL, API_LABEL)}
    out["v2_three_way_intent"] = three_way_intent(v2x, (API_LABEL, AGENT_LABEL, GEMINI_LABEL))
    # The Gemini web app judged a stratified sample, not every run.
    out["gemini_sample"] = {"n": out["v2_pairs"]["gemini_vs_agent"]["n_shared_runs"],
                            "stratified_by": "condition,variant"}
    out["v3_pairs"] = {"llama_vs_agent": _pair(v3, API_LABEL, AGENT_LABEL)}
    return out


def realpr_block(root: Path) -> dict:
    sheet = root / "runs/realpr/labelling_sheet.csv"
    if not sheet.exists():
        return {"available": False}
    with open(sheet, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    first_lang = Counter((r.get("languages") or "").split(",")[0] or "unknown" for r in rows)
    return {"available": True, "n_prs": len(rows),
            "n_repos": len({r["repo"] for r in rows}),
            "languages": dict(first_lang.most_common()),
            "n_labelled": sum(1 for r in rows if (r.get("adjudicated") or "").strip()),
            "n_annotated": sum(1 for r in rows if (r.get("annotator_1") or "").strip()
                               or (r.get("annotator_2") or "").strip())}


def v3_local_block(root: Path) -> dict:
    db = root / "data/study_v3_ollama.db"
    if not db.exists():
        return {"available": False}
    out = study_with_judge(db, AGENT_LABEL)
    out["judge_label"] = AGENT_LABEL
    out["judge_model"] = _one_model(db, AGENT_LABEL)
    return out


def v3_gemini_block(root: Path) -> dict:
    """The v3 study set (96 rows, every verified mutant) on the main reviewer.

    Same reviewer, question, oracle and judge models as v2, so it is the v2
    design at the full v3 size rather than a second-model replication. Only
    complete triples enter the paired tests, as everywhere else.
    """
    db = root / "data/study_v3_gemini.db"
    if not db.exists():
        return {"available": False}
    out = study(db)
    conn = _ro_conn(db)
    try:
        out["review_models"] = sorted(r["m"] for r in q(
            conn, "SELECT DISTINCT model m FROM runs WHERE error IS NULL") if r["m"])
        # Where the detector did not ask, floor and treatment saw identical input, so any
        # disagreement between them is the reviewer's run-to-run variation, not clarification.
        rows = q(conn, """
            WITH f AS (SELECT r.pr_id, j.intent_recovered ir FROM runs r JOIN judgements j
                       ON j.run_id=r.id WHERE r.condition='stripped_plain' AND r.error IS NULL),
                 t AS (SELECT r.pr_id, j.intent_recovered ir, r.asked, r.answered FROM runs r
                       JOIN judgements j ON j.run_id=r.id
                       WHERE r.condition='stripped_clarify' AND r.error IS NULL)
            SELECT t.asked, t.answered, t.ir > f.ir better FROM f JOIN t USING(pr_id)
            WHERE f.ir <> t.ir""")
        out["discordant"] = {
            "total": len(rows),
            "not_asked": sum(1 for r in rows if not r["asked"]),
            "not_asked_treatment_better": sum(1 for r in rows if not r["asked"] and r["better"]),
            "not_asked_floor_better": sum(1 for r in rows if not r["asked"] and not r["better"]),
            "asked_treatment_better": sum(1 for r in rows if r["asked"] and r["better"]),
            "asked_floor_better": sum(1 for r in rows if r["asked"] and not r["better"]),
        }
        out["not_asked_pairs"] = q(conn, """
            SELECT COUNT(*) n FROM runs t WHERE t.condition='stripped_clarify' AND t.error IS NULL
            AND t.asked=0 AND EXISTS (SELECT 1 FROM runs f WHERE f.pr_id=t.pr_id
            AND f.condition='stripped_plain' AND f.error IS NULL)""")[0]["n"]
    finally:
        conn.close()
    out["judge_model"] = _one_model(db, API_LABEL)
    return out


def v3_llama_judge_block(root: Path) -> dict:
    """Reference only: the v3 run scored by its own (llama3.2:3b) judge."""
    db = root / "data/study_v3_ollama.db"
    if not db.exists():
        return {"available": False}
    out = study(db)
    out["judge_model"] = _one_model(db, API_LABEL)
    conn = _ro_conn(db)
    try:
        out["false_alarm_total"] = q(
            conn, "SELECT COALESCE(SUM(false_alarm),0) n FROM judgements")[0]["n"]
        k = q(conn, """SELECT COUNT(*) n, SUM(j.defect_reason LIKE 'No defect was injected%') k
                       FROM judgements j JOIN runs r ON r.id=j.run_id
                       JOIN instances i ON i.pr_id=r.pr_id WHERE i.variant='mutant'""")[0]
        out["no_defect_claim_mutant"] = {"n": k["n"], "k": k["k"] or 0}
    finally:
        conn.close()
    return out


def tests_by_file(root: Path) -> dict:
    res = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=root,
                         capture_output=True, text=True)
    counts: Counter = Counter()
    for line in res.stdout.splitlines():
        m = re.match(r"^(tests/[^:]+\.py)::", line.replace("\\", "/"))
        if m:
            counts[m.group(1)] += 1
    return dict(sorted(counts.items()))


def live_demo_block(root: Path) -> dict:
    """The live GitHub demonstration (two constructed PRs in the authors' sandbox repo),
    read from the committed snapshot data/live_demo.json. A demonstration, not a study:
    nothing here enters a study table or a test."""
    path = root / "data/live_demo.json"
    if not path.exists():
        return {"available": False}
    raw = json.loads(path.read_text(encoding="utf-8"))
    runs = [pr["run"] for pr in raw["prs"]]
    out: dict = {"available": True, "repo": raw["repo"], "n_prs": len(runs),
                 "n_asked": sum(r["asked"] for r in runs),
                 "n_answered": sum(r["answered"] for r in runs),
                 "n_timed_out": sum(r["timed_out"] for r in runs),
                 "n_defects_flagged": sum(r["flagged_defect"] for r in runs),
                 "n_request_changes": sum(r["verdict"] == "request_changes" for r in runs),
                 "n_approve": sum(r["verdict"] == "approve" for r in runs),
                 "n_findings": sum(len(r["findings"]) for r in runs),
                 "n_entry_points": len({r["entry_point"] for r in runs}),
                 "total_cost_usd": round(sum(r["cost_usd"] for r in runs), 4)}
    for pr in raw["prs"]:
        r = pr["run"]
        d = {"url": pr["url"], "entry_point": r["entry_point"], "detector": r["detector"],
             "score": r["score"], "threshold": r["threshold"], "asked": r["asked"],
             "answered": r["answered"], "answer_round_trip_s": r["answer_round_trip_s"],
             "verdict": r["verdict"], "n_findings": len(r["findings"]),
             "flagged_defect": r["flagged_defect"], "intent_summary": r["intent_summary"],
             "overall_confidence": r["overall_confidence"], "reviewer_model": r["reviewer_model"],
             "question_model": r["question_model"], "latency_s": round(r["latency_ms"] / 1000, 1),
             "cost_usd": r["cost_usd"], "question": r["question"], "answer": r["answer"]}
        if r["findings"]:
            f = r["findings"][0]
            d.update(finding_severity=f["severity"], finding_category=f["category"],
                     finding_file=f["file"], finding_line=f["line"])
        wa = pr.get("without_answer")
        if wa:
            d["without_answer"] = {"intent_summary": wa["intent_summary"],
                                   "overall_confidence": wa["overall_confidence"],
                                   "verdict": wa["verdict"]}
            d["confidence_gain_points"] = round(
                (r["overall_confidence"] - wa["overall_confidence"]) * 100)
        if pr.get("facts"):
            d["facts"] = pr["facts"]
        out[f"pr{pr['pr_number']}"] = d
    return out


def derived_block(nums: dict) -> dict:
    """Counts and small arithmetic the builders and the prose need, computed once.

    Nothing here is measured afresh; every value is a function of keys already in
    `nums`, so a builder never has to do arithmetic on a number it prints.
    """
    d: dict = {}
    for study in ("v2", "v2_agent_judge", "v3_local", "v3_local_llama_judge"):
        tests = (nums.get(study) or {}).get("tests") or {}
        d[study] = {}
        for label, t in tests.items():
            n = t["n"]
            ceil, floor = t["ceiling"], t["floor"]
            d[study][label] = {
                "n": n,
                "floor_k": round(floor * n), "treatment_k": round(t["treatment"] * n),
                "ceiling_k": round(ceil * n),
                "gap_points": round((ceil - floor) * 100),
                "treatment_points": round((t["treatment"] - floor) * 100),
                "discordant_total": t["discordant_treatment_better"] + t["discordant_floor_better"],
            }
    v2d = d["v2"].get("defect_mutant")
    if v2d:
        d["v2_defect_max_caught"] = max(v2d["floor_k"], v2d["treatment_k"], v2d["ceiling_k"])
        d["v2_defect_ceiling_missed"] = v2d["n"] - v2d["ceiling_k"]
    det = nums.get("detectors") or {}
    unc = [det[k] for k in ("sampling", "perturbation") if k in det]
    if unc:
        d["uncertainty_instances"] = unc[0]["n_decisions"] // 2
        d["uncertainty_s_min"] = round(min(u["mean_ms"] for u in unc) / 1000)
        d["uncertainty_s_max"] = round(max(u["mean_ms"] for u in unc) / 1000)
    m = re.match(r"(\d+) passed(?:, (\d+) skipped)?(?: .*?in ([\d.]+)s)?", nums.get("tests_passing", ""))
    if m:
        d["tests_passed"] = int(m.group(1))
        d["tests_skipped"] = int(m.group(2) or 0)
        d["tests_seconds"] = round(float(m.group(3))) if m.group(3) else None
    asked_s = (nums.get("v2_tokens") or {}).get("asked_mean_latency_s")
    if asked_s:
        d["v2_asked_latency_minutes"] = round(asked_s / 60)
    llama = nums.get("v3_local_llama_judge") or {}
    k = llama.get("no_defect_claim_mutant")
    if k and k["n"]:
        d["llama_no_defect_claim_pct"] = round(100 * k["k"] / k["n"])
    f = (nums.get("v3_local") or {}).get("funnel")
    if f:
        d["v3_asked_on_understood"] = f["asked_total"] - f["detector_asked"]
        d["v3_detector_missed"] = f["floor_misses"] - f["detector_asked"]
    f2_ = (nums.get("v2") or {}).get("funnel")
    if f2_:
        d["v2_asked_on_understood"] = f2_["asked_total"] - f2_["detector_asked"]
    return d


def _clean(x):
    # NaN is how an undefined gap recovery comes out of the analysis (the pilot's
    # floor equalled its ceiling). It is not valid JSON, so it becomes null and the
    # paper prints "n/a" rather than a number that does not exist.
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def acceptance(nums: dict, root: Path = ROOT) -> list[str]:
    """Assertions that pin the new blocks to the reports already on disk.

    Raises AssertionError listing every failure. Run on every collect so a change
    to the judge/DB plumbing cannot silently shift a published number.
    """
    fails: list[str] = []

    def check(name, got, want):
        ok = (abs(got - want) <= 1e-9) if isinstance(want, float) and isinstance(got, (int, float))             else got == want
        if not ok:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    def near(name, got, want, tol=5e-4):
        if got is None or abs(got - want) > tol:
            fails.append(f"{name}: got {got!r}, want {want!r}")

    t = nums["v3_local"]["tests"]
    ia = t["intent_all"]
    near("v3 floor", ia["floor"], 0.667); near("v3 treatment", ia["treatment"], 0.698)
    near("v3 ceiling", ia["ceiling"], 1.0); near("v3 gap", ia["gap_recovery"], 0.09, 0.005)
    near("v3 ci_low", ia["gap_ci"][0], -0.22, 0.005); near("v3 ci_high", ia["gap_ci"][1], 0.33, 0.005)
    near("v3 p", ia["mcnemar_p"], 0.664, 0.0005)
    check("v3 discordant treatment/floor", (ia["discordant_treatment_better"],
                                            ia["discordant_floor_better"]), (12, 9))
    dm = t["defect_mutant"]
    check("v3 defect n", dm["n"], 32)
    check("v3 defect caught floor/treatment/ceiling",
          tuple(round(dm[k] * dm["n"]) for k in ("floor", "treatment", "ceiling")), (1, 2, 3))
    fa = t["false_alarm_golden"]
    check("v3 false alarm n", fa["n"], 64); near("v3 false alarm p", fa["mcnemar_p"], 0.5)
    check("v3 treatment asks", (nums["v3_local"]["treatment_asks"],
                                nums["v3_local"]["treatment_n"]), (17, 96))

    a = nums["v2_agent_judge"]["tests"]["intent_all"]
    near("v2 agent floor", a["floor"], 0.861); near("v2 agent treatment", a["treatment"], 0.917)
    near("v2 agent ceiling", a["ceiling"], 1.0); near("v2 agent G", a["gap_recovery"], 0.40, 0.005)
    near("v2 agent ci_low", a["gap_ci"][0], -0.75, 0.005); near("v2 agent ci_high", a["gap_ci"][1], 1.0, 0.005)
    near("v2 agent p", a["mcnemar_p"], 0.625, 0.0005)

    # The independent report written by experiments.external_judge must agree.
    rep_path = root / "runs/study_a_report_v3_ollama_claude_judge.json"
    if rep_path.exists():
        rep = json.loads(rep_path.read_text(encoding="utf-8"))
        g = rep["intent_recovery"]["gap_recovery"]
        near("v3 report floor", ia["floor"], g["floor_rate"], 5e-5)
        near("v3 report treatment", ia["treatment"], g["treatment_rate"], 5e-5)
        near("v3 report G", ia["gap_recovery"], g["gap_recovery"], 5e-5)
        near("v3 report ci", ia["gap_ci"][1], g["ci_high"], 5e-5)
        near("v3 report p", ia["mcnemar_p"], rep["intent_recovery"]["primary_mcnemar_floor_vs_treatment"]["p_value"], 5e-5)
        check("v3 report defect n", dm["n"], rep["defect_detection_mutants"]["n"])
        check("v3 report false alarm n", fa["n"], rep["false_alarms_golden"]["n"])

    jd = nums["judges"]
    check("three-way intent", (jd["v2_three_way_intent"]["all_agree"], jd["v2_three_way_intent"]["n"]), (25, 30))
    lv = jd["v3_pairs"]["llama_vs_agent"]
    check("llama-vs-agent kappa", tuple(round(lv[m]["kappa"], 2) for m in
                                        ("intent_recovered", "defect_caught", "false_alarm")), (0.20, 0.06, 0.0))
    check("realpr labelled", nums["realpr"]["n_labelled"], 0)
    check("v3 subset of v2", nums["v3_design"]["v2_subset"], True)
    check("v3 mutants == verified", nums["v3_design"]["mutants_used"], nums["mutants"]["by_status"]["verified"])
    check("v3 runs failed", nums["v3_setup"]["runs_failed"], 0)
    check("tests_by_file sums to collected tests", sum(nums["tests_by_file"].values()) > 0, True)

    # No AI-vs-AI result may be passed off as a human one.
    if not (root / "runs/judge_agreement.json").exists():
        check("human.judge_validation.available", nums["human"]["judge_validation"]["available"], False)
    for k, v in nums["human"].items():
        if not (root / {"labelling": "runs/labelling_agreement.json",
                        "thresholds": "runs/threshold_sweep.json",
                        "judge_validation": "runs/judge_agreement.json",
                        "study_b": "runs/study_b_report.json"}[k]).exists():
            check(f"human.{k}.available", v["available"], False)
    ld = nums.get("live_demo") or {}
    if ld.get("available"):
        check("live_demo.n_prs", ld["n_prs"], 2)
        check("live_demo.n_asked", ld["n_asked"], 2)
        check("live_demo.n_answered", ld["n_answered"], 2)
        check("live_demo.n_defects_flagged", ld["n_defects_flagged"], 1)
        check("live_demo.pr1 verdict", ld["pr1"]["verdict"], "approve")
        check("live_demo.pr1 findings", ld["pr1"]["n_findings"], 0)
        check("live_demo.pr1 intent mentions phone", "phone" in ld["pr1"]["intent_summary"], True)
        near("live_demo.pr1 confidence before", ld["pr1"]["without_answer"]["overall_confidence"], 0.8)
        near("live_demo.pr1 confidence after", ld["pr1"]["overall_confidence"], 1.0)
        near("live_demo.pr1 score", ld["pr1"]["score"], 0.8889)
        check("live_demo.pr2 verdict", ld["pr2"]["verdict"], "request_changes")
        check("live_demo.pr2 findings", ld["pr2"]["n_findings"], 1)
        check("live_demo.pr2 severity", ld["pr2"]["finding_severity"], "major")
        check("live_demo.pr2 entry point", ld["pr2"]["entry_point"], "webhook_bot")
        near("live_demo.pr2 score", ld["pr2"]["score"], 0.8889)
    if fails:
        raise AssertionError("acceptance failed:\n  " + "\n  ".join(fails))
    return []


def main(root: Path = ROOT, check: bool = True) -> int:
    root = Path(root)
    nums: dict = {}
    nums["pilot"] = study(root / "data/archive/pilot_2026-09-02.db")
    nums["v2"] = study(root / "data/study_v2.db")

    mut = [json.loads(l) for l in (root / "data/mutants.verified.jsonl").read_text(encoding="utf-8").splitlines() if l]
    nums["mutants"] = {"attempted": len(mut), "by_status": dict(Counter(m["status"] for m in mut)),
                       "operators": dict(Counter(m["mutation_op"] for m in mut if m["status"] == "verified"))}

    inst_v2 = root / "data/instances.v2.jsonl"
    if inst_v2.exists():
        nums["v2_design"] = design_from_instances(inst_v2)[0]
    det = {}
    for f in sorted((root / "runs").glob("detector_comparison*.json")):
        for name, d in json.loads(f.read_text(encoding="utf-8"))["detectors"].items():
            det[name] = {k: v for k, v in d.items() if k != "decisions"}
    nums["detectors"] = det

    tests = list(root.glob("tests/test_*.py"))
    # sys.executable: the interpreter running this script is the project's own
    # environment on every platform (there is no .venv/bin on Windows).
    res = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root,
                         capture_output=True, text=True)
    nums["tests_passing"] = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "?"
    nums["loc"] = {
        "src": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in (root / "src").rglob("*.py")),
        "experiments": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in (root / "experiments").glob("*.py")),
        "tests": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in tests),
    }
    nums["test_files"] = len(tests)
    nums["tests_by_file"] = tests_by_file(root)
    nums["human"] = human_results(root)

    # Second-model replication and judge calibration (AI-vs-AI, never "human").
    nums["v3_local"] = v3_local_block(root)
    nums["v3_local_llama_judge"] = v3_llama_judge_block(root)
    nums["v3_gemini"] = v3_gemini_block(root)
    nums["v3_design"] = v3_design(root, nums["mutants"]["by_status"].get("verified"))
    nums["v3_setup"] = v3_setup(root / "data/study_v3_ollama.db", root)
    nums["v2_agent_judge"] = study_with_judge(root / "data/study_v2_external.db", AGENT_LABEL)
    nums["judges"] = judges_block(root)
    nums["realpr"] = realpr_block(root)
    nums["v2_tokens"] = v2_tokens(root / "data/study_v2.db")
    nums["live_demo"] = live_demo_block(root)
    nums["derived"] = derived_block(nums)
    out = root / "paper/numbers.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_clean(nums), indent=2, default=str, allow_nan=False),
                   encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    print(json.dumps({k: nums[k] for k in ("mutants", "tests_passing", "test_files", "loc")}, indent=2))
    for k in ("v3_setup", "v3_design", "judges", "realpr", "v2_tokens"):
        print(k, json.dumps(nums[k], default=str)[:700])
    for k in ("v3_local", "v2_agent_judge"):
        t = (nums[k].get("tests") or {}).get("intent_all", {})
        print(k, "intent_all", {x: t.get(x) for x in
                                ("n", "floor", "treatment", "ceiling", "gap_recovery",
                                 "gap_ci", "mcnemar_p")})
    if check and nums["v3_local"].get("available") and nums["judges"].get("available"):
        acceptance(_clean(nums), root)
        print("acceptance: all asserts passed")
    return 0


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Collect every number the deliverables report.")
    ap.add_argument("--no-check", action="store_true", help="skip the acceptance asserts")
    ns = ap.parse_args()
    raise SystemExit(main(check=not ns.no_check))
