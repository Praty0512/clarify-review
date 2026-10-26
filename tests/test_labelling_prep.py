"""Tests for the labelling preparation tooling. Offline; nothing here writes a human label."""

import csv
import hashlib
import json
import sys

import pytest

from experiments import label_tool, prelabel
from tests.conftest import AMBIGUOUS_DIFF, CLEAR_DIFF

SHEET_FIELDS = ["pr_id", "repo", "code_change", "annotator_1", "annotator_2",
                "adjudicated", "notes"]


def _sheet(path, rows, bom=False):
    data = []
    for pr_id, diff, a1, a2, adj in rows:
        data.append({"pr_id": pr_id, "repo": "acme/app", "code_change": diff,
                     "annotator_1": a1, "annotator_2": a2, "adjudicated": adj, "notes": ""})
    with path.open("w", newline="", encoding=("utf-8-sig" if bom else "utf-8")) as fh:
        w = csv.DictWriter(fh, fieldnames=SHEET_FIELDS)
        w.writeheader()
        w.writerows(data)


def _md5(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def _read(path):
    return list(csv.DictReader(path.open(newline="", encoding="utf-8")))


# ------------------------------------------------------------ suggestions


def test_suggestions_go_to_a_separate_file_and_leave_the_sheet_untouched(tmp_path):
    sheet, out = tmp_path / "sheet.csv", tmp_path / "sugg.csv"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", ""), ("b", CLEAR_DIFF, "", "", "")])
    before = _md5(sheet)
    assert prelabel.write_suggestions(sheet, out) == 2
    assert _md5(sheet) == before
    rows = _read(out)
    assert list(rows[0]) == prelabel.SUGGESTION_FIELDS
    assert "annotator_1" not in rows[0] and "adjudicated" not in rows[0]
    assert rows[0]["note"].startswith("heuristic aid")


def test_suggested_labels_follow_the_codebook():
    amb = prelabel.suggest_row("a", "acme/app", AMBIGUOUS_DIFF)
    clr = prelabel.suggest_row("b", "acme/app", CLEAR_DIFF)
    # The deleted validation guard is the ambiguous archetype; the strip is clear.
    assert amb["suggested_label"] == "1" and clr["suggested_label"] == "0"
    assert "removes_guard" in amb["evidence_rules"]
    assert "email" in amb["removed_guard_lines"]


def test_always_on_rules_are_not_evidence_and_evidence_only_drops_the_verdict():
    row = prelabel.suggest_row("a", "acme/app", AMBIGUOUS_DIFF, evidence_only=True)
    fired = set(row["evidence_rules"].split(";"))
    assert not fired & prelabel.CONSTANT_IN_CODE_ONLY_VIEW
    assert row["suggested_label"] == "" and row["heuristic_score"] == ""


def test_prelabel_refuses_to_write_over_the_sheet(tmp_path):
    sheet = tmp_path / "sheet.csv"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", "")])
    before = _md5(sheet)
    assert prelabel.main(["--sheet", str(sheet), "--out", str(sheet)]) == 2
    assert _md5(sheet) == before


def test_prelabel_main_writes_readme(tmp_path):
    sheet, out = tmp_path / "sheet.csv", tmp_path / "s.csv"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", "")])
    assert prelabel.main(["--sheet", str(sheet), "--out", str(out)]) == 0
    assert "Do NOT open" in (tmp_path / "s.README.txt").read_text()


# ------------------------------------------------------------ split / combine


def test_split_gives_each_annotator_only_their_own_column(tmp_path):
    sheet = tmp_path / "sheet.csv"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", ""), ("b", CLEAR_DIFF, "", "", "")])
    before = _md5(sheet)
    assert label_tool.main(["split", str(sheet), "--out-dir", str(tmp_path / "l")]) == 0
    assert _md5(sheet) == before
    r1 = _read(tmp_path / "l" / "annotator_1.csv")
    r2 = _read(tmp_path / "l" / "annotator_2.csv")
    assert list(r1[0]) == ["pr_id", "repo", "code_change", "annotator_1", "notes"]
    assert list(r2[0]) == ["pr_id", "repo", "code_change", "annotator_2", "notes"]
    assert r1[0]["annotator_1"] == "" and (tmp_path / "l" / "codebook.txt").exists()


def test_split_refuses_to_overwrite_a_filled_file(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", "")])
    label_tool.main(["split", str(sheet), "--out-dir", str(d)])
    f = d / "annotator_1.csv"
    rows = _read(f)
    rows[0]["annotator_1"] = "1"
    label_tool._write_rows(f, list(rows[0]), rows)
    before = _md5(f)
    assert label_tool.main(["split", str(sheet), "--out-dir", str(d)]) == 2
    assert _md5(f) == before


def test_combine_round_trip_prefixes_notes_and_never_invents_labels(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", ""), ("b", CLEAR_DIFF, "", "", "")])
    label_tool.main(["split", str(sheet), "--out-dir", str(d)])
    r1 = _read(d / "annotator_1.csv")
    r1[0]["annotator_1"], r1[0]["notes"] = "1.0", "torn"     # row b left blank
    label_tool._write_rows(d / "annotator_1.csv", list(r1[0]), r1)
    assert label_tool.main(["combine", str(sheet), str(d / "annotator_1.csv"),
                            str(d / "annotator_2.csv")]) == 0
    out = {r["pr_id"]: r for r in _read(sheet)}
    assert out["a"]["annotator_1"] == "1" and out["a"]["notes"] == "[a1] torn"
    assert out["b"]["annotator_1"] == "" and out["a"]["annotator_2"] == ""
    assert out["a"]["adjudicated"] == ""


def test_combine_refuses_conflicts_and_unknown_ids(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "0", "", "")])
    label_tool.main(["split", str(sheet), "--out-dir", str(d)])
    before = _md5(sheet)
    r1 = _read(d / "annotator_1.csv")
    r1[0]["annotator_1"] = "1"
    label_tool._write_rows(d / "annotator_1.csv", list(r1[0]), r1)
    assert label_tool.main(["combine", str(sheet), str(d / "annotator_1.csv")]) == 2
    r1[0].update(annotator_1="0", pr_id="zzz")
    label_tool._write_rows(d / "annotator_1.csv", list(r1[0]), r1)
    assert label_tool.main(["combine", str(sheet), str(d / "annotator_1.csv")]) == 2
    assert _md5(sheet) == before


# ------------------------------------------------------------ agree / readers


def test_agree_works_offline_from_the_sheet_and_reports_counts(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "datasets", None)       # any import would raise
    sheet = tmp_path / "sheet.csv"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "1", "1", ""), ("b", CLEAR_DIFF, "0", "0", ""),
                   ("c", CLEAR_DIFF, "1", "0", "1"), ("d", CLEAR_DIFF, "1", "0", ""),
                   ("e", CLEAR_DIFF, "", "", "")])
    j, rep = tmp_path / "l.jsonl", tmp_path / "rep.json"
    assert label_tool.main(["agree", str(sheet), "--a", "annotator_1", "--b", "annotator_2",
                            "--to-jsonl", str(j), "--report-json", str(rep)]) == 0
    r = json.loads(rep.read_text())
    assert (r["n"], r["n_rows"], r["n_agreed"], r["n_disagree"]) == (4, 5, 2, 2)
    assert (r["n_adjudicated"], r["n_disagree_unadjudicated"], r["n_written"]) == (1, 1, 3)
    assert r["diff_source"] == "sheet"
    assert {"kappa", "observed_agreement", "table", "reading"} <= set(r)
    lines = [json.loads(l) for l in j.read_text().splitlines()]
    assert {l["pr_id"]: l["label"] for l in lines} == {"a": 1, "b": 0, "c": 1}
    assert all(l["diff_source"] == "sheet" and l["diff"] for l in lines)


def test_readers_accept_bom_and_cp1252_and_normalise_labels(tmp_path):
    bom = tmp_path / "bom.csv"
    _sheet(bom, [("a", CLEAR_DIFF, "TRUE", "1.0", "")], bom=True)
    row = label_tool._read_rows(bom)[0]
    assert "pr_id" in row and label_tool._norm(row["annotator_1"]) == "1"
    assert label_tool._norm(row["annotator_2"]) == "1" and label_tool._norm("FALSE") == "0"

    cp = tmp_path / "cp.csv"
    cp.write_bytes("pr_id,repo,code_change\na,x,café\n".encode("cp1252"))
    assert label_tool._read_rows(cp)[0]["code_change"] == "café"


# ------------------------------------------------------------ page / train


def test_page_embeds_the_diffs_and_no_labels(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF + "</script>", "", "", "")])
    label_tool.main(["split", str(sheet), "--out-dir", str(d)])
    assert label_tool.main(["page", "--out-dir", str(d)]) == 0
    html = (d / "annotator_2.html").read_text(encoding="utf-8")
    assert 'COL="annotator_2"' in html and "validate_user" in html
    assert html.count("</script>") == 1                     # the diff's own tag is escaped
    assert "/*ITEMS*/" not in html and "/*N*/" not in html


def test_train_writes_report_and_creates_model_dir(tmp_path):
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")
    from experiments import train_classifier

    labels = tmp_path / "labels.jsonl"
    with labels.open("w", encoding="utf-8") as fh:
        for i in range(60):
            amb = i % 2 == 0
            fh.write(json.dumps({"pr_id": f"p{i}", "repo": "acme/app", "label": int(amb),
                                 "diff": AMBIGUOUS_DIFF if amb else CLEAR_DIFF}) + "\n")
    rep, model = tmp_path / "rep.json", tmp_path / "new" / "dir" / "clf.joblib"
    rc = train_classifier.main(["--labels", str(labels), "--out", str(model),
                                "--sweep-thresholds",
                                "--thresholds-out", str(tmp_path / "t.json"),
                                "--report-out", str(rep)])
    assert rc == 0 and model.exists()
    r = json.loads(rep.read_text())
    assert {"thresholds", "dev_sweep", "n_labels", "n_ambiguous", "train", "dev"} <= set(r)
    assert r["n_labels"] == 60 and r["n_ambiguous"] == 30


# ------------------------------------------------------------ full-context (real PR) sheet

ISSUE_BODY = "Steps to reproduce: the worker crashes on retry when the queue is empty."
FULL_FIELDS = ["pr_id", "repo", "number", "url", "view", "title", "body", "body_edited",
               "issue_number", "issue_title", "issue_body", "commit_messages", "code_change",
               "diff_truncated", "additions", "deletions", "changed_files", "languages",
               "merged_at", "annotator_1", "annotator_2", "adjudicated", "notes"]


def _full_sheet(path, rows, view="full_context"):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FULL_FIELDS)
        w.writeheader()
        for pr_id, diff, a1, a2, adj, issue in rows:
            n = pr_id.split("#")[1]
            w.writerow({
                "pr_id": pr_id, "repo": pr_id.split("#")[0], "number": n,
                "url": f"https://github.com/{pr_id.split('#')[0]}/pull/{n}", "view": view,
                "title": f"Title {n}", "body": f"Body {n} </script><b>x</b>", "body_edited": "0",
                "issue_number": "12" if issue else "", "issue_title": "Crash" if issue else "",
                "issue_body": ISSUE_BODY if issue else "",
                "commit_messages": json.dumps(["first commit", "second"]), "code_change": diff,
                "diff_truncated": "0", "additions": "3", "deletions": "1", "changed_files": "1",
                "languages": "python", "merged_at": "2025-01-10T00:00:00Z",
                "annotator_1": a1, "annotator_2": a2, "adjudicated": adj, "notes": ""})


def test_split_on_a_full_context_sheet_passes_context_through_and_picks_the_codebook(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _full_sheet(sheet, [("acme/app#1", AMBIGUOUS_DIFF, "", "", "", True)])
    before = _md5(sheet)
    assert label_tool.main(["split", str(sheet), "--out-dir", str(d)]) == 0
    assert _md5(sheet) == before
    r1 = _read(d / "annotator_1.csv")
    assert list(r1[0]) == [c for c in FULL_FIELDS
                           if c not in ("annotator_1", "annotator_2", "adjudicated", "notes",
                                        "url", "merged_at")] + ["annotator_1", "notes"]
    for n in (1, 2):
        path = d / f"annotator_{n}.csv"
        text = path.read_text(encoding="utf-8")
        assert "github.com" not in text and "2025-01-10" not in text
        assert "url" not in _read(path)[0] and "merged_at" not in _read(path)[0]
    assert "url" in _read(sheet)[0] and "merged_at" in _read(sheet)[0]   # master keeps them
    assert r1[0]["title"] == "Title 1" and r1[0]["annotator_1"] == ""
    assert (d / "codebook.txt").read_text(encoding="utf-8") == label_tool.CODEBOOK_FULL
    assert "what a reviewer sees" in label_tool.CODEBOOK_FULL
    assert "Do NOT open the PR on GitHub" in label_tool.CODEBOOK_FULL


def test_code_only_split_and_codebook_are_unchanged(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "", "", "")])
    label_tool.main(["split", str(sheet), "--out-dir", str(d)])
    assert (d / "codebook.txt").read_text(encoding="utf-8") == label_tool.CODEBOOK
    assert label_tool.codebook_for(_read(sheet)) == label_tool.CODEBOOK


def test_split_refuses_a_sheet_that_mixes_views(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _full_sheet(sheet, [("acme/app#1", CLEAR_DIFF, "", "", "", False)])
    rows = _read(sheet)
    rows.append({**rows[0], "pr_id": "acme/app#2", "view": "full_context_opened"})
    label_tool._write_rows(sheet, FULL_FIELDS, rows)
    assert label_tool.main(["split", str(sheet), "--out-dir", str(d)]) == 2
    assert not d.exists()


def test_full_context_page_shows_context_via_textcontent_and_escapes_script_tags(tmp_path):
    sheet, d = tmp_path / "sheet.csv", tmp_path / "l"
    _full_sheet(sheet, [("acme/app#1", AMBIGUOUS_DIFF + "</script>", "", "", "", True)])
    label_tool.main(["split", str(sheet), "--out-dir", str(d)])
    assert label_tool.main(["page", "--out-dir", str(d)]) == 0
    html = (d / "annotator_1.html").read_text(encoding="utf-8")
    assert 'KEY="cr_label_full_1"' in html and 'COL="annotator_1"' in html
    assert 'id="ctx"' in html and "renderCtx(it)" in html and "textContent" in html
    assert "innerHTML" not in html
    assert html.count("</script>") == 1                   # diff and body tags are escaped
    assert "Title 1" in html and "what a reviewer sees" in html and "Steps to reproduce" in html
    assert "/*ITEMS*/" not in html and "/*N*/" not in html
    # the code-only page keeps its own storage key
    sheet2, d2 = tmp_path / "s2.csv", tmp_path / "l2"
    _sheet(sheet2, [("a", CLEAR_DIFF, "", "", "")])
    label_tool.main(["split", str(sheet2), "--out-dir", str(d2)])
    label_tool.main(["page", "--out-dir", str(d2)])
    html2 = (d2 / "annotator_1.html").read_text(encoding="utf-8")
    assert 'KEY="cr_label_1"' in html2 and "renderCtx" not in html2


def test_agree_on_a_full_context_sheet_writes_context_fields_from_the_cache(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "datasets", None)
    sheet = tmp_path / "sheet.csv"
    _full_sheet(sheet, [("acme/app#1", "truncated", "1", "1", "", True),
                        ("acme/app#2", "truncated", "0", "0", "", False),
                        ("acme/app#3", "truncated", "1", "0", "", False)])
    cache = tmp_path / "cache" / "acme__app"
    cache.mkdir(parents=True)
    (cache / "full_1.json").write_text(json.dumps({"diff": AMBIGUOUS_DIFF}), encoding="utf-8")
    (cache / "full_2.json").write_text(json.dumps({"diff": CLEAR_DIFF}), encoding="utf-8")
    j = tmp_path / "l.jsonl"
    assert label_tool.main(["agree", str(sheet), "--a", "annotator_1", "--b", "annotator_2",
                            "--to-jsonl", str(j), "--diff-source", "cache",
                            "--cache-dir", str(tmp_path / "cache")]) == 0
    lines = {l["pr_id"]: l for l in map(json.loads, j.read_text().splitlines())}
    assert set(lines) == {"acme/app#1", "acme/app#2"}
    one = lines["acme/app#1"]
    assert one["diff"] == AMBIGUOUS_DIFF and one["label"] == 1 and one["diff_source"] == "cache"
    assert one["title"] == "Title 1" and one["commit_messages"] == ["first commit", "second"]
    assert (one["issue_number"], one["issue_title"], one["issue_body"]) == (12, "Crash", ISSUE_BODY)
    assert one["view"] == "full_context"
    assert lines["acme/app#2"]["issue_number"] == 0 and lines["acme/app#2"]["issue_body"] == ""


def test_load_labelled_gives_linked_issue_and_real_commit_length_for_full_rows(tmp_path):
    from experiments import train_classifier

    sheet, j = tmp_path / "sheet.csv", tmp_path / "l.jsonl"
    _full_sheet(sheet, [("acme/app#1", AMBIGUOUS_DIFF, "1", "1", "", True),
                        ("acme/app#2", CLEAR_DIFF, "0", "0", "", False)])
    label_tool.main(["agree", str(sheet), "--a", "annotator_1", "--b", "annotator_2",
                     "--to-jsonl", str(j)])
    ctxs, labels = train_classifier.load_labelled(j)
    assert labels == [1, 0]
    from clarifyreview.detect.features import extract

    f1, f2 = extract(ctxs[0]), extract(ctxs[1])
    assert f1["has_linked_issue"] == 1 and f2["has_linked_issue"] == 0
    assert f1["commit_msg_len"] > 0 and f1["pr_body_len"] > 0


def test_code_only_agree_output_keys_are_unchanged(tmp_path):
    sheet, j = tmp_path / "sheet.csv", tmp_path / "l.jsonl"
    _sheet(sheet, [("a", AMBIGUOUS_DIFF, "1", "1", "")])
    label_tool.main(["agree", str(sheet), "--a", "annotator_1", "--b", "annotator_2",
                     "--to-jsonl", str(j)])
    row = json.loads(j.read_text().splitlines()[0])
    assert set(row) == {"pr_id", "repo", "diff", "title", "body", "commit_messages",
                        "issue_body", "label", "diff_source"}
