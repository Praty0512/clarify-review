"""The live bot end to end, offline.

Real FastAPI app driven through TestClient with HMAC-signed payloads, a real SQLite
file, and the real heuristic detector. Only the edges are fake: GitHub (records
comments), the question generator and the review generator (stubs, as in
test_pipeline.py). A fake clock stands in for the passage of days.
"""

import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from clarifyreview.config import reset_settings
from clarifyreview.detect.base import Thresholds
from clarifyreview.detect.heuristic import HeuristicDetector
from clarifyreview.gh import app as bot
from clarifyreview.gh.settings import reset_bot_settings
from clarifyreview.review.render import ERROR_MARKER, MARKER_PREFIX, QUESTION_MARKER
from clarifyreview.store import db
from clarifyreview.types import (
    ClarifyingQuestion, ClarifyingQuestions, LinkedIssue, ReviewFinding, ReviewOutput,
)
from conftest import AMBIGUOUS_DIFF, CLEAR_DIFF

SECRET = "s3cret"
REPO = "acme/app"
BOT = "clarifybot"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeGitHub:
    """Records every comment; serves two canned PRs (1 ambiguous, 2 clear)."""

    def __init__(self):
        self.comments: list[dict] = []  # {"id", "number", "user", "body"}
        self.next_id = 100
        self.login = BOT

    # reads
    def get_pull_request(self, repo, number):
        title = "fix login bug" if number == 1 else "Strip whitespace in slugify"
        return {"title": title, "body": "", "user": {"login": "alice"}}

    def get_diff(self, repo, number):
        return AMBIGUOUS_DIFF if number == 1 else CLEAR_DIFF

    def get_commit_messages(self, repo, number):
        if number == 1:
            return ["fix"]
        return ["Strip surrounding whitespace before slugifying, so that titles pasted "
                "from the CMS do not produce trailing dashes."]

    def get_linked_issue(self, repo, number):
        if number == 1:
            return None
        return LinkedIssue(number=44, title="Slugs from pasted titles have trailing dashes",
                           body="When a title is pasted from the CMS it keeps its surrounding "
                                "whitespace, and _slugify turns that into a trailing dash. "
                                "Trim the input before slugifying. Reproduced on staging.")

    def get_authenticated_login(self):
        return self.login

    def find_reply_after(self, repo, number, after_comment_id, from_user):
        for c in self.comments:
            if (c["number"] == number and c["user"] == from_user
                    and c["id"] > (after_comment_id or 0) and MARKER_PREFIX not in c["body"]):
                return c["body"]
        return None

    # writes
    def post_comment(self, repo, number, body):
        self.next_id += 1
        self.comments.append({"id": self.next_id, "number": number, "user": self.login,
                              "body": body})
        return {"id": self.next_id}

    def user_says(self, number, user, body):
        self.next_id += 1
        self.comments.append({"id": self.next_id, "number": number, "user": user, "body": body})

    def close(self):
        pass

    def bot_comments(self, number=None, marker=None):
        return [c for c in self.comments
                if c["user"] == self.login and (number is None or c["number"] == number)
                and (marker is None or marker in c["body"])]


class CountingDetector:
    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.calls = 0

    def decide(self, ctx):
        self.calls += 1
        return self.inner.decide(ctx)


class StubQuestions:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def generate(self, ctx):
        self.calls += 1
        if self.fail:
            raise RuntimeError("question model unavailable SECRET-TOKEN-123")
        return (
            ClarifyingQuestions(
                ambiguity_summary="a guard disappeared with no stated reason",
                questions=[ClarifyingQuestion(
                    target="app/auth.py:12", question="Was this check moved elsewhere?",
                    why_needed="decides whether this is a bug or a refactor")]),
            0.002,
        )


class StubReviewer:
    def __init__(self):
        self.contexts: list[str] = []
        self.fail = False
        self.big = False

    def generate(self, ctx):
        if self.fail:
            raise RuntimeError("review model unavailable")
        self.contexts.append(ctx.render())
        findings = [ReviewFinding(
            file="app/auth.py", line=12, severity="major", category="correctness",
            claim="guard removed", evidence="x" * (5000 if self.big else 20),
            suggested_fix="restore it", confidence=0.7)]
        if self.big:
            findings = findings * 20
        return (
            ReviewOutput(intent_summary="removes a null check", overall_confidence=0.8,
                         verdict="comment", findings=findings),
            {"model": "stub", "input_tokens": 100, "output_tokens": 50,
             "cache_read_tokens": 0, "cost_usd": 0.001, "latency_ms": 1,
             "context_fingerprint": ctx.fingerprint()},
        )


class Env:
    def __init__(self, monkeypatch, tmp_path, **env):
        self.db_path = tmp_path / "bot.db"
        base = {
            "GITHUB_WEBHOOK_SECRET": SECRET,
            "GITHUB_TOKEN": "unused",
            "CLARIFYREVIEW_DB": str(self.db_path),
            "CLARIFYREVIEW_SWEEP_INTERVAL_S": "0",
            "CLARIFYREVIEW_DETECTOR": "heuristic",
            "CLARIFYREVIEW_CLARIFY_TIMEOUT": "86400",
            "CLARIFYREVIEW_BOT_LOGIN": "",
        }
        for k, v in {**base, **env}.items():
            monkeypatch.setenv(k, str(v))
        reset_settings()
        reset_bot_settings()
        self.gh = FakeGitHub()
        self.clock = Clock()
        self.detector = CountingDetector(
            HeuristicDetector(thresholds=Thresholds({"heuristic": 0.4}, "test")))
        self.questions = StubQuestions()
        self.reviewer = StubReviewer()
        self.install()

    def install(self):
        bot.set_services(bot.Services(
            client_factory=lambda installation_id: self.gh,
            detector_factory=lambda: self.detector,
            question_generator=lambda: self.questions,
            review_generator=lambda: self.reviewer,
            clock=self.clock,
        ))

    def restart(self):
        """What a process restart loses: every in-memory cache and singleton."""
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()
        self.install()

    def rows(self, sql, args=()):
        with db.connect(self.db_path) as conn:
            return [dict(r) for r in conn.execute(sql, args)]


@pytest.fixture
def env(monkeypatch, tmp_path):
    e = Env(monkeypatch, tmp_path)
    yield e
    bot.set_services(None)
    reset_settings()
    reset_bot_settings()


@pytest.fixture
def client(env):
    with TestClient(bot.app) as c:
        yield c


def sign(body: bytes, secret=SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send(client, event, payload, *, delivery=None, secret=SECRET):
    body = json.dumps(payload).encode()
    return client.post("/webhook", content=body, headers={
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery or uuid.uuid4().hex,
        "X-Hub-Signature-256": sign(body, secret),
        "Content-Type": "application/json",
    })


def pr_event(action="opened", number=1, sha="sha1", author="alice", author_type="User",
             draft=False):
    return {
        "action": action,
        "repository": {"full_name": REPO},
        "pull_request": {"number": number, "draft": draft, "head": {"sha": sha},
                         "user": {"login": author, "type": author_type}},
    }


def comment_event(body, user="alice", number=1, user_type="User", is_pr=True):
    issue = {"number": number}
    if is_pr:
        issue["pull_request"] = {"url": "https://api.github.com/x"}
    return {
        "action": "created",
        "repository": {"full_name": REPO},
        "issue": issue,
        "comment": {"body": body, "user": {"login": user, "type": user_type}},
    }


# ----------------------------------------------------------------- the tests


def test_ambiguous_pr_gets_one_marked_question_and_is_parked(env, client):
    r = send(client, "pull_request", pr_event())
    assert r.json() == {"accepted": True, "event": "pull_request"}

    questions = env.gh.bot_comments(1)
    assert len(questions) == 1 and questions[0]["body"].startswith(QUESTION_MARKER)
    assert env.reviewer.contexts == []  # no review yet
    assert client.get("/health").json() == {"status": "ok", "parked_runs": 1}
    parked = env.rows("SELECT * FROM parked_runs")
    assert len(parked) == 1
    assert parked[0]["author"] == "alice" and parked[0]["head_sha"] == "sha1"
    assert parked[0]["question_comment_id"] == questions[0]["id"]
    assert parked[0]["deadline_at"] == env.clock.t + 86400


def test_parked_run_survives_a_restart_and_resumes(env):
    assert not hasattr(bot, "_PARKED")
    with TestClient(bot.app) as c1:
        send(c1, "pull_request", pr_event())
        assert c1.get("/health").json()["parked_runs"] == 1

    env.restart()
    with TestClient(bot.app) as c2:
        assert c2.get("/health").json()["parked_runs"] == 1
        env.gh.user_says(1, "alice", "Yes, moved to the gateway.")
        send(c2, "issue_comment", comment_event("Yes, moved to the gateway."))
        assert len(env.gh.bot_comments(1, "clarifyreview:review")) == 1
        assert c2.get("/health").json()["parked_runs"] == 0


def test_only_the_authors_real_answer_revives_the_run(env, client):
    send(client, "pull_request", pr_event())
    n_before = len(env.gh.comments)

    # A reviewer, a bot, the bot's own marker comment echoed back as the author,
    # an empty comment and a comment on a plain issue: none is an answer.
    send(client, "issue_comment", comment_event("looks fine to me", user="bob"))
    send(client, "issue_comment", comment_event("beep", user="alice", user_type="Bot"))
    send(client, "issue_comment",
         comment_event(f"{QUESTION_MARKER}\n### ClarifyReview question", user="alice"))
    send(client, "issue_comment", comment_event("   ", user="alice"))
    send(client, "issue_comment", comment_event("an answer", user="alice", is_pr=False))
    assert len(env.gh.comments) == n_before
    assert env.reviewer.contexts == []
    assert env.rows("SELECT state FROM parked_runs")[0]["state"] == "parked"

    env.gh.user_says(1, "alice", "Moved to the API gateway.")
    send(client, "issue_comment", comment_event("Moved to the API gateway."))

    reviews = env.gh.bot_comments(1, "clarifyreview:review sha=sha1")
    assert len(reviews) == 1
    assert "No answer" not in reviews[0]["body"]
    assert "Moved to the API gateway." in env.reviewer.contexts[0]
    assert env.rows("SELECT state FROM parked_runs")[0]["state"] == "done"

    [run] = env.rows("SELECT * FROM runs")
    assert (run["asked"], run["answered"], run["timed_out"]) == (1, 1, 0)
    assert run["detector"] == "heuristic" and run["condition"] == "github_live"
    assert run["ask"] == 1 and run["responder"] == "github"
    assert run["cost_usd"] == pytest.approx(0.001 + 0.002)  # review + question
    clar = env.rows("SELECT * FROM clarifications")
    assert len(clar) == 1 and clar[0]["answer"] == "Moved to the API gateway."
    assert env.detector.calls == 1  # decide() ran once, not again on resume
    assert env.rows("SELECT * FROM posted_reviews")[0]["head_sha"] == "sha1"


def test_single_account_testing_the_bots_own_comment_is_not_the_answer(monkeypatch, tmp_path):
    """Token owned by the PR author, so the bot's question is posted *as* alice."""
    e = Env(monkeypatch, tmp_path)
    e.gh.login = "alice"
    try:
        with TestClient(bot.app) as c:
            send(c, "pull_request", pr_event())
            [question] = e.gh.bot_comments(1)
            assert question["user"] == "alice" and QUESTION_MARKER in question["body"]
            # GitHub fires issue_comment for the bot's own question, as alice.
            send(c, "issue_comment", comment_event(question["body"], user="alice"))
            assert e.reviewer.contexts == []
            assert c.get("/health").json()["parked_runs"] == 1
            # Her real reply, unmarked, is the answer.
            send(c, "issue_comment", comment_event("Moved to the gateway.", user="alice"))
            assert len(e.gh.bot_comments(1, "clarifyreview:review")) == 1
    finally:
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()


def test_configured_bot_login_is_never_asked_and_never_an_answerer(monkeypatch, tmp_path):
    e = Env(monkeypatch, tmp_path, CLARIFYREVIEW_BOT_LOGIN="Alice")
    try:
        with TestClient(bot.app) as c:
            send(c, "pull_request", pr_event())  # authored by alice == the bot
            assert e.gh.bot_comments(1, QUESTION_MARKER) == []
            assert len(e.gh.bot_comments(1, "clarifyreview:review")) == 1
    finally:
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()


def test_clear_pr_is_reviewed_at_once_with_one_decision(env, client):
    send(client, "pull_request", pr_event(number=2, sha="shaB"))
    assert env.gh.bot_comments(2, QUESTION_MARKER) == []
    [review] = env.gh.bot_comments(2, "clarifyreview:review sha=shaB")
    assert review["body"].startswith("<!-- clarifyreview:review sha=shaB -->")
    assert env.detector.calls == 1
    assert env.questions.calls == 0
    [run] = env.rows("SELECT * FROM runs")
    assert run["asked"] == 0 and run["condition"] == "github_live"
    assert run["detector"] == "heuristic" and run["ask"] == 0
    assert client.get("/health").json()["parked_runs"] == 0


def test_timeout_publishes_an_unanswered_review(env, client):
    send(client, "pull_request", pr_event())
    assert bot.sweep_expired() == 0  # not due yet
    env.clock.t += 86400 + 1

    assert bot.sweep_expired() == 1
    [review] = env.gh.bot_comments(1, "clarifyreview:review")
    assert "No answer was received" in review["body"]
    [run] = env.rows("SELECT * FROM runs")
    assert (run["asked"], run["answered"], run["timed_out"]) == (1, 0, 1)
    assert env.rows("SELECT state FROM parked_runs")[0]["state"] == "done"
    assert bot.sweep_expired() == 0  # exactly once


def test_sweep_picks_up_a_reply_whose_webhook_was_missed(env, client):
    send(client, "pull_request", pr_event())
    env.gh.user_says(1, "alice", "Moved to the gateway (posted while the bot was down).")
    env.clock.t += 86400 + 1
    assert bot.sweep_expired() == 1
    [run] = env.rows("SELECT * FROM runs")
    assert run["answered"] == 1 and run["timed_out"] == 0


def test_any_webhook_triggers_an_opportunistic_sweep(env, client):
    send(client, "pull_request", pr_event())
    env.clock.t += 86400 + 1
    send(client, "pull_request", pr_event(action="opened", number=2, sha="shaB"))
    assert len(env.gh.bot_comments(1, "clarifyreview:review")) == 1


def test_push_while_parked_updates_head_without_re_asking(env, client):
    send(client, "pull_request", pr_event(sha="sha1"))
    send(client, "pull_request", pr_event(action="synchronize", sha="sha2"))
    send(client, "pull_request", pr_event(action="synchronize", sha="sha3"))

    assert len(env.gh.bot_comments(1, QUESTION_MARKER)) == 1
    assert env.questions.calls == 1
    [row] = env.rows("SELECT * FROM parked_runs")
    assert row["head_sha"] == "sha3" and row["state"] == "parked"

    env.gh.user_says(1, "alice", "Moved.")
    send(client, "issue_comment", comment_event("Moved."))
    assert len(env.gh.bot_comments(1, "clarifyreview:review sha=sha3")) == 1
    assert env.detector.calls == 1


def test_duplicate_delivery_is_ignored(env, client):
    first = send(client, "pull_request", pr_event(), delivery="D-1")
    second = send(client, "pull_request", pr_event(), delivery="D-1")
    assert first.json()["accepted"] is True
    assert second.json() == {"accepted": False, "event": "pull_request", "duplicate": True}
    assert len(env.gh.bot_comments(1)) == 1
    assert env.rows("SELECT status FROM webhook_deliveries") == [{"status": "done"}]


def test_a_different_delivery_for_the_same_head_does_not_repeat_the_review(env, client):
    send(client, "pull_request", pr_event(number=2, sha="shaB"))
    send(client, "pull_request", pr_event(action="reopened", number=2, sha="shaB"))
    assert len(env.gh.bot_comments(2, "clarifyreview:review")) == 1


def test_bad_or_missing_signature_is_rejected(env, client):
    assert send(client, "pull_request", pr_event(), secret="wrong").status_code == 401
    body = json.dumps(pr_event()).encode()
    r = client.post("/webhook", content=body, headers={"X-GitHub-Event": "pull_request"})
    assert r.status_code == 401
    assert env.gh.comments == []


def test_ping_and_irrelevant_events(env, client):
    assert send(client, "ping", {"zen": "x"}).json() == {"pong": True}
    assert send(client, "issue_comment",
                comment_event("hello", is_pr=False)).json()["accepted"] is False
    assert send(client, "pull_request",
                pr_event(action="labeled")).json()["accepted"] is False
    assert send(client, "push", {"repository": {"full_name": REPO}}).json()["accepted"] is False


def test_review_comments_and_submitted_reviews_can_answer(env, client):
    send(client, "pull_request", pr_event())
    send(client, "pull_request_review_comment", {
        "action": "created", "repository": {"full_name": REPO},
        "pull_request": {"number": 1},
        "comment": {"body": "It moved to the gateway.", "user": {"login": "alice", "type": "User"}},
    })
    assert len(env.gh.bot_comments(1, "clarifyreview:review")) == 1


def test_question_generator_failure_reports_exactly_once(env, client):
    env.questions.fail = True
    send(client, "pull_request", pr_event(), delivery="D-1")
    send(client, "pull_request", pr_event(action="reopened"), delivery="D-2")

    errors = env.gh.bot_comments(1, ERROR_MARKER)
    assert len(errors) == 1
    assert "RuntimeError" in errors[0]["body"]
    assert "SECRET-TOKEN" not in errors[0]["body"] and "Traceback" not in errors[0]["body"]
    assert env.rows("SELECT * FROM parked_runs") == []
    assert {r["delivery_id"]: r["status"] for r in
            env.rows("SELECT * FROM webhook_deliveries")} == {"D-1": "failed", "D-2": "failed"}


def test_review_failure_on_resume_releases_the_row(env, client):
    send(client, "pull_request", pr_event())
    env.reviewer.fail = True

    env.gh.user_says(1, "alice", "first answer")
    send(client, "issue_comment", comment_event("first answer"))
    [row] = env.rows("SELECT * FROM parked_runs")
    assert row["state"] == "parked" and row["attempts"] == 1
    assert "RuntimeError" in row["last_error"]
    assert len(env.gh.bot_comments(1, ERROR_MARKER)) == 1

    send(client, "issue_comment", comment_event("second answer"))
    assert env.rows("SELECT attempts FROM parked_runs")[0]["attempts"] == 2
    assert len(env.gh.bot_comments(1, ERROR_MARKER)) == 1  # still only one notice

    env.reviewer.fail = False
    send(client, "issue_comment", comment_event("third answer"))
    assert env.rows("SELECT state FROM parked_runs")[0]["state"] == "done"
    assert len(env.gh.bot_comments(1, "clarifyreview:review")) == 1
    assert "third answer" in env.reviewer.contexts[0]


def test_drafts_closed_prs_and_bot_authors(env, client):
    send(client, "pull_request", pr_event(draft=True))
    assert env.gh.comments == []
    send(client, "pull_request", pr_event(action="ready_for_review", draft=False))
    assert len(env.gh.bot_comments(1, QUESTION_MARKER)) == 1

    send(client, "pull_request", pr_event(action="closed"))
    assert env.rows("SELECT state FROM parked_runs")[0]["state"] == "cancelled"
    assert client.get("/health").json()["parked_runs"] == 0

    # A bot-authored ambiguous PR is reviewed, never asked: nobody can answer.
    send(client, "pull_request",
         pr_event(number=1, sha="shaZ", author="dependabot[bot]", author_type="Bot"))
    assert len(env.gh.bot_comments(1, QUESTION_MARKER)) == 1  # still just the first one
    assert len(env.gh.bot_comments(1, "clarifyreview:review sha=shaZ")) == 1


def test_draft_skipping_can_be_turned_off(monkeypatch, tmp_path):
    e = Env(monkeypatch, tmp_path, CLARIFYREVIEW_SKIP_DRAFTS="false")
    try:
        with TestClient(bot.app) as c:
            send(c, "pull_request", pr_event(draft=True))
            assert len(e.gh.bot_comments(1, QUESTION_MARKER)) == 1
    finally:
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()


def test_zero_timeout_asks_and_reviews_immediately_as_unanswered(monkeypatch, tmp_path):
    e = Env(monkeypatch, tmp_path, CLARIFYREVIEW_CLARIFY_TIMEOUT="0")
    try:
        with TestClient(bot.app) as c:
            send(c, "pull_request", pr_event())
            assert len(e.gh.bot_comments(1, QUESTION_MARKER)) == 1
            [review] = e.gh.bot_comments(1, "clarifyreview:review")
            assert "No answer was received" in review["body"]
            assert c.get("/health").json()["parked_runs"] == 0
            [run] = e.rows("SELECT * FROM runs")
            assert (run["asked"], run["answered"], run["timed_out"]) == (1, 0, 1)
    finally:
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()


def test_new_head_gets_its_own_review_once(env, client):
    send(client, "pull_request", pr_event(number=2, sha="shaB"))
    send(client, "pull_request", pr_event(action="synchronize", number=2, sha="shaC"))
    send(client, "pull_request", pr_event(action="synchronize", number=2, sha="shaC"))
    assert len(env.gh.bot_comments(2, "clarifyreview:review sha=shaB")) == 1
    assert len(env.gh.bot_comments(2, "clarifyreview:review sha=shaC")) == 1
    assert len(env.gh.bot_comments(2, "clarifyreview:review")) == 2


def test_review_on_push_can_be_turned_off(monkeypatch, tmp_path):
    e = Env(monkeypatch, tmp_path, CLARIFYREVIEW_REVIEW_ON_PUSH="false")
    try:
        with TestClient(bot.app) as c:
            send(c, "pull_request", pr_event(number=2, sha="shaB"))
            send(c, "pull_request", pr_event(action="synchronize", number=2, sha="shaC"))
            assert len(e.gh.bot_comments(2, "clarifyreview:review")) == 1
    finally:
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()


def test_oversized_review_is_cut_to_the_configured_limit(monkeypatch, tmp_path):
    e = Env(monkeypatch, tmp_path, CLARIFYREVIEW_MAX_COMMENT_CHARS="3000")
    e.reviewer.big = True
    try:
        with TestClient(bot.app) as c:
            send(c, "pull_request", pr_event(number=2, sha="shaB"))
            [review] = e.gh.bot_comments(2, "clarifyreview:review")
            assert len(review["body"]) <= 3000
            assert review["body"].startswith("<!-- clarifyreview:review sha=shaB -->")
            assert "shortened" in review["body"]
    finally:
        bot.set_services(None)
        reset_settings()
        reset_bot_settings()


def test_unfinished_delivery_is_replayed_on_startup(env):
    """The process died after accepting a webhook but before handling it."""
    with db.connect(env.db_path) as conn:
        db.init(env.db_path)
        db.record_delivery(
            conn, "LOST", "pull_request", REPO, 1, "opened", env.clock.t - 60,
            json.dumps({"kind": "pull_request", "kwargs": {
                "repo": REPO, "number": 1, "action": "opened", "head_sha": "sha1",
                "author": "alice", "author_type": "User", "draft": False,
                "installation_id": None}}),
        )
    with TestClient(bot.app) as c:
        # The replay runs in a startup task; give it a moment via a request.
        import time
        for _ in range(50):
            if env.gh.bot_comments(1, QUESTION_MARKER):
                break
            time.sleep(0.05)
        assert len(env.gh.bot_comments(1, QUESTION_MARKER)) == 1
        assert c.get("/health").json()["parked_runs"] == 1
