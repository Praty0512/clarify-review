"""Stage 1. Assemble a `PRContext` from whatever source the caller has.

Two entry points, one output. `from_github` is the production path; `from_raw`
is the benchmark path, where the diff and metadata come from a SWE-bench instance
rather than a live API. They must produce structurally identical contexts, or the
prototype and the experiment are not measuring the same system.
"""

from __future__ import annotations

from pathlib import Path

from ..types import LinkedIssue, PRContext
from .context import build_neighbourhood, estimate_tokens
from .diff import parse_unified_diff, reconstruct_sides, split_by_file
from .semantic import changed_symbols, language_of

DIFF_TOKEN_BUDGET = 24000
NEIGHBOURHOOD_TOKEN_BUDGET = 6000


def from_raw(
    pr_id: str,
    diff: str,
    *,
    repo: str = "",
    number: int | None = None,
    title: str = "",
    body: str = "",
    commit_messages: list[str] | None = None,
    linked_issue: LinkedIssue | None = None,
    repo_root: Path | None = None,
) -> PRContext:
    """Build a context from a diff plus metadata.

    `repo_root`, when given, is a checkout at the PR's base commit; it enables
    full-file symbol extraction and the caller/callee neighbourhood. Without it
    the symbol extractor works from the diff's reconstructed images, which is
    less precise but never wrong in a way that favours one condition.
    """
    diff, truncated = _truncate_diff(diff, DIFF_TOKEN_BUDGET)
    hunks = parse_unified_diff(diff)
    by_file = split_by_file(hunks)

    post_images: dict[str, str] = {}
    pre_images: dict[str, str] = {}
    for file, file_hunks in by_file.items():
        full = _read_file(repo_root, file) if repo_root else None
        if full is not None:
            # The checkout is at the base commit, so it is the pre-image; apply
            # the hunks to get a usable post-image.
            pre_images[file] = full
            post_images[file] = _apply(full, file_hunks)
        else:
            pre, post = reconstruct_sides(file_hunks)
            pre_images[file] = pre
            post_images[file] = post

    symbols = changed_symbols(hunks, post_images, pre_images)

    neighbourhood: list = []
    nb_truncated = False
    if repo_root is not None:
        neighbourhood, nb_truncated = build_neighbourhood(
            repo_root, symbols, budget_tokens=NEIGHBOURHOOD_TOKEN_BUDGET
        )

    return PRContext(
        pr_id=pr_id,
        repo=repo,
        number=number,
        title=title,
        body=body,
        commit_messages=list(commit_messages or []),
        diff=diff,
        hunks=hunks,
        changed_symbols=symbols,
        neighbourhood=neighbourhood,
        linked_issue=linked_issue,
        languages=sorted({_lang(f) for f in by_file} - {""}),
        truncated=truncated or nb_truncated,
    )


def from_github(client, repo: str, number: int, repo_root: Path | None = None) -> PRContext:
    """Production path. `client` is a `gh.client.GitHubClient`."""
    pr = client.get_pull_request(repo, number)
    diff = client.get_diff(repo, number)
    commits = client.get_commit_messages(repo, number)
    issue = client.get_linked_issue(repo, number)

    return from_raw(
        pr_id=f"{repo}#{number}",
        diff=diff,
        repo=repo,
        number=number,
        title=pr.get("title", ""),
        body=pr.get("body") or "",
        commit_messages=commits,
        linked_issue=issue,
        repo_root=repo_root,
    )


# ------------------------------------------------------------------ helpers


def _lang(path: str) -> str:
    """Display name of a file's language ("" when unsupported). TSX reports as
    typescript; Go is labelled for the prompt only, it has no symbol extractor."""
    lang = language_of(path)
    if lang == "tsx":
        return "typescript"
    if lang:
        return lang
    return "go" if path.endswith(".go") else ""


def _read_file(root: Path | None, rel: str) -> str | None:
    if root is None:
        return None
    p = root / rel
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _truncate_diff(diff: str, budget: int) -> tuple[str, bool]:
    """Drop whole trailing hunks until the diff fits. Never cut mid-hunk.

    Deterministic by construction: hunks are dropped from the end in file order,
    so the same oversized diff always truncates identically.
    """
    if estimate_tokens(diff) <= budget:
        return diff, False
    lines = diff.splitlines()
    kept: list[str] = []
    used = 0
    truncated = False
    block: list[str] = []

    def flush() -> bool:
        nonlocal used, kept, block
        if not block:
            return True
        cost = estimate_tokens("\n".join(block))
        if used + cost > budget:
            block = []
            return False
        kept.extend(block)
        used += cost
        block = []
        return True

    for line in lines:
        if line.startswith(("diff --git ", "@@ ")) and block:
            if not flush():
                truncated = True
        block.append(line)
    if not flush():
        truncated = True
    return "\n".join(kept), truncated


def _apply(original: str, hunks: list) -> str:
    """Apply hunks to a base-commit file to recover the post-image.

    Hunks are applied bottom-up so earlier line numbers stay valid. A hunk whose
    context does not match is skipped rather than force-applied - a corrupted
    post-image would produce phantom changed symbols, which is worse than a
    missing one.
    """
    lines = original.splitlines()
    for h in sorted(hunks, key=lambda x: x.old_start, reverse=True):
        new_block: list[str] = []
        ok = True
        cursor = h.old_start - 1
        for raw in h.body.splitlines()[1:]:
            if raw.startswith("+"):
                new_block.append(raw[1:])
            elif raw.startswith("-"):
                if cursor >= len(lines) or lines[cursor] != raw[1:]:
                    ok = False
                    break
                cursor += 1
            else:
                text = raw[1:] if raw.startswith(" ") else raw
                if cursor < len(lines):
                    new_block.append(lines[cursor])
                    cursor += 1
                else:
                    new_block.append(text)
        if ok:
            lines[h.old_start - 1 : cursor] = new_block
    return "\n".join(lines)
