"""Tests for experiments.fetch_prs against a fake GitHub API. Offline; no token needed."""

import csv
import json
import re
from argparse import Namespace

import pytest

from experiments import fetch_prs, label_tool


class RateLimited(Exception):
    reset_at = 0


def _pr(number, *, files, adds, dels, merged="2025-01-10T00:00:00Z", login="alice",
        utype="User", title=None, body="", created="2025-01-09T00:00:00Z"):
    return {"number": number, "title": title or f"PR {number}", "body": body,
            "user": {"login": login, "type": utype}, "additions": adds, "deletions": dels,
            "changed_files": len(files), "merged_at": merged, "created_at": created,
            "html_url": f"https://github.com/acme/app/pull/{number}",
            "base": {"sha": "b" * 40}, "head": {"sha": "h" * 40}, "labels": [],
            "_files": files}


def _f(name, a=10, d=2):
    return {"filename": name, "additions": a, "deletions": d, "status": "modified"}


class FakeAPI:
    """Implements the slice of the GitHubClient interface fetch_prs uses."""

    def __init__(self, repos, issues=None, closing=None, edited=()):
        self.repos = repos                    # repo -> {number: pr}
        self.issues = issues or {}            # number -> issue/PR object
        self.closing = closing or {}          # pr number -> issue number
        self.edited = set(edited)
        self.calls: list[str] = []
        self.search_calls = 0

    def _prs(self, repo):
        return self.repos[repo]

    def get_json(self, path, params=None):
        self.calls.append(path)
        if path == "/search/issues":
            self.search_calls += 1
            q = params["q"]
            repo = re.search(r"repo:(\S+)", q).group(1)
            a, b = re.search(r"merged:(\S+)\.\.(\S+)", q).groups()
            hits = sorted(n for n, p in self._prs(repo).items()
                          if a <= p["merged_at"][:10] <= b
                          and not p["user"]["login"].startswith(("dependabot", "renovate")))
            size = 3                          # tiny pages: exercises pagination
            start = (params["page"] - 1) * size
            return {"total_count": len(hits),
                    "items": [{"number": n} for n in hits[start:start + size]]}
        m = re.match(r"/repos/([^/]+/[^/]+)/issues/(\d+)$", path)
        if m:
            obj = self.issues.get(int(m.group(2)))
            if obj is None:
                raise KeyError(path)
            return obj
        raise AssertionError(f"unexpected path {path}")

    def iter_pages(self, path, params=None, *, max_items=None, item_key=None):
        raise AssertionError("not used")

    def graphql(self, query, variables):
        self.calls.append("graphql")
        n = variables["number"]
        nodes = []
        if n in self.closing:
            i = self.issues[self.closing[n]]
            nodes = [{"number": self.closing[n], "title": i["title"], "body": i["body"]}]
        return {"repository": {"pullRequest": {
            "lastEditedAt": "2025-01-11T00:00:00Z" if n in self.edited else None,
            "closingIssuesReferences": {"nodes": nodes}}}}

    def get_pull_request(self, repo, number):
        self.calls.append("pr")
        return {k: v for k, v in self._prs(repo)[number].items() if k != "_files"}

    def get_pull_files(self, repo, number):
        self.calls.append("files")
        return self._prs(repo)[number]["_files"]

    def get_diff(self, repo, number):
        self.calls.append("diff")
        return f"diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old{number}\n+new{number}\n"

    def get_commit_messages(self, repo, number):
        self.calls.append("commits")
        return [f"commit for {number}", "second commit"]

    def get_linked_issue(self, repo, number):
        raise AssertionError("not used")


def _world():
    prs = {
        1: _pr(1, files=[_f("app/core.py")], adds=20, dels=5, body="Adds caching."),
        2: _pr(2, files=[_f("app/core.py")], adds=20, dels=5, login="dependabot[bot]", utype="Bot"),
        3: _pr(3, files=[_f("app/core.py", 900, 10)], adds=900, dels=10),
        4: _pr(4, files=[_f("README.md"), _f("docs/index.rst")], adds=30, dels=4),
        5: _pr(5, files=[_f("src/lib.rs")], adds=40, dels=3, body="Changes the retry loop."),
        6: _pr(6, files=[_f("web/app.ts")], adds=12, dels=8, body="Fixes #12 for good."),
        7: _pr(7, files=[_f("app/core.py")], adds=20, dels=5),           # used by SWE-bench
        8: _pr(8, files=[_f("cmd/main.go")], adds=20, dels=5),           # Go: not supported
        9: _pr(9, files=[_f("app/core.py")], adds=2, dels=1),            # too small
        10: _pr(10, files=[_f("src/Main.java")], adds=15, dels=4, body="Fixes #13", merged="2025-02-03T00:00:00Z"),
        11: _pr(11, files=[_f("app/util.py")], adds=9, dels=9, merged="2025-02-20T00:00:00Z"),
        12: _pr(12, files=[_f("a.py")] * 20, adds=100, dels=0),           # too many files
    }
    issues = {12: {"number": 12, "title": "Crash on retry", "body": "Steps to reproduce..."},
              13: {"number": 13, "title": "a pull request", "body": "", "pull_request": {}},
              99: {"number": 99, "title": "Linked via GraphQL", "body": "Issue body"}}
    return FakeAPI({"acme/app": prs}, issues=issues, closing={5: 99}, edited={6})


def _args(**kw):
    base = dict(min_lines=5, max_lines=400, max_files=15, languages=list(fetch_prs.LANGUAGES),
                exclude_authors=["dependabot", "renovate"], exclude_ids=set())
    base.update(kw)
    return Namespace(**base)


def _run(tmp_path, api, *extra, out="sheet.csv", cache="cache", seed="1", sleeps=None):
    argv = ["--repos", "acme/app", "--merged-since", "2025-01-01", "--merged-until", "2025-02-28",
            "--out", str(tmp_path / out), "--cache-dir", str(tmp_path / cache),
            "--exclude", str(tmp_path / "used.jsonl"), "--seed", seed, *extra]
    return fetch_prs.main(argv, api=api, clock=lambda: 0.0,
                          sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def _read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture
def used(tmp_path):
    (tmp_path / "used.jsonl").write_text(
        json.dumps({"pr_id": "acme__app-7::treatment"}) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ filters


def test_filters_report_a_reason_for_every_rejection(tmp_path):
    api = _world()
    cache = fetch_prs.Cache(tmp_path)
    args = _args(exclude_ids={"acme/app#7"})
    got = {n: fetch_prs.passes_filters(fetch_prs.fetch_meta(api, "acme/app", n, cache), None, args)
           for n in range(1, 13)}
    assert got[1] == (True, "ok") and got[5] == (True, "ok") and got[6] == (True, "ok")
    assert got[2] == (False, "bot")
    assert got[3] == (False, "too_large")
    assert got[4] == (False, "docs_only")
    assert got[7] == (False, "already_used")
    assert got[8] == (False, "no_supported_language")
    assert got[9] == (False, "too_small")
    assert got[12] == (False, "too_many_files")
    assert fetch_prs.passes_filters(fetch_prs.fetch_meta(api, "acme/app", 5, cache), None,
                                    _args(languages=["python"])) == (False, "language:rust")


def test_language_is_the_majority_of_non_test_lines():
    files = [_f("src/a.py", 5, 0), _f("tests/test_a.py", 200, 0), _f("web/x.ts", 30, 0)]
    top, counts, docs = fetch_prs.language_of(files)
    assert top == "typescript" and counts["python"] == 205 and not docs
    assert fetch_prs.language_of([_f("tests/test_a.py", 9, 0)])[0] == "python"


def test_is_bot_uses_type_login_suffix_and_exclude_list():
    assert fetch_prs.is_bot({"author": "x", "author_type": "Bot"})
    assert fetch_prs.is_bot({"author": "renovate-bot", "author_type": "User"}, ["renovate"])
    assert fetch_prs.is_bot({"author": "ci[bot]", "author_type": "User"})
    assert not fetch_prs.is_bot({"author": "alice", "author_type": "User"}, ["renovate"])


# ----------------------------------------------------------------- end to end


def test_end_to_end_sheet_has_the_full_context_columns(tmp_path, used):
    api = _world()
    assert _run(tmp_path, api) == 0
    rows = {r["pr_id"]: r for r in _read(tmp_path / "sheet.csv")}
    assert set(rows) == {"acme/app#1", "acme/app#5", "acme/app#6", "acme/app#10", "acme/app#11"}
    r = rows["acme/app#5"]
    assert list(r) == fetch_prs.COLUMNS
    assert r["view"] == "full_context" and r["repo"] == "acme/app" and r["number"] == "5"
    assert r["issue_number"] == "99" and r["issue_title"] == "Linked via GraphQL"   # GraphQL link
    assert r["languages"] == "rust" and r["additions"] == "40"
    assert json.loads(r["commit_messages"]) == ["commit for 5", "second commit"]
    assert "+new5" in r["code_change"]
    r6 = rows["acme/app#6"]                                  # "Fixes #12" in the body
    assert (r6["issue_number"], r6["issue_title"]) == ("12", "Crash on retry")
    assert r6["body_edited"] == "1" and rows["acme/app#1"]["body_edited"] == "0"
    r10 = rows["acme/app#10"]                                # "Fixes #13" is a PR: no issue
    assert r10["issue_number"] == "" and r10["issue_body"] == ""
    for c in ("annotator_1", "annotator_2", "adjudicated", "notes"):
        assert all(x[c] == "" for x in rows.values())


def test_second_run_makes_zero_api_calls(tmp_path, used):
    assert _run(tmp_path, _world()) == 0
    first = (tmp_path / "sheet.csv").read_bytes()
    again = _world()
    assert _run(tmp_path, again) == 0
    assert again.calls == [] and (tmp_path / "sheet.csv").read_bytes() == first


def test_per_repo_cap_and_seed_reproducibility(tmp_path, used):
    assert _run(tmp_path, _world(), "--per-repo", "2", seed="5", out="a.csv", cache="c1") == 0
    assert _run(tmp_path, _world(), "--per-repo", "2", seed="5", out="b.csv", cache="c2") == 0
    a = [r["pr_id"] for r in _read(tmp_path / "a.csv")]
    assert len(a) == 2 and a == [r["pr_id"] for r in _read(tmp_path / "b.csv")]


def test_n_caps_the_total(tmp_path, used):
    assert _run(tmp_path, _world(), "--n", "3") == 0
    assert len(_read(tmp_path / "sheet.csv")) == 3


def test_search_is_paced_to_thirty_per_minute(tmp_path, used):
    api, sleeps = _world(), []
    assert _run(tmp_path, api, sleeps=sleeps) == 0
    assert api.search_calls > 2                      # two month windows, paged
    assert len(sleeps) == api.search_calls - 1 and all(abs(s - 2.0) < 1e-9 for s in sleeps)


def test_pacer_only_sleeps_for_the_remaining_gap():
    now, slept = [0.0], []
    p = fetch_prs.Pacer(30, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    p.wait()
    now[0] += 0.5
    p.wait()
    now[0] += 5
    p.wait()
    assert slept == [1.5]


# -------------------------------------------------------------- sheet safety


def test_append_keeps_existing_rows_and_labels_and_only_adds(tmp_path, used):
    assert _run(tmp_path, _world(), "--n", "2") == 0
    path = tmp_path / "sheet.csv"
    rows = _read(path)
    rows[0]["annotator_1"], rows[0]["notes"] = "1", "[a1] torn"
    label_tool._write_rows(path, list(rows[0]), rows)
    before = path.read_bytes()

    assert _run(tmp_path, _world(), "--n", "5") == 2          # refuses without --append
    assert path.read_bytes() == before

    assert _run(tmp_path, _world(), "--n", "5", "--append") == 0
    after = _read(path)
    assert [r["pr_id"] for r in after[:2]] == [r["pr_id"] for r in rows]
    assert after[0]["annotator_1"] == "1" and after[0]["notes"] == "[a1] torn"
    assert len(after) == 5 and len({r["pr_id"] for r in after}) == 5


def test_write_sheet_overwrites_an_unlabelled_sheet(tmp_path):
    rec = {c: "" for c in fetch_prs.COLUMNS} | {"pr_id": "a/b#1"}
    p = tmp_path / "s.csv"
    assert fetch_prs.write_sheet([rec], p, False) == 1
    assert fetch_prs.write_sheet([rec | {"pr_id": "a/b#2"}], p, False) == 1
    assert [r["pr_id"] for r in _read(p)] == ["a/b#2"]


def test_columns_are_capped(tmp_path):
    meta = {"repo": "a/b", "number": 1, "url": "u", "title": "t" * 9000, "body": "b" * 9000,
            "additions": 1, "deletions": 1, "changed_files": 1, "merged_at": "x",
            "language_lines": {"python": 2}}
    full = {"diff": "".join(f"+line {i}\n" for i in range(9000)),
            "commit_messages": ["m" * 400] * 40,
            "issue": {"number": 3, "title": "i", "body": "z" * 20000}, "body_edited": False}
    r = fetch_prs.build_record(meta, full)
    assert len(r["title"]) == 6000 and len(r["body"]) == 6000 and len(r["issue_body"]) == 8000
    assert len(r["code_change"]) <= 30000 and r["diff_truncated"] == "1"
    assert r["code_change"].endswith("\n") is False and "+line" in r["code_change"]
    assert len(r["commit_messages"]) <= 4000 and isinstance(json.loads(r["commit_messages"]), list)


# --------------------------------------------------------- errors and limits


def test_rate_limit_stops_cleanly_with_a_resume_message(tmp_path, used, capsys):
    api = _world()

    def boom(repo, number):
        raise RateLimited("limit")

    api.get_pull_request = boom
    assert _run(tmp_path, api) == 3
    assert "re-run" in capsys.readouterr().err and not (tmp_path / "sheet.csv").exists()


def test_missing_token_gives_a_clear_message(tmp_path, monkeypatch, capsys):
    import clarifyreview.config as config

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(config, "settings", lambda: Namespace(github_token=None))
    assert fetch_prs.main(["--repos", "a/b", "--out", str(tmp_path / "s.csv")]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_used_ids_maps_swebench_ids(tmp_path):
    f = tmp_path / "u.jsonl"
    f.write_text(json.dumps({"pr_id": "psf__requests-1234::x"}) + "\n"
                 + json.dumps({"pr_id": "a/b#5"}) + "\n", encoding="utf-8")
    assert fetch_prs.used_ids([str(f), str(tmp_path / "missing")]) == {"psf/requests#1234", "a/b#5"}


def test_cache_writes_are_atomic_files(tmp_path):
    c = fetch_prs.Cache(tmp_path / "x")
    c.put("meta_1", {"a": 1})
    assert c.get("meta_1") == {"a": 1} and c.get("nope") is None
    assert [p.name for p in (tmp_path / "x").iterdir()] == ["meta_1.json"]
