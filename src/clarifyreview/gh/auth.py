"""GitHub App authentication (optional).

A personal access token is the quick path; an App is the right one for anything
shared, because its comments come from a `<slug>[bot]` account that is never the PR
author. Needs `pyjwt[crypto]` (the `app` extra); it is imported lazily so the rest of
the bot works without it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import httpx

# Refresh this long before GitHub says the token expires.
_REFRESH_MARGIN_S = 300


class AppTokenProvider:
    """Callable returning a valid installation access token, cached until close to
    expiry. Pass it to `GitHubClient(token_provider=...)`."""

    def __init__(
        self,
        app_id: str | int,
        private_key_pem: str,
        installation_id: int,
        *,
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
        api_url: str = "https://api.github.com",
    ) -> None:
        self.app_id = str(app_id)
        self.private_key_pem = private_key_pem
        self.installation_id = installation_id
        self._http = http or httpx.Client(timeout=30.0)
        self._clock = clock
        self._api_url = api_url.rstrip("/")
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def _jwt(self) -> str:
        try:
            import jwt
        except ImportError as exc:  # pragma: no cover - exercised only without pyjwt
            raise RuntimeError(
                "GitHub App auth needs pyjwt: pip install 'clarifyreview[app]'"
            ) from exc
        now = int(self._clock())
        # iat backdated 60 s to tolerate clock drift; GitHub caps lifetime at 10 min.
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": self.app_id}
        token = jwt.encode(payload, self.private_key_pem, algorithm="RS256")
        return token.decode() if isinstance(token, bytes) else token

    def __call__(self) -> str:
        with self._lock:
            now = self._clock()
            if self._token and now < self._expires_at - _REFRESH_MARGIN_S:
                return self._token
            r = self._http.post(
                f"{self._api_url}/app/installations/{self.installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {self._jwt()}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            r.raise_for_status()
            data = r.json()
            self._token = data["token"]
            self._expires_at = _parse_expiry(data.get("expires_at"), now)
            return self._token


def _parse_expiry(value: str | None, now: float) -> float:
    """GitHub returns an ISO-8601 UTC timestamp; fall back to the documented hour."""
    if value:
        from datetime import datetime

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return now + 3600
