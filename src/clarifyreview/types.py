"""The shared data model.

`PRContext` is the single input every stage of the pipeline reads. Stage 1 builds
it, Stage 2 scores it, Stage 3 may append to it, Stage 4 reviews it. No stage is
allowed a private side channel: if a detector needs something, it goes in here.

Determinism matters. The ablation compares conditions that differ *only* in
whether Stage 2 and Stage 3 ran, so the same pull request must serialise to a
byte-identical prompt on every invocation. Everything that renders is sorted, and
`fingerprint()` exists so tests can assert it.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- diff pieces


class Hunk(BaseModel):
    """One @@ hunk of a unified diff."""

    file: str
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    section: str = ""  # the trailing context on the @@ line, if any
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    body: str = ""  # verbatim hunk text, markers included

    @property
    def net_lines(self) -> int:
        return len(self.added) - len(self.removed)


class ChangedSymbol(BaseModel):
    """A function or class the diff actually touches.

    This is what separates a semantic diff from a line diff: reviewers reason
    about symbols, so the detector features do too.
    """

    file: str
    name: str
    kind: Literal["function", "method", "class"]
    start_line: int
    end_line: int
    signature: str = ""
    change: Literal["added", "removed", "modified"] = "modified"
    is_public: bool = True
    signature_changed: bool = False


class CodeSnippet(BaseModel):
    """One hop of surrounding code: a caller or callee of a changed symbol."""

    file: str
    name: str
    relation: Literal["caller", "callee"]
    start_line: int
    text: str


class LinkedIssue(BaseModel):
    number: int
    title: str
    body: str

    @property
    def is_substantive(self) -> bool:
        return len(self.body.strip()) >= 40


# ---------------------------------------------------------------- the context


class PRContext(BaseModel):
    """Everything the pipeline knows about one pull request."""

    pr_id: str  # stable key: "<repo>#<number>" or a benchmark instance id
    repo: str = ""
    number: int | None = None
    title: str = ""
    body: str = ""
    commit_messages: list[str] = Field(default_factory=list)

    diff: str = ""
    hunks: list[Hunk] = Field(default_factory=list)
    changed_symbols: list[ChangedSymbol] = Field(default_factory=list)
    neighbourhood: list[CodeSnippet] = Field(default_factory=list)
    linked_issue: LinkedIssue | None = None

    languages: list[str] = Field(default_factory=list)
    truncated: bool = False
    # Live tool: generated, vendored and lockfile changes left out of the diff.
    skipped_files: list[str] = Field(default_factory=list)

    # Set by Stage 3 when a developer (or the benchmark oracle) answers.
    clarification: ClarificationExchange | None = None

    @property
    def files_touched(self) -> list[str]:
        return sorted({h.file for h in self.hunks})

    def fingerprint(self) -> str:
        """Stable hash of the rendered context. Ingestion determinism test hangs
        off this."""
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()[:16]

    def render(self, include_clarification: bool = True) -> str:
        """The deterministic prompt rendering. Sort order is fixed everywhere."""
        parts: list[str] = []
        parts.append(f"## Pull request\nrepo: {self.repo}\ntitle: {self.title}")
        if self.body.strip():
            parts.append(f"### Description\n{self.body.strip()}")
        if self.commit_messages:
            joined = "\n".join(f"- {m}" for m in self.commit_messages)
            parts.append(f"### Commit messages\n{joined}")

        if self.linked_issue is not None:
            parts.append(
                f"### Linked issue #{self.linked_issue.number}: "
                f"{self.linked_issue.title}\n{self.linked_issue.body.strip()}"
            )
        else:
            parts.append("### Linked issue\n(none)")

        if self.changed_symbols:
            rows = "\n".join(
                f"- {s.file}:{s.start_line} {s.kind} {s.name}{s.signature} "
                f"[{s.change}{', signature changed' if s.signature_changed else ''}]"
                for s in sorted(
                    self.changed_symbols, key=lambda s: (s.file, s.start_line, s.name)
                )
            )
            parts.append(f"### Changed symbols\n{rows}")

        parts.append(f"### Diff\n```diff\n{self.diff.rstrip()}\n```")

        if self.neighbourhood:
            snips = "\n\n".join(
                f"# {s.file}:{s.start_line} ({s.relation} of a changed symbol)\n{s.text}"
                for s in sorted(
                    self.neighbourhood, key=lambda s: (s.file, s.start_line, s.name)
                )
            )
            fence = "python" if all(s.file.endswith(".py") for s in self.neighbourhood) else ""
            parts.append(f"### Surrounding code\n```{fence}\n{snips}\n```")

        if self.skipped_files:
            shown = ", ".join(self.skipped_files[:20])
            more = f" and {len(self.skipped_files) - 20} more" if len(self.skipped_files) > 20 else ""
            parts.append(f"(Left out as generated, vendored or lockfile changes: {shown}{more}.)")

        if self.truncated:
            parts.append("(Context was truncated to fit the ingestion token budget.)")

        if include_clarification and self.clarification is not None:
            parts.append(self.clarification.render())

        return "\n\n".join(parts)


# ------------------------------------------------------- stage 2: the branch


class DetectorName(str, Enum):
    HEURISTIC = "heuristic"
    CLASSIFIER = "classifier"
    SAMPLING = "sampling"
    PERTURBATION = "perturbation"


class Decision(BaseModel):
    """What every ambiguity detector returns. One shape, three implementations.

    `score` is comparable *within* a detector, not across them - each has its own
    frozen threshold. `why` is required because a detector nobody can interrogate
    is not a research result.
    """

    ask: bool
    score: float
    why: str
    detector: DetectorName
    threshold: float
    latency_ms: int = 0
    cost_usd: float = 0.0
    extra: dict = Field(default_factory=dict)


# -------------------------------------------------- stage 3: clarification


class ClarifyingQuestion(BaseModel):
    """A question is only allowed to exist if it names something concrete.

    `target` is required by the schema precisely so the model cannot fall back on
    'could you explain this PR?' - a generic question is worse than no question,
    because it costs the developer attention and returns nothing.
    """

    target: str = Field(description="The file:line, symbol, or hunk the question is about.")
    question: str = Field(description="One specific question, at most two sentences.")
    why_needed: str = Field(description="What the answer changes about the review.")


class ClarifyingQuestions(BaseModel):
    ambiguity_summary: str = Field(description="What is unclear, in one sentence.")
    questions: list[ClarifyingQuestion] = Field(
        description="At most two questions, ordered by importance.", max_length=2
    )


class ClarificationExchange(BaseModel):
    questions: ClarifyingQuestions
    answer: str | None = None
    answered: bool = False
    timed_out: bool = False
    responder: str = "unknown"  # "github" | "oracle" | "none"
    round_trip_s: float = 0.0

    def render(self) -> str:
        asked = "\n".join(f"- [{q.target}] {q.question}" for q in self.questions.questions)
        if not self.answered:
            return (
                "### Clarification\n"
                f"The following was asked and NOT answered "
                f"({'timed out' if self.timed_out else 'no reply'}):\n{asked}\n\n"
                "Review without this information and mark your confidence accordingly."
            )
        return (
            "### Clarification\n"
            f"The following was asked:\n{asked}\n\n"
            f"The pull request author replied:\n{(self.answer or '').strip()}\n\n"
            "Treat this reply as authoritative about intent."
        )


# ---------------------------------------------------- stage 4: the review


Severity = Literal["blocking", "major", "minor", "nit"]
Category = Literal[
    "correctness",
    "security",
    "performance",
    "maintainability",
    "testing",
    "style",
]


class ReviewFinding(BaseModel):
    """Structured, not prose.

    Study A scores findings mechanically. If the generator returns paragraphs,
    scoring becomes regex archaeology, so the schema is enforced at the API
    boundary rather than trusted to the prompt.
    """

    file: str
    line: int | None = None
    severity: Severity
    category: Category
    claim: str = Field(description="What is wrong, in one sentence.")
    evidence: str = Field(description="The specific code or context supporting the claim.")
    suggested_fix: str = Field(description="Concrete change, or 'none' if not applicable.")
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewOutput(BaseModel):
    intent_summary: str = Field(description="What this PR is trying to do, in one sentence.")
    findings: list[ReviewFinding] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    verdict: Literal["approve", "comment", "request_changes"]

    @property
    def flagged_a_defect(self) -> bool:
        """Whether this review asserts something is actually wrong.

        Style and nit-level comments do not count: a reviewer that says 'rename
        this variable' has not claimed the patch is broken, and scoring it as a
        false positive against a known-good patch would be unfair to every
        condition equally but would also wash out the effect we are measuring.
        """
        return any(
            f.severity in ("blocking", "major")
            and f.category in ("correctness", "security", "performance")
            for f in self.findings
        )


class ReviewRun(BaseModel):
    """One end-to-end pass. This is the row that lands in the experiment log."""

    pr_id: str
    condition: str  # "full_plain" | "stripped_plain" | "stripped_clarify"
    detector: DetectorName | None = None
    decision: Decision | None = None
    clarification: ClarificationExchange | None = None
    review: ReviewOutput | None = None
    context_fingerprint: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True)
