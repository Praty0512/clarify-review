"""The webhook receiver.

Two events matter. `pull_request` (opened, synchronize) starts a run.
`issue_comment` revives one that is parked waiting for an answer - a developer may
take a day to reply, so the loop cannot be a blocking wait in a request handler.

A parked run ends one of two ways: the author replies, or the clarification
timeout expires and the review is posted anyway, flagged as written without an
answer. Parked runs live in memory, which is correct for a lab prototype and
clearly wrong for anything else; the note on `Parked` says so.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from dataclasses import dataclass

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from ..config import settings
from ..types import Decision, PRContext
from .client import GitHubClient

log = logging.getLogger(__name__)
app = FastAPI(title="ClarifyReview")

# Every comment the bot posts - question or review - opens with this header, so
# none of them can be mistaken for the author's answer.
BOT_MARKER = "### ClarifyReview"


@dataclass
class Parked:
    """A run waiting for the author's answer.

    In-process only: a restart forgets every parked run, which for a
    single-machine lab deployment is an acceptable trade against running a job
    queue. Move to the `runs` table if this ever needs to survive a deploy.
    """

    ctx: PRContext
    decision: Decision
    question_comment_id: int
    author: str | None
    timer: threading.Timer | None = None


_PARKED: dict[str, Parked] = {}
# Webhook handlers run on a thread pool, and the timeout fires on its own
# thread, so a reply and an expiry can race for the same parked run.
_LOCK = threading.Lock()


def verify_signature(body: bytes, signature: str | None) -> bool:
    secret = settings().github_webhook_secret
    if not secret:
        log.warning("GITHUB_WEBHOOK_SECRET unset; refusing to process webhooks")
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "parked_runs": len(_PARKED)}


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> dict:
    body = await request.body()
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="bad signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event == "pull_request" and payload.get("action") in ("opened", "synchronize"):
        repo = payload["repository"]["full_name"]
        number = payload["pull_request"]["number"]
        background.add_task(handle_pull_request, repo, number)
        return {"accepted": True, "event": event}

    if event == "issue_comment" and payload.get("action") == "created":
        repo = payload["repository"]["full_name"]
        number = payload["issue"]["number"]
        comment = payload["comment"]
        background.add_task(handle_comment, repo, number, comment["user"]["login"],
                            comment["body"], comment.get("id"))
        return {"accepted": True, "event": event}

    return {"accepted": False, "event": event}


class _RecordedDecision:
    """Replays the Stage 2 decision made when the run was parked.

    Resuming must not re-decide: the logged run has to show the decision that
    actually caused the question, not a control-condition "never asks".
    """

    def __init__(self, decision: Decision) -> None:
        self._decision = decision
        self.name = decision.detector

    def decide(self, ctx: PRContext) -> Decision:
        return self._decision


def handle_pull_request(repo: str, number: int) -> None:
    """Stages 1 and 2. If the detector says ask, park; otherwise review now."""
    from ..detect import build as build_detector
    from ..ingest import from_github
    from ..pipeline import CONDITION_STRIPPED_CLARIFY, Pipeline
    from ..review.render import render_questions
    from ..types import ClarificationExchange

    cfg = settings()
    with GitHubClient() as gh:
        ctx = from_github(gh, repo, number)
        detector = build_detector(cfg.clarifyreview_detector)
        decision = detector.decide(ctx)
        log.info("%s: ask=%s score=%.2f (%s)", ctx.pr_id, decision.ask, decision.score,
                 decision.why)

        if decision.ask:
            from ..clarify.question import QuestionGenerator

            try:
                questions, _ = QuestionGenerator().generate(ctx)
            except Exception:  # noqa: BLE001
                # A question that cannot be generated must not leave the pull
                # request without a review; review it as a single pass instead.
                log.exception("%s: question generation failed; reviewing without asking",
                              ctx.pr_id)
            else:
                exchange = ClarificationExchange(questions=questions, responder="github")
                comment = gh.post_comment(repo, number, render_questions(exchange))
                author = gh.get_pull_request(repo, number).get("user", {}).get("login")
                ctx.clarification = exchange
                _park(Parked(ctx, decision, comment["id"], author),
                      cfg.clarifyreview_clarify_timeout)
                return

        pipeline = Pipeline(detector=_RecordedDecision(decision), responder=None,
                            condition=CONDITION_STRIPPED_CLARIFY)
        run = pipeline.run(ctx)
        _publish(gh, repo, number, run)


def _park(parked: Parked, timeout_s: int) -> None:
    pr_id = parked.ctx.pr_id
    with _LOCK:
        old = _PARKED.pop(pr_id, None)
        if old and old.timer:
            old.timer.cancel()      # a new push supersedes the earlier question
        if timeout_s > 0:
            parked.timer = threading.Timer(timeout_s, expire, args=(pr_id,))
            parked.timer.daemon = True
            parked.timer.start()
        _PARKED[pr_id] = parked


def handle_comment(repo: str, number: int, commenter: str, body: str,
                   comment_id: int | None = None) -> None:
    """Stage 3 resumption, then Stage 4."""
    pr_id = f"{repo}#{number}"
    with _LOCK:
        parked = _PARKED.get(pr_id)
        if parked is None:
            return
        # The question itself arrives as an issue_comment event too. When the
        # bot runs under the author's own token - the usual lab setup - it would
        # otherwise read its own question as the answer.
        if comment_id is not None and comment_id == parked.question_comment_id:
            return
        if (body or "").lstrip().startswith(BOT_MARKER):
            return
        if parked.author and commenter != parked.author:
            return                  # not the author; keep waiting
        _PARKED.pop(pr_id)
        if parked.timer:
            parked.timer.cancel()

    exchange = parked.ctx.clarification
    if exchange is not None:
        exchange.answer = body
        exchange.answered = bool(body and body.strip())
        exchange.timed_out = False
    _finish(parked)


def expire(pr_id: str) -> None:
    """No answer within the timeout: review anyway, flagged low-confidence."""
    with _LOCK:
        parked = _PARKED.pop(pr_id, None)
    if parked is None:
        return
    exchange = parked.ctx.clarification
    if exchange is not None:
        exchange.answered = False
        exchange.timed_out = True
    log.info("%s: no answer within the timeout; reviewing without it", pr_id)
    _finish(parked)


def _finish(parked: Parked) -> None:
    from ..pipeline import CONDITION_STRIPPED_CLARIFY, Pipeline

    ctx = parked.ctx
    repo, number = ctx.repo, ctx.number
    pipeline = Pipeline(detector=_RecordedDecision(parked.decision), responder=None,
                        condition=CONDITION_STRIPPED_CLARIFY)
    run = pipeline.run(ctx)
    run.clarification = ctx.clarification
    with GitHubClient() as gh:
        _publish(gh, repo, number, run)


def _publish(gh: GitHubClient, repo: str, number: int, run) -> None:
    from ..review.render import render_review
    from ..store import db

    if run.review is None:
        log.error("%s: no review produced (%s)", run.pr_id, run.error)
        return
    note = None
    if run.clarification and not run.clarification.answered:
        note = "No answer was received, so this review was written without it."
    gh.post_comment(repo, number, render_review(run.review, detector_note=note))

    cfg = settings()
    db.init(cfg.clarifyreview_db)
    with db.connect(cfg.clarifyreview_db) as conn:
        db.record_run(conn, run)
