"""Stage 3b: ask, wait, or fall through.

The `Responder` abstraction is what lets production and the benchmark run the
*same* clarification loop. On GitHub a responder posts a comment and waits for a
human; in Study A it calls the bounded oracle synchronously; in the timeout tests
it never answers. Nothing else in the pipeline changes between those cases, which
is the only way the prototype and the experiment can be said to measure one system.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from ..types import ClarificationExchange, ClarifyingQuestions, PRContext
from .question import QuestionGenerator

log = logging.getLogger(__name__)


class Responder(Protocol):
    name: str

    def ask(self, ctx: PRContext, questions: ClarifyingQuestions) -> str | None:
        """Return the author's answer, or None if none arrived."""


class NullResponder:
    """Nobody answers. Used to exercise the timeout path in tests."""

    name = "none"

    def ask(self, ctx: PRContext, questions: ClarifyingQuestions) -> str | None:
        return None


class GitHubResponder:
    """Production. Posts the question, then polls the PR thread for a reply.

    Polling rather than resuming from the webhook keeps this callable
    synchronously from the CLI. The webhook path in `gh/events.py` handles the
    long-lived case, where a run is parked and revived by an `issue_comment`
    event days later.
    """

    name = "github"

    def __init__(self, client, repo: str, number: int, timeout_s: int, poll_s: int = 30):
        self._client = client
        self.repo = repo
        self.number = number
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def ask(self, ctx: PRContext, questions: ClarifyingQuestions) -> str | None:
        from ..review.render import render_questions

        exchange = ClarificationExchange(questions=questions)
        comment = self._client.post_comment(
            self.repo, self.number, render_questions(exchange)
        )
        comment_id = comment.get("id")
        author = self._client.get_pull_request(self.repo, self.number).get("user", {}).get(
            "login"
        )

        if self.timeout_s <= 0:
            return None

        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            reply = self._client.find_reply_after(
                self.repo, self.number, after_comment_id=comment_id, from_user=author
            )
            if reply:
                return reply
            time.sleep(self.poll_s)
        log.info("no reply on %s#%s within %ss", self.repo, self.number, self.timeout_s)
        return None


class ClarificationLoop:
    def __init__(self, responder: Responder, question_generator: QuestionGenerator | None = None):
        self.responder = responder
        self.questions = question_generator or QuestionGenerator()

    def run(self, ctx: PRContext) -> tuple[ClarificationExchange, float]:
        """Ask, then attach the result to the context in place.

        A timeout is not an error. It produces an exchange with `answered=False`,
        which Stage 4 reads and turns into an explicitly lower-confidence review.
        The pull request is never blocked waiting for a reply.
        """
        questions, cost = self.questions.generate(ctx)
        started = time.monotonic()
        answer = self.responder.ask(ctx, questions)
        elapsed = time.monotonic() - started

        exchange = ClarificationExchange(
            questions=questions,
            answer=answer,
            answered=bool(answer and answer.strip()),
            timed_out=answer is None,
            responder=self.responder.name,
            round_trip_s=round(elapsed, 2),
        )
        ctx.clarification = exchange
        return exchange, cost
