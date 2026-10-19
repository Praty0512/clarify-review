"""One hop of surrounding code, under a fixed token budget.

Budgeting deliberately uses a local character-based estimate rather than the
token-counting endpoint. Truncation has to be deterministic and offline: if the
size of the context depended on a network call, two runs of the same PR could
produce different prompts and the ablation's core assumption would not hold.
The estimate is calibrated conservatively, so the real count comes in under it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..types import ChangedSymbol, CodeSnippet

CHARS_PER_TOKEN = 3.6  # conservative for source code, which tokenises densely


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def build_neighbourhood(
    repo_root: Path,
    changed: list[ChangedSymbol],
    budget_tokens: int = 6000,
    max_per_symbol: int = 2,
) -> tuple[list[CodeSnippet], bool]:
    """Find callers and callees of each changed symbol, one hop out.

    Returns the snippets plus whether the budget forced truncation. Callees are
    collected before callers because a reviewer needs to know what the changed
    code calls more often than who calls it.
    """
    if not repo_root.exists():
        return [], False

    index = _index_repo(repo_root)
    snippets: list[CodeSnippet] = []
    seen: set[tuple[str, str]] = set()

    for sym in sorted(changed, key=lambda s: (s.file, s.start_line)):
        target_path = repo_root / sym.file
        if not target_path.exists():
            continue
        source = _read(target_path)
        if source is None:
            continue

        for name in _callees(source, sym)[:max_per_symbol]:
            loc = index.get(name)
            if loc is None or (loc[0], name) in seen:
                continue
            seen.add((loc[0], name))
            snippets.append(
                CodeSnippet(
                    file=loc[0], name=name, relation="callee", start_line=loc[1], text=loc[2]
                )
            )

        for file, line, text in _callers(index, sym.name.rsplit(".", 1)[-1])[:max_per_symbol]:
            if (file, sym.name) in seen or file == sym.file:
                continue
            seen.add((file, sym.name))
            snippets.append(
                CodeSnippet(
                    file=file, name=sym.name, relation="caller", start_line=line, text=text
                )
            )

    # Deterministic order, then trim to budget.
    snippets.sort(key=lambda s: (s.file, s.start_line, s.name))
    kept: list[CodeSnippet] = []
    used = 0
    truncated = False
    for s in snippets:
        cost = estimate_tokens(s.text)
        if used + cost > budget_tokens:
            truncated = True
            continue
        kept.append(s)
        used += cost
    return kept, truncated


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _index_repo(root: Path, max_files: int = 4000) -> dict[str, tuple[str, int, str]]:
    """Map top-level symbol name -> (relative path, line, source text)."""
    index: dict[str, tuple[str, int, str]] = {}
    for i, path in enumerate(sorted(root.rglob("*.py"))):
        if i >= max_files:
            break
        if any(p in {".venv", "node_modules", ".git", "build", "dist"} for p in path.parts):
            continue
        source = _read(path)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        lines = source.splitlines()
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = getattr(node, "end_lineno", node.lineno) or node.lineno
                body = "\n".join(lines[node.lineno - 1 : min(end, node.lineno + 40)])
                index.setdefault(node.name, (rel, node.lineno, body))
    return index


def _callees(source: str, sym: ChangedSymbol) -> list[str]:
    """Names called from inside the changed symbol's body."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.lineno != sym.start_line:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                fn = inner.func
                if isinstance(fn, ast.Name):
                    names.append(fn.id)
                elif isinstance(fn, ast.Attribute):
                    names.append(fn.attr)
    # Stable order, deduplicated.
    return sorted(dict.fromkeys(names))


def _callers(
    index: dict[str, tuple[str, int, str]], name: str
) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    needle = f"{name}("
    for file, line, text in sorted(index.values()):
        if needle in text:
            out.append((file, line, text))
    return out
