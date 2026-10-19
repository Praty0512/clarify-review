"""Stage 3a: generating the question.

The schema requires a `target` on every question. That constraint does more work
than any amount of prompt wording: a model that must name a file, line, or symbol
cannot fall back on "could you explain what this PR does?", and a generic question
is worse than no question at all - it spends the developer's attention and returns
nothing the reviewer can use.
"""

from __future__ import annotations

from ..config import question_model
from ..types import ClarifyingQuestions, PRContext

SYSTEM = """\
You write the single question a code reviewer would ask the author of a pull \
request before reviewing it, when the diff alone does not make the author's \
intent clear.

A good question:
- names a specific file, line, or symbol in `target`;
- asks about *intent*, not about facts you could read off the diff yourself;
- distinguishes between two readings you genuinely cannot choose between;
- is answerable in one sentence by someone who wrote the change.

A bad question asks the author to explain the pull request, restates the diff, \
or asks something the diff already answers. Never write one.

Ask one question. Ask a second only if it is about a genuinely separate ambiguity \
in a different part of the change. Two questions about the same thing is one \
question written badly.\
"""

INSTRUCTION = """\
This pull request was flagged as having unclear intent. Identify what is actually \
ambiguous, then write the question (or at most two) whose answer would most change \
your review.\
"""


class QuestionGenerator:
    def __init__(self, llm=None, model: str | None = None) -> None:
        self._llm = llm
        self._model = model

    @property
    def model(self) -> str:
        return self._model or question_model()

    @property
    def llm(self):
        if self._llm is None:
            from ..llm.client import LLM

            self._llm = LLM()
        return self._llm

    def generate(self, ctx: PRContext) -> tuple[ClarifyingQuestions, float]:
        result = self.llm.structured(
            model=self.model,
            schema=ClarifyingQuestions,
            system=SYSTEM,
            cached_context=ctx.render(),
            instruction=INSTRUCTION,
            max_tokens=2000,
            thinking=True,
        )
        questions = result.value
        # The schema caps the list at two; this guards the ordering guarantee the
        # prompt asks for but cannot enforce.
        questions.questions = questions.questions[:2]
        return questions, result.usage.cost_usd
