"""Live tool only: decide which files of a large pull request deserve the budget.

The study's diffs are small SWE-bench patches and never reach this module. A
real pull request on a large repository is different: lockfiles, generated
code, vendored dependencies and test baselines can make up most of the diff, and
`builder._truncate_diff` drops whole trailing files in path order. Without
triage the reviewer can spend its whole budget on `package-lock.json` and never
see the source change the PR is about.

Two steps, both deterministic and offline:

1. drop files nobody reviews by hand (generated, vendored, lockfiles, minified,
   snapshots and test baselines), recording their paths;
2. reorder the rest so source comes first, then tests, then everything else,
   then docs, keeping path order inside each group.
"""

from __future__ import annotations

import fnmatch
import re

# Matched against the full path, case-insensitively.
_SKIP_GLOBS = (
    # lockfiles
    "*package-lock.json", "*yarn.lock", "*pnpm-lock.yaml", "*bun.lockb", "*cargo.lock",
    "*poetry.lock", "*pipfile.lock", "*uv.lock", "*composer.lock", "*gemfile.lock",
    "*go.sum", "*gradle.lockfile", "*packages.lock.json", "*podfile.lock",
    # minified, bundled, maps
    "*.min.js", "*.min.css", "*.bundle.js", "*.map",
    # generated code
    "*_pb2.py", "*_pb2.pyi", "*_pb2_grpc.py", "*.pb.go", "*.pb.cc", "*.pb.h",
    "*_generated.*", "*.generated.*", "*.g.dart", "*.designer.cs",
    # snapshots and test baselines
    "*.snap", "*__snapshots__/*", "*/baselines/reference/*", "*.baseline",
    "*/testdata/*.golden", "*.golden",
)
_SKIP_DIRS = {
    "node_modules", "vendor", "third_party", "third-party", "thirdparty", "external",
    "dist", "build", "out", ".next", "__generated__", "generated", "gen",
}
_TEST_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec|specs|testing|testdata)(/|$)"
    r"|(^|/)test_[^/]*$|_tests?\.[^/.]+$|\.(test|spec)\.[^/.]+$|Tests?\.[^/.]+$"
)
_DOC_EXT = (".md", ".rst", ".txt", ".adoc")
_SOURCE_EXT = {
    "py", "pyi", "js", "jsx", "mjs", "cjs", "ts", "tsx", "mts", "cts", "java", "kt", "kts",
    "scala", "go", "rs", "c", "h", "cc", "cpp", "cxx", "hpp", "hh", "cs", "rb", "php",
    "swift", "m", "mm", "dart", "lua", "sh", "sql",
}

# Group order: lower is reviewed first.
SOURCE, TEST, OTHER, DOCS = 0, 1, 2, 3


def skip_reason(path: str) -> str | None:
    """Why a file is left out of the review, or None to keep it."""
    p = path.replace("\\", "/")
    low = p.lower()
    parts = low.split("/")[:-1]
    if any(d in _SKIP_DIRS for d in parts):
        return "vendored or build output"
    for g in _SKIP_GLOBS:
        if fnmatch.fnmatchcase(low, g) or fnmatch.fnmatchcase(low, "*/" + g.lstrip("*")):
            return "generated, lockfile or baseline"
    return None


def group_of(path: str) -> int:
    p = path.replace("\\", "/")
    if p.lower().endswith(_DOC_EXT) or p.lower().startswith("docs/"):
        return DOCS
    if _TEST_RE.search(p):
        return TEST
    ext = p.rsplit(".", 1)[-1].lower() if "." in p.rsplit("/", 1)[-1] else ""
    return SOURCE if ext in _SOURCE_EXT else OTHER


def split_blocks(diff: str) -> list[tuple[str, str]]:
    """(path, block text) for each `diff --git` section, in input order."""
    blocks: list[tuple[str, str]] = []
    cur: list[str] = []
    path = ""
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur:
                blocks.append((path, "".join(cur)))
            cur = [line]
            m = re.match(r"diff --git a/(.*?) b/(.*)$", line.rstrip("\n"))
            path = m.group(2) if m else ""
        else:
            cur.append(line)
    if cur:
        blocks.append((path, "".join(cur)))
    return blocks


def prioritise(diff: str, extra_skip: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """Reorder a unified diff for review and drop the files nobody reviews.

    Returns the new diff and the sorted list of skipped paths. `extra_skip` holds
    further globs (from CLARIFYREVIEW_SKIP_GLOBS). A diff without `diff --git`
    headers is returned unchanged.
    """
    blocks = split_blocks(diff)
    if not blocks or not blocks[0][0]:
        return diff, []
    kept: list[tuple[int, int, str]] = []
    skipped: list[str] = []
    for i, (path, text) in enumerate(blocks):
        low = path.lower()
        if skip_reason(path) or any(fnmatch.fnmatchcase(low, g.lower()) for g in extra_skip):
            skipped.append(path)
            continue
        kept.append((group_of(path), i, text))
    kept.sort(key=lambda k: (k[0], k[1]))
    return "".join(t if t.endswith("\n") else t + "\n" for _, _, t in kept), sorted(skipped)
