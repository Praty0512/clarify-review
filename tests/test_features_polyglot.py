"""Feature extraction beyond Python, and the Python invariance snapshot.

The snapshot (tests/fixtures/python_snapshot.json) was captured from the
single-language implementation: `examples/*.diff`, the conftest diffs and 50
SWE-bench rows of runs/labelling_sheet.csv. Multi-language support must not move
a single Python feature value, symbol or context fingerprint, or the trained
classifier and its thresholds would silently shift.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clarifyreview.detect.features import _TEST_FILE, extract
from clarifyreview.ingest import from_raw

SNAPSHOT = Path(__file__).parent / "fixtures" / "python_snapshot.json"


def _cases():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_snapshot_has_the_expected_coverage():
    ids = [c["id"] for c in _cases()]
    assert "conftest_ambiguous" in ids and "conftest_clear" in ids
    assert any(i.endswith(".diff") for i in ids)
    assert len(ids) >= 50


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["id"])
def test_python_features_symbols_and_fingerprint_are_byte_identical(case):
    ctx = from_raw(
        case["id"],
        case["diff"],
        title=case["title"],
        commit_messages=case["commit_messages"],
    )
    assert json.dumps(extract(ctx), sort_keys=True) == json.dumps(case["features"], sort_keys=True)
    assert [s.model_dump() for s in ctx.changed_symbols] == case["symbols"]
    assert ctx.languages == case["languages"]
    assert ctx.fingerprint() == case["fingerprint"]


def _diff(path: str, removed: list[str], added: list[str], section: str = "") -> str:
    body = "".join(f"-{line}\n" for line in removed) + "".join(f"+{line}\n" for line in added)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -10,{len(removed) + 1} +10,{len(added) + 1} @@ {section}\n context\n{body}"
    )


def feats(path: str, removed: list[str], added: list[str], **kw):
    return extract(from_raw("o/r#1", _diff(path, removed, added), title="t", commit_messages=["fix"], **kw))


@pytest.mark.parametrize(
    "path",
    [
        "src/__tests__/auth.js",
        "web/__tests__/App.tsx",
        "web/a.test.jsx",
        "lib/b.spec.mjs",
        "src/test/java/com/x/FooTest.java",
        "app/FooTests.java",
        "app/FooIT.java",
        "src/foo_test.cc",
        "src/foo_unittest.cc",
        "src/test_foo.c",
        # already matched before this change
        "tests/test_x.py",
        "a_test.go",
        "x.spec.ts",
    ],
)
def test_test_files_recognised(path):
    assert _TEST_FILE.search(path), path
    assert feats(path, ["a"], ["b"])["test_file_changed"] == 1.0


@pytest.mark.parametrize(
    "path", ["src/auth.js", "src/Foo.java", "src/lib.rs", "src/a.c", "src/contest.py", "latest.js"]
)
def test_non_test_files_not_flagged(path):
    assert feats(path, ["a"], ["b"])["test_file_changed"] == 0.0


GUARD_REMOVALS = {
    "js-null-check": ("a.js", ["  if (user == null) {", "    return;", "  }"], ["  return;"]),
    "js-strict-undefined": ("a.ts", ["  if (x === undefined) return 0;"], ["  return 1;"]),
    "js-not": ("a.jsx", ["  if (!token) throw new Error('x');"], ["  use(token);"]),
    "java-requireNonNull": ("A.java", ["        Objects.requireNonNull(k);"], ["        use(k);"]),
    "java-preconditions": ("A.java", ["        Preconditions.checkArgument(n > 0);"], ["        use(n);"]),
    "java-null-if": ("A.java", ["        if (k == null) return;"], ["        use(k);"]),
    "rust-assert": ("a.rs", ["    assert!(x > 0);"], ["    use_it(x);"]),
    "rust-ensure": ("a.rs", ["    ensure!(x > 0, \"bad\");"], ["    use_it(x);"]),
    "rust-bail": ("a.rs", ["    bail!(\"nope\");"], ["    use_it(x);"]),
    "c-assert": ("a.c", ["    assert(p != NULL);"], ["    use(p);"]),
    "c-null-if": ("a.c", ["    if (p == NULL) return -1;"], ["    use(p);"]),
    "cpp-not-ptr": ("a.cc", ["    if (!ptr) return;"], ["    use(ptr);"]),
}


@pytest.mark.parametrize("name", sorted(GUARD_REMOVALS))
def test_removed_guard_counted_per_language(name):
    path, removed, added = GUARD_REMOVALS[name]
    assert feats(path, removed, added)["removes_guard"] == 1.0, name


@pytest.mark.parametrize("name", sorted(GUARD_REMOVALS))
def test_guard_moved_not_removed(name):
    path, removed, added = GUARD_REMOVALS[name]
    assert feats(path, removed, removed + added)["removes_guard"] == 0.0, name


def test_unrelated_non_python_change_removes_no_guard():
    assert feats("a.rs", ["    let a = 1;"], ["    let a = 2;"])["removes_guard"] == 0.0
    assert feats("a.js", ["  const a = 1;"], ["  const a = 2;"])["removes_guard"] == 0.0


def test_language_rules_apply_only_to_their_own_files():
    """`== NULL` removed from a Python file is not a C guard; Python rules decide."""
    assert feats("a.py", ["    x = p == NULL"], ["    x = 1"])["removes_guard"] == 0.0


def test_error_handling_per_language():
    assert feats("a.rs", ["    let v = f()?;"], ["    let v = f().unwrap();"])["modifies_error_handling"] == 1.0
    assert feats("a.rs", ["    return Ok(1);"], ["    return Err(e);"])["modifies_error_handling"] == 1.0
    assert feats("a.js", ["  p.then(f);"], ["  p.then(f).catch(g);"])["modifies_error_handling"] == 1.0
    assert feats("A.java", ["void f() {"], ["void f() throws IOException {"])["modifies_error_handling"] == 1.0
    assert feats("a.c", ["  r = f();"], ["  r = f(); if (r) goto err;"])["modifies_error_handling"] == 1.0
    assert feats("a.c", ["  r = 1;"], ["  r = 2;"])["modifies_error_handling"] == 0.0


def test_sensitive_per_language():
    assert feats("a.js", ["  x = 1;"], ["  el.innerHTML = s;"])["touches_sensitive_symbol"] == 1.0
    assert feats("a.js", ["  x = 1;"], ["  const cp = require('child_process');"])["touches_sensitive_symbol"] == 1.0
    assert feats("A.java", ["  x = 1;"], ["  Runtime.getRuntime().exec(c);"])["touches_sensitive_symbol"] == 1.0
    assert feats("a.rs", ["  x = 1;"], ["  unsafe { f() }"])["touches_sensitive_symbol"] == 1.0
    assert feats("a.c", ["  x = 1;"], ["  strcpy(dst, src);"])["touches_sensitive_symbol"] == 1.0
    assert feats("a.c", ["  n = 1;"], ["  n = 2;"])["touches_sensitive_symbol"] == 0.0


def test_public_symbol_from_fallback_counts_for_rust(monkeypatch):
    from clarifyreview.ingest import semantic

    monkeypatch.setattr(semantic, "_parser", lambda *_a: (_ for _ in ()).throw(ImportError()))
    ctx = from_raw(
        "o/r#1",
        _diff("src/lib.rs", ["a"], ["b"], section="pub fn handle(x: u32) -> u32 {"),
        title="t",
    )
    assert extract(ctx)["touches_public_symbol"] == 1.0
    ctx = from_raw(
        "o/r#1", _diff("src/lib.rs", ["a"], ["b"], section="fn handle(x: u32) {"), title="t"
    )
    assert extract(ctx)["touches_public_symbol"] == 0.0
