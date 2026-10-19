"""A thin GitHub REST/GraphQL client.

Deliberately small: five calls is the entire surface this project needs, and a
full SDK would bring an object model that has to be translated into `PRContext`
anyway.
"""

from __future__ import annotations

import logging

import httpx

from ..config import settings
from ..types import LinkedIssue

log = logging.getLogger(__name__)

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"

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


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: float = 30.0) -> None:
        self.token = token or settings().github_token
        if not self.token:
            raise ValueError("GITHUB_TOKEN is not set")
        self._http = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.token}",
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

    # ---------------------------------------------------------------- reads

    def get_pull_request(self, repo: str, number: int) -> dict:
        r = self._http.get(f"{API}/repos/{repo}/pulls/{number}")
        r.raise_for_status()
        return r.json()

    def get_diff(self, repo: str, number: int) -> str:
        r = self._http.get(
            f"{API}/repos/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        r.raise_for_status()
        return r.text

    def get_commit_messages(self, repo: str, number: int) -> list[str]:
        r = self._http.get(f"{API}/repos/{repo}/pulls/{number}/commits", params={"per_page": 100})
        r.raise_for_status()
        return [c["commit"]["message"] for c in r.json()]

    def get_linked_issue(self, repo: str, number: int) -> LinkedIssue | None:
        owner, name = repo.split("/", 1)
        r = self._http.post(
            GRAPHQL,
            json={
                "query": _LINKED_ISSUE_QUERY,
                "variables": {"owner": owner, "name": name, "number": number},
            },
        )
        r.raise_for_status()
        try:
            nodes = r.json()["data"]["repository"]["pullRequest"][
                "closingIssuesReferences"
            ]["nodes"]
        except (KeyError, TypeError):
            return None
        if not nodes:
            return None
        n = nodes[0]
        return LinkedIssue(number=n["number"], title=n["title"] or "", body=n["body"] or "")

    def list_comments(self, repo: str, number: int) -> list[dict]:
        r = self._http.get(
            f"{API}/repos/{repo}/issues/{number}/comments", params={"per_page": 100}
        )
        r.raise_for_status()
        return r.json()

    def find_reply_after(
        self, repo: str, number: int, after_comment_id: int | None, from_user: str | None
    ) -> str | None:
        """The author's first comment after ours.

        Restricting to the PR author matters: a passing reviewer answering on the
        author's behalf is not the signal Stage 3 is supposed to capture, and in
        Study B it would confound whose intent the comment reflects.
        """
        for c in self.list_comments(repo, number):
            if after_comment_id is not None and c["id"] <= after_comment_id:
                continue
            if from_user and c.get("user", {}).get("login") != from_user:
                continue
            body = (c.get("body") or "").strip()
            if body:
                return body
        return None

    # --------------------------------------------------------------- writes

    def post_comment(self, repo: str, number: int, body: str) -> dict:
        r = self._http.post(
            f"{API}/repos/{repo}/issues/{number}/comments", json={"body": body}
        )
        r.raise_for_status()
        return r.json()
