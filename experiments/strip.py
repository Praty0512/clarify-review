"""The ambiguity manipulation.

Stripping removes the author's stated intent and nothing else. The diff is
untouched: both the floor and the treatment condition see byte-identical code, so
any difference between them is attributable to the missing intent rather than to
the code they were shown.

The withheld text is returned, not discarded. It is the oracle's entire world in
`oracle.py`, and the scorer needs it too.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from clarifyreview.types import PRContext

# A rotation rather than a single constant: one fixed placeholder repeated 200
# times is a signal in itself, and a model that learns to recognise "cleanup" as
# "this is the stripped condition" would confound the comparison.
PLACEHOLDER_MESSAGES: tuple[str, ...] = (
    "cleanup",
    "update",
    "fix",
    "minor changes",
    "wip",
    "small fix",
    "tidy up",
    "misc",
)


@dataclass
class Withheld:
    """What the stripped condition cannot see. The oracle's only input."""

    problem_statement: str
    commit_messages: list[str]
    pr_body: str
    issue_title: str = ""

    def is_empty(self) -> bool:
        return not (self.problem_statement.strip() or self.pr_body.strip())


def strip_context(ctx: PRContext) -> tuple[PRContext, Withheld]:
    """Return (stripped copy, what was removed).

    The placeholder is chosen by hashing the PR id, so the same instance always
    gets the same placeholder across runs - a re-run of the ablation must be
    byte-comparable with the original.
    """
    withheld = Withheld(
        problem_statement=(ctx.linked_issue.body if ctx.linked_issue else ""),
        commit_messages=list(ctx.commit_messages),
        pr_body=ctx.body or "",
        issue_title=(ctx.linked_issue.title if ctx.linked_issue else ""),
    )

    idx = int(hashlib.sha256(ctx.pr_id.encode()).hexdigest(), 16) % len(PLACEHOLDER_MESSAGES)
    stripped = ctx.model_copy(deep=True)
    stripped.linked_issue = None
    stripped.body = ""
    stripped.commit_messages = [PLACEHOLDER_MESSAGES[idx]]

    # The title often restates the issue, so it is stripped too - leaving it in
    # would leak most of what the manipulation is supposed to remove.
    stripped.title = PLACEHOLDER_MESSAGES[idx]

    return stripped, withheld


def is_properly_stripped(ctx: PRContext) -> bool:
    """Guard for the runner. A leak here invalidates the whole condition."""
    return (
        ctx.linked_issue is None
        and not (ctx.body or "").strip()
        and len(ctx.commit_messages) == 1
        and ctx.commit_messages[0] in PLACEHOLDER_MESSAGES
        and ctx.title in PLACEHOLDER_MESSAGES
    )
