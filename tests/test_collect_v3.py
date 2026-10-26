"""judged_copy and the new paper/collect.py blocks, on a tiny fixture database."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from experiments import external_judge as ej
from paper import collect
from tests.test_external_judge import CONDS, _db


def _with_external(db: Path, label="agent", model="agent-model"):
    conn = sqlite3.connect(db)
    ej._ensure_table(conn)
    for (rid, ir, dc, fa) in conn.execute(
            "SELECT run_id, intent_recovered, defect_caught, false_alarm FROM judgements").fetchall():
        conn.execute("INSERT INTO external_judgements (run_id, judge_label, intent_recovered, "
                     "defect_caught, false_alarm, intent_reason, defect_reason, "
                     "false_alarm_reason, judge_model) VALUES (?,?,?,?,?,?,?,?,?)",
                     (rid, label, 1 - ir, dc, fa, "r", "r", "r", model))
    conn.commit()
    conn.close()


def _rows(db: Path, table="judgements"):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
    finally:
        conn.close()


def test_judged_copy_swaps_scores_in_a_copy_and_leaves_source_alone(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    _with_external(db)
    before = db.read_bytes()
    with ej.judged_copy(db, "agent") as tmp:
        assert tmp != db and tmp.exists()
        copied = _rows(tmp)
        assert {r[7] for r in copied} == {"agent-model"}
        # the fixture's agent label flips intent_recovered
        orig = {r[0]: r[1] for r in _rows(db)}
        assert all(r[1] == 1 - orig[r[0]] for r in copied)
        gone = tmp
    assert not gone.exists()
    assert db.read_bytes() == before


def test_judged_copy_api_label_keeps_existing_judgements(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    with ej.judged_copy(db, "api") as tmp:
        assert _rows(tmp) == _rows(db)


def test_study_with_judge_matches_study_on_the_copy(tmp_path):
    db = tmp_path / "s.db"
    _db(db, n=3)
    _with_external(db)
    api = collect.study_with_judge(db, "api")
    agent = collect.study_with_judge(db, "agent")
    assert api["judged"] == agent["judged"] == 9
    assert api["per_condition"]["full_plain"]["ir"] != agent["per_condition"]["full_plain"]["ir"]
    assert collect.study_with_judge(tmp_path / "missing.db", "api") == {"available": False}


def test_pair_and_three_way_use_compare_fields(tmp_path):
    db = tmp_path / "s.db"
    _db(db)
    _with_external(db, "agent", "agent-model")
    _with_external(db, "web", "web-model")
    pair = collect._pair(db, "api", "agent")
    assert pair["n_shared_runs"] == 12
    assert set(pair["intent_recovered"]) == {"n", "percent_agreement", "kappa", "reading"}
    assert pair["intent_recovered"]["percent_agreement"] == 0.0
    assert pair["defect_caught"]["percent_agreement"] == 1.0
    tw = collect.three_way_intent(db, ("api", "agent", "web"))
    assert tw == {"n": 12, "all_agree": 0}
    assert collect._one_model(db, "agent") == "agent-model"
    assert collect._one_model(db, "api") == "gemini-api"


def test_v3_design_and_oracle_model(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "runs").mkdir()

    def row(i, arm, variant, repo="a/a"):
        return {"pr_id": f"{i}::{variant}", "arm": arm, "variant": variant, "repo": repo,
                "difficulty": "easy"}

    v2 = [row("a", "mutant", "golden"), row("a", "mutant", "mutant")]
    v3 = v2 + [row("b", "mutant", "golden"), row("b", "mutant", "mutant"),
               row("c", "golden", "golden", "z/z")]
    for name, rows in (("v2", v2), ("v3", v3)):
        (tmp_path / f"data/instances.{name}.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (tmp_path / "runs/oracle_log.jsonl").write_text(
        "\n".join(json.dumps(r) for r in [
            {"pr_id": "a::golden", "model": "gemma"},   # v2 entry: must be ignored
            {"pr_id": "b::golden", "model": "llama"},
            {"pr_id": "c::golden", "model": "llama"}]), encoding="utf-8")
    d = collect.v3_design(tmp_path, verified_mutants=2)
    assert d["rows"] == 5 and d["n_new_rows"] == 3 and d["v2_subset"] is True
    assert d["mutants_used"] == 2 and d["all_verified_mutants_used"] is True
    assert d["golden_only_rows"] == 1 and d["golden_only_repos_not_in_mutants"] == 1
    o = collect.question_oracle_model(tmp_path, {r["pr_id"] for r in v3}, {r["pr_id"] for r in v2})
    assert o["model"] == "llama" and o["n_logged"] == 2 and o["per_row_in_db"] is False


def test_realpr_block_counts_only_adjudicated_rows(tmp_path):
    (tmp_path / "runs/realpr").mkdir(parents=True)
    (tmp_path / "runs/realpr/labelling_sheet.csv").write_text(
        "pr_id,repo,languages,annotator_1,annotator_2,adjudicated\n"
        "r#1,r,\"rust,c\",,,\n"
        "r#2,r,python,x,,\n"
        "s#3,s,python,x,x,y\n", encoding="utf-8")
    b = collect.realpr_block(tmp_path)
    assert (b["n_prs"], b["n_repos"], b["n_labelled"], b["n_annotated"]) == (3, 2, 1, 2)
    assert b["languages"] == {"python": 2, "rust": 1}
    assert collect.realpr_block(tmp_path / "nowhere") == {"available": False}


def test_v2_tokens_sums_successful_runs_only(tmp_path):
    db = tmp_path / "s.db"
    _db(db, n=2)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE runs SET input_tokens=10, output_tokens=2, cache_read_tokens=1")
    conn.execute("UPDATE runs SET error='boom' WHERE id=1")
    conn.commit()
    conn.close()
    t = collect.v2_tokens(db)
    assert (t["runs"], t["input"], t["output"], t["cache_read"]) == (5, 50, 10, 5)
    assert set(t["by_condition"]) == set(CONDS)


def test_ai_calibration_never_lands_in_the_human_block(tmp_path):
    h = collect.human_results(tmp_path)
    assert h["judge_validation"] == {"available": False}
