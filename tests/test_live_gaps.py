"""Live-tool-only behaviour: default thresholds, body-reference issues, Python
symbols without a checkout. None of it may leak into the study defaults."""

import json

import httpx
import pytest

from clarifyreview import detect
from clarifyreview.config import reset_settings
from clarifyreview.gh.client import GitHubClient
from clarifyreview.gh.linked import body_issue_number
from clarifyreview.ingest import from_raw
from clarifyreview.detect.base import DEFAULT_THRESHOLDS

API = "https://api.github.com"
NO_CLOSING = {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": []}}}}}


def make(routes):
    def handler(request):
        if request.url.path == "/graphql":
            return httpx.Response(200, json=NO_CLOSING)
        r = routes.get(request.url.path)
        return httpx.Response(200, json=r) if r is not None else httpx.Response(404, json={})
    return GitHubClient(token="t", api_url=API, transport=httpx.MockTransport(handler),
                        sleep=lambda s: None)


# ---------------------------------------------------------------- gap 2


def test_body_regex_matches_fetch_prs():
    from experiments import fetch_prs
    assert fetch_prs._FIXES is not None
    for body in ("Fixes #5774.", "closes: #3", "Resolved #9", "fix other/repo#4 and #7",
                 "see #1", "fix a/b#2"):
        assert fetch_prs._body_issue_number(body, "a/b") == body_issue_number(body, "a/b")
    assert body_issue_number("fixes #5774", "pallets/flask") == 5774
    assert body_issue_number("fix other/repo#4", "a/b") is None
    assert body_issue_number(None, "a/b") is None


def test_linked_issue_falls_back_to_pr_body():
    gh = make({
        "/repos/a/b/pulls/1": {"body": "This fixes #7 nicely"},
        "/repos/a/b/issues/7": {"title": "Bug", "body": "details"},
    })
    issue = gh.get_linked_issue("a/b", 1)
    assert (issue.number, issue.title, issue.body) == (7, "Bug", "details")


def test_linked_issue_fallback_skips_pull_requests_and_dead_links():
    gh = make({"/repos/a/b/pulls/1": {"body": "fixes #7"},
               "/repos/a/b/issues/7": {"title": "x", "pull_request": {}}})
    assert gh.get_linked_issue("a/b", 1) is None
    gh = make({"/repos/a/b/pulls/1": {"body": "fixes #8"}})  # 404
    assert gh.get_linked_issue("a/b", 1) is None
    gh = make({"/repos/a/b/pulls/1": {"body": "no reference"}})
    assert gh.get_linked_issue("a/b", 1) is None


# ---------------------------------------------------------------- gap 1


def test_live_thresholds_default_unless_opted_in(tmp_path, monkeypatch):
    monkeypatch.delenv("CLARIFYREVIEW_THRESHOLDS_PATH", raising=False)
    reset_settings()
    t = detect.live_thresholds()
    assert t.values == DEFAULT_THRESHOLDS and "defaults" in t.source
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"heuristic": 0.8}))
    monkeypatch.setenv("CLARIFYREVIEW_THRESHOLDS_PATH", str(f))
    reset_settings()
    try:
        t = detect.live_thresholds()
        assert t.values["heuristic"] == 0.8 and str(f) in t.source
        monkeypatch.setenv("CLARIFYREVIEW_THRESHOLDS_PATH", str(tmp_path / "missing.json"))
        reset_settings()
        with pytest.raises(FileNotFoundError):
            detect.live_thresholds()
    finally:
        monkeypatch.delenv("CLARIFYREVIEW_THRESHOLDS_PATH", raising=False)
        reset_settings()


def test_study_build_still_reads_frozen_file():
    from clarifyreview.config import settings
    assert settings().clarifyreview_thresholds_path is None
    assert detect.build("heuristic").thresholds.source == str(settings().thresholds_path)


# ---------------------------------------------------------------- gap 3

PY_DIFF = """diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -10,6 +10,7 @@ class Greeter:
     def greet(self, name):
-        return "hi " + name
+        msg = "hi " + name
+        return msg
 
     def other(self):
         pass
"""


def test_python_symbols_off_by_default_on_for_live():
    off = from_raw("x#1", PY_DIFF)
    assert off.changed_symbols == []
    on = from_raw("x#1", PY_DIFF, python_fallback=True)
    assert [s.name for s in on.changed_symbols] == ["greet"]


def test_python_section_regex_fallback_without_grammar(monkeypatch):
    import clarifyreview.ingest.semantic as sem

    def boom(*a, **k):
        raise ImportError("no grammar")
    monkeypatch.setattr(sem, "TreeSitterExtractor", boom)
    ctx = from_raw("x#1", PY_DIFF, python_fallback=True)
    assert [s.name for s in ctx.changed_symbols] == ["Greeter"]
