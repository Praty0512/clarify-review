"""Unified diff parsing.

Hand-rolled rather than pulled from a library, for two reasons: the ingestion
layer has to be byte-deterministic and a dependency that changes its whitespace
handling between minor versions would silently break the ablation, and the
golden-file tests are only meaningful if they test our parser.
"""

from __future__ import annotations

import re

from ..types import Hunk

_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_lines>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))? @@(?P<section>.*)$"
)

# "diff --git a/foo.py b/foo.py" -> foo.py. Falls back to the +++ line.
_GIT_HEADER_RE = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")


def parse_unified_diff(diff_text: str) -> list[Hunk]:
    """Split a unified diff into hunks, tagged with the file each belongs to.

    Deleted files keep their old path; new files use the new path. Binary files
    and pure-rename entries produce no hunks, which is correct - there is nothing
    for a reviewer to read.
    """
    hunks: list[Hunk] = []
    current_file: str | None = None
    current: Hunk | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal current, body
        if current is not None:
            current.body = "\n".join(body)
            hunks.append(current)
        current = None
        body = []

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            flush()
            m = _GIT_HEADER_RE.match(raw)
            current_file = m.group("b") if m else None
            continue

        if raw.startswith("--- "):
            path = raw[4:].strip()
            if path != "/dev/null" and current_file is None:
                current_file = path[2:] if path.startswith(("a/", "b/")) else path
            continue

        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path != "/dev/null":
                current_file = path[2:] if path.startswith(("a/", "b/")) else path
            continue

        m = _HUNK_RE.match(raw)
        if m:
            flush()
            current = Hunk(
                file=current_file or "<unknown>",
                old_start=int(m.group("old_start")),
                old_lines=int(m.group("old_lines") or 1),
                new_start=int(m.group("new_start")),
                new_lines=int(m.group("new_lines") or 1),
                section=m.group("section").strip(),
            )
            body = [raw]
            continue

        if current is None:
            continue

        body.append(raw)
        if raw.startswith("+"):
            current.added.append(raw[1:])
        elif raw.startswith("-"):
            current.removed.append(raw[1:])

    flush()
    return hunks


def changed_line_ranges(hunks: list[Hunk], file: str) -> list[tuple[int, int]]:
    """Post-image line ranges touched in `file`, for mapping hunks onto symbols."""
    return [
        (h.new_start, h.new_start + max(h.new_lines, 1) - 1)
        for h in hunks
        if h.file == file
    ]


def removed_line_ranges(hunks: list[Hunk], file: str) -> list[tuple[int, int]]:
    """Pre-image line ranges, needed to notice symbols the diff deleted."""
    return [
        (h.old_start, h.old_start + max(h.old_lines, 1) - 1)
        for h in hunks
        if h.file == file
    ]


def split_by_file(hunks: list[Hunk]) -> dict[str, list[Hunk]]:
    out: dict[str, list[Hunk]] = {}
    for h in hunks:
        out.setdefault(h.file, []).append(h)
    return out


def reconstruct_sides(hunks: list[Hunk]) -> tuple[str, str]:
    """Best-effort pre- and post-image text of the changed regions only.

    This is not the whole file - it is the changed regions with their context,
    which is what the symbol extractor needs when the repository checkout is not
    available (the common case when reviewing a PR through the API).

    Crucially, the output is *line-aligned*: each hunk's lines are placed at the
    line numbers they occupy in the real file, with blank padding in between.
    Without that alignment the extractor reports symbols at reconstruction-local
    line numbers while the hunk ranges are in real-file coordinates, the two never
    overlap, and every diff silently produces zero changed symbols.
    """
    pre: dict[int, str] = {}
    post: dict[int, str] = {}
    for h in hunks:
        old_no, new_no = h.old_start, h.new_start
        for line in h.body.splitlines()[1:]:  # skip the @@ line
            if line.startswith("+"):
                post[new_no] = line[1:]
                new_no += 1
            elif line.startswith("-"):
                pre[old_no] = line[1:]
                old_no += 1
            elif line.startswith(" ") or line == "":
                text = line[1:] if line else ""
                pre[old_no] = text
                post[new_no] = text
                old_no += 1
                new_no += 1
    return _densify(pre), _densify(post)


def _densify(sparse: dict[int, str]) -> str:
    """Sparse line-number map -> text with blank padding at the missing lines."""
    if not sparse:
        return ""
    return "\n".join(sparse.get(i, "") for i in range(1, max(sparse) + 1))
