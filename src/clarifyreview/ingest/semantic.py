"""Semantic diffing: which *symbols* changed, not which lines.

The proposal names tree-sitter. For the Python-only scope this project actually
needs, the standard library's `ast` module is strictly better: it is exact rather
than approximate, it ships with the interpreter, and it cannot drift between
versions of a third-party grammar. Tree-sitter is kept behind the same protocol
as the path to other languages, and is used automatically when the optional
`polyglot` extra is installed and the file is not Python.

Both extractors answer one question: given the pre- and post-image of a file and
the line ranges the diff touched, which functions and classes did it touch, and
did any of their signatures change?
"""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from ..types import ChangedSymbol
from .diff import Hunk, changed_line_ranges, removed_line_ranges


@dataclass(frozen=True)
class _Symbol:
    name: str
    kind: str
    start: int
    end: int
    signature: str
    public: bool | None = None  # language-specific verdict; None = Python naming rule

    @property
    def is_public(self) -> bool:
        if self.public is not None:
            return self.public
        return not self.name.rsplit(".", 1)[-1].startswith("_")


class SymbolExtractor(Protocol):
    def symbols(self, source: str) -> list[_Symbol]: ...


# ------------------------------------------------------------------ Python


class PythonAstExtractor:
    """Exact symbol extraction via the standard library."""

    def symbols(self, source: str) -> list[_Symbol]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Expected when reconstructing partial files from diff hunks; the
            # caller falls back to line-level attribution.
            return []
        out: list[_Symbol] = []
        self._walk(tree, prefix="", out=out)
        return out

    def _walk(self, node: ast.AST, prefix: str, out: list[_Symbol]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                out.append(
                    _Symbol(
                        name=name,
                        kind="method" if prefix else "function",
                        start=child.lineno,
                        end=getattr(child, "end_lineno", child.lineno) or child.lineno,
                        signature=_signature(child),
                    )
                )
                self._walk(child, prefix=f"{name}.", out=out)
            elif isinstance(child, ast.ClassDef):
                name = f"{prefix}{child.name}"
                out.append(
                    _Symbol(
                        name=name,
                        kind="class",
                        start=child.lineno,
                        end=getattr(child, "end_lineno", child.lineno) or child.lineno,
                        signature="",
                    )
                )
                self._walk(child, prefix=f"{name}.", out=out)
            else:
                self._walk(child, prefix=prefix, out=out)


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    a = fn.args
    parts: list[str] = []
    for arg in list(a.posonlyargs) + list(a.args):
        parts.append(arg.arg)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    for arg in a.kwonlyargs:
        parts.append(arg.arg)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return "(" + ", ".join(parts) + ")"


# -------------------------------------------------------------- tree-sitter

# File extension -> language key (shared with ingest.builder._lang).
EXT_LANG: dict[str, str] = {
    "py": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript", "jsx": "javascript",
    "ts": "typescript", "mts": "typescript", "cts": "typescript",
    "tsx": "tsx",
    "java": "java",
    "rs": "rust",
    "c": "c", "h": "c",
    "cc": "cpp", "cpp": "cpp", "cxx": "cpp", "hpp": "cpp", "hh": "cpp",
}


def language_of(path: str) -> str:
    """Language key for a path, or "" when unsupported."""
    if "." not in path:
        return ""
    return EXT_LANG.get(path.rsplit(".", 1)[-1], "")


def _text(node) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


def _squash(text: str) -> str:
    return " ".join(text.split())


_JS_FUNC_VALUES = {
    "arrow_function", "function_expression", "function", "generator_function",
}
_JS_FIELD_NODES = {"field_definition", "public_field_definition"}
_JS_VALUE_HOLDERS = ("variable_declarator", *_JS_FIELD_NODES)


def _js_target(node):
    """The node that carries the parameter list for a JS/TS definition."""
    if node.type in _JS_VALUE_HOLDERS:
        return node.child_by_field_name("value")
    return node


def _js_name(node) -> str | None:
    t = node.type
    if t == "variable_declarator":
        val = node.child_by_field_name("value")
        name = node.child_by_field_name("name")
        if val is None or val.type not in _JS_FUNC_VALUES or name is None:
            return None
        return _text(name) if name.type == "identifier" else None
    if t in _JS_FIELD_NODES:
        val = node.child_by_field_name("value")
        if val is None or val.type not in _JS_FUNC_VALUES:
            return None
        n = node.child_by_field_name("name") or node.child_by_field_name("property")
        return _text(n) or None
    return _generic_name(node)


def _generic_name(node) -> str | None:
    n = node.child_by_field_name("name")
    return (_text(n) or None) if n is not None else None


def _declarator_chain(node):
    """Descend a C/C++ declarator to the innermost name node and its params."""
    d = node.child_by_field_name("declarator")
    params = None
    while d is not None:
        if d.type == "function_declarator" and params is None:
            params = d.child_by_field_name("parameters")
        if d.type in ("function_declarator", "pointer_declarator", "array_declarator",
                      "parenthesized_declarator", "reference_declarator",
                      "attributed_declarator"):
            nxt = d.child_by_field_name("declarator")
            if nxt is None:
                named = [c for c in d.children if c.is_named]
                nxt = named[0] if named else None
            d = nxt
            continue
        break
    return d, params


def _c_name(node) -> str | None:
    d, _ = _declarator_chain(node)
    if d is None:
        return None
    return _text(d).replace("::", ".") or None


def _c_class_name(node) -> str | None:
    if node.child_by_field_name("body") is None:
        return None  # `struct foo *p` is a reference, not a definition
    return _generic_name(node)


def _rust_impl_name(node) -> str | None:
    t = node.child_by_field_name("type")
    while t is not None and t.type in ("generic_type", "reference_type", "scoped_type_identifier"):
        t = t.child_by_field_name("type")
    return _text(t) or None


def _ancestors(node):
    p = node.parent
    while p is not None:
        yield p
        p = p.parent


def _modifier_words(node) -> set[str]:
    out: set[str] = set()
    for c in node.children:
        if c.type == "modifiers":
            out.update(_text(c).split())
        elif c.type in ("accessibility_modifier", "storage_class_specifier"):
            out.add(_text(c))
    return out


def _js_public(node, name: str, path: str) -> bool:
    last = name.rsplit(".", 1)[-1]
    if last.startswith(("_", "#")):
        return False
    if _modifier_words(node) & {"private", "protected"}:
        return False
    for anc in _ancestors(node):
        if anc.type == "export_statement":
            return True
        if anc.type in ("function_declaration", "generator_function_declaration",
                        "arrow_function", "function_expression", "function",
                        "method_definition", "statement_block"):
            return False
    return False


def _java_public(node, name: str, path: str) -> bool:
    words = _modifier_words(node)
    if "private" in words:
        return False
    if words & {"public", "protected"}:
        return True
    parent = node.parent
    # Interface (and annotation) members are implicitly public.
    return bool(parent is not None and parent.type in ("interface_body", "annotation_type_body"))


def _rust_public(node, name: str, path: str) -> bool:
    for c in node.children:
        if c.type == "visibility_modifier":
            return _text(c).strip() == "pub"
    parent = node.parent
    if parent is not None and parent.type == "declaration_list":
        owner = parent.parent
        if owner is not None and owner.type == "impl_item" and owner.child_by_field_name("trait") is not None:
            return True  # trait impl members are as public as the trait
        if owner is not None and owner.type == "trait_item":
            return True
    return False


def _c_public(node, name: str, path: str) -> bool:
    if name.rsplit(".", 1)[-1].startswith("_"):
        return False
    if "static" in _modifier_words(node):
        return False
    parent = node.parent
    if parent is not None and parent.type == "field_declaration_list":
        owner = parent.parent
        access = "private" if owner is not None and owner.type == "class_specifier" else "public"
        for sib in parent.children:
            if sib.start_byte >= node.start_byte:
                break
            if sib.type == "access_specifier":
                access = _text(sib).rstrip(":").strip()
        if access == "private":
            return False
    return True


def _c_params(node) -> str:
    _, params = _declarator_chain(node)
    return _text(params)


def _generic_params(node) -> str:
    target = _js_target(node) if node.type in _JS_VALUE_HOLDERS else node
    if target is None:
        return ""
    p = target.child_by_field_name("parameters") or target.child_by_field_name("parameter")
    return _text(p)


def _return_of(node, lang: str) -> str:
    target = _js_target(node) if node.type in _JS_VALUE_HOLDERS else node
    if target is None:
        return ""
    r = target.child_by_field_name("return_type")
    if r is None and lang in ("java", "c", "cpp"):
        r = target.child_by_field_name("type")
    return _squash(_text(r)).lstrip(": ").strip() if r is not None else ""


@dataclass(frozen=True)
class LangSpec:
    key: str
    module: str
    func: str
    defs: dict  # node type -> "function" | "class"
    containers: dict  # node type -> name_of(node); adds a name prefix, no symbol
    name_of: object
    params_of: object
    is_public: object


_JS_DEFS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "function",
    "variable_declarator": "function",
    "field_definition": "function",
}
_TS_DEFS = {
    **_JS_DEFS,
    "public_field_definition": "function",
    "interface_declaration": "class",
    "abstract_class_declaration": "class",
    "enum_declaration": "class",
}
_JAVA_DEFS = {
    "method_declaration": "function",
    "constructor_declaration": "function",
    "class_declaration": "class",
    "interface_declaration": "class",
    "enum_declaration": "class",
    "record_declaration": "class",
}
_RUST_DEFS = {
    "function_item": "function",
    "struct_item": "class",
    "enum_item": "class",
    "trait_item": "class",
}
_PY_DEFS = {"function_definition": "function", "class_definition": "class"}
_C_DEFS = {"function_definition": "function", "struct_specifier": "class"}
_CPP_DEFS = {**_C_DEFS, "class_specifier": "class"}


def _c_any_name(n):
    return _c_name(n) if n.type == "function_definition" else _c_class_name(n)


def _py_public(node, name: str, path: str) -> bool:
    return not name.rsplit(".", 1)[-1].startswith("_")


LANGS: dict[str, LangSpec] = {
    # Python is NOT reached through extractor_for (that stays on stdlib ast, so the
    # study is untouched). This entry exists only for the opt-in live fallback in
    # `changed_symbols(python_fallback=True)`.
    "python": LangSpec("python", "tree_sitter_python", "language",
                       _PY_DEFS, {}, _generic_name, _generic_params, _py_public),
    "javascript": LangSpec("javascript", "tree_sitter_javascript", "language",
                           _JS_DEFS, {}, _js_name, _generic_params, _js_public),
    "typescript": LangSpec("typescript", "tree_sitter_typescript", "language_typescript",
                           _TS_DEFS, {}, _js_name, _generic_params, _js_public),
    "tsx": LangSpec("tsx", "tree_sitter_typescript", "language_tsx",
                    _TS_DEFS, {}, _js_name, _generic_params, _js_public),
    "java": LangSpec("java", "tree_sitter_java", "language",
                     _JAVA_DEFS, {}, _generic_name, _generic_params, _java_public),
    "rust": LangSpec("rust", "tree_sitter_rust", "language",
                     _RUST_DEFS, {"impl_item": _rust_impl_name, "mod_item": _generic_name},
                     _generic_name, _generic_params, _rust_public),
    "c": LangSpec("c", "tree_sitter_c", "language", _C_DEFS, {},
                  _c_any_name, _c_params, _c_public),
    "cpp": LangSpec("cpp", "tree_sitter_cpp", "language", _CPP_DEFS,
                    {"namespace_definition": _generic_name},
                    _c_any_name, _c_params, _c_public),
}

_CLASS_LIKE = frozenset({
    "class_declaration", "interface_declaration", "enum_declaration", "record_declaration",
    "abstract_class_declaration", "struct_item", "enum_item", "trait_item",
    "struct_specifier", "class_specifier",
})


@lru_cache(maxsize=None)
def _parser(lang: str):
    """One parser per language. Raises when the grammar is not installed."""
    from tree_sitter import Language, Parser  # noqa: PLC0415

    spec = LANGS[lang]
    mod = importlib.import_module(spec.module)
    return Parser(Language(getattr(mod, spec.func)()))


class TreeSitterExtractor:
    """Symbol extraction for non-Python files. Requires the `polyglot` extra."""

    def __init__(self, language: str = "javascript") -> None:
        if language not in LANGS:
            raise ValueError(f"unsupported language: {language}")
        self._spec = LANGS[language]
        self._parser = _parser(language)
        self._language = language

    def symbols(self, source: str) -> list[_Symbol]:
        if not source.strip():
            return []
        spec = self._spec
        tree = self._parser.parse(source.encode("utf-8"))
        out: list[_Symbol] = []
        # (node, name prefix, kind of the enclosing symbol or "")
        stack = [(tree.root_node, "", "")]
        while stack:
            node, prefix, enclosing = stack.pop()
            t = node.type
            next_prefix, next_enclosing = prefix, enclosing
            if t in spec.defs:
                name = spec.name_of(node)
                if name:
                    kind = spec.defs[t]
                    if kind == "function":
                        qualified = "." in name and self._language in ("c", "cpp")
                        kind = "method" if enclosing == "class" or qualified else "function"
                    full = f"{prefix}{name}"
                    out.append(
                        _Symbol(
                            name=full,
                            kind=kind,
                            start=node.start_point[0] + 1,
                            end=node.end_point[0] + 1,
                            signature=self._signature(node),
                            public=bool(spec.is_public(node, full, "")),
                        )
                    )
                    next_prefix = f"{full}."
                    next_enclosing = "class" if kind == "class" else "function"
            elif t in spec.containers:
                name = spec.containers[t](node)
                if name:
                    next_prefix = f"{prefix}{name}."
                    next_enclosing = "class" if t == "impl_item" else enclosing
            for child in reversed(node.children):
                stack.append((child, next_prefix, next_enclosing))
        out.sort(key=lambda s: (s.start, s.end, s.name))
        return out

    def _signature(self, node) -> str:
        if node.type in _CLASS_LIKE:
            return ""
        params = _squash(self._spec.params_of(node))
        ret = _return_of(node, self._language)
        return f"{params} -> {ret}" if ret else params


def extractor_for(path: str) -> SymbolExtractor | None:
    """Pick an extractor by file extension. Returns None for unsupported types."""
    if path.endswith(".py"):
        return PythonAstExtractor()
    lang = language_of(path)
    if not lang:
        return None
    try:
        return TreeSitterExtractor(lang)
    except Exception:
        # polyglot extra not installed, or no grammar for this language.
        return None


# ------------------------------------------------- git hunk-header fallback

_FALLBACK_RE: dict[str, list[tuple[re.Pattern, str]]] = {
    # Only consulted for Python when changed_symbols(python_fallback=True).
    "python": [
        (re.compile(r"^\s*(?:async\s+)?def\s+(\w+)"), "function"),
        (re.compile(r"^\s*class\s+(\w+)"), "class"),
    ],
    "rust": [
        (re.compile(r"\bfn\s+(\w+)"), "function"),
        (re.compile(r"\b(?:struct|enum|trait|impl(?:<[^>]*>)?)\s+(\w+)"), "class"),
    ],
    "javascript": [
        (re.compile(r"\bfunction\s*\*?\s*(\w+)"), "function"),
        (re.compile(r"\bclass\s+(\w+)"), "class"),
        (re.compile(r"\b(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|\w+\s*=>|function)"), "function"),
        (re.compile(r"^\s*(?:async\s+|static\s+)*(\w+)\s*\("), "function"),
    ],
    "java": [
        (re.compile(r"\b(?:class|interface|enum|record)\s+(\w+)"), "class"),
        (re.compile(r"(\w+)\s*\("), "function"),
    ],
    "c": [
        (re.compile(r"\b(?:struct|class)\s+(\w+)\s*\{?\s*$"), "class"),
        (re.compile(r"(\w+)\s*\("), "function"),
    ],
}
_FALLBACK_RE["typescript"] = _FALLBACK_RE["tsx"] = _FALLBACK_RE["javascript"]
_FALLBACK_RE["cpp"] = _FALLBACK_RE["c"]
_NOT_NAMES = {"if", "for", "while", "switch", "return", "catch", "sizeof", "else", "do"}


def _section_symbol(file: str, lang: str, hunk: Hunk) -> ChangedSymbol | None:
    section = hunk.section
    if not section:
        return None
    for pattern, kind in _FALLBACK_RE.get(lang, []):
        m = pattern.search(section)
        if m and m.group(1) not in _NOT_NAMES:
            name = m.group(1)
            return ChangedSymbol(
                file=file,
                name=name,
                kind=kind,  # type: ignore[arg-type]
                start_line=hunk.new_start,
                end_line=hunk.new_start,
                signature="",
                change="modified",
                is_public=_section_public(section, name, lang),
            )
    return None


def _section_public(section: str, name: str, lang: str) -> bool:
    if name.startswith("_"):
        return False
    words = set(re.findall(r"\w+", section))
    if lang == "rust":
        return "pub" in words and "pub(" not in section
    if lang == "java":
        return "private" not in words
    if lang in ("javascript", "typescript", "tsx"):
        return "export" in words and not words & {"private", "protected"}
    return "static" not in words


# ---------------------------------------------------------------- the API


def changed_symbols(
    hunks: list[Hunk],
    post_images: dict[str, str],
    pre_images: dict[str, str] | None = None,
    *,
    python_fallback: bool = False,
) -> list[ChangedSymbol]:
    """Map diff hunks onto the symbols they touch.

    `python_fallback` is a live-tool opt-in. A Python file whose stdlib-ast parse
    yields nothing (typically a hunk-only reconstruction, which is not valid
    Python) is retried with error-tolerant tree-sitter-python and then with the
    `@@` hunk-section `def`/`class` regex. Off by default: the study never sets it.

    `post_images` maps file path to the file's content after the change. When the
    full file is unavailable, pass the reconstructed post-image from
    `diff.reconstruct_sides` - attribution degrades but does not break.
    """
    pre_images = pre_images or {}
    results: list[ChangedSymbol] = []

    for file in sorted({h.file for h in hunks}):
        lang = language_of(file)
        if not lang:
            continue
        ex = extractor_for(file)

        if lang != "python":
            if ex is None:
                results.extend(_fallback_symbols(hunks, file, lang))
                continue
            post_syms = ex.symbols(post_images.get(file, ""))
            pre_syms = ex.symbols(pre_images.get(file, ""))
            if not post_syms and not pre_syms:
                results.extend(_fallback_symbols(hunks, file, lang))
                continue
            results.extend(_diff_symbols(hunks, file, post_syms, pre_syms, overloads=True))
            continue

        post_syms = ex.symbols(post_images.get(file, ""))
        pre_syms = ex.symbols(pre_images.get(file, ""))
        if python_fallback and not post_syms and not pre_syms:
            results.extend(_python_live_fallback(hunks, file, post_images, pre_images))
            continue
        results.extend(_diff_symbols(hunks, file, post_syms, pre_syms, overloads=False))

    return sorted(results, key=lambda s: (s.file, s.start_line, s.name))


def _python_live_fallback(
    hunks: list[Hunk], file: str, post_images: dict[str, str], pre_images: dict[str, str]
) -> list[ChangedSymbol]:
    """tree-sitter-python (tolerates partial code), then the hunk-section regex."""
    try:
        ts = TreeSitterExtractor("python")
        found = _diff_symbols(
            hunks, file,
            ts.symbols(post_images.get(file, "")),
            ts.symbols(pre_images.get(file, "")),
            overloads=True,
        )
    except Exception:  # noqa: BLE001 - polyglot extra missing; regex still works
        found = []
    return found or _fallback_symbols(hunks, file, "python")


def _fallback_symbols(hunks: list[Hunk], file: str, lang: str) -> list[ChangedSymbol]:
    """No usable parse: read the symbol out of each hunk's `@@` function context."""
    seen: set[str] = set()
    out: list[ChangedSymbol] = []
    for h in hunks:
        if h.file != file:
            continue
        sym = _section_symbol(file, lang, h)
        if sym is not None and sym.name not in seen:
            seen.add(sym.name)
            out.append(sym)
    return out


def _diff_symbols(
    hunks: list[Hunk],
    file: str,
    post_syms: list[_Symbol],
    pre_syms: list[_Symbol],
    *,
    overloads: bool,
) -> list[ChangedSymbol]:
    """Match touched post/pre symbols. `overloads=False` is the Python behaviour:
    one symbol per name, the last wins. Elsewhere same-name symbols (Java and C++
    overloads) are told apart by signature."""
    results: list[ChangedSymbol] = []
    if overloads:
        pre_multi: dict[str, list[_Symbol]] = {}
        post_multi: dict[str, list[_Symbol]] = {}
        for sy in pre_syms:
            pre_multi.setdefault(sy.name, []).append(sy)
        for sy in post_syms:
            post_multi.setdefault(sy.name, []).append(sy)

        def find_before(sym: _Symbol) -> _Symbol | None:
            cands = pre_multi.get(sym.name, [])
            for c in cands:
                if c.signature == sym.signature:
                    return c
            if len(cands) == 1 and len(post_multi.get(sym.name, [])) == 1:
                return cands[0]
            return None

        def still_present(sym: _Symbol) -> bool:
            cands = post_multi.get(sym.name, [])
            if any(c.signature == sym.signature for c in cands):
                return True
            return len(cands) == 1 and len(pre_multi.get(sym.name, [])) == 1
    else:
        pre_by_name = {s.name: s for s in pre_syms}
        post_by_name = {s.name: s for s in post_syms}

        def find_before(sym: _Symbol) -> _Symbol | None:
            return pre_by_name.get(sym.name)

        def still_present(sym: _Symbol) -> bool:
            return sym.name in post_by_name

    if overloads:
        # Non-Python: attribute each run of +/- lines on its own, so one hunk
        # that spans two functions reports both. Python keeps whole-hunk ranges.
        added_runs, removed_runs = _edit_runs(hunks, file)
        touched_post = _overlapping(post_syms, added_runs)
        touched_pre = _overlapping(pre_syms, removed_runs)
        # A line deleted inside a function that survives is a modification of it.
        for sym in touched_pre:
            for cand in post_multi.get(sym.name, []):
                if (cand.signature == sym.signature or len(post_multi[sym.name]) == 1)                         and cand not in touched_post:
                    touched_post.append(cand)
                    break
    else:
        touched_post = _overlapping(post_syms, changed_line_ranges(hunks, file))
        touched_pre = _overlapping(pre_syms, removed_line_ranges(hunks, file))

    for sym in touched_post:
        before = find_before(sym)
        if before is None and pre_syms:
            change = "added"
        elif before is None:
            change = "modified"  # no pre-image available; do not over-claim
        else:
            change = "modified"
        results.append(
            ChangedSymbol(
                file=file,
                name=sym.name,
                kind=sym.kind,  # type: ignore[arg-type]
                start_line=sym.start,
                end_line=sym.end,
                signature=sym.signature,
                change=change,  # type: ignore[arg-type]
                is_public=sym.is_public,
                signature_changed=bool(before is not None and before.signature != sym.signature),
            )
        )

    # Symbols that existed before and are gone now.
    for sym in touched_pre:
        if still_present(sym):
            continue
        results.append(
            ChangedSymbol(
                file=file,
                name=sym.name,
                kind=sym.kind,  # type: ignore[arg-type]
                start_line=sym.start,
                end_line=sym.end,
                signature=sym.signature,
                change="removed",
                is_public=sym.is_public,
                signature_changed=True,
            )
        )
    return results


def _edit_runs(hunks: list[Hunk], file: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Contiguous runs of added lines (post-image numbers) and removed lines
    (pre-image numbers) for `file`."""
    added: list[tuple[int, int]] = []
    removed: list[tuple[int, int]] = []
    for h in hunks:
        if h.file != file:
            continue
        old_no, new_no = h.old_start, h.new_start
        run_add: list[int] = []
        run_rem: list[int] = []
        for line in h.body.splitlines()[1:]:
            if line.startswith("+"):
                run_add.append(new_no)
                new_no += 1
            elif line.startswith("-"):
                run_rem.append(old_no)
                old_no += 1
            else:
                if run_add:
                    added.append((run_add[0], run_add[-1]))
                if run_rem:
                    removed.append((run_rem[0], run_rem[-1]))
                run_add, run_rem = [], []
                if line.startswith(" ") or line == "":
                    old_no += 1
                    new_no += 1
        if run_add:
            added.append((run_add[0], run_add[-1]))
        if run_rem:
            removed.append((run_rem[0], run_rem[-1]))
    return added, removed


def _overlapping(symbols: list[_Symbol], ranges: list[tuple[int, int]]) -> list[_Symbol]:
    """Innermost symbol wins: a changed method is reported, not its whole class.

    A class is only reported when the change lands in the class body outside any
    of its methods, which is where decorators and class attributes live.
    """
    hit: list[_Symbol] = []
    for lo, hi in ranges:
        covering = [s for s in symbols if s.start <= hi and s.end >= lo]
        if not covering:
            continue
        innermost = min(covering, key=lambda s: (s.end - s.start))
        if innermost not in hit:
            hit.append(innermost)
    return hit
