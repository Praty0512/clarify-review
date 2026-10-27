"""Live tool only: a small, sparse checkout of the PR's merge base.

`builder.from_raw` gives much better context when it has the base-commit files:
full-file symbol extraction instead of hunk fragments, and a caller/callee
neighbourhood. Cloning a large repository for every pull request is not
practical, so this fetches one commit with no history and no blobs up front
(`--depth 1 --filter=blob:none`), then checks out only the directories that hold
the changed files. On a repository the size of transformers that is a few
megabytes rather than gigabytes.

Every failure (no git, network, private repo without a token, timeout) returns
None and the caller carries on without a checkout, exactly as before.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

MAX_DIRS = 40
TIMEOUT_S = 120


def _dirs_for(paths: list[str], max_dirs: int = MAX_DIRS) -> list[str]:
    """Parent directories of the changed source files, most-changed first, capped.

    Test, doc and config files contribute no directory: a test-case folder can
    hold thousands of files and none of them is a callee of the change.
    """
    from .triage import SOURCE, group_of

    counts: dict[str, int] = {}
    for p in paths:
        if group_of(p) != SOURCE:
            continue
        parent = str(PurePosixPath(p).parent)
        counts[parent] = counts.get(parent, 0) + 1
    ranked = sorted(counts, key=lambda d: (-counts[d], d))
    return sorted(ranked[:max_dirs])


def _sparse_patterns(paths: list[str]) -> list[str]:
    """Non-cone patterns: every changed file, plus the files (not the
    subdirectories) directly inside each changed source file's directory."""
    out: list[str] = []
    for d in _dirs_for(paths):
        base = "" if d == "." else f"/{d}"
        out += [f"{base}/*", f"!{base}/*/"]
    out += [f"/{p}" for p in sorted(set(paths))]
    return out


def _git_env(token: str | None) -> dict[str, str]:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if token:
        # Passed as config through the environment so it never appears in argv.
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.extraHeader",
                   GIT_CONFIG_VALUE_0=f"Authorization: Basic {basic}")
    return env


def sparse_checkout(
    repo: str,
    sha: str,
    paths: list[str],
    root: Path,
    *,
    token: str | None = None,
    host: str = "https://github.com",
    timeout: float = TIMEOUT_S,
) -> Path | None:
    """Check out `paths`' directories of `repo` at `sha` under `root`.

    Reuses an existing checkout of the same commit. Returns its path, or None.
    """
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha or "") or not shutil.which("git"):
        return None
    dest = root / repo.replace("/", "__") / sha[:12]
    if (dest / ".clarifyreview-ok").exists():
        return dest
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    env = _git_env(token)

    def git(*args: str, input: list[str] | None = None) -> None:
        # Patterns go through stdin: a large PR's paths would overflow argv on Windows.
        subprocess.run(["git", *args], cwd=dest, env=env, check=True, timeout=timeout,
                       input="\n".join(input).encode() + b"\n" if input else None,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    try:
        git("init", "-q")
        git("remote", "add", "origin", f"{host}/{repo}.git")
        git("sparse-checkout", "set", "--no-cone", "--stdin", input=_sparse_patterns(paths))
        git("fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", sha)
        git("checkout", "-q", "FETCH_HEAD")
    except (subprocess.SubprocessError, OSError) as exc:
        err = getattr(exc, "stderr", b"") or b""
        log.warning("%s@%s: sparse checkout failed (%s); continuing without one",
                    repo, sha[:12], err.decode("utf-8", "replace").strip()[:200] or exc)
        shutil.rmtree(dest, ignore_errors=True)
        return None
    (dest / ".clarifyreview-ok").write_text(sha, encoding="utf-8")
    return dest


def prune(root: Path, keep: int = 20) -> None:
    """Delete all but the `keep` most recently used checkouts."""
    if not root.exists():
        return
    found = sorted(root.glob("*/*/.clarifyreview-ok"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for marker in found[keep:]:
        shutil.rmtree(marker.parent, ignore_errors=True)
