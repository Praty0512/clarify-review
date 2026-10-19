"""Stage 4: the review generator.

Emits structured findings, not prose. Study A scores findings mechanically; if
this returned paragraphs, scoring would become regex archaeology and December
would be spent on it. The schema is enforced at the API boundary rather than
requested politely in the prompt.

The generator is deliberately unaware of which detector ran, or whether one ran
at all. Its only knowledge of Stage 3 is whether `ctx.clarification` is present.
"""

from __future__ import annotations

import time

from ..config import review_model
from ..types import PRContext, ReviewOutput

SYSTEM = """\
You are a careful code reviewer. You review one pull request at a time and report \
only what you can support from the diff and the context you were given.

Rules you follow without exception:

1. Report a finding only when you can point to the specific code that makes it \
true. If your reasoning is "this could be a problem if X", and you cannot tell \
whether X holds, do not report it.
2. Severity means what it says. `blocking` and `major` assert the change is \
actually wrong. Use `minor`, `nit`, or the `style`/`maintainability` categories \
for anything you are merely suggesting.
3. Your `confidence` is a real estimate, not a formality. A finding you are 0.5 \
confident of should say 0.5.
4. If the change looks correct, say so and return no findings. An empty findings \
list is a valid, and often correct, review.
5. When a clarification from the pull request author is present, it is \
authoritative about intent. Do not second-guess a stated intent; review whether \
the code achieves it.

Always fill `intent_summary` with what you believe the change is trying to do, \
even when you are unsure - it is scored separately from your findings.\
"""

INSTRUCTION_PLAIN = """\
Review this pull request. Report the findings you can support, set \
`intent_summary` to what you believe the change is for, and choose a verdict.\
"""

INSTRUCTION_CLARIFIED = """\
Review this pull request. The author has answered a question about their intent - \
treat that answer as authoritative and review whether the code achieves what they \
described. Report the findings you can support, set `intent_summary` to what you \
now believe the change is for, and choose a verdict.\
"""

INSTRUCTION_UNANSWERED = """\
Review this pull request. A question about the author's intent was asked and went \
unanswered, so you are reviewing without it. Report only findings you can support \
without knowing the answer, lower `overall_confidence` accordingly, and set \
`intent_summary` to your best reading of what the change is for.\
"""


class ReviewGenerator:
    def __init__(self, llm=None, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    @property
    def model(self) -> str:
        # Resolved late so a provider switch is picked up without reconstruction.
        return self._model or review_model()

    @property
    def llm(self):
        if self._llm is None:
            from ..llm.client import LLM

            self._llm = LLM()
        return self._llm

    def generate(self, ctx: PRContext) -> tuple[ReviewOutput, dict]:
        """Produce a review. Returns the review plus usage metadata for the log."""
        if ctx.clarification is None:
            instruction = INSTRUCTION_PLAIN
        elif ctx.clarification.answered:
            instruction = INSTRUCTION_CLARIFIED
        else:
            instruction = INSTRUCTION_UNANSWERED

        started = time.monotonic()
        result = self.llm.structured(
            model=self.model,
            schema=ReviewOutput,
            system=SYSTEM,
            cached_context=ctx.render(),
            instruction=instruction,
            max_tokens=16000,
            thinking=True,
        )
        meta = {
            "model": result.usage.served_model or self.model,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_read_tokens": result.usage.cache_read_tokens,
            "cost_usd": result.usage.cost_usd,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "context_fingerprint": ctx.fingerprint(),
        }
        return result.value, meta
