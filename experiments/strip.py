"""The ambiguity manipulation.

Stripping removes the author's stated intent and nothing else. Two levels:

  "issue"  v1, used in the 2 September pilot. Removes the linked issue, PR body,
           title and commit messages. The pilot showed this is not enough: the
           floor recovered intent on 5/5 instances, because golden patches state
           their purpose in the comments and docstrings they add.

  "prose"  v2, the default. Additionally removes every natural-language
           statement of intent the patch itself adds - comment lines, trailing
           comments and docstrings - while leaving every line of code untouched.

At either level the floor and the treatment see byte-identical diffs, so any
difference between them is attributable to the clarification step rather than to
the code they were shown. The ceiling sees the original diff and the issue.

The withheld text is returned, not discarded. It is the oracle's entire world in
`oracle.py`, and the scorer needs it too.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from clarifyreview.ingest.diff import parse_unified_diff
from clarifyreview.types import PRContext

STRIP_LEVELS = ("issue", "prose")

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


# ------------------------------------------------------------ prose removal

_DOC_OPEN = re.compile(r'^\s*(?:[rRbBuUfF]{0,2})("""|\'\'\')')
_HUNK_HDR = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _strip_trailing_comment(code: str) -> str:
    """Cut a trailing `# ...` comment, ignoring any `#` inside a string literal."""
    quote = None
    i = 0
    while i < len(code):
        ch = code[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return code[:i].rstrip()
        i += 1
    return code


def strip_prose_from_diff(diff: str) -> str:
    """Remove natural-language intent that a patch adds, leaving its code intact.

    Only added lines are touched. Removed lines are old code and say nothing
    about why the change is being made. Hunk headers are rewritten so the result
    is still a valid unified diff, and a hunk left with no changes is dropped.
    """
    out: list[str] = []
    hunk: list[str] = []
    header: re.Match | None = None
    shift = 0          # cumulative lines removed earlier in this file
    in_doc = None      # the open triple-quote delimiter, if inside a docstring

    def flush() -> None:
        nonlocal hunk, header, shift
        if header is None:
            return
        old_s, old_n, new_s, new_n, section = header.groups()
        old_n = 1 if old_n is None else int(old_n)
        new_n = 1 if new_n is None else int(new_n)
        dropped = sum(1 for line in hunk if line == "\0")
        kept = [line for line in hunk if line != "\0"]
        if any(line.startswith(("+", "-")) for line in kept):
            out.append(f"@@ -{old_s},{old_n} +{int(new_s) - shift},{new_n - dropped} @@"
                       f"{section}")
            out.extend(kept)
        shift += dropped
        hunk, header = [], None

    for line in diff.splitlines():
        if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
            flush()
            if line.startswith("diff --git "):
                shift, in_doc = 0, None
            out.append(line)
            continue
        m = _HUNK_HDR.match(line)
        if m:
            flush()
            header, in_doc = m, None
            continue
        if header is None:
            out.append(line)
            continue

        marker, text = (line[:1], line[1:]) if line else (" ", "")
        stripped = text.strip()

        # A docstring is removed only when the patch itself opened it on an
        # added line. A hunk can begin inside an existing docstring, where a lone
        # closing delimiter is indistinguishable from an opening one; tracking
        # state through context lines once deleted real code that followed such a
        # closer. The conservative rule can leave a little prose behind in rare
        # cases, but it can never remove a line of code.
        if in_doc:
            if marker != "+":
                in_doc = None          # left the added block; it was not ours
            else:
                if in_doc in stripped:
                    in_doc = None
                hunk.append("\0")
                continue
        if marker == "+":
            opened = _DOC_OPEN.match(text)
            if opened:
                delim = opened.group(1)
                if delim not in text[opened.end():]:
                    in_doc = delim
                hunk.append("\0")
                continue

        if marker == "+":
            if not stripped:
                hunk.append(line)      # a blank line is layout, not prose
                continue
            if stripped.startswith("#"):
                hunk.append("\0")
                continue
            cut = _strip_trailing_comment(text)
            hunk.append("+" + cut if cut.strip() else "\0")
            continue
        hunk.append(line)

    flush()
    return "\n".join(out) + ("\n" if diff.endswith("\n") else "")


def added_prose_lines(diff: str) -> int:
    """How many added lines are pure comment or docstring. Used as a leak check."""
    return sum(
        1 for h in parse_unified_diff(diff) for a in h.added
        if a.strip().startswith(("#", '"""', "\'\'\'"))
    )


# ---------------------------------------------------------------- context

def strip_context(ctx: PRContext, level: str = "prose") -> tuple[PRContext, Withheld]:
    """Return (stripped copy, what was removed).

    The placeholder is chosen by hashing the PR id, so the same instance always
    gets the same placeholder across runs - a re-run of the ablation must be
    byte-comparable with the original.
    """
    if level not in STRIP_LEVELS:
        raise ValueError(f"unknown strip level {level!r}; expected one of {STRIP_LEVELS}")
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

    if level == "prose":
        from clarifyreview.ingest import from_raw

        rebuilt = from_raw(
            pr_id=ctx.pr_id,
            diff=strip_prose_from_diff(ctx.diff),
            repo=ctx.repo,
            number=ctx.number,
            title=stripped.title,
            body="",
            commit_messages=stripped.commit_messages,
            linked_issue=None,
        )
        rebuilt.neighbourhood = ctx.neighbourhood
        stripped = rebuilt

    return stripped, withheld


def is_properly_stripped(ctx: PRContext, level: str = "issue") -> bool:
    """Guard for the runner. A leak here invalidates the whole condition."""
    if level == "prose" and added_prose_lines(ctx.diff):
        return False
    return (
        ctx.linked_issue is None
        and not (ctx.body or "").strip()
        and len(ctx.commit_messages) == 1
        and ctx.commit_messages[0] in PLACEHOLDER_MESSAGES
        and ctx.title in PLACEHOLDER_MESSAGES
    )
