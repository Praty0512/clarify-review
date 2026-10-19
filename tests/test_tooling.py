"""Tests for the human-in-the-loop tooling: judge validation, oracle audit, sweeps."""

import csv
import json

from experiments.analyze import judge_agreement
from experiments.oracle import exchange_summary, write_audit_sheet
from experiments.sweep_uncertainty import score_dev, sweep_recorded

FIELDS = ["run_id", "human_intent_recovered", "human_defect_caught", "human_false_alarm",
          "judge_intent_recovered", "judge_defect_caught", "judge_false_alarm"]


def _sheet(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow(dict(zip(FIELDS, r)))


def test_judge_agreement_compares_each_human_with_the_judge_and_each_other(tmp_path):
    a, b = tmp_path / "yashika.csv", tmp_path / "pratyaksh.csv"
    _sheet(a, [(1, "1", "0", "0", 1, 0, 0), (2, "0", "0", "1", 0, 0, 1),
               (3, "1", "1", "0", 1, 1, 0), (4, "0", "", "0", 1, 0, 0)])
    _sheet(b, [(1, "yes", "no", "no", 1, 0, 0), (2, "no", "no", "yes", 0, 0, 1),
               (3, "yes", "yes", "no", 1, 1, 0), (4, "yes", "no", "no", 1, 0, 0)])
    out = judge_agreement([a, b])

    hj = out["human_vs_judge"]["yashika"]["intent_recovered"]
    assert hj["n"] == 4 and hj["percent_agreement"] == 0.75
    # A blank cell is excluded, not counted as disagreement.
    assert out["human_vs_judge"]["yashika"]["defect_caught"]["n"] == 3
    # The second scorer agrees with the judge everywhere; yes/no parse as 1/0.
    assert out["human_vs_judge"]["pratyaksh"]["intent_recovered"]["kappa"] == 1.0
    hh = out["human_vs_human"]["pratyaksh vs yashika"]["intent_recovered"]
    assert hh["n"] == 4 and hh["percent_agreement"] == 0.75
    assert "reading" in hh


def _log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_oracle_summary_separates_versions_and_outcomes(tmp_path):
    log = tmp_path / "o.jsonl"
    _log(log, [
        {"pr_id": "a", "questions": [], "answer": None},                       # v1, empty
        {"pr_id": "b", "questions": [], "answer": "I'm not sure, I don't have that context to hand."},
        {"pr_id": "c", "questions": [], "answer": "To stop the crash.", "prompt_version": "v2"},
    ])
    s = exchange_summary(log)
    assert s["v1"] == {"exchanges": 2, "answered": 0, "refused": 1, "empty": 1}
    assert s["v2"]["answered"] == 1


def test_audit_sheet_samples_only_substantive_answers(tmp_path):
    log, out = tmp_path / "o.jsonl", tmp_path / "audit.csv"
    q = [{"question": "Why?"}]
    _log(log, [
        {"pr_id": "a", "questions": q, "answer": "", "prompt_version": "v2"},
        {"pr_id": "b", "questions": q, "answer": "I'm not sure, I don't have that context to hand.",
         "prompt_version": "v2"},
        {"pr_id": "c", "questions": q, "answer": "Note that line 4 looks wrong.", "prompt_version": "v2"},
        {"pr_id": "d", "questions": q, "answer": "To support other packages.", "prompt_version": "v1"},
    ])
    assert write_audit_sheet(log, out, n=10, prompt_version="v2") == 1
    rows = list(csv.DictReader(out.open()))
    assert rows[0]["pr_id"] == "c"
    assert rows[0]["suspected_leak"] == "1"
    assert rows[0]["leak_scorer_1"] == ""
    assert write_audit_sheet(log, out, n=10, prompt_version=None) == 2


def test_recorded_sweep_finds_a_separating_threshold():
    comparison = {"detectors": {
        "sampling": {"decisions": [{"score": 0.7, "label": 1}, {"score": 0.72, "label": 1},
                                   {"score": 0.5, "label": 0}, {"score": 0.45, "label": 0}]},
        "heuristic": {"decisions": [{"score": 0.9, "label": 1}]},
    }}
    out = sweep_recorded(comparison)
    assert set(out) == {"sampling"}             # only the uncertainty detectors
    assert out["sampling"]["f1"] == 1.0
    assert 0.5 < out["sampling"]["threshold"] <= 0.7


class _Ctx:
    def __init__(self, pr_id):
        self.pr_id = pr_id


def test_dev_scoring_resumes_from_its_cache(tmp_path, monkeypatch):
    calls = []

    class FakeDetector:
        def score(self, ctx):
            calls.append(ctx.pr_id)
            return 0.5, "", {}

    monkeypatch.setattr("clarifyreview.detect.build", lambda name, **kw: FakeDetector())
    cache = tmp_path / "cache.jsonl"
    ctxs = [_Ctx("a"), _Ctx("b")]
    scores, done = score_dev(["sampling"], ctxs, cache, None, 8)
    assert done and scores["sampling"] == [0.5, 0.5] and calls == ["a", "b"]

    scores, done = score_dev(["sampling"], ctxs, cache, None, 8)
    assert calls == ["a", "b"]                  # nothing paid for twice
    assert scores["sampling"] == [0.5, 0.5]
