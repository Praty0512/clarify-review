"""Compare the ambiguity detectors on the same contexts.

Labels are constructed, not judged: the stripped context of an instance is
ambiguous by construction (its stated intent was removed) and the full context
is clear. That makes accuracy measurable without hand labels, with one caveat
worth stating in any write-up - a detector that keys on "no linked issue" gets
part of the way for free, so the heuristic's recall here is an upper bound on
its real-world recall, not an estimate of it.

The uncertainty detectors cost eight model calls per decision. On a free key
they are run on a separate model from the reviewer so they do not consume the
review model's daily quota; the report records which model was used.

    python -m experiments.compare_detectors --instances data/instances.v2.jsonl \\
        --detectors heuristic sampling perturbation --limit 6 \\
        --model gemini-3.1-flash-lite

Fully local, no quota (needs `ollama pull qwen3:4b`; see docs/ollama.md). Local
results are a separate study and must not be pooled with Gemini results:

    CLARIFYREVIEW_PROVIDER=ollama python -m experiments.compare_detectors         --instances data/instances.v2.jsonl --detectors heuristic sampling         --limit 6 --model qwen3:4b
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from clarifyreview import detect
from clarifyreview.detect.base import Thresholds

from .run_matrix import Instance
from .strip import strip_context

log = logging.getLogger("compare_detectors")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instances", default="data/instances.v2.jsonl")
    ap.add_argument("--detectors", nargs="+", default=["heuristic"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=None,
                    help="model for the uncertainty detectors (default: config)")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--out", default="runs/detector_comparison.json")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    rows = [json.loads(l) for l in Path(args.instances).read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r["variant"] == "golden"]     # one context pair per change
    if args.limit:
        rows = rows[: args.limit]

    thresholds = Thresholds.load(Path("data/thresholds.json"))
    report: dict = {"labels": "constructed: stripped=1 (ambiguous), full=0 (clear)",
                    "n_instances": len(rows), "detectors": {}}
    for name in args.detectors:
        kwargs = {"thresholds": thresholds}
        if name in ("sampling", "perturbation"):
            kwargs["n"] = args.samples
            if args.model:
                kwargs["model"] = args.model
        det = detect.build(name, **kwargs)
        decisions = []
        for r in rows:
            inst = Instance.from_json(json.dumps(r))
            full = inst.context()
            stripped, _ = strip_context(full, level="prose")
            for label, ctx in ((1, stripped), (0, full)):
                t0 = time.monotonic()
                try:
                    d = det.decide(ctx)
                    decisions.append({"pr_id": r["pr_id"], "label": label, "ask": int(d.ask),
                                      "score": d.score, "cost_usd": d.cost_usd,
                                      "ms": int((time.monotonic() - t0) * 1000)})
                except Exception as exc:  # noqa: BLE001
                    log.warning("%s on %s failed: %s", name, r["pr_id"], str(exc)[:120])
                    if "PerDay" in str(exc):
                        break
            log.info("%s: %d decisions so far", name, len(decisions))
        tp = sum(1 for d in decisions if d["label"] and d["ask"])
        fp = sum(1 for d in decisions if not d["label"] and d["ask"])
        fn = sum(1 for d in decisions if d["label"] and not d["ask"])
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        stripped_scores = [d["score"] for d in decisions if d["label"]]
        full_scores = [d["score"] for d in decisions if not d["label"]]
        report["detectors"][name] = {
            "model": getattr(det, "model", None) if name in ("sampling", "perturbation") else None,
            "n_decisions": len(decisions),
            "ask_rate": round(sum(d["ask"] for d in decisions) / len(decisions), 4) if decisions else None,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "mean_score_stripped": round(sum(stripped_scores) / len(stripped_scores), 4) if stripped_scores else None,
            "mean_score_full": round(sum(full_scores) / len(full_scores), 4) if full_scores else None,
            "mean_ms": round(sum(d["ms"] for d in decisions) / len(decisions), 1) if decisions else None,
            "decisions": decisions,
        }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2))
    summary = {k: {kk: vv for kk, vv in v.items() if kk != "decisions"}
               for k, v in report["detectors"].items()}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
