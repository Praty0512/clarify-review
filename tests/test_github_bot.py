"""The GitHub bot, end to end, against a fake GitHub - no network, no key.

These cover the paths a live deployment depends on and the benchmark never
exercises: webhook authentication and routing, parking a run on a question,
resuming it on the author's reply, ignoring everyone else (including the bot's
own question), and the timeout fallback that keeps a pull request from waiting
forever.
"""

import hashlib
import hmac
import json

import pytest

from clarifyreview.config import reset_settings
from clarifyreview.gh import app as bot
from clarifyreview.types import (
    ClarifyingQuestion,
    ClarifyingQuestions,
    ReviewFinding,
    ReviewOutput,
)

from conftest import AMBIGUOUS_DIFF, CLEAR_DIFF

REPO, AUTHOR, BOT = "acme/app", "alice", "clarifyreview-bot"
QUESTION = "one thing before I review"   # header of the question comment


class FakeGitHub:
    def __init__(self, diff, commit="fix", author=AUTHOR):
        self.diff, self.commit, self.author = diff, commit, author
        self.comments: list[dict] = []
        self._next_id = 100

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get_pull_request(self, repo, number):
        return {"title": "update", "body": "", "user": {"login": self.author}}

    def get_diff(self, repo, number):
        return self.diff

    def get_commit_messages(self, repo, number):
        return [self.commit]

    def get_linked_issue(self, repo, number):
        return None

    def post_comment(self, repo, number, body):
        self._next_id += 1
        c = {"id": self._next_id, "body": body, "user": {"login": BOT}}
        self.comments.append(c)
        return c


class StubQuestions:
    def generate(self, ctx):
        return ClarifyingQuestions(
            ambiguity_summary="a guard disappeared with no stated reason",
            questions=[ClarifyingQuestion(target="app/auth.py:12",
                                          question="Was this check moved elsewhere?",
                                          why_needed="decides whether this is a defect")],
        ), 0.0


def _stub_review(self, ctx):
    answered = bool(ctx.clarification and ctx.clarification.answered)
    review = ReviewOutput(
        intent_summary="validation moved upstream" if answered else "removes a null check",
        overall_confidence=0.9 if answered else 0.5,
        verdict="approve" if answered else "comment",
        findings=[] if answered else [ReviewFinding(
            file="app/auth.py", line=12, severity="major", category="correctness",
            claim="guard removed", evidence="the check is gone", suggested_fix="restore it",
            confidence=0.6)],
    )
    return review, {"model": "stub", "input_tokens": 1, "output_tokens": 1,
                    "cache_read_tokens": 0, "cost_usd": 0.0, "latency_ms": 1,
                    "context_fingerprint": ctx.fingerprint()}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLARIFYREVIEW_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("CLARIFYREVIEW_CLARIFY_TIMEOUT", "3600")
    monkeypatch.setenv("CLARIFYREVIEW_DETECTOR", "heuristic")
    reset_settings()
    monkeypatch.setattr("clarifyreview.clarify.question.QuestionGenerator", StubQuestions)
    monkeypatch.setattr("clarifyreview.review.generator.ReviewGenerator.generate", _stub_review)
    bot._PARKED.clear()
    yield tmp_path
    for p in bot._PARKED.values():
        if p.timer:
            p.timer.cancel()
    bot._PARKED.clear()
    reset_settings()


def _use(monkeypatch, gh):
    monkeypatch.setattr(bot, "GitHubClient", lambda *a, **k: gh)


def _logged(tmp_path):
    import sqlite3
    conn = sqlite3.connect(tmp_path / "log.db")
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM runs").fetchall(), \
        conn.execute("SELECT * FROM clarifications").fetchall()


# ------------------------------------------------------------- webhooks

def _sign(body: bytes, secret="s3cret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_verification(env):
    body = b'{"x": 1}'
    assert bot.verify_signature(body, _sign(body))
    assert not bot.verify_signature(body, _sign(body, "wrong"))
    assert not bot.verify_signature(body, None)


def test_webhook_rejects_unsigned_and_routes_signed_events(env, monkeypatch):
    from fastapi.testclient import TestClient

    seen = []
    monkeypatch.setattr(bot, "handle_pull_request", lambda repo, n: seen.append(("pr", repo, n)))
    monkeypatch.setattr(bot, "handle_comment", lambda *a: seen.append(("comment",) + a))
    client = TestClient(bot.app)

    pr = json.dumps({"action": "opened", "repository": {"full_name": REPO},
                     "pull_request": {"number": 7}}).encode()
    assert client.post("/webhook", content=pr, headers={"X-GitHub-Event": "pull_request"}
                       ).status_code == 401
    r = client.post("/webhook", content=pr, headers={
        "X-GitHub-Event": "pull_request", "X-Hub-Signature-256": _sign(pr)})
    assert r.json()["accepted"] is True

    comment = json.dumps({"action": "created", "repository": {"full_name": REPO},
                          "issue": {"number": 7},
                          "comment": {"id": 5, "body": "yes", "user": {"login": AUTHOR}}}).encode()
    client.post("/webhook", content=comment, headers={
        "X-GitHub-Event": "issue_comment", "X-Hub-Signature-256": _sign(comment)})
    assert seen == [("pr", REPO, 7), ("comment", REPO, 7, AUTHOR, "yes", 5)]


# ------------------------------------------------------- the clarify path

def test_ambiguous_pr_is_parked_with_a_question_not_reviewed(env, monkeypatch):
    gh = FakeGitHub(AMBIGUOUS_DIFF)
    _use(monkeypatch, gh)
    bot.handle_pull_request(REPO, 1)

    assert len(gh.comments) == 1
    assert QUESTION in gh.comments[0]["body"]
    assert f"{REPO}#1" in bot._PARKED
    assert bot._PARKED[f"{REPO}#1"].timer is not None


def test_authors_reply_resumes_and_the_log_shows_what_happened(env, monkeypatch):
    gh = FakeGitHub(AMBIGUOUS_DIFF)
    _use(monkeypatch, gh)
    bot.handle_pull_request(REPO, 1)
    qid = gh.comments[0]["id"]

    # The bot's own question, a bystander, and a reply that quotes the question
    # are all ignored; only the author's own answer resumes the run.
    bot.handle_comment(REPO, 1, AUTHOR, gh.comments[0]["body"], qid)
    bot.handle_comment(REPO, 1, "bob", "I think it was moved", 200)
    assert len(gh.comments) == 1 and f"{REPO}#1" in bot._PARKED

    bot.handle_comment(REPO, 1, AUTHOR, "Yes - validation moved to the API gateway.", 201)
    assert f"{REPO}#1" not in bot._PARKED
    assert len(gh.comments) == 2
    assert "validation moved upstream" in gh.comments[1]["body"]

    runs, clars = _logged(env)
    assert len(runs) == 1
    assert runs[0]["ask"] == 1 and runs[0]["detector"] == "heuristic"
    assert runs[0]["asked"] == 1 and runs[0]["answered"] == 1
    assert clars[0]["answer"].startswith("Yes - validation moved")


def test_timeout_reviews_anyway_and_says_so(env, monkeypatch):
    gh = FakeGitHub(AMBIGUOUS_DIFF)
    _use(monkeypatch, gh)
    bot.handle_pull_request(REPO, 1)

    bot.expire(f"{REPO}#1")
    assert f"{REPO}#1" not in bot._PARKED
    assert len(gh.comments) == 2
    assert "No answer was received" in gh.comments[1]["body"]
    runs, _ = _logged(env)
    assert runs[0]["asked"] == 1 and runs[0]["answered"] == 0 and runs[0]["timed_out"] == 1

    # A late reply after expiry does nothing.
    bot.handle_comment(REPO, 1, AUTHOR, "sorry, late", 300)
    assert len(gh.comments) == 2


def test_the_timeout_actually_fires(env, monkeypatch):
    import time

    monkeypatch.setenv("CLARIFYREVIEW_CLARIFY_TIMEOUT", "1")
    reset_settings()
    gh = FakeGitHub(AMBIGUOUS_DIFF)
    _use(monkeypatch, gh)
    bot.handle_pull_request(REPO, 1)
    deadline = time.monotonic() + 5
    while len(gh.comments) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(gh.comments) == 2 and "No answer was received" in gh.comments[1]["body"]


def test_clear_pr_is_reviewed_immediately(env, monkeypatch):
    gh = FakeGitHub(CLEAR_DIFF, commit="Trim surrounding whitespace before slugifying so "
                                         "pasted CMS titles do not produce trailing dashes")
    _use(monkeypatch, gh)
    bot.handle_pull_request(REPO, 2)
    assert not bot._PARKED
    assert len(gh.comments) == 1
    assert QUESTION not in gh.comments[0]["body"]
    runs, _ = _logged(env)
    assert runs[0]["ask"] == 0 and runs[0]["asked"] == 0


def test_question_failure_still_produces_a_review(env, monkeypatch):
    class Broken:
        def generate(self, ctx):
            raise RuntimeError("provider down")

    monkeypatch.setattr("clarifyreview.clarify.question.QuestionGenerator", Broken)
    gh = FakeGitHub(AMBIGUOUS_DIFF)
    _use(monkeypatch, gh)
    bot.handle_pull_request(REPO, 1)
    assert not bot._PARKED
    assert len(gh.comments) == 1
    assert QUESTION not in gh.comments[0]["body"]
