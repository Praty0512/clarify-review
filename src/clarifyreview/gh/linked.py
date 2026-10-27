"""Body-reference fallback for "which issue does this PR address".

GitHub's `closingIssuesReferences` only knows about links it recognised itself
(default branch, keyword in the PR body or a commit). It misses plenty of PRs
whose body plainly says "fixes #123". The real-PR labelling set
(`experiments/fetch_prs.py`) and the live tool both fall back to the PR body; this
module is the one place that regex lives so they see the same context.
"""

from __future__ import annotations

import re

FIXES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+"
                   r"(?:([\w.-]+/[\w.-]+))?#(\d+)", re.I)


def body_issue_number(body: str | None, repo: str) -> int | None:
    """First `fixes #N` / `closes owner/repo#N` in `body` that points at `repo`."""
    for m in FIXES.finditer(body or ""):
        if m.group(1) is None or m.group(1).lower() == repo.lower():
            return int(m.group(2))
    return None
