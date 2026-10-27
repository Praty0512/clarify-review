"""A thin GitHub REST/GraphQL client.

Deliberately small - a full SDK would bring an object model that has to be
translated into `PRContext` anyway - but it handles what a long-running bot meets
on day two: pagination, rate limits, transient 5xx, and diffs too large for the
diff media type.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from ..config import settings
from ..types import LinkedIssue
from .linked import body_issue_number
from .settings import bot_settings

log = logging.getLogger(__name__)

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

# GitHub rejects comment bodies above 65,536 characters.
MAX_COMMENT_CHARS = 65000

_RETRIES = 3  # transient failures (5xx, transport errors)
_RATE_RETRIES = 3  # rate-limit sleeps before giving up

# The REST API only exposes a PR's closing issues through GraphQL.
_LINKED_ISSUE_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      closingIssuesReferences(first: 1) {
        nodes { number title body }
      }
    }
  }
}
"""


class RateLimited(Exception):
    """The API asked us to wait longer than we are willing to."""

    def __init__(self, reset_at: float, message: str = "") -> None:
        self.reset_at = reset_at
        super().__init__(message or f"GitHub rate limit; resets at {reset_at:.0f}")


class GitHubGraphQLError(RuntimeError):
    def __init__(self, errors: list) -> None:
        self.errors = errors
        super().__init__("; ".join(str(e.get("message", e)) for e in errors)[:500])


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        timeout: float = 30.0,
        *,
        transport: httpx.BaseTransport | None = None,
        api_url: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_rate_wait_s: float = 900.0,
        token_provider: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.token_provider = token_provider
        self.token = token or (None if token_provider else settings().github_token)
        if not self.token and token_provider is None:
            raise ValueError("GITHUB_TOKEN is not set")
        self.api_url = (api_url or bot_settings().github_api_url).rstrip("/")
        self._sleep = sleep
        self._clock = clock
        self.max_rate_wait_s = max_rate_wait_s
        self.rate_limit: dict[str, Any] = {}
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------ transport

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return self.api_url + (path if path.startswith("/") else "/" + path)

    @property
    def graphql_url(self) -> str:
        # GitHub Enterprise Server: .../api/v3 pairs with .../api/graphql.
        if self.api_url.endswith("/api/v3"):
            return self.api_url[: -len("/api/v3")] + "/api/graphql"
        return self.api_url + "/graphql"

    def _auth_headers(self) -> dict[str, str]:
        token = self.token_provider() if self.token_provider else self.token
        return {"Authorization": f"Bearer {token}"}

    def _note_rate_limit(self, r: httpx.Response) -> None:
        h = r.headers
        if "x-ratelimit-remaining" in h:
            try:
                self.rate_limit = {
                    "remaining": int(h["x-ratelimit-remaining"]),
                    "reset": int(h.get("x-ratelimit-reset", 0)),
                    "resource": h.get("x-ratelimit-resource", ""),
                }
            except ValueError:
                pass

    def _rate_wait(self, r: httpx.Response) -> tuple[float, float] | None:
        """(seconds to wait, reset epoch) if this 403/429 is a rate limit, else None."""
        now = self._clock()
        retry_after = r.headers.get("retry-after")
        if retry_after:
            try:
                wait = max(0.0, float(retry_after))
                return wait, now + wait
            except ValueError:
                pass
        if r.headers.get("x-ratelimit-remaining") == "0":
            try:
                reset = float(r.headers.get("x-ratelimit-reset", 0))
            except ValueError:
                reset = now + 60
            return max(0.0, reset - now), reset
        text = r.text[:500].lower() if r.status_code == 403 else ""
        if "rate limit" in text or "abuse" in text:
            return 60.0, now + 60
        if r.status_code == 429:
            return 60.0, now + 60
        return None

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(30.0, (2**attempt) * 0.5 + random.uniform(0, 0.5)))

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        """One door for every call. Returns the response for any status that is not
        retried or rate limited; callers decide what a 404 means."""
        url = self._url(path)
        headers = {**self._auth_headers(), **(kw.pop("headers", None) or {})}
        transient = 0
        rate_sleeps = 0
        while True:
            try:
                r = self._http.request(method, url, headers=headers, **kw)
            except httpx.TransportError as exc:
                if transient >= _RETRIES:
                    raise
                log.warning("GitHub transport error (%s); retrying", type(exc).__name__)
                self._backoff(transient)
                transient += 1
                continue
            self._note_rate_limit(r)

            if r.status_code >= 500:
                if transient >= _RETRIES:
                    return r
                log.warning("GitHub %s on %s; retrying", r.status_code, method)
                self._backoff(transient)
                transient += 1
                continue

            if r.status_code in (403, 429):
                waited = self._rate_wait(r)
                if waited is not None:
                    wait, reset_at = waited
                    if wait > self.max_rate_wait_s or rate_sleeps >= _RATE_RETRIES:
                        raise RateLimited(reset_at)
                    log.warning("GitHub rate limit; sleeping %.0fs", wait)
                    self._sleep(wait)
                    rate_sleeps += 1
                    continue
            return r

    # ---------------------------------------------------------- generic reads

    def get_json(self, path: str, params: dict | None = None) -> Any:
        r = self._request("GET", path, params=params)
        r.raise_for_status()
        return r.json()

    def iter_pages(
        self,
        path: str,
        params: dict | None = None,
        *,
        max_items: int | None = None,
        item_key: str | None = None,
    ) -> Iterator[dict]:
        """Follow `Link: rel="next"`. `item_key="items"` for /search responses."""
        url: str | None = path
        query: dict | None = {"per_page": 100, **(params or {})}
        n = 0
        while url:
            r = self._request("GET", url, params=query)
            r.raise_for_status()
            data = r.json()
            items = data.get(item_key, []) if item_key else data
            for item in items:
                if max_items is not None and n >= max_items:
                    return
                n += 1
                yield item
            url = r.links.get("next", {}).get("url")
            query = None  # the next URL already carries its query string

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        r = self._request(
            "POST", self.graphql_url, json={"query": query, "variables": variables or {}}
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise GitHubGraphQLError(payload["errors"])
        return payload.get("data") or {}

    # ------------------------------------------------------------------ reads

    def get_authenticated_login(self) -> str | None:
        """Who the token belongs to. None for an App installation token."""
        try:
            return self.get_json("/user").get("login")
        except (httpx.HTTPError, ValueError):
            return None

    def get_pull_request(self, repo: str, number: int) -> dict:
        return self.get_json(f"/repos/{repo}/pulls/{number}")

    def get_pull_files(self, repo: str, number: int) -> list[dict]:
        return list(self.iter_pages(f"/repos/{repo}/pulls/{number}/files"))

    def get_diff(self, repo: str, number: int) -> str:
        r = self._request(
            "GET",
            f"/repos/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        if r.status_code in (406, 422):
            # "diff exceeded the maximum number of lines/files". The per-file
            # patches are still served (GitHub omits only the individual huge ones).
            log.info("%s#%s: diff too large for one response; using per-file patches",
                     repo, number)
            return self._diff_from_files(self.get_pull_files(repo, number))
        r.raise_for_status()
        return r.text

    @staticmethod
    def _diff_from_files(files: list[dict]) -> str:
        parts: list[str] = []
        for f in files:
            patch = f.get("patch")
            if not patch:
                continue  # binary, renamed without edits, or too large on its own
            new = f["filename"]
            old = f.get("previous_filename") or new
            patch = patch.rstrip("\n")
            parts.append(f"diff --git a/{old} b/{new}\n--- a/{old}\n+++ b/{new}\n{patch}\n")
        return "".join(parts)

    def get_commit_messages(self, repo: str, number: int) -> list[str]:
        return [
            c["commit"]["message"]
            for c in self.iter_pages(f"/repos/{repo}/pulls/{number}/commits")
        ]

    def get_linked_issue(self, repo: str, number: int) -> LinkedIssue | None:
        """GraphQL `closingIssuesReferences`, else the PR body's "fixes #N".

        The body fallback matches `experiments/fetch_prs.py` (shared regex in
        `gh.linked`) and skips a number that is itself a pull request.
        """
        owner, name = repo.split("/", 1)
        try:
            data = self.graphql(
                _LINKED_ISSUE_QUERY, {"owner": owner, "name": name, "number": number}
            )
            nodes = data["repository"]["pullRequest"]["closingIssuesReferences"]["nodes"]
        except GitHubGraphQLError as exc:
            log.warning("%s#%s: linked-issue lookup failed: %s", repo, number, exc)
            nodes = []
        except (KeyError, TypeError):
            nodes = []
        if nodes:
            n = nodes[0]
            return LinkedIssue(number=n["number"], title=n["title"] or "", body=n["body"] or "")
        return self._issue_from_body(repo, number)

    def _issue_from_body(self, repo: str, number: int) -> LinkedIssue | None:
        try:
            pr = self.get_pull_request(repo, number)
            n = body_issue_number((pr or {}).get("body"), repo)
            if not n:
                return None
            obj = self.get_json(f"/repos/{repo}/issues/{n}")
        except Exception as exc:  # noqa: BLE001 - a dead link or API hiccup is not fatal
            log.warning("%s#%s: body-reference issue lookup failed: %s", repo, number, exc)
            return None
        if not isinstance(obj, dict) or "pull_request" in obj:
            return None
        return LinkedIssue(number=n, title=obj.get("title") or "", body=obj.get("body") or "")

    def list_comments(self, repo: str, number: int) -> list[dict]:
        return list(self.iter_pages(f"/repos/{repo}/issues/{number}/comments"))

    def find_reply_after(
        self, repo: str, number: int, after_comment_id: int | None, from_user: str | None
    ) -> str | None:
        """The author's first comment after ours.

        Restricting to the PR author matters: a passing reviewer answering on the
        author's behalf is not the signal Stage 3 is supposed to capture, and in
        Study B it would confound whose intent the comment reflects. Comments that
        carry the bot's own marker are skipped: with a personal access token the
        bot *is* the author as far as GitHub is concerned.
        """
        from ..review.render import has_marker

        for c in self.list_comments(repo, number):
            if after_comment_id is not None and c["id"] <= after_comment_id:
                continue
            if from_user and (c.get("user") or {}).get("login") != from_user:
                continue
            if has_marker(c.get("body")):
                continue
            body = (c.get("body") or "").strip()
            if body:
                return body
        return None

    # ----------------------------------------------------------------- writes

    def post_comment(self, repo: str, number: int, body: str) -> dict:
        if len(body) > MAX_COMMENT_CHARS:
            body = body[: MAX_COMMENT_CHARS - 40].rstrip() + "\n\n_(comment truncated)_"
        r = self._request(
            "POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body}
        )
        r.raise_for_status()
        return r.json()
