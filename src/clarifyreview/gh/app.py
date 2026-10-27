"""The webhook receiver.

Two kinds of event matter. A `pull_request` event starts a run; if the detector says
ask, the bot posts one question and *parks* the run. An answer - the author's next
comment on the PR - or the clarification deadline revives it. A developer may take a
day to reply, so the wait is state in SQLite (`parked_runs`), not a blocking call in
a request handler, and it survives a restart.

Everything the handlers touch outside this module is injected through `Services`, so
the whole flow runs offline in tests with a fake GitHub client and stub generators.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from ..config import settings
from ..detect.base import BaseDetector
from ..review.render import (
    ERROR_MARKER,
    QUESTION_MARKER,
    build_pr_review,
    has_marker,
    render_questions,
    render_review,
    review_marker,
)
from ..store import db
from ..types import ClarificationExchange, Decision, PRContext
from .client import GitHubClient
from .settings import bot_settings

log = logging.getLogger(__name__)

NO_ANSWER_NOTE = "No answer was received, so this review was written without it."
TRUNCATED_NOTE = "The context was truncated to fit the token budget."
QUESTION_FAILED_NOTE = ("I meant to ask a clarifying question first but could not "
                        "generate one, so this review was written without it.")
_PR_ACTIONS = {"opened", "reopened", "ready_for_review", "synchronize", "closed"}


# ------------------------------------------------------------------ services


@dataclass
class Services:
    """Everything the handlers reach out for, so tests can substitute all of it."""

    client_factory: Callable[[int | None], GitHubClient]  # arg: installation id
    detector_factory: Callable[[], BaseDetector]
    question_generator: Callable[[], object]
    review_generator: Callable[[], object]
    clock: Callable[[], float] = field(default=time.time)


_services: Services | None = None
_app_providers: dict[int, object] = {}
_db_ready: set[str] = set()
_pr_locks: dict[str, threading.Lock] = {}
_pr_locks_guard = threading.Lock()


def _default_client(installation_id: int | None) -> GitHubClient:
    bs = bot_settings()
    if bs.github_app_id and bs.github_app_private_key_path and installation_id:
        from pathlib import Path

        from .auth import AppTokenProvider

        provider = _app_providers.get(installation_id)
        if provider is None:
            provider = AppTokenProvider(
                bs.github_app_id,
                Path(bs.github_app_private_key_path).read_text(encoding="utf-8"),
                installation_id,
                api_url=bs.github_api_url,
            )
            _app_providers[installation_id] = provider
        return GitHubClient(token_provider=provider)
    return GitHubClient()


def _default_detector() -> BaseDetector:
    from ..detect import build, live_thresholds

    return build(settings().clarifyreview_detector, thresholds=live_thresholds())


def _default_questions():
    from ..clarify.question import QuestionGenerator

    return QuestionGenerator()


def _default_reviewer():
    from ..review.generator import ReviewGenerator

    return ReviewGenerator()


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services(
            client_factory=_default_client,
            detector_factory=_default_detector,
            question_generator=_default_questions,
            review_generator=_default_reviewer,
        )
    return _services


def set_services(s: Services | None) -> None:
    """Install fakes, or pass None to drop everything cached (a simulated restart)."""
    global _services
    _services = s
    _app_providers.clear()
    _db_ready.clear()


@contextmanager
def _client(installation_id: int | None) -> Iterator[GitHubClient]:
    gh = get_services().client_factory(installation_id)
    try:
        yield gh
    finally:
        close = getattr(gh, "close", None)
        if close is not None:
            close()


@contextmanager
def _conn() -> Iterator:
    path = settings().clarifyreview_db
    if str(path) not in _db_ready:
        db.init(path)
        _db_ready.add(str(path))
    with db.connect(path) as conn:
        yield conn


def _pr_lock(pr_id: str) -> threading.Lock:
    with _pr_locks_guard:
        return _pr_locks.setdefault(pr_id, threading.Lock())


# ------------------------------------------------------------------ security


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


# ------------------------------------------------------------------ the app


def _reprocess_pending(older_than: float) -> int:
    """Replay deliveries that were accepted but never finished (a crash mid-handler).
    Handlers are idempotent - they dedupe on head sha and parked state."""
    with _conn() as conn:
        pending = db.pending_deliveries(conn, older_than)
    for row in pending:
        try:
            spec = json.loads(row["args_json"])
        except (TypeError, ValueError):
            continue
        log.info("replaying unfinished delivery %s", row["delivery_id"])
        _run_delivery(row["delivery_id"], spec["kind"], spec["kwargs"])
    return len(pending)


async def _sweep_loop(interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await run_in_threadpool(sweep_expired)
        except Exception:  # noqa: BLE001 - the loop must outlive one bad sweep
            log.exception("sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = get_services().clock()
    with _conn():
        pass  # create the schema before the first webhook arrives
    background = [asyncio.create_task(run_in_threadpool(_reprocess_pending, started))]
    interval = bot_settings().clarifyreview_sweep_interval_s
    if interval > 0:
        background.append(asyncio.create_task(_sweep_loop(interval)))
    try:
        yield
    finally:
        for t in background:
            t.cancel()


app = FastAPI(title="ClarifyReview", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    with _conn() as conn:
        return {"status": "ok", "parked_runs": db.count_parked(conn)}


def _parse_event(event: str, payload: dict) -> tuple[str, dict, str | None, int | None] | None:
    """Reduce a webhook payload to (kind, handler kwargs, action, number), or None
    for anything the bot ignores."""
    repo = (payload.get("repository") or {}).get("full_name")
    installation_id = (payload.get("installation") or {}).get("id")
    action = payload.get("action")
    if not repo:
        return None

    if event == "pull_request" and action in _PR_ACTIONS:
        pr = payload["pull_request"]
        user = pr.get("user") or {}
        kwargs = dict(
            repo=repo, number=pr["number"], action=action,
            head_sha=(pr.get("head") or {}).get("sha"),
            author=user.get("login"), author_type=user.get("type"),
            draft=bool(pr.get("draft")), installation_id=installation_id,
        )
        return "pull_request", kwargs, action, pr["number"]

    comment = None
    number = None
    if event == "issue_comment" and action == "created":
        # GitHub sends issue_comment for plain issues too.
        if not (payload.get("issue") or {}).get("pull_request"):
            return None
        comment, number = payload.get("comment"), payload["issue"]["number"]
    elif event == "pull_request_review_comment" and action == "created":
        comment, number = payload.get("comment"), payload["pull_request"]["number"]
    elif event == "pull_request_review" and action == "submitted":
        comment, number = payload.get("review"), payload["pull_request"]["number"]
    if comment is None or not (comment.get("body") or "").strip():
        return None
    user = comment.get("user") or {}
    kwargs = dict(
        repo=repo, number=number, commenter=user.get("login"),
        commenter_type=user.get("type"), body=comment["body"],
        installation_id=installation_id,
    )
    return "comment", kwargs, action, number


@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> dict:
    body = await request.body()
    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="bad signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"pong": True}
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON") from None

    parsed = _parse_event(event, payload)
    if parsed is None:
        return {"accepted": False, "event": event}
    kind, kwargs, action, number = parsed

    delivery_id = request.headers.get("X-GitHub-Delivery") or uuid.uuid4().hex
    args_json = json.dumps({"kind": kind, "kwargs": kwargs})

    def record() -> bool:
        with _conn() as conn:
            return db.record_delivery(
                conn, delivery_id, event, kwargs["repo"], number, action,
                get_services().clock(), args_json,
            )

    if not await run_in_threadpool(record):
        log.info("duplicate delivery %s ignored", delivery_id)
        return {"accepted": False, "event": event, "duplicate": True}

    background.add_task(_run_delivery, delivery_id, kind, kwargs)
    return {"accepted": True, "event": event}


def _run_delivery(delivery_id: str, kind: str, kwargs: dict) -> None:
    """Background entry point. Never raises: an exception here would vanish into the
    server log, so handlers report to the PR themselves and this records the outcome."""
    handler = handle_pull_request if kind == "pull_request" else handle_comment
    status = "done"
    try:
        handler(**kwargs)
    except Exception:  # noqa: BLE001
        log.exception("delivery %s (%s) failed", delivery_id, kind)
        status = "failed"
    try:
        with _conn() as conn:
            db.mark_delivery(conn, delivery_id, status)
    except Exception:  # noqa: BLE001
        log.exception("could not record the outcome of delivery %s", delivery_id)
    try:
        sweep_expired()  # opportunistic: runs that expired while no sweeper was alive
    except Exception:  # noqa: BLE001
        log.exception("opportunistic sweep failed")


# ------------------------------------------------------------------ handlers


def _bot_login() -> str:
    """The login configured as the bot's own, lower-cased, or "".

    Deliberately not looked up from the token. The bot's comments are recognised by
    their hidden marker, which is what makes it safe to run on a token owned by the
    PR author (single-account testing); treating the token owner as "the bot" would
    make the author's real reply unanswerable. Set CLARIFYREVIEW_BOT_LOGIN only when
    the bot has its own account, so its PRs are never asked and its comments never
    count as answers.
    """
    return bot_settings().clarifyreview_bot_login.strip().lower()


@contextmanager
def _reporting(gh, repo: str, number: int, head_sha: str | None) -> Iterator[None]:
    """Whatever goes wrong inside, tell the PR once, then let the error propagate."""
    try:
        yield
    except Exception as exc:
        log.exception("%s#%s failed", repo, number)
        _report_error(gh, repo, number, head_sha, type(exc).__name__)
        raise


def _report_error(gh, repo: str, number: int, head_sha: str | None, message: str) -> None:
    """Post a short failure notice, at most once per head sha. No stack traces and
    nothing from the exception beyond its class name: the PR is public, the log is not."""
    pr_id = f"{repo}#{number}"
    key = f"error:{head_sha or ''}"
    try:
        with _conn() as conn:
            if db.review_posted_for(conn, pr_id, key):
                return
            db.record_posted_review(conn, pr_id, key, None, None, get_services().clock())
        safe = "".join(ch for ch in message if ch.isalnum() or ch in "._ -")[:80]
        gh.post_comment(
            repo, number,
            f"{ERROR_MARKER}\n### ClarifyReview\n\nI hit an error ({safe}) and could not "
            "review this pull request. A maintainer can find the details in the bot's logs; "
            "pushing a new commit will make me try again.",
        )
    except Exception:  # noqa: BLE001 - reporting must never mask the original error
        log.exception("could not post the error notice for %s", pr_id)


def handle_pull_request(
    repo: str,
    number: int,
    *,
    action: str,
    head_sha: str | None,
    author: str | None,
    author_type: str | None,
    draft: bool,
    installation_id: int | None = None,
) -> None:
    """Stages 1 and 2. If the detector says ask, post the question and park;
    otherwise review now."""
    pr_id = f"{repo}#{number}"
    cfg = bot_settings()
    with _pr_lock(pr_id):
        if action == "closed":
            with _conn() as conn:
                row = db.get_parked(conn, pr_id)
                if row and row["state"] == "parked":
                    db.finish_parked(conn, pr_id, "cancelled")
                    log.info("%s closed; cancelled its parked run", pr_id)
            return
        if draft and cfg.clarifyreview_skip_drafts:
            log.info("%s is a draft; skipping", pr_id)
            return

        with _conn() as conn:
            row = db.get_parked(conn, pr_id)
            reviewed = db.review_posted_for(conn, pr_id, head_sha)
        waiting = row is not None and row["state"] in ("parked", "claimed")
        is_push = action == "synchronize"

        if is_push and waiting:
            if row["state"] == "parked":
                _refresh_parked(repo, number, head_sha, installation_id, row)
            return  # never re-ask on a push
        if is_push and not cfg.clarifyreview_review_on_push:
            return
        if reviewed or waiting:
            log.info("%s@%s already handled; skipping", pr_id, head_sha)
            return

        _review_pr(repo, number, head_sha, author, author_type, installation_id,
                   can_ask_on_open=not is_push)


def _refresh_parked(repo, number, head_sha, installation_id, row) -> None:
    """A push while parked: swap in the new code, keep the question and deadline."""
    from ..ingest import from_github

    with _client(installation_id) as gh, _reporting(gh, repo, number, head_sha):
        ctx = from_github(gh, repo, number)
        ctx.clarification = PRContext.model_validate_json(row["context_json"]).clarification
        with _conn() as conn:
            db.update_parked_context(conn, row["pr_id"], ctx, head_sha)
    log.info("%s: new head %s while parked; context refreshed, not re-asked",
             row["pr_id"], head_sha)


def _review_pr(repo, number, head_sha, author, author_type, installation_id,
               *, can_ask_on_open: bool) -> None:
    from ..detect.base import NeverAskDetector
    from ..ingest import from_github
    from ..pipeline import Pipeline

    svc = get_services()
    cfg = bot_settings()
    pr_id = f"{repo}#{number}"

    with _client(installation_id) as gh, _reporting(gh, repo, number, head_sha):
        ctx = from_github(gh, repo, number)

        bot_authored = (author_type == "Bot") or (
            bool(author) and author.lower() == _bot_login()
        )
        if bot_authored:
            decision = NeverAskDetector().decide(ctx)  # a bot cannot answer a question
        else:
            decision = svc.detector_factory().decide(ctx)
        can_ask = can_ask_on_open and not bot_authored
        log.info("%s: ask=%s score=%.2f (%s)", pr_id, decision.ask, decision.score,
                 decision.why)

        if decision.ask and can_ask:
            _ask(gh, svc, ctx, decision, repo, number, head_sha, author, installation_id)
            return

        pipeline = Pipeline(generator=svc.review_generator(),
                            condition=cfg.clarifyreview_bot_condition)
        run = pipeline.run(ctx, decision=decision)  # Stage 2 already paid for
        _publish(gh, repo, number, head_sha, ctx, run)


def _ask(gh, svc, ctx, decision, repo, number, head_sha, author, installation_id) -> None:
    from ..pipeline import Pipeline

    cfg = bot_settings()
    try:
        questions, qcost = svc.question_generator().generate(ctx)
    except Exception as exc:  # noqa: BLE001
        # A question that cannot be generated must not leave the pull request with
        # an error notice instead of a review. Review it single-pass and say why.
        log.exception("%s: question generation failed; reviewing without asking", ctx.pr_id)
        pipeline = Pipeline(generator=svc.review_generator(),
                            condition=cfg.clarifyreview_bot_condition)
        run = pipeline.run(ctx, decision=decision)
        _publish(gh, repo, number, head_sha, ctx, run,
                 extra_note=f"{QUESTION_FAILED_NOTE} ({type(exc).__name__})")
        return
    exchange = ClarificationExchange(questions=questions, responder="github")
    ctx.clarification = exchange
    comment = gh.post_comment(
        repo, number, render_questions(exchange, marker=QUESTION_MARKER)
    )

    timeout = settings().clarifyreview_clarify_timeout
    if timeout <= 0:
        # Nobody is going to be waited for: say so, and review straight away.
        exchange.timed_out = True
        pipeline = Pipeline(generator=svc.review_generator(),
                            condition=cfg.clarifyreview_bot_condition)
        run = pipeline.run(ctx, decision=decision)
        _publish(gh, repo, number, head_sha, ctx, run, question_cost=qcost)
        return

    now = svc.clock()
    with _conn() as conn:
        db.park(
            conn, pr_id=f"{repo}#{number}", repo=repo, number=number, author=author,
            head_sha=head_sha, installation_id=installation_id,
            comment_id=comment.get("id"), ctx=ctx, decision=decision,
            detector=decision.detector.value, question_cost=qcost,
            now=now, deadline=now + timeout,
        )
    log.info("%s: question posted, parked until %s", ctx.pr_id, int(now + timeout))


def handle_comment(
    repo: str,
    number: int,
    *,
    commenter: str | None,
    commenter_type: str | None,
    body: str,
    installation_id: int | None = None,
) -> None:
    """Stage 3 resumption: the author's reply revives the parked run."""
    pr_id = f"{repo}#{number}"
    if commenter_type == "Bot" or has_marker(body) or not (body or "").strip():
        return  # our own comments, other bots, and empty reviews are never answers
    with _pr_lock(pr_id):
        with _conn() as conn:
            row = db.get_parked(conn, pr_id)
        if row is None or row["state"] != "parked":
            return
        is_author = bool(commenter) and commenter.lower() == (row["author"] or "").lower()
        if not commenter or not (is_author or _may_answer(commenter)):
            return  # a passing reviewer is not the author (CLARIFYREVIEW_ANSWER_FROM)

        with _client(row["installation_id"]) as gh:
            if commenter.lower() == _bot_login():
                return
            with _conn() as conn:
                claimed = db.claim_parked(conn, pr_id, get_services().clock())
            if claimed is None:
                return  # another worker got there first
            if not is_author:
                # The reviewer model is told whose word this is, not the author's.
                body = f"(Answered by @{commenter}, a reviewer, not the PR author.) {body}"
            _resume(gh, claimed, answer=body)


def _may_answer(commenter: str) -> bool:
    """Whether someone other than the PR author may answer the bot's question.

    CLARIFYREVIEW_ANSWER_FROM: "author" (default) - only the author; "anyone" -
    any human commenter; otherwise a comma-separated list of logins allowed to
    answer besides the author.
    """
    rule = bot_settings().clarifyreview_answer_from.strip().lower()
    if rule in ("", "author"):
        return False
    if rule == "anyone":
        return True
    return commenter.lower() in {u.strip().lstrip("@") for u in rule.split(",") if u.strip()}


def _resume(gh, row: dict, *, answer: str | None) -> None:
    """Run the claimed row to completion, or give it back and tell the PR."""
    try:
        _resume_and_publish(gh, row, answer=answer)
        with _conn() as conn:
            db.finish_parked(conn, row["pr_id"], "done")
    except Exception as exc:
        log.exception("%s: resume failed", row["pr_id"])
        with _conn() as conn:
            state = db.release_parked(conn, row["pr_id"], f"{type(exc).__name__}: {exc}")
        log.warning("%s: released as %r", row["pr_id"], state)
        _report_error(gh, row["repo"], row["number"], row["head_sha"], type(exc).__name__)
        raise


def _resume_and_publish(gh, row: dict, *, answer: str | None) -> None:
    from ..pipeline import Pipeline

    svc = get_services()
    cfg = bot_settings()
    ctx = PRContext.model_validate_json(row["context_json"])
    decision = Decision.model_validate_json(row["decision_json"])

    exchange = ctx.clarification
    if exchange is not None:
        if answer is not None and answer.strip():
            exchange.answer = answer
            exchange.answered = True
            exchange.timed_out = False
        else:
            exchange.answer = None
            exchange.answered = False
            exchange.timed_out = True
        exchange.round_trip_s = round(max(0.0, svc.clock() - row["created_at"]), 2)

    pipeline = Pipeline(generator=svc.review_generator(),
                        condition=cfg.clarifyreview_bot_condition)
    run = pipeline.run(ctx, decision=decision)
    _publish(gh, row["repo"], row["number"], row["head_sha"], ctx, run,
             question_cost=row["question_cost_usd"] or 0.0)


def _fit(body: str, limit: int) -> str:
    if len(body) <= limit:
        return body
    note = "\n\n_(Review shortened to fit GitHub's comment size limit.)_"
    return body[: max(0, limit - len(note))].rstrip() + note


def _publish(gh, repo: str, number: int, head_sha: str | None, ctx: PRContext, run,
             *, question_cost: float = 0.0, extra_note: str | None = None) -> None:
    """Post the review and log the run. `run.cost_usd` already holds the detector's
    cost (the pipeline adds it); the question's is added here."""
    if run.review is None:
        raise RuntimeError(run.error or "no review produced")
    run.cost_usd += question_cost

    notes = []
    if run.clarification is not None and not run.clarification.answered:
        notes.append(NO_ANSWER_NOTE)
    if ctx.skipped_files:
        shown = ", ".join(f"`{p}`" for p in ctx.skipped_files[:5])
        more = f" and {len(ctx.skipped_files) - 5} more" if len(ctx.skipped_files) > 5 else ""
        notes.append(f"Not reviewed (generated, vendored or lockfile): {shown}{more}.")
    if ctx.truncated:
        notes.append(TRUNCATED_NOTE)
    if extra_note:
        notes.append(extra_note)
    body = _fit(
        render_review(run.review, detector_note=" ".join(notes) or None,
                      marker=review_marker(head_sha)),
        bot_settings().clarifyreview_max_comment_chars,
    )
    comment = gh.post_comment(repo, number, body)
    if bot_settings().clarifyreview_pr_review and hasattr(gh, "create_review"):
        try:
            event, review_body, inline = build_pr_review(run.review, ctx.hunks)
            gh.create_review(repo, number, commit_id=head_sha, event=event,
                             body=review_body, comments=inline)
        except Exception as exc:  # noqa: BLE001 - the summary comment is already up
            log.warning("%s#%s: could not submit the code review (%s)", repo, number,
                        type(exc).__name__)

    with _conn() as conn:
        run_id = db.record_run(conn, run)
        conn.commit()
        db.record_posted_review(conn, run.pr_id, head_sha or "", run_id,
                                comment.get("id"), get_services().clock())


# --------------------------------------------------------------------- sweep


def sweep_expired(now: float | None = None, limit: int = 20) -> int:
    """Finish parked runs whose deadline passed (and ones a dead worker abandoned).
    Returns how many it handled. Safe to call from several places at once: each row
    is claimed atomically."""
    svc = get_services()
    now = svc.clock() if now is None else now
    with _conn() as conn:
        rows = db.claim_expired(conn, now, limit=limit)

    handled = 0
    for row in rows:
        try:
            with _client(row["installation_id"]) as gh:
                answer = None
                try:
                    # A webhook missed while the server was down would otherwise be
                    # reported as "no answer".
                    answer = gh.find_reply_after(
                        row["repo"], row["number"], row["question_comment_id"], row["author"]
                    )
                except Exception:  # noqa: BLE001
                    log.warning("%s: could not look for a missed reply", row["pr_id"])
                _resume(gh, row, answer=answer)
            handled += 1
        except Exception:  # noqa: BLE001 - one bad row must not stop the sweep
            log.warning("%s: sweep could not finish this run", row["pr_id"])
    return handled
