"""Tests for experiments.finish and paper.collect's human-results plumbing.

Offline. Every test runs against a tmp_path project root; none calls collect.main
against the real ROOT or rewrites the real paper/numbers.json, and the slow or
networked seams (training, collect, node) are replaced.
"""

import csv
import json
import sys
from pathlib import Path

from experiments import finish, label_tool
from paper import collect
from tests.conftest import AMBIGUOUS_DIFF, CLEAR_DIFF

REAL_ROOT = Path(__file__).resolve().parents[1]
SHEET_FIELDS = ["pr_id", "repo", "code_change", "annotator_1", "annotator_2", "adjudicated", "notes"]


def _sheet(root, labels):
    """labels: list of (a1, a2, adj)."""
    path = root / "runs/labelling_sheet.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SHEET_FIELDS)
        w.writeheader()
        for i, (a1, a2, adj) in enumerate(labels):
            w.writerow({"pr_id": f"pr{i}", "repo": "acme/app",
                        "code_change": AMBIGUOUS_DIFF if i % 2 else CLEAR_DIFF,
                        "annotator_1": a1, "annotator_2": a2, "adjudicated": adj, "notes": ""})
    return path


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _judge_file(root, name, filled):
    d = root / "runs/judge_validation"
    d.mkdir(parents=True, exist_ok=True)
    fields = ["run_id", "pr_id", "has_defect", "injected_defect", "problem_statement",
              "intent_summary", "verdict", "findings", "human_intent_recovered",
              "human_defect_caught", "human_false_alarm", "notes"]
    with (d / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for i in range(6):
            bad = i % 2
            row = {"run_id": str(i), "pr_id": f"p{i}", "has_defect": str(bad)}
            if filled:
                row["human_intent_recovered"] = "1"
                row["human_defect_caught" if bad else "human_false_alarm"] = "1" if i % 3 else "0"
            w.writerow(row)


def _responses(root, n_participants):
    d = root / "study/responses"
    d.mkdir(parents=True, exist_ok=True)
    for p in range(n_participants):
        with (d / f"clarifyreview_responses_P{p:02d}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["participant", "years", "item", "label",
                                               "usefulness", "trust", "would_act", "why"])
            w.writeheader()
            for item in ("i1", "i2", "i3"):
                for label, u in (("A", 4 + p % 2), ("B", 2)):
                    w.writerow({"participant": f"P{p:02d}", "years": "3", "item": item, "label": label,
                                "usefulness": u, "trust": u, "would_act": "yes", "why": ""})


def _fake_seams(monkeypatch, calls):
    def train(argv):
        calls.append("train")
        Path(argv[argv.index("--thresholds-out") + 1]).write_text("{}")
        Path(argv[argv.index("--report-out") + 1]).write_text(json.dumps({"n_labels": 4}))
        return 0

    monkeypatch.setattr(finish, "_train", train)
    monkeypatch.setattr(finish, "_collect", lambda root: calls.append("collect") or 0)
    monkeypatch.setattr(finish, "_run_node", lambda root: calls.append("node") or (0, ""))


# ------------------------------------------------------------------- status


def test_status_on_an_empty_project_is_all_blocked_writes_nothing_and_exits_zero(tmp_path, capsys):
    assert finish.main(["--status"], root=tmp_path) == 0
    assert _snapshot(tmp_path) == {}
    results = finish.run(tmp_path, status_only=True)
    assert [r.name for r in results] == finish.STEP_ORDER
    assert [r.status for r in results[:4]] == ["blocked"] * 4
    assert results[4].status == "skipped"
    assert "Still needs people" in capsys.readouterr().out


def test_status_reports_ready_without_writing(tmp_path):
    _sheet(tmp_path, [("1", "1", ""), ("0", "1", "1"), ("0", "0", "")])
    _judge_file(tmp_path, "a", True)
    _judge_file(tmp_path, "b", True)
    _responses(tmp_path, 2)
    before = _snapshot(tmp_path)
    results = {r.name: r for r in finish.run(tmp_path, status_only=True, min_participants=2)}
    assert _snapshot(tmp_path) == before
    for name in ("labelling", "judge", "study_b"):
        assert results[name].status == "skipped" and "ready" in results[name].detail


# --------------------------------------------------------------- labelling


def test_unadjudicated_disagreement_blocks_everything_downstream(tmp_path, monkeypatch):
    calls = []
    _fake_seams(monkeypatch, calls)
    _sheet(tmp_path, [("1", "1", ""), ("0", "1", ""), ("0", "0", "")])
    before = _snapshot(tmp_path)
    res = {r.name: r for r in finish.run(tmp_path)}
    assert res["labelling"].status == "blocked"
    assert "1 unadjudicated" in res["labelling"].detail
    assert res["training"].status == "blocked"
    assert calls == []
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / "data/labelled_prs.jsonl").exists()


def test_allow_partial_gives_interim_kappa_and_writes_no_jsonl(tmp_path, monkeypatch):
    calls = []
    _fake_seams(monkeypatch, calls)
    _sheet(tmp_path, [("1", "1", ""), ("0", "0", ""), ("", "", "")])
    res = {r.name: r for r in finish.run(tmp_path, allow_partial=True)}
    assert "interim kappa" in res["labelling"].detail
    assert res["training"].status == "skipped"
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "runs/labelling_agreement.json").exists()
    assert calls == []


def test_combines_annotator_files_before_checking_readiness(tmp_path, monkeypatch):
    calls = []
    _fake_seams(monkeypatch, calls)
    sheet = _sheet(tmp_path, [("", "", ""), ("", "", "")])
    d = tmp_path / "runs/labelling"
    d.mkdir(parents=True)
    for n, vals in ((1, ["1", "0"]), (2, ["1", "0"])):
        with (d / f"annotator_{n}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["pr_id", "repo", "code_change", f"annotator_{n}", "notes"])
            for i, v in enumerate(vals):
                w.writerow([f"pr{i}", "acme/app", "x", v, ""])
    res = {r.name: r for r in finish.run(tmp_path, paper="never")}
    assert res["labelling"].status == "done"
    rows = label_tool._read_rows(sheet)
    assert [r["annotator_1"] for r in rows] == ["1", "0"]
    assert [r["annotator_2"] for r in rows] == ["1", "0"]
    assert (tmp_path / "data/labelled_prs.jsonl").exists()


# ---------------------------------------------------------------- full run


def test_runs_ready_steps_in_order_and_blocks_paper_without_node_modules(tmp_path, monkeypatch):
    calls = []
    _fake_seams(monkeypatch, calls)
    monkeypatch.setitem(sys.modules, "datasets", None)       # the sheet path must be offline
    _sheet(tmp_path, [("1", "1", ""), ("0", "1", "1"), ("0", "0", ""), ("1", "1", "")])
    _judge_file(tmp_path, "a", True)
    _judge_file(tmp_path, "b", True)
    _responses(tmp_path, 2)
    res = finish.run(tmp_path, min_participants=2)
    assert [(r.name, r.status) for r in res] == [
        ("labelling", "done"), ("training", "done"), ("judge", "done"),
        ("study_b", "done"), ("paper", "blocked")]
    assert calls == ["train", "collect"]                       # numbers refreshed, node never run
    assert "npm install" in res[4].needs
    rep = json.loads((tmp_path / "runs/labelling_agreement.json").read_text())
    assert rep["n"] == 4 and rep["n_written"] == 4 and rep["n_disagree"] == 1
    assert rep["diff_source"] == "sheet"
    assert (tmp_path / "runs/judge_agreement.json").exists()
    assert json.loads((tmp_path / "runs/study_b_report.json").read_text())["participants"] == 2
    assert "WARNING: Study A used the DEFAULT thresholds" in res[1].detail
    assert "fewer than 12" in res[3].detail
    # second run: the labelled set is unchanged, so training is not repeated
    calls.clear()
    res2 = finish.run(tmp_path, min_participants=2)
    assert "train" not in calls and res2[1].status == "done"


def test_paper_builds_with_node_when_the_docx_package_is_installed(tmp_path, monkeypatch):
    calls = []
    _fake_seams(monkeypatch, calls)
    (tmp_path / "paper/node_modules/docx").mkdir(parents=True)
    _judge_file(tmp_path, "a", True)
    _judge_file(tmp_path, "b", True)
    res = {r.name: r for r in finish.run(tmp_path)}
    assert res["paper"].status == "done" and calls == ["collect", "node"]


def test_judge_needs_two_fully_scored_copies(tmp_path):
    _judge_file(tmp_path, "a", True)
    _judge_file(tmp_path, "b", False)
    r = finish.step_judge(tmp_path, dry=False)
    assert r.status == "blocked" and "1 of 2" in r.detail
    assert not (tmp_path / "runs/judge_agreement.json").exists()


def test_study_b_blocks_below_minimum_participants(tmp_path):
    _responses(tmp_path, 2)
    r = finish.step_study_b(tmp_path, dry=False, min_participants=6)
    assert r.status == "blocked" and "2 participants" in r.detail
    assert not (tmp_path / "runs/study_b.csv").exists()


# ------------------------------------------------------------------ collect


def test_human_results_marks_missing_files_unavailable(tmp_path):
    h = collect.human_results(tmp_path)
    assert set(h) == {"labelling", "thresholds", "judge_validation", "study_b"}
    assert all(v == {"available": False} for v in h.values())


def test_human_results_reads_the_result_files(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "labelling_agreement.json").write_text(json.dumps({
        "n": 300, "kappa": 0.6, "observed_agreement": 0.8, "reading": "substantial",
        "n_rows": 300, "n_disagree": 60, "n_adjudicated": 60, "n_disagree_unadjudicated": 0,
        "n_written": 300, "diff_source": "sheet"}))
    (runs / "threshold_sweep.json").write_text(json.dumps({
        "thresholds": {"heuristic": 0.4}, "dev_sweep": {}, "n_labels": 300, "n_ambiguous": 90}))
    (runs / "judge_agreement.json").write_text(json.dumps({
        "scorers": ["a", "b"],
        "human_vs_judge": {"a": {"intent_recovered": {"n": 60, "kappa": 0.5},
                                 "defect_caught": {"n": 0}, "false_alarm": {"n": 30, "kappa": None}},
                           "b": {"intent_recovered": {"n": 58, "kappa": 0.7}}},
        "human_vs_human": {}}))
    (runs / "study_b_report.json").write_text(json.dumps({
        "participants": 10, "usefulness": {"n": 10, "p_value": 0.03}, "trust": {"n": 0},
        "would_act": {}}))
    h = collect.human_results(tmp_path)
    assert h["labelling"]["available"] and h["labelling"]["kappa"] == 0.6
    assert h["thresholds"]["values"] == {"heuristic": 0.4}
    jv = h["judge_validation"]
    assert jv["available"] and jv["n_scorers"] == 2
    assert jv["metrics"]["intent_recovered"]["n"] == 60
    assert abs(jv["metrics"]["intent_recovered"]["kappa_mean"] - 0.6) < 1e-9
    assert "defect_caught" not in jv["metrics"]
    assert jv["metrics"]["false_alarm"]["kappa_mean"] is None
    assert h["study_b"]["available"] and h["study_b"]["participants"] == 10


def test_labelling_with_unadjudicated_disagreements_is_not_available(tmp_path):
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs/labelling_agreement.json").write_text(json.dumps({
        "n": 10, "kappa": 0.5, "n_disagree_unadjudicated": 2}))
    assert collect.human_results(tmp_path)["labelling"] == {"available": False}


def test_collect_runs_pytest_with_the_current_interpreter_in_the_given_root(tmp_path, monkeypatch):
    real = REAL_ROOT / "paper/numbers.json"
    before = real.read_bytes()
    for d in ("src", "experiments", "tests", "data", "runs"):
        (tmp_path / d).mkdir()
    (tmp_path / "data/mutants.verified.jsonl").write_text("")
    seen = {}

    class R:
        stdout = "3 passed in 0.1s\n"

    def fake_run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return R()

    monkeypatch.setattr(collect.subprocess, "run", fake_run)
    assert collect.main(tmp_path) == 0
    assert seen["cmd"][0] == sys.executable and seen["cwd"] == tmp_path
    nums = json.loads((tmp_path / "paper/numbers.json").read_text())
    assert nums["tests_passing"] == "3 passed in 0.1s"
    assert nums["human"]["labelling"] == {"available": False}
    assert real.read_bytes() == before


# ------------------------------------------------------- --labelling-set realpr

REAL_FIELDS = ["pr_id", "repo", "view", "title", "body", "issue_number", "issue_title",
               "issue_body", "commit_messages", "code_change", "annotator_1", "annotator_2",
               "adjudicated", "notes"]


def _realpr_sheet(root, labels):
    path = root / "runs/realpr/labelling_sheet.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REAL_FIELDS)
        w.writeheader()
        for i, (a1, a2, adj) in enumerate(labels):
            w.writerow({"pr_id": f"acme/app#{i + 1}", "repo": "acme/app", "view": "full_context",
                        "title": f"t{i}", "body": "b", "issue_number": "", "issue_title": "",
                        "issue_body": "", "commit_messages": json.dumps(["m"]),
                        "code_change": "truncated", "annotator_1": a1, "annotator_2": a2,
                        "adjudicated": adj, "notes": ""})
        for i in range(len(labels)):
            cache = root / "data/cache/realpr/acme__app"
            cache.mkdir(parents=True, exist_ok=True)
            (cache / f"full_{i + 1}.json").write_text(
                json.dumps({"diff": AMBIGUOUS_DIFF if i % 2 else CLEAR_DIFF}), encoding="utf-8")
    return path


def test_realpr_status_reports_its_own_paths_and_writes_nothing(tmp_path, capsys):
    _realpr_sheet(tmp_path, [("1", "1", ""), ("0", "0", "")])
    before = _snapshot(tmp_path)
    assert finish.main(["--labelling-set", "realpr", "--status"], root=tmp_path) == 0
    assert _snapshot(tmp_path) == before
    res = {r.name: r for r in finish.run(tmp_path, status_only=True, labelling_set="realpr")}
    assert res["labelling"].status == "skipped" and "ready" in res["labelling"].detail
    for name in ("judge", "study_b", "paper"):
        assert res[name].status == "skipped" and "realpr" in res[name].detail
    out = capsys.readouterr().out
    assert "judge" in out


def test_realpr_blocked_message_points_at_fetch_prs_and_its_own_directory(tmp_path):
    res = finish.run(tmp_path, status_only=True, labelling_set="realpr")
    assert res[0].status == "blocked" and "realpr" in res[0].detail and "labelling_sheet.csv" in res[0].detail
    assert "fetch_prs" in res[0].needs


def test_realpr_run_writes_only_realpr_files_never_the_study_model(tmp_path, monkeypatch):
    calls, seen = [], {}

    def train(argv):
        calls.append("train")
        seen["argv"] = argv
        for flag in ("--out", "--thresholds-out", "--report-out"):
            Path(argv[argv.index(flag) + 1]).parent.mkdir(parents=True, exist_ok=True)
            Path(argv[argv.index(flag) + 1]).write_text("{}")
        return 0

    monkeypatch.setattr(finish, "_train", train)
    monkeypatch.setattr(finish, "_collect", lambda root: calls.append("collect") or 0)
    monkeypatch.setattr(finish, "_run_node", lambda root: calls.append("node") or (0, ""))
    _realpr_sheet(tmp_path, [("1", "1", ""), ("0", "0", ""), ("1", "0", "1")])
    res = {r.name: r for r in finish.run(tmp_path, labelling_set="realpr")}
    assert res["labelling"].status == "done" and res["training"].status == "done"
    assert calls == ["train"]                                      # no paper, no node
    argv = seen["argv"]
    assert argv[argv.index("--labels") + 1].endswith("labelled_prs.realpr.jsonl")
    assert argv[argv.index("--out") + 1].endswith("ambiguity_clf.realpr.joblib")
    assert argv[argv.index("--thresholds-out") + 1].endswith("thresholds.realpr.json")
    rows = [json.loads(l) for l in (tmp_path / "data/labelled_prs.realpr.jsonl").read_text().splitlines()]
    assert [r["label"] for r in rows] == [1, 0, 1]
    assert all(r["diff_source"] == "cache" and r["diff"] != "truncated" for r in rows)
    assert (tmp_path / "runs/realpr/labelling_agreement.json").exists()
    for study_path in ("data/labelled_prs.jsonl", "data/thresholds.json",
                       "data/models/ambiguity_clf.joblib", "runs/labelling_agreement.json",
                       "runs/threshold_sweep.json"):
        assert not (tmp_path / study_path).exists()


def test_default_labelling_set_is_still_the_study_sheet(tmp_path):
    _sheet(tmp_path, [("1", "1", "")])
    _realpr_sheet(tmp_path, [("1", "1", "")])
    a = finish.run(tmp_path, status_only=True)
    b = finish.run(tmp_path, status_only=True, labelling_set="swebench")
    assert [(r.name, r.status, r.detail) for r in a] == [(r.name, r.status, r.detail) for r in b]
    assert "runs/labelling_sheet.csv" not in finish.REALPR.sheet and finish.SWEBENCH.diff_source == "sheet"
