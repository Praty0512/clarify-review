"""Symbol extraction for JavaScript, TypeScript/TSX, Java, C, C++ and Rust.

Each grammar test skips when its grammar is not installed (the `polyglot` extra),
so the suite passes without the extra. The fallback and Python tests need nothing.
"""

from __future__ import annotations

import difflib

import pytest

from clarifyreview.ingest import from_raw
from clarifyreview.ingest import semantic
from clarifyreview.ingest.diff import parse_unified_diff
from clarifyreview.ingest.semantic import (
    PythonAstExtractor,
    TreeSitterExtractor,
    changed_symbols,
    extractor_for,
)

GRAMMAR = {
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "tsx": "tree_sitter_typescript",
    "java": "tree_sitter_java",
    "rust": "tree_sitter_rust",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
}


def need(lang: str) -> None:
    pytest.importorskip("tree_sitter")
    pytest.importorskip(GRAMMAR[lang])


def make_diff(path: str, pre: str, post: str) -> str:
    lines = difflib.unified_diff(
        pre.splitlines(True), post.splitlines(True), f"a/{path}", f"b/{path}", n=3
    )
    return f"diff --git a/{path} b/{path}\n" + "".join(lines)


def run(path: str, pre: str, post: str):
    """Changed symbols from full pre/post images (the checkout path)."""
    hunks = parse_unified_diff(make_diff(path, pre, post))
    return {s.name: s for s in changed_symbols(hunks, {path: post}, {path: pre})}


JS_PRE = """export class Session {
  validate(user, strict) {
    if (user.email === null) throw new Error("email");
    return user.id;
  }

  _hidden() {
    return 1;
  }
}

export const login = (u) => {
  return u.id;
};

function helper() {
  return 2;
}
"""
JS_POST = (
    JS_PRE.replace("validate(user, strict)", "validate(user)")
    .replace("(u) =>", "(u, opts) =>")
    .replace("return 2;", "return 3;")
)

TS_PRE = """export interface Opts { a: number }

export function run(o: Opts): number {
  return o.a;
}

class Priv {
  private m(x: number): string {
    return "";
  }
}
"""
TS_POST = TS_PRE.replace("run(o: Opts)", "run(o: Opts, k: number)").replace('return "";', 'return "x";')

TSX_PRE = """export const C = (p: {a: number}) => {
  return <div>{p.a}</div>;
};

function Local() {
  return <b/>;
}
"""
TSX_POST = TSX_PRE.replace("{p.a}", "{p.a + 1}").replace("<b/>", "<i/>")

JAVA_PRE = """public class A {
    public int get(String k, int d) {
        Objects.requireNonNull(k);
        return 1;
    }

    private void helper() {
        int x = 1;
    }

    int pkg() {
        return 0;
    }
}

interface I {
    void run();
    default int one() { return 1; }
}
"""
JAVA_POST = (
    JAVA_PRE.replace("get(String k, int d)", "get(String k)")
    .replace("        Objects.requireNonNull(k);\n", "")
    .replace("int x = 1;", "int x = 2;")
    .replace("return 1; }", "return 2; }")
    .replace("return 0;", "return 5;")
)

RUST_PRE = """pub struct Foo;

impl Foo {
    pub fn go(&self, x: u32) -> u32 {
        assert!(x > 0);
        x
    }

    fn hidden(&self) {
        let a = 1;
    }
}

pub fn free(a: i32) -> i32 {
    a
}
"""
RUST_POST = (
    RUST_PRE.replace("x: u32) -> u32", "x: u64) -> u64")
    .replace("        assert!(x > 0);\n", "")
    .replace("let a = 1;", "let a = 2;")
    .replace("    a\n}", "    a + 1\n}")
)

C_PRE = """static int helper(int a) {
    return a;
}

int *get(char *p, int n) {
    assert(p != NULL);
    return 0;
}

int _internal(void) {
    return 1;
}
"""
C_POST = (
    C_PRE.replace("return a;", "return a + 1;")
    .replace("char *p, int n", "char *p")
    .replace("    assert(p != NULL);\n", "")
    .replace("return 1;", "return 2;")
)

CPP_PRE = """namespace ns {
class Foo {
public:
    int bar(int x) const {
        if (!x) return 0;
        return 1;
    }
private:
    void p() {
        int a = 1;
    }
};
}

int ns::Foo::baz(int y) {
    return y;
}
"""
CPP_POST = (
    CPP_PRE.replace("bar(int x)", "bar(long x)")
    .replace("        if (!x) return 0;\n", "")
    .replace("int a = 1;", "int a = 2;")
    .replace("return y;", "return y + 1;")
)


def test_javascript_symbols_publicness_and_signature_change():
    need("javascript")
    got = run("src/auth.js", JS_PRE, JS_POST)
    assert set(got) == {"Session.validate", "login", "helper"}
    assert got["Session.validate"].kind == "method"
    assert got["Session.validate"].is_public and got["Session.validate"].signature_changed
    assert got["login"].kind == "function" and got["login"].signature_changed
    assert got["login"].signature == "(u, opts)"
    assert not got["helper"].is_public  # not exported
    assert not got["helper"].signature_changed


def test_javascript_underscore_method_is_private():
    need("javascript")
    syms = {s.name: s for s in TreeSitterExtractor("javascript").symbols(JS_PRE)}
    assert not syms["Session._hidden"].is_public
    assert syms["Session"].kind == "class" and syms["Session"].is_public


@pytest.mark.parametrize("path", ["a.mjs", "a.cjs", "a.jsx"])
def test_javascript_extensions(path):
    need("javascript")
    assert isinstance(extractor_for(path), TreeSitterExtractor)


def test_typescript_loads_despite_missing_language_function():
    """tree_sitter_typescript has language_typescript()/language_tsx(), no language()."""
    need("typescript")
    got = run("src/a.ts", TS_PRE, TS_POST)
    assert got["run"].signature_changed and got["run"].is_public
    assert got["run"].signature == "(o: Opts, k: number) -> number"
    assert got["Priv.m"].kind == "method" and not got["Priv.m"].is_public
    names = {s.name: s for s in TreeSitterExtractor("typescript").symbols(TS_PRE)}
    assert names["Opts"].kind == "class"  # interface


@pytest.mark.parametrize("path", ["a.mts", "a.cts"])
def test_typescript_extensions(path):
    need("typescript")
    assert isinstance(extractor_for(path), TreeSitterExtractor)


def test_tsx_component():
    need("tsx")
    got = run("src/C.tsx", TSX_PRE, TSX_POST)
    assert got["C"].is_public and got["C"].kind == "function"
    assert not got["Local"].is_public


def test_java_methods_overloads_and_visibility():
    need("java")
    got = run("src/A.java", JAVA_PRE, JAVA_POST)
    assert got["A.get"].kind == "method"
    assert got["A.get"].is_public and got["A.get"].signature_changed
    assert got["A.get"].signature == "(String k) -> int"
    assert not got["A.helper"].is_public
    assert not got["A.pkg"].is_public  # package-private
    syms = {s.name: s for s in TreeSitterExtractor("java").symbols(JAVA_PRE)}
    assert syms["I.run"].is_public  # interface members are implicitly public


def test_java_overloads_are_not_mistaken_for_signature_changes():
    need("java")
    pre = "class A {\n    void f(int a) { }\n\n    void f(String s) { int q = 1; }\n}\n"
    post = pre.replace("int q = 1;", "int q = 2;")
    got = run("A.java", pre, post)
    assert list(got) == ["A.f"]
    assert not got["A.f"].signature_changed
    assert got["A.f"].signature == "(String s) -> void"


def test_rust_impl_methods_are_qualified_and_pub_decides_publicness():
    need("rust")
    got = run("src/lib.rs", RUST_PRE, RUST_POST)
    assert got["Foo.go"].kind == "method"
    assert got["Foo.go"].is_public and got["Foo.go"].signature_changed
    assert got["Foo.go"].signature == "(&self, x: u64) -> u64"
    assert not got["Foo.hidden"].is_public
    assert got["free"].kind == "function" and got["free"].is_public
    syms = {s.name: s for s in TreeSitterExtractor("rust").symbols(RUST_PRE)}
    assert syms["Foo"].kind == "class"


def test_c_static_and_underscore_are_not_public():
    need("c")
    got = run("src/a.c", C_PRE, C_POST)
    assert not got["helper"].is_public  # static
    assert not got["_internal"].is_public  # leading underscore
    assert got["get"].is_public and got["get"].signature_changed
    assert got["get"].signature == "(char *p) -> int"  # pointer stripped from the name


def test_c_struct_reference_is_not_a_symbol():
    need("c")
    syms = TreeSitterExtractor("c").symbols("struct foo *make(void) { return 0; }\nstruct bar { int x; };\n")
    assert {s.name for s in syms} == {"make", "bar"}


def test_cpp_methods_namespaces_and_access():
    need("cpp")
    got = run("src/a.cpp", CPP_PRE, CPP_POST)
    assert got["ns.Foo.bar"].kind == "method"
    assert got["ns.Foo.bar"].is_public and got["ns.Foo.bar"].signature_changed
    assert not got["ns.Foo.p"].is_public  # private section
    # Out-of-line definition: qualified name, so it is a method.
    assert got["ns.Foo.baz"].kind == "method"
    syms = {s.name: s for s in TreeSitterExtractor("cpp").symbols(CPP_PRE)}
    assert syms["ns.Foo"].kind == "class"


@pytest.mark.parametrize("path", ["a.cc", "a.cpp", "a.cxx", "a.hpp", "a.hh"])
def test_cpp_extensions(path):
    need("cpp")
    assert isinstance(extractor_for(path), TreeSitterExtractor)


def test_header_files_parse_as_c():
    need("c")
    assert isinstance(extractor_for("include/x.h"), TreeSitterExtractor)


def test_one_hunk_spanning_two_functions_reports_both():
    need("c")
    got = run("a.c", "int f(void) {\n    return 1;\n}\nint g(void) {\n    return 2;\n}\n",
              "int f(void) {\n    return 3;\n}\nint g(void) {\n    return 4;\n}\n")
    assert set(got) == {"f", "g"}


def test_deleted_function_is_reported_removed():
    need("rust")
    pre = "pub fn keep() {\n    let a = 1;\n}\n\npub fn gone(x: i32) {\n    let b = 2;\n}\n"
    post = "pub fn keep() {\n    let a = 1;\n}\n"
    got = run("src/lib.rs", pre, post)
    assert got["gone"].change == "removed"


def test_parser_is_cached_per_language():
    need("javascript")
    assert semantic._parser("javascript") is semantic._parser("javascript")


def test_from_raw_end_to_end_each_language():
    for lang, path, pre, post in [
        ("javascript", "src/auth.js", JS_PRE, JS_POST),
        ("java", "src/A.java", JAVA_PRE, JAVA_POST),
        ("rust", "src/lib.rs", RUST_PRE, RUST_POST),
        ("c", "src/a.c", C_PRE, C_POST),
    ]:
        need(lang)
        ctx = from_raw("o/r#1", make_diff(path, pre, post), title="t")
        assert ctx.languages == [lang]
        assert ctx.changed_symbols, lang


# ------------------------------------------------ fallback: no grammar needed


SECTION_DIFFS = {
    "rust": ("src/lib.rs", "pub fn handle(req: Request) -> Response {", "handle", True),
    "javascript": ("web/app.js", "export function render(props) {", "render", True),
    "typescript": ("web/app.ts", "class Store {", "Store", False),
    "java": ("src/Main.java", "    public void process(Event e) {", "process", True),
    "c": ("src/a.c", "static int parse(const char *s)", "parse", False),
    "cpp": ("src/a.cc", "int Foo::run(int x)", "run", True),
}


def section_diff(path: str, section: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -40,3 +40,3 @@ {section}\n context\n-old line\n+new line\n context\n"
    )


@pytest.mark.parametrize("lang", sorted(SECTION_DIFFS))
def test_fallback_uses_hunk_section_when_grammar_unavailable(lang, monkeypatch):
    def boom(*_a, **_k):
        raise ImportError("grammar missing")

    monkeypatch.setattr(semantic, "_parser", boom)
    path, section, name, public = SECTION_DIFFS[lang]
    ctx = from_raw("o/r#1", section_diff(path, section), title="t")
    assert extractor_for(path) is None
    [sym] = ctx.changed_symbols
    assert sym.name == name
    assert sym.kind == ("class" if name == "Store" else "function")
    assert sym.start_line == sym.end_line == 40
    assert sym.signature == "" and sym.change == "modified"
    assert sym.is_public is public


def test_fallback_when_parse_yields_nothing():
    """A grammar that is installed but finds no symbols in a fragment still falls
    back to the git function context."""
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_rust")
    ctx = from_raw("o/r#1", section_diff("src/lib.rs", "pub fn handle(req: Request) {"), title="t")
    assert [s.name for s in ctx.changed_symbols] == ["handle"]


def test_fallback_without_section_gives_nothing(monkeypatch):
    monkeypatch.setattr(semantic, "_parser", lambda *_a: (_ for _ in ()).throw(ImportError()))
    diff = "diff --git a/x.rs b/x.rs\n--- a/x.rs\n+++ b/x.rs\n@@ -1,1 +1,1 @@\n-a\n+b\n"
    assert from_raw("o/r#1", diff, title="t").changed_symbols == []


def test_unsupported_extension_has_no_symbols():
    diff = "diff --git a/x.kt b/x.kt\n--- a/x.kt\n+++ b/x.kt\n@@ -1,1 +1,1 @@ fun main() {\n-a\n+b\n"
    assert extractor_for("x.kt") is None
    assert from_raw("o/r#1", diff, title="t").changed_symbols == []


# ------------------------------------------------------- Python is unchanged


def test_python_still_uses_ast_and_ignores_section_fallback():
    assert isinstance(extractor_for("a/b.py"), PythonAstExtractor)
    # Unparseable Python image: no symbols, and no regex fallback from the section.
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -5,3 +5,3 @@ def validate(x):\n     y = (\n-    1\n+    2\n"
    )
    assert from_raw("o/r#1", diff, title="t").changed_symbols == []


def test_python_symbols_have_no_explicit_publicness():
    syms = PythonAstExtractor().symbols("def _a():\n    pass\n\ndef b():\n    pass\n")
    assert all(s.public is None for s in syms)
    assert [s.is_public for s in syms] == [False, True]
