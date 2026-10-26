import json

import pytest

from experiments.build_study_set import load_swebench_rows, merge_superset


def _row(pr_id, diff="d"):
    return {"pr_id": pr_id, "diff": diff}


def test_merge_keeps_base_rows_first_and_appends_new(tmp_path):
    base = tmp_path / "v2.jsonl"
    base.write_text("\n".join(json.dumps(_row(i), sort_keys=True) for i in ("a", "b")) + "\n")
    merged = merge_superset([_row("c"), _row("b"), _row("a")], str(base))
    assert [r["pr_id"] for r in merged] == ["a", "b", "c"]


def test_merge_rejects_changed_or_missing_base_row(tmp_path):
    base = tmp_path / "v2.jsonl"
    base.write_text(json.dumps(_row("a")) + "\n")
    with pytest.raises(ValueError):
        merge_superset([_row("a", diff="other")], str(base))
    with pytest.raises(ValueError):
        merge_superset([_row("z")], str(base))


def test_local_dataset_file_needs_no_datasets_package(tmp_path):
    f = tmp_path / "swe.jsonl"
    f.write_text(json.dumps({"instance_id": "x__x-1", "repo": "x/x"}) + "\n")
    assert list(load_swebench_rows(str(f))) == ["x__x-1"]
