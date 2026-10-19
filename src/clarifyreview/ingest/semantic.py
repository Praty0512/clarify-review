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
from dataclasses import dataclass
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

    @property
    def is_public(self) -> bool:
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


class TreeSitterExtractor:
    """Optional path for non-Python files. Requires the `polyglot` extra."""

    def __init__(self, language: str = "python") -> None:
        from tree_sitter import Language, Parser  # noqa: PLC0415

        mod = __import__(f"tree_sitter_{language}")
        self._parser = Parser(Language(mod.language()))
        self._language = language

    def symbols(self, source: str) -> list[_Symbol]:
        tree = self._parser.parse(source.encode("utf-8"))
        out: list[_Symbol] = []
        wanted = {
            "function_definition": "function",
            "class_definition": "class",
            "method_definition": "method",
            "function_declaration": "function",
            "class_declaration": "class",
        }
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            kind = wanted.get(node.type)
            if kind:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    out.append(
                        _Symbol(
                            name=name_node.text.decode("utf-8"),
                            kind=kind,
                            start=node.start_point[0] + 1,
                            end=node.end_point[0] + 1,
                            signature="",
                        )
                    )
            stack.extend(node.children)
        return out


def extractor_for(path: str) -> SymbolExtractor | None:
    """Pick an extractor by file extension. Returns None for unsupported types."""
    if path.endswith(".py"):
        return PythonAstExtractor()
    lang = {
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",
        ".java": "java",
    }.get("." + path.rsplit(".", 1)[-1] if "." in path else "")
    if lang is None:
        return None
    try:
        return TreeSitterExtractor(lang)
    except Exception:
        # polyglot extra not installed, or no grammar for this language.
        return None


# ---------------------------------------------------------------- the API


def changed_symbols(
    hunks: list[Hunk],
    post_images: dict[str, str],
    pre_images: dict[str, str] | None = None,
) -> list[ChangedSymbol]:
    """Map diff hunks onto the symbols they touch.

    `post_images` maps file path to the file's content after the change. When the
    full file is unavailable, pass the reconstructed post-image from
    `diff.reconstruct_sides` - attribution degrades but does not break.
    """
    pre_images = pre_images or {}
    results: list[ChangedSymbol] = []

    for file in sorted({h.file for h in hunks}):
        ex = extractor_for(file)
        if ex is None:
            continue

        post_syms = ex.symbols(post_images.get(file, ""))
        pre_syms = ex.symbols(pre_images.get(file, ""))
        pre_by_name = {s.name: s for s in pre_syms}
        post_by_name = {s.name: s for s in post_syms}

        touched_post = _overlapping(post_syms, changed_line_ranges(hunks, file))
        touched_pre = _overlapping(pre_syms, removed_line_ranges(hunks, file))

        for sym in touched_post:
            before = pre_by_name.get(sym.name)
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
                    signature_changed=bool(
                        before is not None and before.signature != sym.signature
                    ),
                )
            )

        # Symbols that existed before and are gone now.
        for sym in touched_pre:
            if sym.name in post_by_name:
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

    return sorted(results, key=lambda s: (s.file, s.start_line, s.name))


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
