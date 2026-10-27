"""Command line entry points.

    clarifyreview init-db
    clarifyreview ingest      --repo owner/name --pr 42
    clarifyreview detect      --repo owner/name --pr 42 [--detector sampling]
    clarifyreview review      --repo owner/name --pr 42 [--post]
    clarifyreview serve       [--port 8000] [--sweep-interval 300]
    clarifyreview sweep       [--limit 20]
    clarifyreview replay      [--db data/study_v2.db] [--pr-id ID | --list]

`--diff` accepts a local diff file anywhere `--repo/--pr` is accepted, so the
whole pipeline can be exercised without touching GitHub or spending an API call
on ingestion.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import settings
from .types import PRContext


def _load_context(args) -> PRContext:
    from .ingest import from_raw

    if args.diff:
        diff = Path(args.diff).read_text(encoding="utf-8")
        return from_raw(
            pr_id=args.pr_id or Path(args.diff).stem,
            diff=diff,
            title=args.title or "",
            commit_messages=[args.commit_msg] if args.commit_msg else [],
            repo_root=Path(args.repo_root) if args.repo_root else None,
            python_fallback=True,
        )

    from .gh.client import GitHubClient
    from .ingest import from_github

    if not (args.repo and args.pr):
        raise SystemExit("give either --diff, or both --repo and --pr")
    with GitHubClient() as gh:
        return from_github(gh, args.repo, args.pr,
                           Path(args.repo_root) if args.repo_root else None)


def cmd_init_db(args) -> int:
    from .store import db

    path = Path(args.db) if args.db else settings().clarifyreview_db
    db.init(path)
    print(f"initialised {path}")
    return 0


def cmd_ingest(args) -> int:
    ctx = _load_context(args)
    if args.json:
        print(json.dumps(ctx.model_dump(mode="json"), indent=2, sort_keys=True))
    else:
        print(ctx.render())
    print(f"\n--- fingerprint: {ctx.fingerprint()}", file=sys.stderr)
    print(
        f"--- {len(ctx.hunks)} hunks, {len(ctx.changed_symbols)} changed symbols, "
        f"{len(ctx.files_touched)} files",
        file=sys.stderr,
    )
    return 0


def cmd_detect(args) -> int:
    from . import detect
    from .detect.features import extract

    ctx = _load_context(args)
    thresholds = detect.live_thresholds()
    det = detect.build(args.detector, thresholds=thresholds)
    decision = det.decide(ctx)

    print(f"detector : {decision.detector.value}")
    print(f"decision : {'ASK' if decision.ask else 'PROCEED'}")
    print(f"score    : {decision.score:.3f}  (threshold {decision.threshold:.2f})")
    print(f"thresholds: {thresholds.source}")
    print(f"why      : {decision.why}")
    if args.features:
        print("\nfeatures:")
        for k, v in extract(ctx).items():
            print(f"  {k:<26} {v:g}")
    return 0


def cmd_review(args) -> int:
    from .clarify.loop import GitHubResponder, NullResponder
    from .pipeline import CONDITION_STRIPPED_CLARIFY, build_condition, live_condition
    from .review.render import render_review
    from .store import db

    # Stages 1 and 2 run offline; Stage 4 always calls the provider. Check up
    # front so a missing key is one clear line rather than an SDK traceback
    # mid-demo.
    if not settings().api_key():
        print(_key_help(), file=sys.stderr)
        return 2

    ctx = _load_context(args)
    responder = NullResponder()
    if args.post and args.repo and args.pr:
        from .gh.client import GitHubClient

        gh = GitHubClient()
        responder = GitHubResponder(
            gh, args.repo, args.pr, timeout_s=settings().clarifyreview_clarify_timeout
        )

    from .detect import live_thresholds

    thresholds = live_thresholds()
    print(f"[stage 2] thresholds: {thresholds.source}", file=sys.stderr)
    pipeline = build_condition(
        CONDITION_STRIPPED_CLARIFY, detector_name=args.detector, responder=responder,
        thresholds=thresholds,
    )
    # A run on a real PR is a live run, not a Study A row: log it as such so it can
    # never be counted in the ablation's treatment arm. Local --diff runs are unchanged.
    pipeline.condition = live_condition(pipeline.condition, live=bool(args.repo and args.pr))
    run = pipeline.run(ctx)

    if run.error:
        print(f"error: {run.error}", file=sys.stderr)
        return 1

    if run.decision:
        print(
            f"[stage 2] {'ASK' if run.decision.ask else 'PROCEED'} "
            f"score={run.decision.score:.3f} — {run.decision.why}\n",
            file=sys.stderr,
        )
    if run.clarification:
        for q in run.clarification.questions.questions:
            print(f"[stage 3] asked [{q.target}] {q.question}", file=sys.stderr)
        print(f"[stage 3] answered={run.clarification.answered}\n", file=sys.stderr)

    note = None
    if run.clarification and not run.clarification.answered:
        note = "No answer was received, so this review was written without it."
    print(render_review(run.review, detector_note=note))
    if args.post and args.repo and args.pr:
        # --post promised the PR a review, so it goes back as a comment too,
        # marked like the bot's so a later reply never mistakes it for an answer.
        from .review.render import review_marker

        head_sha = gh.get_pull_request(args.repo, args.pr).get("head", {}).get("sha")
        gh.post_comment(args.repo, args.pr, render_review(
            run.review, detector_note=note, marker=review_marker(head_sha)))
        print(f"[stage 4] review posted to {args.repo}#{args.pr}", file=sys.stderr)
    print(
        f"\n--- ${run.cost_usd:.4f}, {run.latency_ms}ms, "
        f"{run.input_tokens}in/{run.output_tokens}out "
        f"({run.cache_read_tokens} cached)",
        file=sys.stderr,
    )

    path = Path(args.db) if args.db else settings().clarifyreview_db
    db.init(path)
    with db.connect(path) as conn:
        db.record_run(conn, run)
    return 0


def _key_help() -> str:
    cfg = settings()
    if cfg.provider == "gemini":
        how = ("  Get a free key at https://aistudio.google.com/apikey\n"
               "  then:  export GEMINI_API_KEY=...")
    else:
        how = "  export ANTHROPIC_API_KEY=sk-ant-..."
    return (
        f"No API key found for provider {cfg.provider!r}.\n"
        f"  `review` runs the full pipeline, and Stage 4 needs one.\n"
        f"{how}\n"
        f"  (or copy .env.example to .env and fill it in)\n\n"
        f"  Stages 1 and 2 need no key - try these instead:\n"
        f"    clarifyreview ingest --diff examples/ambiguous.diff\n"
        f"    clarifyreview detect --diff examples/ambiguous.diff "
        f"--commit-msg 'fix' --features"
    )


def cmd_models(args) -> int:
    """List the models this key can actually reach, and the configured roles."""
    from .llm.client import LLM

    cfg = settings()
    print(f"provider : {cfg.provider}")
    print("roles    :")
    for role in ("review", "question", "judge", "oracle", "sampling"):
        print(f"    {role:<9} {cfg.model_for(role)}")

    if not cfg.api_key():
        sys.stdout.flush()  # keep the role listing above the help text
        print("\n" + _key_help(), file=sys.stderr)
        return 2
    print("\navailable to this key:")
    try:
        for m in LLM().list_models():
            print(f"    {m}")
    except Exception as exc:
        print(f"    could not list models: {exc}", file=sys.stderr)
        return 1
    return 0


CONDITION_LABELS = (
    ("stripped_plain", "FLOOR      intent withheld, single pass"),
    ("stripped_clarify", "TREATMENT  intent withheld, ClarifyReview"),
    ("full_plain", "CEILING    full context, single pass"),
)
DEFAULT_REPLAY = "sympy__sympy-12481::golden"


def cmd_replay(args) -> int:
    """Replay a recorded study instance through all four stages, offline.

    Stages 3 and 4 call the model provider, which is slow and can fail on a
    busy free tier - the wrong thing to depend on in front of an audience. Every
    run is logged in full, so the recorded one can be shown instead: the same
    pull request in all three conditions, with the question asked, the answer
    received and how the judge scored each review.
    """
    import sqlite3

    path = Path(args.db)
    if not path.exists():
        print(f"no experiment log at {path}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    judged = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='judgements'").fetchone())

    if args.list:
        rows = conn.execute(
            "SELECT pr_id, ambiguity_score, answered FROM runs "
            "WHERE condition='stripped_clarify' AND asked=1 AND error IS NULL "
            "ORDER BY pr_id").fetchall()
        print(f"{len(rows)} recorded instances where the detector asked:\n")
        for r in rows:
            print(f"  {r['pr_id']:<45} score={r['ambiguity_score']:.3f}")
        return 0

    pr_id = args.pr_id or DEFAULT_REPLAY
    inst = conn.execute("SELECT * FROM instances WHERE pr_id=?", (pr_id,)).fetchone()
    if inst is None:
        print(f"{pr_id} is not in {path}; try --list", file=sys.stderr)
        return 1

    def rule(title: str) -> None:
        print(f"\n── {title} " + "─" * max(4, 66 - len(title)))

    rule(f"{pr_id}  ({'injected defect: ' + inst['mutation_op'] if inst['has_defect'] else 'accepted fix, no defect'})")
    print("What the author actually wanted (withheld from the floor and treatment):")
    import textwrap

    issue = " ".join((inst["problem_statement"] or "").split())
    print(textwrap.indent(textwrap.fill(textwrap.shorten(issue, 420, placeholder=" ..."), 76), "  "))

    for condition, label in CONDITION_LABELS:
        run = conn.execute(
            "SELECT * FROM runs WHERE pr_id=? AND condition=? AND error IS NULL "
            "ORDER BY id DESC LIMIT 1", (pr_id, condition)).fetchone()
        if run is None:
            continue
        payload = json.loads(run["payload"])
        rule(label)
        if condition == "stripped_clarify":
            print(f"[stage 2] {'ASK' if run['ask'] else 'PROCEED'}  "
                  f"score {run['ambiguity_score']:.3f} (threshold {run['threshold']:.2f})")
            print(f"          {run['detector_why']}")
            clar = payload.get("clarification")
            if clar:
                for q in clar["questions"]["questions"]:
                    print(f"[stage 3] Q [{q['target']}] {q['question']}")
                print(f"[stage 3] A {clar.get('answer') or '(no answer)'}")
        review = payload.get("review") or {}
        print(f"[stage 4] intent : {review.get('intent_summary')}")
        print(f"          verdict: {review.get('verdict')}, "
              f"{len(review.get('findings', []))} finding(s)")
        for f in review.get("findings", [])[:3]:
            print(f"          - [{f['severity']}/{f['category']}] {f['claim'][:110]}")
        if judged:
            j = conn.execute("SELECT * FROM judgements WHERE run_id=?", (run["id"],)).fetchone()
            if j:
                marks = [("intent recovered", j["intent_recovered"])]
                marks.append(("defect caught", j["defect_caught"]) if inst["has_defect"]
                             else ("false alarm", j["false_alarm"]))
                print("[judge]   " + ",  ".join(f"{k}: {'yes' if v else 'no'}" for k, v in marks))
    return 0


def cmd_sweep(args) -> int:
    """One pass over parked runs whose clarification deadline has passed - for cron
    or a scheduled task when the server itself is not left running."""
    from .gh.app import sweep_expired

    handled = sweep_expired(limit=args.limit)
    print(f"swept {handled} expired parked run(s)")
    return 0


def cmd_serve(args) -> int:
    import os

    import uvicorn

    if args.sweep_interval is not None:
        from .gh.settings import reset_bot_settings

        os.environ["CLARIFYREVIEW_SWEEP_INTERVAL_S"] = str(args.sweep_interval)
        reset_bot_settings()
    uvicorn.run("clarifyreview.gh.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _force_utf8_streams() -> None:
    """Keep output with box-drawing characters from crashing on Windows code
    pages (cp1252) when stdout/stderr is piped or redirected."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower().replace("_", "-")
        if enc in ("utf-8", "utf8"):
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(prog="clarifyreview")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_source(p) -> None:
        p.add_argument("--repo", help="owner/name")
        p.add_argument("--pr", type=int, help="pull request number")
        p.add_argument("--diff", help="path to a local unified diff file")
        p.add_argument("--pr-id", help="identifier to use with --diff")
        p.add_argument("--title", help="PR title, with --diff")
        p.add_argument("--commit-msg", help="commit message, with --diff")
        p.add_argument("--repo-root", help="checkout at the base commit, for context")

    p = sub.add_parser("init-db", help="create the experiment log")
    p.add_argument("--db")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("ingest", help="stage 1 only: show the assembled context")
    add_source(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("detect", help="stage 2 only: ask or proceed")
    add_source(p)
    p.add_argument(
        "--detector",
        default=settings().clarifyreview_detector,
        choices=["heuristic", "classifier", "sampling", "perturbation"],
    )
    p.add_argument("--features", action="store_true", help="print the feature vector")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("review", help="the full pipeline")
    add_source(p)
    p.add_argument("--detector", default=settings().clarifyreview_detector)
    p.add_argument("--post", action="store_true", help="post the question and the review to the PR, waiting for a reply in between")
    p.add_argument("--db")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("models", help="show configured models and what the key can reach")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("replay", help="replay a recorded study run, all stages, offline")
    p.add_argument("--db", default="data/study_v2.db")
    p.add_argument("--pr-id", help=f"instance to replay (default {DEFAULT_REPLAY})")
    p.add_argument("--list", action="store_true", help="list instances where it asked")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("serve", help="run the webhook receiver")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.add_argument("--sweep-interval", type=float, default=None,
                   help="seconds between sweeps for expired parked runs "
                        "(default CLARIFYREVIEW_SWEEP_INTERVAL_S=300; 0 turns it off)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("sweep", help="finish parked runs whose clarification deadline passed")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_sweep)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
