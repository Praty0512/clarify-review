from __future__ import annotations

import csv
import json
import sqlite3

from clarifyreview.store import db as store
from experiments import external_judge as ej
from experiments.analyze import (
    CONDITION_FULL_PLAIN,
    CONDITION_STRIPPED_CLARIFY,
    CONDITION_STRIPPED_PLAIN,
)

CONDS = [CONDITION_FULL_PLAIN, CONDITION_STRIPPED_PLAIN, CONDITION_STRIPPED_CLARIFY]


def _db(path, n=4):
    store.init(path)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE judgements (run_id INTEGER PRIMARY KEY, intent_recovered INTEGER,
        defect_caught INTEGER, false_alarm INTEGER, intent_reason TEXT, defect_reason TEXT,
        false_alarm_reason TEXT, judge_model TEXT)""")
    for k in range(n):
        d = k % 2
        conn.execute("INSERT INTO instances (pr_id, variant, has_defect, mutation_op, "
                     "mutation_target, problem_statement) VALUES (?,?,?,?,?,?)",
                     (f"x#{k}", "mutant" if d else "golden", d, "flip" if d else None,
                      "f.py:3" if d else None, f"Problem {k}"))
        for c in CONDS:
            review = {"intent_summary": f"S{k}", "verdict": "approve", "findings": []}
            cur = conn.execute(
                "INSERT INTO runs (pr_id, condition, ask, ambiguity_score, threshold, "
                "detector_why, asked, intent_summary, verdict, payload, detector) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"x#{k}", c, 0, .5, .5, "", 0, f"S{k}", "approve",
                 json.dumps({"review": review}), "det"))
            conn.execute("INSERT INTO judgements VALUES (?,?,?,?,?,?,?,?)",
                         (cur.lastrowid, k % 2, d, 1 - d, "r", "r", "r", "gemini-api"))
    conn.commit()
    conn.close()


def test_export_hides_condition_and_run_ids_and_is_deterministic(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    a, b = tmp_path / "a", tmp_path / "b"
    ej.export(db, a, batch_size=5, seed=1)
    ej.export(db, b, batch_size=5, seed=1)
    for f in sorted(p.name for p in a.iterdir()):
        assert (a / f).read_bytes() == (b / f).read_bytes()
    prompt = "".join(p.read_text(encoding="utf-8") for p in a.glob("*.prompt.md"))
    for c in CONDS:
        assert c not in prompt
    assert "detector" not in prompt.lower()
    assert "return only a json array" in prompt.lower()
    assert "J0001" in prompt and "You score a code review" in prompt
    key = list(csv.DictReader(open(a / "key.csv", encoding="utf-8")))
    assert len(key) == 12
    assert [int(r["run_id"]) for r in key] != sorted(int(r["run_id"]) for r in key)
    sizes = [len(p.read_text(encoding="utf-8").splitlines())
             for p in sorted(a.glob("*.items.jsonl"))]
    assert sizes == [5, 5, 2]
    assert "key.csv" in (a / "README.txt").read_text(encoding="utf-8")
    for line in (a / "batch_001.items.jsonl").read_text(encoding="utf-8").splitlines():
        assert set(json.loads(line)) == {"item_id", "judge_context", "schema"}


def test_stratified_sample_and_filters(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    out = tmp_path / "o"
    r = ej.export(db, out, batch_size=10, sample=6, stratify=["condition", "variant"])
    assert r["items"] == 6
    key = list(csv.DictReader(open(out / "key.csv", encoding="utf-8")))
    assert len({(k["condition"], k["variant"]) for k in key}) == 6
    assert ej.export(db, tmp_path / "p", run_ids=[1, 2])["items"] == 2
    assert ej.export(db, tmp_path / "q", only_unjudged_by="api")["items"] == 0
    assert ej.export(db, tmp_path / "r", only_unjudged_by="gemini-web")["items"] == 12


def _respond(out, fenced=True, drop=None, dup=False, bad=None):
    for p in sorted(out.glob("batch_*.items.jsonl")):
        objs = []
        for line in p.read_text(encoding="utf-8").splitlines():
            objs.append({"item_id": json.loads(line)["item_id"], "intent_recovered": True,
                         "intent_reason": "x", "defect_caught": False, "defect_reason": "x",
                         "false_alarm": False, "false_alarm_reason": "x"})
        if drop:
            objs = [o for o in objs if o["item_id"] != drop]
        if dup:
            objs.append(dict(objs[0]))
        for o in objs:
            if o["item_id"] == bad:
                o["defect_caught"] = "maybe"
        body = json.dumps(objs)
        text = f"Sure! Here you go:\n```json\n{body}\n```\nHope that helps." if fenced else body
        (out / p.name.replace(".items.jsonl", ".response.json")).write_text(text, encoding="utf-8")


def test_import_tolerates_fences_maps_ids_and_keeps_api_rows(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    out = tmp_path / "o"
    ej.export(db, out, batch_size=5)
    _respond(out, fenced=True)
    before = sqlite3.connect(db).execute("SELECT * FROM judgements ORDER BY run_id").fetchall()
    res = ej.import_responses(db, out, "gemini-web", "gemini-3")
    assert res["stored"] == 12 and not res["missing"] and not res["invalid"]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT * FROM judgements ORDER BY run_id").fetchall() == before
    assert conn.execute("SELECT COUNT(*), MIN(judge_model) FROM external_judgements "
                        "WHERE judge_label='gemini-web'").fetchone() == (12, "gemini-3")
    key = {r["item_id"]: int(r["run_id"])
           for r in csv.DictReader(open(out / "key.csv", encoding="utf-8"))}
    assert {r[0] for r in conn.execute("SELECT run_id FROM external_judgements")} == set(key.values())
    ej.import_responses(db, out, "claude-agent")
    ej.import_responses(db, out, "claude-agent")
    assert conn.execute("SELECT COUNT(*) FROM external_judgements").fetchone()[0] == 24


def test_import_reports_missing_duplicate_invalid_and_never_invents(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    out = tmp_path / "o"
    ej.export(db, out, batch_size=12)
    _respond(out, fenced=False, drop="J0003", dup=True, bad="J0005")
    res = ej.import_responses(db, out, "g")
    assert res["missing"] == ["J0003", "J0005"]
    assert res["duplicates"] == ["J0001"]
    assert [i["item_id"] for i in res["invalid"]] == ["J0005"]
    assert res["stored"] == 10
    (out / "batch_001.response.json").write_text("no json here", encoding="utf-8")
    res = ej.import_responses(db, out, "h")
    assert res["stored"] == 0 and res["unparsable_files"] == ["batch_001.response.json"]


def test_compare_identical_gives_kappa_one(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    conn = sqlite3.connect(db)
    ej._ensure_table(conn)
    conn.execute("""INSERT INTO external_judgements SELECT run_id, 'copy', intent_recovered,
        defect_caught, false_alarm, intent_reason, defect_reason, false_alarm_reason,
        'm', 't' FROM judgements""")
    conn.commit()
    conn.close()
    rep = ej.compare(db, "api", "copy")
    assert rep["n_shared_runs"] == 12 and rep["a"]["models"] == ["gemini-api"]
    for f in ej.FIELDS:
        assert rep["fields"][f]["kappa"] == 1.0
        assert rep["fields"][f]["percent_agreement"] == 1.0


def test_analyze_with_label_uses_that_judges_scores(tmp_path):
    db = tmp_path / "s.db"
    _db(db, n=6)
    conn = sqlite3.connect(db)
    ej._ensure_table(conn)
    conn.execute("""INSERT INTO external_judgements
        SELECT r.id, 'ext', CASE WHEN r.condition=? THEN 1 ELSE 0 END, 0, 0, 'a','a','a','m','t'
        FROM runs r""", (CONDITION_STRIPPED_CLARIFY,))
    conn.commit()
    conn.close()
    snap = sqlite3.connect(db).execute("SELECT * FROM judgements").fetchall()
    out = tmp_path / "rep" / "r.json"
    rep = ej.analyze_with_label(db, "ext", out)
    assert json.loads(out.read_text(encoding="utf-8"))["judge"] == {"label": "ext",
                                                                    "n_judged_runs": 18}
    assert rep["intent_recovery"]["n"] == 6
    assert rep["intent_recovery"]["gap_recovery"]["floor_rate"] == 0.0
    assert rep["intent_recovery"]["gap_recovery"]["treatment_rate"] == 1.0
    assert sqlite3.connect(db).execute("SELECT * FROM judgements").fetchall() == snap
    api = ej.analyze_with_label(db, "api", tmp_path / "api.json")
    assert api["judge"]["n_judged_runs"] == 18
