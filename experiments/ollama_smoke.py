"""One-command live check of the Ollama backend against a running server.

    CLARIFYREVIEW_PROVIDER is forced to ollama; nothing is written to any database.

    .venv\\Scripts\\python.exe -m experiments.ollama_smoke
    .venv\\Scripts\\python.exe -m experiments.ollama_smoke --model qwen3:4b --diff examples/clear.diff

It lists the pulled models, then makes one structured call (a full review of the
diff, through the normal Pipeline -> ReviewGenerator -> LLM path, validated
against ReviewOutput) and one text call (the sampling detector's intent
hypothesis, temperature 1.0), and prints the served model (with weights digest),
token counts, latency and whether the JSON validated. Exit code 0 only if both
calls succeed. Pull the models first: `ollama pull qwen3:4b`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--diff", default="examples/ambiguous.diff")
    ap.add_argument("--model", default=None,
                    help="model for both calls (default: the configured review/sampling roles)")
    ap.add_argument("--host", default=None, help="override OLLAMA_HOST")
    ap.add_argument("--skip-text", action="store_true")
    args = ap.parse_args(argv)

    os.environ["CLARIFYREVIEW_PROVIDER"] = "ollama"
    if args.host:
        os.environ["OLLAMA_HOST"] = args.host

    from clarifyreview import config
    from clarifyreview.detect.uncertainty import INTENT_INSTRUCTION, INTENT_SYSTEM
    from clarifyreview.ingest import from_raw
    from clarifyreview.llm.client import LLM
    from clarifyreview.llm.providers.ollama_backend import OllamaBackend, OllamaUnavailable
    from clarifyreview.pipeline import Pipeline
    from clarifyreview.review.generator import ReviewGenerator

    config.reset_settings()
    cfg = config.settings()
    backend = OllamaBackend()
    print(f"host            {backend.host}")
    print(f"think={backend.think}  num_ctx_max={backend.num_ctx_max}  "
          f"num_predict_max={backend.num_predict_max}  keep_alive={backend.keep_alive}")

    try:
        pulled = backend.list_models()
    except OllamaUnavailable as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"pulled models   {', '.join(pulled) or '(none)'}")

    review_model = args.model or cfg.model_for("review")
    sampling_model = args.model or cfg.model_for("sampling")
    missing = sorted({m for m in (review_model, sampling_model) if m not in pulled})
    if missing:
        for m in missing:
            print(f"FAIL: {m} is not pulled. Run: ollama pull {m}", file=sys.stderr)
        return 2

    diff_path = Path(args.diff)
    ctx = from_raw(pr_id=f"smoke/{diff_path.stem}#1", diff=diff_path.read_text(encoding="utf-8"),
                   title="fix login bug", commit_messages=["fix"])
    llm = LLM(backend=backend)
    ok = True

    print(f"\n[structured] review of {diff_path} with {review_model}")
    run = Pipeline.plain("ollama_smoke", ReviewGenerator(llm=llm, model=review_model)).run(ctx)
    if run.error or run.review is None:
        ok = False
        print(f"  JSON validated : NO  ({run.error})")
    else:
        print("  JSON validated : yes (ReviewOutput)")
        print(f"  served model   : {run.model}")
        print(f"  tokens         : {run.input_tokens} in / {run.output_tokens} out")
        print(f"  latency        : {run.latency_ms} ms  (first call includes model load)")
        print(f"  model calls    : {llm.total.calls}  (>1 means repair turns were needed)")
        print(f"  verdict        : {run.review.verdict}, {len(run.review.findings)} finding(s)")
        print(f"  intent         : {run.review.intent_summary[:160]}")

    if not args.skip_text:
        print(f"\n[text] intent hypothesis with {sampling_model}, temperature 1.0")
        before = llm.total.calls
        try:
            res = llm.text(model=sampling_model, system=INTENT_SYSTEM,
                           cached_context=ctx.render(), instruction=INTENT_INSTRUCTION,
                           max_tokens=200, thinking=False, temperature=1.0)
        except Exception as exc:  # noqa: BLE001 - report, don't traceback
            ok = False
            print(f"  FAIL: {type(exc).__name__}: {exc}")
        else:
            u = res.usage
            print(f"  served model   : {u.served_model}")
            print(f"  tokens         : {u.input_tokens} in / {u.output_tokens} out")
            print(f"  latency        : {u.latency_ms} ms  (calls: {llm.total.calls - before})")
            print(f"  text           : {res.value[:200]!r}")
            if not res.value.strip():
                ok = False
                print("  FAIL: empty reply (a thinking model may have used its whole budget)")

    print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
