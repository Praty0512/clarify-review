"""Live-tool support for large repositories: triage, polyglot context, checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clarifyreview.ingest import from_raw
from clarifyreview.ingest.checkout import _dirs_for, _git_env, _sparse_patterns, sparse_checkout
from clarifyreview.ingest.context import _CALL_RE, build_neighbourhood
from clarifyreview.ingest.triage import DOCS, OTHER, SOURCE, TEST, group_of, prioritise, skip_reason
from clarifyreview.types import ChangedSymbol


def _block(path: str, added: str = "x = 1") -> str:
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -1,1 +1,2 @@\n context\n+{added}\n")


@pytest.mark.parametrize("path", [
    "package-lock.json", "web/yarn.lock", "Cargo.lock", "go.sum", "static/app.min.js",
    "api/foo_pb2.py", "node_modules/x/index.js", "third_party/lib/a.c",
    "src/__snapshots__/a.test.ts.snap", "tests/baselines/reference/x.types",
])
def test_noise_files_are_skipped(path):
    assert skip_reason(path)


@pytest.mark.parametrize("path", [
    "src/app.py", "lib/parser.ts", "Cargo.toml", "README.md", "build.rs", "src/vendors.py",
])
def test_real_files_are_kept(path):
    assert skip_reason(path) is None


def test_groups():
    assert group_of("src/app.py") == SOURCE
    assert group_of("tests/test_app.py") == TEST
    assert group_of("src/app.test.ts") == TEST
    assert group_of("pkg/thing_test.go") == TEST
    assert group_of("pyproject.toml") == OTHER
    assert group_of("docs/guide.md") == DOCS


def test_prioritise_orders_source_first_and_drops_noise():
    diff = (_block("README.md") + _block("package-lock.json") + _block("tests/test_a.py")
            + _block("src/z.py") + _block("src/a.py"))
    out, skipped = prioritise(diff)
    order = [line.split(" b/")[1] for line in out.splitlines() if line.startswith("diff --git")]
    assert order == ["src/z.py", "src/a.py", "tests/test_a.py", "README.md"]
    assert skipped == ["package-lock.json"]


def test_prioritise_extra_globs_and_headerless_diff():
    out, skipped = prioritise(_block("src/a.py") + _block("schema/gen.sql"), ("schema/*",))
    assert skipped == ["schema/gen.sql"]
    raw = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert prioritise(raw) == (raw, [])


def test_live_keeps_source_when_noise_would_exhaust_budget():
    noise = _block("package-lock.json", "y" * 40_000) + _block("web/yarn.lock", "y" * 40_000)
    diff = noise + _block("src/main.py", "def main():\n+    return 1\n+" + "#" * 20_000)
    study = from_raw("t", diff)
    live = from_raw("t", diff, live=True)
    assert "return 1" not in study.diff  # the study path is unchanged: lockfiles first
    assert "return 1" in live.diff and "package-lock.json" not in live.diff
    assert live.skipped_files == ["package-lock.json", "web/yarn.lock"]
    assert "Left out as generated" in live.render()
    assert "Left out" not in study.render()


def test_call_regex():
    found = _CALL_RE.findall("let v = parse::<u8>(s); helper(x); obj.run (); if (a) {}")
    assert {"helper", "run", "if"} <= set(found)


@pytest.mark.parametrize("ext,callee_src,caller_src", [
    ("ts", "export function helper(a: number) { return a + 1; }",
     "export function changed(x: number) {\n  return helper(x) * 2;\n}\n"),
    ("rs", "pub fn helper(a: u32) -> u32 { a + 1 }",
     "pub fn changed(x: u32) -> u32 {\n    helper(x) * 2\n}\n"),
])
def test_polyglot_neighbourhood(tmp_path: Path, ext, callee_src, caller_src):
    pytest.importorskip("tree_sitter")
    (tmp_path / "src").mkdir()
    (tmp_path / f"src/util.{ext}").write_text(callee_src + "\n", encoding="utf-8")
    (tmp_path / f"src/main.{ext}").write_text(caller_src, encoding="utf-8")
    sym = ChangedSymbol(file=f"src/main.{ext}", name="changed", kind="function",
                        start_line=1, end_line=3, change="modified")
    off, _ = build_neighbourhood(tmp_path, [sym])
    on, _ = build_neighbourhood(tmp_path, [sym], polyglot=True)
    assert off == []
    assert [(s.file, s.name, s.relation) for s in on] == [(f"src/util.{ext}", "helper", "callee")]


def test_dirs_for_ranks_and_caps():
    paths = ["a/x.py", "a/y.py", "b/z.py", "top.py", "tests/cases/t1.ts", "README.md"]
    assert _dirs_for(paths) == [".", "a", "b"]
    assert _dirs_for(paths, max_dirs=1) == ["a"]


def test_sparse_patterns_never_take_whole_subtrees():
    pats = _sparse_patterns(["Herebyfile.mjs", "src/a.ts", "tests/cases/t1.ts"])
    assert pats == ["/*", "!/*/", "/src/*", "!/src/*/",
                    "/Herebyfile.mjs", "/src/a.ts", "/tests/cases/t1.ts"]


def test_token_never_in_argv():
    env = _git_env("secret-token")
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert "secret-token" not in env["GIT_CONFIG_VALUE_0"]  # base64-encoded


def test_sparse_checkout_rejects_bad_sha(tmp_path):
    assert sparse_checkout("o/r", "not-a-sha", ["a.py"], tmp_path) is None


def test_sparse_checkout_from_local_remote(tmp_path):
    """End to end against a local bare repository standing in for GitHub."""
    src = tmp_path / "src"
    (src / "pkg").mkdir(parents=True)
    (src / "pkg/a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (src / "other").mkdir()
    (src / "other/b.py").write_text("b = 2\n", encoding="utf-8")

    def git(*args, cwd=src):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                              text=True).stdout.strip()
    try:
        git("init", "-q")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    git("config", "uploadpack.allowFilter", "true")
    git("config", "uploadpack.allowAnySHA1InWant", "true")
    sha = git("rev-parse", "HEAD")
    host = (tmp_path).as_uri()
    (tmp_path / "o").mkdir()
    git("clone", "-q", "--bare", str(src), str(tmp_path / "o" / "r.git"), cwd=tmp_path)
    git("config", "uploadpack.allowFilter", "true", cwd=tmp_path / "o" / "r.git")
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=tmp_path / "o" / "r.git")

    dest = sparse_checkout("o/r", sha, ["pkg/a.py"], tmp_path / "co", host=host)
    assert dest is not None
    assert (dest / "pkg/a.py").exists()
    assert not (dest / "other/b.py").exists()
    assert sparse_checkout("o/r", sha, ["pkg/a.py"], tmp_path / "co", host=host) == dest


def test_go_symbols_and_changed_method():
    pytest.importorskip("tree_sitter_go")
    from clarifyreview.ingest.semantic import changed_symbols, extractor_for
    from clarifyreview.ingest.diff import parse_unified_diff

    src = ("package x\n\ntype Timer struct{ d int }\n\n"
           "func (t *Timer) Reset(d int) error {\n\treturn helper(d)\n}\n\n"
           "func helper(d int) error { return nil }\n")
    syms = {s.name: s for s in extractor_for("t.go").symbols(src)}
    assert syms["Timer"].kind == "class"
    assert syms["Timer.Reset"].kind == "method" and syms["Timer.Reset"].signature == "(d int) -> error"
    assert syms["helper"].public is False and syms["Timer"].public is True

    diff = ("diff --git a/t.go b/t.go\n--- a/t.go\n+++ b/t.go\n"
            "@@ -5,3 +5,3 @@ func (t *Timer) Reset(d int) error {\n"
            " func (t *Timer) Reset(d int) error {\n-\treturn nil\n+\treturn helper(d)\n }\n")
    got = changed_symbols(parse_unified_diff(diff), {"t.go": src}, {"t.go": src.replace("helper(d)", "nil", 1)})
    assert [(s.name, s.kind) for s in got] == [("Timer.Reset", "method")]


# ------------------------------------------------- GitHub pull request review


def _review(findings):
    from clarifyreview.types import ReviewOutput

    return ReviewOutput(intent_summary="Trim titles before slugifying.", findings=findings,
                        overall_confidence=0.8,
                        verdict="request_changes" if findings else "approve")


def _finding(file, line, severity="major"):
    from clarifyreview.types import ReviewFinding

    return ReviewFinding(file=file, line=line, severity=severity, category="correctness",
                         claim="Disabled users can log in.", evidence="the check is gone",
                         suggested_fix="Restore the check.", confidence=0.9)


def test_pr_review_puts_findings_on_changed_lines():
    from clarifyreview.ingest.diff import parse_unified_diff
    from clarifyreview.review.render import build_pr_review, commentable_lines

    diff = ("diff --git a/app/auth.py b/app/auth.py\n--- a/app/auth.py\n+++ b/app/auth.py\n"
            "@@ -10,4 +10,3 @@ def login(user):\n     a = 1\n-    if user.disabled:\n"
            "-        raise Error\n+    b = 2\n     return a\n")
    hunks = parse_unified_diff(diff)
    assert commentable_lines(hunks) == {"app/auth.py": {10, 11, 12}}
    event, body, inline = build_pr_review(
        _review([_finding("app/auth.py", 11), _finding("app/other.py", 3, "minor")]), hunks)
    assert event == "REQUEST_CHANGES"
    assert inline == [{"path": "app/auth.py", "line": 11, "side": "RIGHT",
                       "body": inline[0]["body"]}]
    assert "Disabled users can log in." in inline[0]["body"]
    assert "Outside the changed lines" in body and "`app/other.py`:3" in body
    assert build_pr_review(_review([]), hunks)[0] == "APPROVE"


class _Resp:
    def __init__(self, code):
        self.status_code = code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"id": 1}


def test_create_review_falls_back_on_own_pr_and_bad_lines():
    from clarifyreview.gh.client import GitHubClient

    sent = []
    codes = iter([422, 422, 200])
    gh = GitHubClient.__new__(GitHubClient)
    gh._request = lambda method, path, json: (sent.append(json), _Resp(next(codes)))[1]
    gh.create_review("o/r", 1, commit_id="abc", event="APPROVE", body="b",
                     comments=[{"path": "a.py", "line": 3, "side": "RIGHT", "body": "x"}])
    assert [s["event"] for s in sent] == ["APPROVE", "COMMENT", "COMMENT"]
    assert sent[2]["comments"] == [] and "`a.py`:3" in sent[2]["body"]
