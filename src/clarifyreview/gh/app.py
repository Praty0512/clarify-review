"""The webhook receiver.

Two events matter. `pull_request` (opened, synchronize) starts a run.
`issue_comment` revives one that is parked waiting for an answer - a developer may
take a day to reply, so the loop cannot be a blocking wait in a request handler.

Parked runs live in memory here, which is correct for a lab prototype and clearly
wrong for anything else; the note on `_PARKED` says so rather than pretending
otherwise.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from ..config import settings
from ..types import PRContext
from .client import GitHubClient

log = logging.getLogger(__name__)
app = FastAPI(title="ClarifyReview")

# pr_id -> (context, posted question comment id). In-process only: a restart
# forgets every parked run, which for a single-machine lab deployment is an
# acceptable trade against running a job queue. Move to the `runs` table if this
# ever needs to survive a deploy.
_PARKED: dict[str, tuple[PRContext, int]] = {}


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
        commenter = payload["comment"]["user"]["login"]
        body_text = payload["comment"]["body"]
        background.add_task(handle_comment, repo, number, commenter, body_text)
        return {"accepted": True, "event": event}

    return {"accepted": False, "event": event}


def handle_pull_request(repo: str, number: int) -> None:
    """Stages 1 and 2. If the detector says ask, park; otherwise review now."""
    from ..detect import build as build_detector
    from ..ingest import from_github
    from ..pipeline import CONDITION_STRIPPED_CLARIFY, Pipeline
    from ..review.render import render_questions, render_review
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

            questions, _ = QuestionGenerator().generate(ctx)
            exchange = ClarificationExchange(questions=questions, responder="github")
            comment = gh.post_comment(repo, number, render_questions(exchange))
            ctx.clarification = exchange
            _PARKED[ctx.pr_id] = (ctx, comment["id"])
            return

        pipeline = Pipeline.plain(CONDITION_STRIPPED_CLARIFY)
        pipeline.detector = detector
        run = pipeline.run(ctx)
        _publish(gh, repo, number, run)


def handle_comment(repo: str, number: int, commenter: str, body: str) -> None:
    """Stage 3 resumption, then Stage 4."""
    from ..pipeline import CONDITION_STRIPPED_CLARIFY, Pipeline

    pr_id = f"{repo}#{number}"
    parked = _PARKED.pop(pr_id, None)
    if parked is None:
        return

    ctx, _comment_id = parked
    with GitHubClient() as gh:
        author = gh.get_pull_request(repo, number).get("user", {}).get("login")
        if commenter != author:
            _PARKED[pr_id] = parked  # not the author; keep waiting
            return

        if ctx.clarification is not None:
            ctx.clarification.answer = body
            ctx.clarification.answered = True
            ctx.clarification.timed_out = False

        run = Pipeline.plain(CONDITION_STRIPPED_CLARIFY).run(ctx)
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
