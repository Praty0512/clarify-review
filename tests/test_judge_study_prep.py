"""Tests for the judge-validation and Study B preparation tooling (all offline)."""

import csv
import json
import os
import sqlite3
from pathlib import Path

import pytest

from clarifyreview.store import db as store
from experiments.analyze import judge_agreement, study_b_report
from experiments.judge import BLIND_FIELDS, write_blind_copies
from study import assign, build_study, merge_responses
from study.assign import clarify_is_a


def _db(path, n=6):
    store.init(path)
    conn = sqlite3.connect(path)
    for k in range(n):
        defect = k % 2
        conn.execute("INSERT INTO instances (pr_id, variant, has_defect, mutation_op, "
                     "mutation_target, problem_statement) VALUES (?,?,?,?,?,?)",
                     (f"x#{k}", "mutant" if defect else "golden", defect,
                      "flip_cmp" if defect else None, "f.py:3" if defect else None,
                      f"Problem number {k} " + "long " * 200))
        review = {"intent_summary": f"S{k}", "verdict": "approve", "findings": [
            {"severity": "major", "category": "correctness", "file": "f.py", "line": 3,
             "claim": f"claim{k}", "confidence": 0.8}]}
        conn.execute("INSERT INTO runs (pr_id, condition, ask, ambiguity_score, threshold, "
                     "detector_why, asked, intent_summary, verdict, payload) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (f"x#{k}", "stripped_clarify", 0, 0.5, 0.5, "", 0, f"S{k}", "approve",
                      json.dumps({"review": review})))
    conn.commit()
    conn.close()


def _sample(path, ids):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["run_id", "condition", "judge_intent_recovered",
                                           "human_intent_recovered"])
        w.writeheader()
        for i in ids:
            w.writerow({"run_id": i, "condition": "stripped_clarify",
                        "judge_intent_recovered": 1, "human_intent_recovered": ""})


def test_blind_copies_hide_judge_and_condition_and_shuffle_per_scorer(tmp_path):
    db, sample, out = tmp_path / "t.db", tmp_path / "s.csv", tmp_path / "blind"
    _db(db)
    _sample(sample, range(1, 7))
    paths = write_blind_copies(sample, db, ["ann", "bob"], out)
    rows = {p.stem: list(csv.DictReader(p.open(encoding="utf-8"))) for p in paths}
    assert list(rows["ann"][0]) == BLIND_FIELDS
    assert not any(k.startswith("judge_") or k in ("condition", "variant") for k in rows["ann"][0])
    assert sorted(r["run_id"] for r in rows["ann"]) == sorted(r["run_id"] for r in rows["bob"])
    assert [r["run_id"] for r in rows["ann"]] != [r["run_id"] for r in rows["bob"]]
    r = next(r for r in rows["ann"] if r["pr_id"] == "x#1")
    assert r["injected_defect"] == "flip_cmp on f.py:3" and "claim1" in r["findings"]
    assert len(r["problem_statement"]) > 400                  # not truncated
    assert next(r for r in rows["ann"] if r["pr_id"] == "x#0")["injected_defect"].startswith("none")
    assert (out / "INSTRUCTIONS.txt").exists()
    again = write_blind_copies(sample, db, ["ann", "bob"], tmp_path / "blind2")
    assert again[0].read_bytes() == paths[0].read_bytes()      # deterministic


def test_blind_copies_refuse_to_overwrite_filled_files(tmp_path):
    db, sample, out = tmp_path / "t.db", tmp_path / "s.csv", tmp_path / "blind"
    _db(db)
    _sample(sample, [1, 2])
    (p,) = write_blind_copies(sample, db, ["ann"], out)
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    rows[0]["human_intent_recovered"] = "1"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BLIND_FIELDS)
        w.writeheader()
        w.writerows(rows)
    before = p.read_bytes()
    with pytest.raises(FileExistsError):
        write_blind_copies(sample, db, ["ann"], out)
    assert p.read_bytes() == before


def test_judge_agreement_looks_up_judge_in_reference(tmp_path):
    ref = tmp_path / "sample.csv"
    ref.write_text("run_id,judge_intent_recovered,judge_defect_caught,judge_false_alarm\n"
                   "1,1,0,0\n2,0,0,1\n", encoding="utf-8")
    a = tmp_path / "ann.csv"
    a.write_text("﻿run_id,human_intent_recovered,human_defect_caught,human_false_alarm\n"
                 "1,1,0,0\n2,1,0,1\n", encoding="utf-8")
    out = judge_agreement([a], ref)
    assert out["human_vs_judge"]["ann"]["intent_recovered"]["percent_agreement"] == 0.5
    assert out["human_vs_judge"]["ann"]["false_alarm"]["n"] == 2
    assert judge_agreement([a])["human_vs_judge"]["ann"]["intent_recovered"] == {"n": 0}


HEADER = "participant,years,item,label,usefulness,trust,would_act,why\n"


def _resp(path, pid, items, u="4", t="3", act="1"):
    lines = [f"{pid},5,{i},{L},{u},{t},{act},ok" for i in items for L in "AB"]
    path.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")


def test_merge_reads_directories_dedupes_and_reports(tmp_path):
    d = tmp_path / "responses"
    d.mkdir()
    _resp(d / "a.csv", "P01", ["i1", "i2"], u="2")
    _resp(d / "b.csv", "P01", ["i1"], u="5")                    # second download
    _resp(d / "c.csv", "P02", ["i1"])
    os.utime(d / "a.csv", (1, 1))
    out = tmp_path / "m.csv"
    res = merge_responses.merge([str(d)], out, None)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert res["duplicates_dropped"] == 2 and res["participants"] == 2 and len(rows) == 6
    assert {r["usefulness"] for r in rows if r["participant"] == "P01" and r["pr_id"] == "i1"} == {"5"}
    assert merge_responses.main([str(d / "*.csv"), "--out", str(out),
                                 "--html", str(tmp_path / "no.html")]) == 0
    assert merge_responses.main([str(tmp_path / "empty*"), "--out", str(out)]) == 1


def test_merge_unblinds_with_the_shared_hash(tmp_path):
    f = tmp_path / "r.csv"
    _resp(f, "P03", ["i1"])
    out = tmp_path / "m.csv"
    merge_responses.merge([str(f)], out, None)
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert {r["condition"] for r in rows} == {"stripped_clarify", "stripped_plain"}
    a_row = next(r for r in rows if r["condition"] == "stripped_clarify")
    assert clarify_is_a("P03", "i1") == (rows.index(a_row) == 0)   # label A is written first


def test_study_b_report_covers_usefulness_trust_and_would_act(tmp_path):
    p = tmp_path / "b.csv"
    lines = ["participant,years,pr_id,condition,usefulness,trust,would_act,why"]
    for k in range(8):
        lines.append(f"P{k},3,i1,stripped_plain,{2 + k % 2},2,0,")
        lines.append(f"P{k},3,i1,stripped_clarify,{4 + k % 2},{3 + k % 2},1,")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep = study_b_report(p)
    assert rep["participants"] == 8 and rep["ratings"] == 16
    assert rep["usefulness"]["effect_size_r"] > 0 and "p_value" in rep["trust"]
    assert rep["would_act"] == {"plain": {"n": 8, "rate": 0.0}, "clarify": {"n": 8, "rate": 1.0}}


def test_assign_writes_codes_and_refuses_to_overwrite_entries(tmp_path):
    out = tmp_path / "p.csv"
    assert assign.main(["--codes", "3", "--out", str(out), "--html", str(tmp_path / "x.html")]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["participant"] for r in rows] == ["P01", "P02", "P03"]
    assert assign.main(["--codes", "3", "--out", str(out)]) == 0      # still empty: rewrite ok
    out.write_text(out.read_text(encoding="utf-8").replace("P01,,,", "P01,Sam,,", 1),
                   encoding="utf-8")
    assert assign.main(["--codes", "3", "--out", str(out)]) == 2
    assert "Sam" in out.read_text(encoding="utf-8")


def test_template_has_autosave_and_per_participant_filename():
    t = (build_study.HERE / "template.html").read_text(encoding="utf-8")
    assert "cr_study_" in t and "clarifyreview_responses_${safeName" in t


def test_shipped_study_page_is_current():
    root = Path(__file__).resolve().parents[1]
    if not (root / "data/study_v2.db").exists():
        pytest.skip("study database not present")
    assert build_study.is_current(root / "data/study_v2.db", root / "data/instances.v2.jsonl",
                                  root / "study/study.html")
