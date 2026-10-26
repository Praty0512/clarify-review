"""The prose-placeholder plumbing: formats, fail-loud rule, ids kept in step."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs"))

import prose  # noqa: E402
import prose_spec  # noqa: E402
import prose_tool  # noqa: E402

NUMS = {"a": {"rate": 0.6667, "p": 0.625, "n": 96, "ci": [-0.2175, 0.3333], "big": 187121,
              "name": "qwen"}, "lst": [3, 4]}


@pytest.fixture
def files(tmp_path, monkeypatch):
    p = tmp_path / "prose_v3.json"
    monkeypatch.setattr(prose, "PROSE_JSON", p)
    monkeypatch.setattr(prose, "_CACHE", None)
    monkeypatch.delenv("ALLOW_EMPTY_PROSE", raising=False)
    prose.USED.clear()
    yield p
    monkeypatch.setattr(prose, "_CACHE", None)


def test_formats():
    f = prose.fmt
    assert f(0.6667, "pct") == "67%" and f(0.125, "pct") == "13%"
    assert f(0.625, "f2") == "0.63" and f(-0.2175, "f2") == "-0.22"
    assert f([-0.2175, 0.3333], "ci") == "-0.22 to 0.33"
    assert f(187121, "k") == "187,121" and f(11, "word") == "eleven" and f(30, "word") == "30"
    assert f(0.001, "p2") == "<0.01" and f("x", None) == "x" and f(7, None) == "7"
    assert f(None, "pct") == "n/a"
    for bad in ((0.5, None), ([1, 2], None), ("s", "pct"), (1, "nope")):
        with pytest.raises(prose.PlaceholderError):
            f(*bad)


def test_render_resolves_paths_and_rejects_unknown_keys():
    r = prose.render("G {a.rate:pct}, CI {a.ci:ci}, n={a.n}, {lst.1:int} of {a.name}", NUMS)
    assert r == "G 67%, CI -0.22 to 0.33, n=96, 4 of qwen"
    with pytest.raises(prose.PlaceholderError):
        prose.render("{a.missing:pct}", NUMS)


def test_empty_placeholder_fails_unless_scaffold_flag(files, monkeypatch):
    files.write_text(json.dumps({"x.full": "n is {a.n}", "x.empty": "", "x.blank": "  "}),
                     encoding="utf-8")
    assert prose.prose("x.full", NUMS) == "n is 96"
    with pytest.raises(prose.PlaceholderError, match="x.empty"):
        prose.prose("x.empty", NUMS)
    with pytest.raises(prose.PlaceholderError):
        prose.prose("x.blank", NUMS)
    with pytest.raises(prose.PlaceholderError, match="not in"):
        prose.prose("x.absent", NUMS)
    monkeypatch.setenv("ALLOW_EMPTY_PROSE", "1")
    assert prose.prose("x.empty", NUMS) == "[[PROSE:x.empty]]"
    monkeypatch.setenv("ALLOW_EMPTY_PROSE", "0")
    with pytest.raises(prose.PlaceholderError):
        prose.prose("x.empty", NUMS)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_python_and_javascript_format_identically():
    cases = [(0.625, "f2"), (-0.2175, "f2"), (0.0937, "f2"), (0.6667, "pct"), (0.125, "pct"),
             (187121, "k"), (12, "word"), (0.3333, "f3"), (0.004, "p2"), (5, "int"),
             ([-0.75, 1.0], "ci"), (0.5, "f1")]
    js = ("const {fmt}=require('./paper/prose.js');const c=" + json.dumps(cases) +
          ";console.log(JSON.stringify(c.map(([v,s])=>fmt(v,s,'t'))))")
    out = subprocess.run(["node", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == [prose.fmt(v, s) for v, s in cases]


def test_spec_json_and_builders_use_the_same_ids():
    used = prose_tool.used_ids()
    assert set(used) == set(prose_spec.IDS)
    data = json.loads((ROOT / "docs/prose_v3.json").read_text(encoding="utf-8"))
    assert set(data) == set(prose_spec.IDS)
    nums = json.loads((ROOT / "paper/numbers.json").read_text(encoding="utf-8"))
    for e in prose_spec.SPEC:  # every token a writer may use must resolve today
        for t in e["tokens"]:
            path, _, spec = t.partition(":")
            prose.fmt(prose.lookup(path, nums), spec or None, path)


def test_lint_flags_digits_validation_and_foreign_tokens():
    ok = "G was {v3_local.tests.intent_all.gap_recovery:f2} (see Table III and Fig. 6, Section V-G)."
    allowed = {"v3_local.tests.intent_all.gap_recovery"}
    assert prose_tool.lint_text("t", ok, allowed) == []
    assert prose_tool.lint_text("t", "There were 96 rows.", allowed)
    assert prose_tool.lint_text("t", "The judge was validated against humans.", allowed)
    assert prose_tool.lint_text("t", "The judge is not validated against humans.", allowed) == []
    assert prose_tool.lint_text("t", "A trend toward benefit.", allowed)
    assert prose_tool.lint_text("t", "The Gemini judge agreed.", allowed)
    assert prose_tool.lint_text("t", "n = {v3_local.tests.intent_all.n:int}", allowed)
