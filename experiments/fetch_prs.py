"""Build a labelling sheet of REAL merged pull requests from GitHub.

The SWE-bench sheet (label_tool sheet) shows annotators a stripped, code-only diff.
This builds the other kind: what a reviewer sees when a PR is opened - title,
description, linked issue, commit messages and the diff - for PRs from repos you
choose, in the seven languages the semantic layer supports.

    python -m experiments.fetch_prs --repos pallets/flask psf/requests \\
        --merged-since 2025-01-01 --merged-until 2026-06-30 \\
        --per-repo 30 --n 300 --out runs/realpr/labelling_sheet.csv

Needs GITHUB_TOKEN (env or .env). Staged, so the expensive calls only happen for
PRs that survive the cheap filters:

  1. search      one paced /search/issues query per month window (<= 30/min)
  2. meta        PR + file list for candidates, taken in seeded random order until
                 --per-repo pass the filters (bots, size, language, docs-only,
                 SWE-bench ids already used)
  3. full        diff, commits, linked issue - only for the sampled PRs

Every response is cached under --cache-dir (one JSON file per key), so a re-run, or
a run resumed after a rate limit, makes zero repeat calls. The sheet is never
overwritten once it holds a label unless you pass --append, which only adds rows.
Nothing here writes an annotator_*, adjudicated or notes value.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Protocol

from clarifyreview.gh.linked import FIXES, body_issue_number

csv.field_size_limit(10**8)

VIEW_FULL = "full_context"
VIEW_OPENED = "full_context_opened"

COLUMNS = [
    "pr_id", "repo", "number", "url", "view", "title", "body", "body_edited",
    "issue_number", "issue_title", "issue_body", "commit_messages", "code_change",
    "diff_truncated", "additions", "deletions", "changed_files", "languages",
    "merged_at", "annotator_1", "annotator_2", "adjudicated", "notes",
]
HUMAN_COLUMNS = ("annotator_1", "annotator_2", "adjudicated", "notes")

CAPS = {"title": 6000, "body": 6000, "issue_body": 8000, "commit_messages": 4000,
        "code_change": 30000}

LANGUAGES = ["python", "javascript", "typescript", "java", "c", "cpp", "rust"]
EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript", ".tsx": "typescript",
    ".java": "java",
    ".rs": "rust",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
}
DOC_EXT = {".md", ".rst", ".txt", ".adoc", ".markdown", ".rdoc"}
SEARCH_PER_MINUTE = 30
SEARCH_CAP = 1000


class GitHubAPI(Protocol):
    """The slice of gh.client.GitHubClient this module uses."""

    def get_json(self, path: str, params: dict | None = None) -> Any: ...
    def iter_pages(self, path: str, params: dict | None = None, *,
                   max_items: int | None = None, item_key: str | None = None): ...
    def graphql(self, query: str, variables: dict) -> dict: ...
    def get_pull_request(self, repo: str, number: int) -> dict: ...
    def get_diff(self, repo: str, number: int) -> str: ...
    def get_commit_messages(self, repo: str, number: int) -> list[str]: ...
    def get_linked_issue(self, repo: str, number: int): ...
    def get_pull_files(self, repo: str, number: int) -> list[dict]: ...


# ------------------------------------------------------------------- plumbing


class Cache:
    """One JSON file per key. Writes are atomic (tmp + os.replace)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._#@-]", "_", key)
        return self.root / f"{safe}.json"

    def get(self, key: str):
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, key: str, obj) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)


def repo_cache(cache_dir: str | Path, repo: str) -> Cache:
    return Cache(Path(cache_dir) / repo.replace("/", "__"))


class Pacer:
    """Keeps search calls under `per_minute`. Clock and sleep are injectable."""

    def __init__(self, per_minute: int = SEARCH_PER_MINUTE,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.gap = 60.0 / per_minute
        self.clock, self.sleep = clock, sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self._last is not None:
            delay = self._last + self.gap - now
            if delay > 0:
                self.sleep(delay)
                now = self.clock()
        self._last = now


def is_rate_limited(exc: BaseException) -> bool:
    """gh.client.RateLimited, matched by class name so this works before/without it."""
    return any(c.__name__ == "RateLimited" for c in type(exc).__mro__)


# ----------------------------------------------------------------- languages


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[name.rfind("."):].lower() if "." in name else ""


def is_test_path(path: str) -> bool:
    p = path.lower()
    parts = p.split("/")
    name = parts[-1]
    return (any(x in ("test", "tests", "__tests__", "spec", "specs", "testing") for x in parts[:-1])
            or name.startswith("test_") or name.startswith("tests.")
            or bool(re.search(r"(_test|_tests|\.test|\.spec|_unittest)\.[a-z]+$", name))
            or bool(re.search(r"(test|tests|it)\.java$", name)))


def language_of(files: list[dict]) -> tuple[str | None, dict[str, int], bool]:
    """(majority language, changed lines per language, docs_only).

    Majority is by changed non-test lines; if every code file is a test the test
    lines are used instead. docs_only is True when no file has a supported code
    extension and every file looks like documentation.
    """
    prod: Counter = Counter()
    test: Counter = Counter()
    docs = 0
    for f in files:
        path = f.get("filename") or ""
        lang = EXT_LANG.get(_ext(path))
        lines = int(f.get("additions") or 0) + int(f.get("deletions") or 0)
        if lang:
            (test if is_test_path(path) else prod)[lang] += lines
        elif _ext(path) in DOC_EXT or path.lower().startswith(("docs/", "doc/")):
            docs += 1
    counts = prod if prod else test
    all_counts: Counter = Counter()
    all_counts.update(prod)
    all_counts.update(test)
    top = None
    if counts:
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    docs_only = not all_counts and bool(files) and docs == len(files)
    return top, dict(all_counts), docs_only


# ------------------------------------------------------------------- search


def _month_windows(since: dt.date, until: dt.date) -> list[tuple[dt.date, dt.date]]:
    out, cur = [], since
    while cur <= until:
        nxt = (cur.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        end = min(nxt - dt.timedelta(days=1), until)
        out.append((cur, end))
        cur = nxt
    return out


def _search_window(api, repo, a: dt.date, b: dt.date, cache: Cache, pacer, authors) -> list[int]:
    key = f"search_{a.isoformat()}_{b.isoformat()}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    q = f"repo:{repo} is:pr is:merged merged:{a.isoformat()}..{b.isoformat()}"
    for name in authors:
        q += f" -author:app/{name}"
    numbers: list[int] = []
    total = 0
    for page in range(1, 11):
        if pacer:
            pacer.wait()
        data = api.get_json("/search/issues", {"q": q, "per_page": 100, "page": page,
                                               "sort": "created", "order": "asc"})
        items = (data or {}).get("items") or []
        total = int((data or {}).get("total_count") or 0)
        numbers += [int(i["number"]) for i in items]
        if not items or len(numbers) >= total:
            break
    if total > SEARCH_CAP and a < b:                  # search returns at most 1000: split
        mid = a + (b - a) // 2
        numbers = (_search_window(api, repo, a, mid, cache, pacer, authors)
                   + _search_window(api, repo, mid + dt.timedelta(days=1), b, cache, pacer, authors))
    result = sorted(set(numbers))
    cache.put(key, result)
    return result


def search_candidates(api, repo: str, since: str | dt.date, until: str | dt.date,
                      cache: Cache, pacer: Pacer | None = None,
                      authors: tuple[str, ...] = ("dependabot", "renovate")) -> list[int]:
    s = since if isinstance(since, dt.date) else dt.date.fromisoformat(since)
    u = until if isinstance(until, dt.date) else dt.date.fromisoformat(until)
    found: set[int] = set()
    for a, b in _month_windows(s, u):
        found |= set(_search_window(api, repo, a, b, cache, pacer, authors))
    return sorted(found)


# --------------------------------------------------------------------- meta


def fetch_meta(api, repo: str, number: int, cache: Cache, *,
               skip_files_over: int | None = None) -> dict:
    key = f"meta_{number}"
    hit = cache.get(key)
    if hit is not None and not (hit.get("files_skipped") and (
            skip_files_over is None or hit["changed_files"] <= skip_files_over)):
        return hit
    pr = api.get_pull_request(repo, number)
    user = pr.get("user") or {}
    changed = int(pr.get("changed_files") or 0)
    skipped = skip_files_over is not None and changed > skip_files_over
    files = [] if skipped else [
        {"filename": f.get("filename", ""), "additions": int(f.get("additions") or 0),
         "deletions": int(f.get("deletions") or 0), "status": f.get("status", "")}
        for f in api.get_pull_files(repo, number)]
    top, counts, docs_only = language_of(files)
    meta = {
        "repo": repo, "number": number,
        "url": pr.get("html_url") or f"https://github.com/{repo}/pull/{number}",
        "title": pr.get("title") or "", "body": pr.get("body") or "",
        "author": user.get("login") or "ghost", "author_type": user.get("type") or "User",
        "additions": int(pr.get("additions") or 0), "deletions": int(pr.get("deletions") or 0),
        "changed_files": changed, "merged_at": pr.get("merged_at") or "",
        "created_at": pr.get("created_at") or "",
        "base_sha": (pr.get("base") or {}).get("sha") or "",
        "head_sha": (pr.get("head") or {}).get("sha") or "",
        "labels": [l.get("name", "") for l in (pr.get("labels") or [])],
        "files": files, "files_skipped": skipped,
        "language": top, "language_lines": counts, "docs_only": docs_only,
    }
    cache.put(key, meta)
    return meta


def is_bot(meta: dict, exclude_authors=()) -> bool:
    login = (meta.get("author") or "").lower()
    if (meta.get("author_type") or "").lower() == "bot" or login.endswith("[bot]"):
        return True
    return any(x.lower() and x.lower() in login for x in exclude_authors)


def passes_filters(meta: dict, files: list[dict] | None, args) -> tuple[bool, str]:
    """(keep, reason). `files` defaults to the list stored in meta."""
    files = meta.get("files", []) if files is None else files
    if not meta.get("merged_at"):
        return False, "not_merged"
    if is_bot(meta, getattr(args, "exclude_authors", ())):
        return False, "bot"
    if f"{meta['repo']}#{meta['number']}" in getattr(args, "exclude_ids", ()):
        return False, "already_used"
    lines = int(meta.get("additions") or 0) + int(meta.get("deletions") or 0)
    if lines < args.min_lines:
        return False, "too_small"
    if lines > args.max_lines:
        return False, "too_large"
    if int(meta.get("changed_files") or 0) > args.max_files:
        return False, "too_many_files"
    top, _counts, docs_only = language_of(files)
    if docs_only:
        return False, "docs_only"
    if top is None:
        return False, "no_supported_language"
    if top not in args.languages:
        return False, f"language:{top}"
    return True, "ok"


# ------------------------------------------------------------------- sample


def sample(cands_by_repo: dict[str, list[int]], per_repo: int, n: int,
           seed: int) -> list[tuple[str, int]]:
    """Seeded, per-repo capped, round-robin across repos so no repo dominates."""
    queues: dict[str, list[int]] = {}
    for repo in sorted(cands_by_repo):
        nums = sorted(set(cands_by_repo[repo]))
        random.Random(f"{seed}:{repo}").shuffle(nums)
        queues[repo] = nums[:per_repo]
    out: list[tuple[str, int]] = []
    while len(out) < n and any(queues.values()):
        for repo in sorted(queues):
            if queues[repo] and len(out) < n:
                out.append((repo, queues[repo].pop(0)))
    return out


# --------------------------------------------------------------------- full

_CLOSING_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      lastEditedAt
      closingIssuesReferences(first: 1) { nodes { number title body } }
    }
  }
}
"""
# One regex for the live tool and this labelling set (clarifyreview.gh.linked).
_FIXES = FIXES


def _body_issue_number(body: str, repo: str) -> int | None:
    return body_issue_number(body, repo)


def _diff_from_files(files: list[dict]) -> str:
    parts = []
    for f in files:
        patch = f.get("patch")
        if not patch:
            continue
        name = f.get("filename", "")
        parts.append(f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n{patch}")
    return "\n".join(p if p.endswith("\n") else p + "\n" for p in parts)


def _opened_snapshot(api, repo: str, number: int, meta: dict) -> tuple[str, list[str]]:
    """Diff base..(last commit within 1h of opening) and the messages up to it."""
    commits = list(api.iter_pages(f"/repos/{repo}/pulls/{number}/commits"))
    try:
        cutoff = (dt.datetime.fromisoformat(meta["created_at"].replace("Z", "+00:00"))
                  + dt.timedelta(hours=1))
    except (KeyError, ValueError):
        cutoff = None
    keep = commits[:1]
    if cutoff is not None:
        early = []
        for c in commits:
            when = ((c.get("commit") or {}).get("committer") or {}).get("date", "")
            try:
                if dt.datetime.fromisoformat(when.replace("Z", "+00:00")) <= cutoff:
                    early.append(c)
            except ValueError:
                continue
        keep = early or commits[:1]
    last = keep[-1]["sha"] if keep else meta["head_sha"]
    cmp = api.get_json(f"/repos/{repo}/compare/{meta['base_sha']}...{last}")
    return (_diff_from_files(cmp.get("files") or []),
            [(c.get("commit") or {}).get("message", "") for c in keep])


def fetch_full(api, repo: str, number: int, cache: Cache, snapshot: str = "final") -> dict:
    key = f"full_{number}" + ("_opened" if snapshot == "opened" else "")
    hit = cache.get(key)
    if hit is not None:
        return hit
    meta = fetch_meta(api, repo, number, cache)
    if snapshot == "opened":
        diff, commits = _opened_snapshot(api, repo, number, meta)
    else:
        diff = api.get_diff(repo, number)
        commits = api.get_commit_messages(repo, number)
    owner, name = repo.split("/", 1)
    issue, edited = None, False
    try:
        data = api.graphql(_CLOSING_QUERY, {"owner": owner, "name": name, "number": number})
        pr = ((data or {}).get("repository") or {}).get("pullRequest") or {}
        edited = bool(pr.get("lastEditedAt"))
        nodes = (pr.get("closingIssuesReferences") or {}).get("nodes") or []
        if nodes:
            issue = {"number": nodes[0]["number"], "title": nodes[0].get("title") or "",
                     "body": nodes[0].get("body") or ""}
    except Exception as e:                            # noqa: BLE001 - GraphQL is best effort
        if is_rate_limited(e):
            raise
    if issue is None:
        n = _body_issue_number(meta["body"], repo)
        if n:
            try:
                obj = api.get_json(f"/repos/{repo}/issues/{n}")
            except Exception as e:                    # noqa: BLE001 - a dead link is fine
                if is_rate_limited(e):
                    raise
                obj = None
            if obj and "pull_request" not in obj:
                issue = {"number": n, "title": obj.get("title") or "", "body": obj.get("body") or ""}
    full = {"diff": diff, "commit_messages": list(commits), "issue": issue,
            "body_edited": edited, "snapshot": snapshot}
    cache.put(key, full)
    return full


# -------------------------------------------------------------------- sheet


def _cap_diff(diff: str, limit: int) -> tuple[str, bool]:
    if len(diff) <= limit:
        return diff, False
    cut = diff[:limit]
    nl = cut.rfind("\n")
    return (cut[:nl] if nl > 0 else cut), True


def _cap_commits(msgs: list[str], limit: int) -> str:
    msgs = [m[:500] for m in msgs]
    while msgs and len(json.dumps(msgs, ensure_ascii=False)) > limit:
        msgs.pop()
    return json.dumps(msgs, ensure_ascii=False)


def build_record(meta: dict, full: dict, snapshot: str = "final") -> dict:
    diff, truncated = _cap_diff(full.get("diff") or "", CAPS["code_change"])
    issue = full.get("issue") or {}
    langs = sorted(meta.get("language_lines", {}).items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "pr_id": f"{meta['repo']}#{meta['number']}", "repo": meta["repo"],
        "number": meta["number"], "url": meta["url"],
        "view": VIEW_OPENED if snapshot == "opened" else VIEW_FULL,
        "title": meta["title"][:CAPS["title"]], "body": meta["body"][:CAPS["body"]],
        "body_edited": "1" if full.get("body_edited") else "0",
        "issue_number": issue.get("number", ""), "issue_title": issue.get("title", ""),
        "issue_body": (issue.get("body") or "")[:CAPS["issue_body"]],
        "commit_messages": _cap_commits(full.get("commit_messages") or [], CAPS["commit_messages"]),
        "code_change": diff, "diff_truncated": "1" if truncated else "0",
        "additions": meta["additions"], "deletions": meta["deletions"],
        "changed_files": meta["changed_files"], "languages": ",".join(k for k, _ in langs),
        "merged_at": meta["merged_at"],
        "annotator_1": "", "annotator_2": "", "adjudicated": "", "notes": "",
    }


def _read_sheet(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        r = csv.DictReader(fh)
        rows = list(r)
        return list(r.fieldnames or []), rows


def sheet_has_human_cells(path: Path) -> bool:
    if not Path(path).exists():
        return False
    _, rows = _read_sheet(Path(path))
    return any((r.get(c) or "").strip() for r in rows for c in HUMAN_COLUMNS)


def write_sheet(records: list[dict], out: str | Path, append: bool = False) -> int:
    """Write the sheet; returns the number of rows added.

    Refuses (ValueError) to replace a sheet that holds any annotator/adjudicated/
    notes value unless append is True; append only adds rows and never reorders.
    """
    out = Path(out)
    fields, existing = list(COLUMNS), []
    if out.exists():
        if append:
            fields, existing = _read_sheet(out)
            fields += [c for c in COLUMNS if c not in fields]
        elif sheet_has_human_cells(out):
            raise ValueError(f"{out} already contains labels or notes; pass --append to add rows")
    have = {r["pr_id"] for r in existing}
    new = [r for r in records if r["pr_id"] not in have]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(existing)
        w.writerows(new)
    os.replace(tmp, out)
    return len(new)


# --------------------------------------------------------------------- main

_INSTANCE = re.compile(r"^(.+?)__(.+)-(\d+)$")


def used_ids(files: list[str]) -> set[str]:
    """owner/name#N for every PR in the given JSONL files (SWE-bench ids or already ours)."""
    out: set[str] = set()
    for f in files:
        p = Path(f)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                pid = json.loads(line)["pr_id"].split("::")[0]
            except (ValueError, KeyError, AttributeError):
                continue
            m = _INSTANCE.match(pid)
            out.add(f"{m.group(1)}/{m.group(2)}#{m.group(3)}" if m else pid)
    return out


def _load_repos(args) -> list[str]:
    repos = list(args.repos or [])
    if args.repos_file:
        for line in Path(args.repos_file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                repos.append(line)
    seen, out = set(), []
    for r in repos:
        if "/" in r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repos", nargs="*", default=[], help="owner/name ...")
    ap.add_argument("--repos-file", help="one owner/name per line; # comments allowed")
    ap.add_argument("--merged-since", default="2025-01-01")
    ap.add_argument("--merged-until", default="2026-06-30")
    ap.add_argument("--min-lines", type=int, default=5)
    ap.add_argument("--max-lines", type=int, default=400)
    ap.add_argument("--max-files", type=int, default=15)
    ap.add_argument("--per-repo", type=int, default=30)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--languages", nargs="+", default=list(LANGUAGES), choices=LANGUAGES)
    ap.add_argument("--exclude-authors", nargs="*", default=["dependabot", "renovate"])
    ap.add_argument("--exclude", nargs="*",
                    default=["data/instances.v2.jsonl", "data/archive/instances.pilot.jsonl"],
                    help="JSONL files whose PRs are already used (SWE-bench ids are mapped to owner/name#N)")
    ap.add_argument("--seed", type=int, default=20261026)
    ap.add_argument("--cache-dir", default="data/cache/realpr")
    ap.add_argument("--out", default="runs/realpr/labelling_sheet.csv")
    ap.add_argument("--append", action="store_true",
                    help="add new rows to an existing sheet; never changes or reorders existing rows")
    ap.add_argument("--snapshot", choices=["final", "opened"], default="final",
                    help="opened (experimental): diff as of ~1h after the PR was opened")
    return ap


def _default_api():
    from clarifyreview.config import settings

    token = os.environ.get("GITHUB_TOKEN") or settings().github_token
    if not token:
        print("GITHUB_TOKEN is not set. Create a fine-grained token with read-only public "
              "repository access, put GITHUB_TOKEN=... in .env, and re-run "
              "(see docs/real_pr_labelling.md).", file=sys.stderr)
        return None
    from clarifyreview.gh.client import GitHubClient

    return GitHubClient(token=token)


def main(argv: list[str] | None = None, *, api=None,
         clock: Callable[[], float] = time.monotonic,
         sleep: Callable[[float], None] = time.sleep) -> int:
    args = build_parser().parse_args(argv)
    repos = _load_repos(args)
    if not repos:
        print("give at least one repo: --repos owner/name [...] or --repos-file", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.exists() and not args.append and sheet_has_human_cells(out):
        print(f"refusing to overwrite {out}: it already contains labels or notes. "
              f"Use --append to add rows.", file=sys.stderr)
        return 2
    if api is None:
        api = _default_api()
        if api is None:
            return 2

    args.exclude_ids = used_ids(args.exclude)
    if args.append and out.exists():
        args.exclude_ids |= {r["pr_id"] for r in _read_sheet(out)[1]}
    pacer = Pacer(SEARCH_PER_MINUTE, clock, sleep)
    reasons: Counter = Counter()
    accepted: dict[str, list[int]] = {}
    try:
        for repo in repos:
            cache = repo_cache(args.cache_dir, repo)
            cands = search_candidates(api, repo, args.merged_since, args.merged_until, cache,
                                      pacer, tuple(args.exclude_authors))
            order = sorted(cands)
            random.Random(f"{args.seed}:meta:{repo}").shuffle(order)
            keep: list[int] = []
            for number in order:
                if len(keep) >= args.per_repo:
                    break
                if f"{repo}#{number}" in args.exclude_ids:
                    reasons["already_used"] += 1
                    continue
                meta = fetch_meta(api, repo, number, cache, skip_files_over=args.max_files)
                ok, why = passes_filters(meta, None, args)
                reasons[why] += 1
                if ok:
                    keep.append(number)
            accepted[repo] = keep
            print(f"{repo}: {len(cands)} candidates, {len(keep)} kept")
        picks = sample(accepted, args.per_repo, args.n, args.seed)
        records = []
        for repo, number in picks:
            cache = repo_cache(args.cache_dir, repo)
            meta = fetch_meta(api, repo, number, cache)
            records.append(build_record(meta, fetch_full(api, repo, number, cache, args.snapshot),
                                        args.snapshot))
    except Exception as e:                            # noqa: BLE001
        if is_rate_limited(e):
            print(f"GitHub rate limit reached ({e}). Everything fetched so far is cached in "
                  f"{args.cache_dir}; re-run the same command after the limit resets and it "
                  f"will carry on without repeating calls.", file=sys.stderr)
            return 3
        raise
    try:
        added = write_sheet(records, out, args.append)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print("filter outcomes: " + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())))
    print(f"wrote {added} PRs to {out} ({len(records)} sampled)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
