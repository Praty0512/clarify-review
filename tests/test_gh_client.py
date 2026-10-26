"""GitHubClient against httpx.MockTransport - no network."""

import json

import httpx
import pytest

from clarifyreview.gh.client import (
    MAX_COMMENT_CHARS, GitHubClient, GitHubGraphQLError, RateLimited,
)

API = "https://api.github.com"


def make(handler, **kw):
    sleeps: list[float] = []
    client = GitHubClient(
        token="t", api_url=API, transport=httpx.MockTransport(handler),
        sleep=sleeps.append, **kw,
    )
    return client, sleeps


def test_iter_pages_follows_link_header():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"n": 3}])
        return httpx.Response(
            200, json=[{"n": 1}, {"n": 2}],
            headers={"Link": f'<{API}/x?per_page=100&page=2>; rel="next"'},
        )

    gh, _ = make(handler)
    assert [i["n"] for i in gh.iter_pages("/x")] == [1, 2, 3]
    assert len(seen) == 2 and "per_page=100" in seen[0]
    assert [i["n"] for i in gh.iter_pages("/x", max_items=2)] == [1, 2]


def test_iter_pages_item_key_for_search():
    def handler(request):
        return httpx.Response(200, json={"total_count": 2, "items": [{"a": 1}, {"a": 2}]})

    gh, _ = make(handler)
    assert list(gh.iter_pages("/search/issues", {"q": "x"}, item_key="items")) == [
        {"a": 1}, {"a": 2}]


def test_commits_and_comments_are_paginated():
    def handler(request):
        page = request.url.params.get("page", "1")
        nxt = {"Link": f'<{API}{request.url.path}?page=2>; rel="next"'} if page == "1" else {}
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[{"commit": {"message": f"m{page}"}}], headers=nxt)
        return httpx.Response(200, json=[{"id": int(page)}], headers=nxt)

    gh, _ = make(handler)
    assert gh.get_commit_messages("a/b", 1) == ["m1", "m2"]
    assert [c["id"] for c in gh.list_comments("a/b", 1)] == [1, 2]


def test_primary_rate_limit_sleeps_until_reset_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                403, json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"},
            )
        return httpx.Response(200, json={"ok": True},
                              headers={"X-RateLimit-Remaining": "4999",
                                       "X-RateLimit-Reset": "4600",
                                       "X-RateLimit-Resource": "core"})

    gh, sleeps = make(handler, clock=lambda: 1000.0)
    assert gh.get_json("/x") == {"ok": True}
    assert sleeps == [30.0]
    assert gh.rate_limit == {"remaining": 4999, "reset": 4600, "resource": "core"}


def test_rate_limit_longer_than_budget_raises():
    def handler(request):
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "0",
                                            "X-RateLimit-Reset": "99999999999"})

    gh, sleeps = make(handler, max_rate_wait_s=60)
    with pytest.raises(RateLimited) as exc:
        gh.get_json("/x")
    assert exc.value.reset_at == 99999999999 and sleeps == []


def test_retry_after_on_429():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=[])

    gh, sleeps = make(handler)
    assert gh.get_json("/x") == []
    assert sleeps == [7.0]


def test_plain_403_is_not_retried():
    def handler(request):
        return httpx.Response(403, json={"message": "Resource not accessible"})

    gh, sleeps = make(handler)
    with pytest.raises(httpx.HTTPStatusError):
        gh.get_json("/x")
    assert sleeps == []


def test_5xx_is_retried_then_gives_up():
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        return httpx.Response(502) if calls["n"] < 3 else httpx.Response(200, json={"ok": 1})

    gh, sleeps = make(flaky)
    assert gh.get_json("/x") == {"ok": 1}
    assert len(sleeps) == 2

    gh, sleeps = make(lambda r: httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        gh.get_json("/x")
    assert len(sleeps) == 3


def test_transport_errors_are_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": 1})

    gh, sleeps = make(handler)
    assert gh.get_json("/x") == {"ok": 1} and len(sleeps) == 1


def test_get_diff_falls_back_to_file_patches_when_too_large():
    def handler(request):
        if request.url.path.endswith("/pulls/5") and "diff" in request.headers["accept"]:
            return httpx.Response(406, json={"message": "diff exceeded the maximum"})
        if request.url.path.endswith("/pulls/5/files"):
            return httpx.Response(200, json=[
                {"filename": "a.py", "patch": "@@ -1 +1 @@\n-x\n+y"},
                {"filename": "img.png"},  # no patch: skipped
                {"filename": "new.py", "previous_filename": "old.py",
                 "patch": "@@ -1 +1 @@\n-1\n+2\n"},
            ])
        raise AssertionError(request.url)

    gh, _ = make(handler)
    diff = gh.get_diff("a/b", 5)
    assert diff == (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/old.py b/new.py\n--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-1\n+2\n"
    )
    from clarifyreview.ingest import parse_unified_diff
    assert {h.file for h in parse_unified_diff(diff)} == {"a.py", "new.py"}


def test_get_diff_normal_path():
    gh, _ = make(lambda r: httpx.Response(200, text="diff --git a/x b/x\n"))
    assert gh.get_diff("a/b", 1) == "diff --git a/x b/x\n"


def test_graphql_returns_data_and_raises_on_errors():
    def handler(request):
        if b"bad" in request.content:
            return httpx.Response(200, json={"errors": [{"message": "nope"}]})
        return httpx.Response(200, json={"data": {"viewer": {"login": "me"}}})

    gh, _ = make(handler)
    assert gh.graphql("query { viewer { login } }", {}) == {"viewer": {"login": "me"}}
    with pytest.raises(GitHubGraphQLError, match="nope"):
        gh.graphql("bad", {})


def test_linked_issue_tolerates_graphql_errors():
    gh, _ = make(lambda r: httpx.Response(200, json={"errors": [{"message": "x"}]}))
    assert gh.get_linked_issue("a/b", 1) is None


def test_linked_issue_parsed():
    def handler(request):
        return httpx.Response(200, json={"data": {"repository": {"pullRequest": {
            "closingIssuesReferences": {"nodes": [
                {"number": 3, "title": "T", "body": None}]}}}}})

    gh, _ = make(handler)
    issue = gh.get_linked_issue("a/b", 1)
    assert issue.number == 3 and issue.body == ""


def test_post_comment_truncates_oversized_bodies():
    sent = {}

    def handler(request):
        sent["body"] = json.loads(request.content)["body"]
        return httpx.Response(201, json={"id": 1})

    gh, _ = make(handler)
    gh.post_comment("a/b", 1, "x" * 70000)
    assert len(sent["body"]) <= MAX_COMMENT_CHARS < 65536


def test_find_reply_after_skips_bot_marker_and_other_users():
    comments = [
        {"id": 1, "user": {"login": "alice"}, "body": "<!-- clarifyreview:question -->\nQ"},
        {"id": 2, "user": {"login": "bob"}, "body": "drive-by"},
        {"id": 3, "user": {"login": "alice"}, "body": "the real answer"},
    ]
    gh, _ = make(lambda r: httpx.Response(200, json=comments))
    assert gh.find_reply_after("a/b", 1, after_comment_id=None, from_user="alice") == (
        "the real answer")


def test_token_provider_is_called_per_request():
    tokens = iter(["one", "two"])
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={})

    gh = GitHubClient(api_url=API, transport=httpx.MockTransport(handler),
                      token_provider=lambda: next(tokens))
    gh.get_json("/x")
    gh.get_json("/x")
    assert seen == ["Bearer one", "Bearer two"]


def test_app_token_provider_caches_until_near_expiry():
    pytest.importorskip("jwt")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from clarifyreview.gh.auth import AppTokenProvider

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    now = {"t": 1_700_000_000.0}
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(201, json={
            "token": f"tok{len(calls)}", "expires_at": "2023-11-14T23:13:20Z"})  # now + 1h

    p = AppTokenProvider(1, pem, 42, http=httpx.Client(transport=httpx.MockTransport(handler)),
                         clock=lambda: now["t"])
    assert p() == "tok1" and p() == "tok1"
    assert calls == ["/app/installations/42/access_tokens"]
    now["t"] += 3400  # inside the 5-minute refresh margin
    assert p() == "tok2"
