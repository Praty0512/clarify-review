"""Findings become markdown at the very last step, never before.

Everything upstream moves structured data around. This module exists only so a
human on GitHub sees something readable, and nothing in the evaluation path
depends on it.
"""

from __future__ import annotations

from ..types import ClarificationExchange, ReviewOutput

# Hidden markers let the bot recognise its own comments. They matter when the bot
# runs on a personal access token: its question is then posted by the same account
# as the PR author, and without a marker it would read as the author's answer.
MARKER_PREFIX = "<!-- clarifyreview"
QUESTION_MARKER = "<!-- clarifyreview:question -->"
ERROR_MARKER = "<!-- clarifyreview:error -->"


def review_marker(head_sha: str | None = None) -> str:
    if head_sha:
        return f"<!-- clarifyreview:review sha={head_sha} -->"
    return "<!-- clarifyreview:review -->"


def has_marker(body: str | None) -> bool:
    return MARKER_PREFIX in (body or "")


_SEVERITY_MARK = {
    "blocking": "**blocking**",
    "major": "**major**",
    "minor": "minor",
    "nit": "nit",
}
_VERDICT_LINE = {
    "approve": "No blocking issues found.",
    "comment": "Some comments below, nothing blocking.",
    "request_changes": "Changes requested.",
}


def render_review(
    review: ReviewOutput, detector_note: str | None = None, marker: str | None = None
) -> str:
    lines: list[str] = ["### ClarifyReview", "", f"**What this looks like:** {review.intent_summary}", ""]

    if not review.findings:
        lines.append(_VERDICT_LINE[review.verdict])
    else:
        lines.append(_VERDICT_LINE[review.verdict])
        lines.append("")
        for f in sorted(
            review.findings,
            key=lambda f: (
                ["blocking", "major", "minor", "nit"].index(f.severity),
                f.file,
                f.line or 0,
            ),
        ):
            where = f"`{f.file}`" + (f":{f.line}" if f.line else "")
            lines.append(
                f"- {_SEVERITY_MARK[f.severity]} · {f.category} · {where} — {f.claim}"
            )
            lines.append(f"  - Why: {f.evidence}")
            if f.suggested_fix and f.suggested_fix.lower() != "none":
                lines.append(f"  - Suggested: {f.suggested_fix}")
            lines.append(f"  - Confidence: {f.confidence:.0%}")

    lines += ["", f"_Overall confidence: {review.overall_confidence:.0%}_"]
    if detector_note:
        lines.append(f"_{detector_note}_")
    out = "\n".join(lines)
    return out if marker is None else f"{marker}\n{out}"


def render_questions(exchange: ClarificationExchange, marker: str | None = None) -> str:
    """The comment posted when Stage 2 says ask.

    Kept short on purpose. A question that arrives wrapped in three paragraphs of
    preamble gets skimmed, and an unanswered question is the failure mode this
    whole stage exists to avoid.
    """
    qs = exchange.questions
    lines = [
        "### ClarifyReview — one thing before I review",
        "",
        qs.ambiguity_summary,
        "",
    ]
    for q in qs.questions:
        lines.append(f"- **{q.target}** — {q.question}")
    lines += ["", "_Reply here and I'll review with that in mind._"]
    out = "\n".join(lines)
    return out if marker is None else f"{marker}\n{out}"
