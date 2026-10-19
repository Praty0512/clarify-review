"""Findings become markdown at the very last step, never before.

Everything upstream moves structured data around. This module exists only so a
human on GitHub sees something readable, and nothing in the evaluation path
depends on it.
"""

from __future__ import annotations

from ..types import ClarificationExchange, ReviewOutput

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


def render_review(review: ReviewOutput, detector_note: str | None = None) -> str:
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
    return "\n".join(lines)


def render_questions(exchange: ClarificationExchange) -> str:
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
    return "\n".join(lines)
