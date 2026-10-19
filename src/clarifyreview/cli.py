"""Command line entry points.

    clarifyreview init-db
    clarifyreview ingest      --repo owner/name --pr 42
    clarifyreview detect      --repo owner/name --pr 42 [--detector sampling]
    clarifyreview review      --repo owner/name --pr 42 [--post]
    clarifyreview serve       [--port 8000]

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
    det = detect.build(args.detector)
    decision = det.decide(ctx)

    print(f"detector : {decision.detector.value}")
    print(f"decision : {'ASK' if decision.ask else 'PROCEED'}")
    print(f"score    : {decision.score:.3f}  (threshold {decision.threshold:.2f})")
    print(f"why      : {decision.why}")
    if args.features:
        print("\nfeatures:")
        for k, v in extract(ctx).items():
            print(f"  {k:<26} {v:g}")
    return 0


def cmd_review(args) -> int:
    from .clarify.loop import GitHubResponder, NullResponder
    from .pipeline import CONDITION_STRIPPED_CLARIFY, build_condition
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

    pipeline = build_condition(
        CONDITION_STRIPPED_CLARIFY, detector_name=args.detector, responder=responder
    )
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

    print(render_review(run.review))
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


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("clarifyreview.gh.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
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
    p.add_argument("--post", action="store_true", help="post to the PR and wait for a reply")
    p.add_argument("--db")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("models", help="show configured models and what the key can reach")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("serve", help="run the webhook receiver")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
