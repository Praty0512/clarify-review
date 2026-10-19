"""Freeze the two uncertainty detectors' thresholds on the dev split.

`train_classifier --sweep-thresholds` freezes the heuristic and the classifier,
which score offline. The sampling and perturbation detectors cost eight model
calls per decision, so their sweep is this separate, explicit step. It uses the
same labelled set and the same split, so all four thresholds are tuned on the
same pull requests and none of them on the ablation set.

    python -m experiments.sweep_uncertainty --labels data/labelled_prs.jsonl

Scores are cached as they arrive, so a run stopped by a daily quota resumes
where it left off rather than paying for the same decisions twice.

There is also a diagnostic mode that re-sweeps the scores already recorded by
`compare_detectors`. Those come from the ablation instances, so it reports what
threshold would have suited them but never writes one - tuning on the test set
would make every later number from that detector optimistic.

    python -m experiments.sweep_uncertainty \\
        --from-comparison runs/detector_comparison_uncertainty.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from clarifyreview import detect
from clarifyreview.config import settings
from clarifyreview.detect.base import Thresholds

from .train_classifier import load_labelled, split, sweep_threshold

log = logging.getLogger("sweep_uncertainty")

UNCERTAINTY = ("sampling", "perturbation")


def sweep_recorded(comparison: dict) -> dict:
    """Best threshold per detector over decisions `compare_detectors` recorded."""
    out = {}
    for name, d in comparison.get("detectors", {}).items():
        decisions = d.get("decisions") or []
        if name not in UNCERTAINTY or not decisions:
            continue
        threshold, stats = sweep_threshold([x["score"] for x in decisions],
                                           [x["label"] for x in decisions])
        out[name] = {"threshold": threshold, "n_decisions": len(decisions), **stats}
    return out


def _load_cache(path: Path) -> dict[tuple[str, str], float]:
    if not path.exists():
        return {}
    cache = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            cache[(row["detector"], row["pr_id"])] = row["score"]
    return cache


def score_dev(names, dev_ctx, cache_path: Path, model: str | None, samples: int):
    """Score every dev context with each detector, reusing cached scores."""
    cache = _load_cache(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    scores: dict[str, list[float | None]] = {}
    with cache_path.open("a", encoding="utf-8") as fh:
        for name in names:
            kwargs: dict = {"n": samples}
            if model:
                kwargs["model"] = model
            det = detect.build(name, **kwargs)
            out: list[float | None] = []
            for ctx in dev_ctx:
                key = (name, ctx.pr_id)
                if key not in cache:
                    try:
                        cache[key] = det.score(ctx)[0]
                    except Exception as exc:  # noqa: BLE001
                        log.warning("%s on %s failed: %s", name, ctx.pr_id, str(exc)[:120])
                        if "PerDay" in str(exc):
                            log.error("daily quota exhausted; re-run to resume from the cache")
                            return scores, False
                        out.append(None)
                        continue
                    fh.write(json.dumps({"detector": name, "pr_id": ctx.pr_id,
                                         "score": cache[key]}) + "\n")
                    fh.flush()
                out.append(cache[key])
            scores[name] = out
    return scores, True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--labels", default="data/labelled_prs.jsonl")
    ap.add_argument("--from-comparison", default=None, metavar="JSON",
                    help="diagnostic only: sweep scores recorded by compare_detectors")
    ap.add_argument("--detectors", nargs="+", default=list(UNCERTAINTY), choices=UNCERTAINTY)
    ap.add_argument("--model", default=None, help="model for the detectors (default: config)")
    ap.add_argument("--samples", type=int, default=8)
    ap.add_argument("--cache", default="runs/uncertainty_dev_scores.jsonl")
    ap.add_argument("--thresholds-out", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "google_genai", "google_genai.models"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.from_comparison:
        result = sweep_recorded(json.loads(Path(args.from_comparison).read_text()))
        print(json.dumps(result, indent=2))
        print("Diagnostic only: these decisions come from the ablation instances, so "
              "no threshold was written.")
        return 0

    labels_path = Path(args.labels)
    if not labels_path.exists():
        log.error("no labelled set at %s. The dev split comes from the hand-labelled "
                  "PRs - run experiments.label_tool first.", labels_path)
        return 1

    contexts, labels = load_labelled(labels_path)
    _, (dev_ctx, dev_y) = split(contexts, labels)
    log.info("dev split: %d PRs, %d ambiguous; %d detector calls at most",
             len(dev_y), sum(dev_y), len(dev_y) * len(args.detectors) * args.samples)

    scores, complete = score_dev(args.detectors, dev_ctx, Path(args.cache),
                                 args.model, args.samples)
    if not complete:
        return 2

    cfg = settings()
    tpath = Path(args.thresholds_out) if args.thresholds_out else cfg.thresholds_path
    thresholds = Thresholds.load(tpath)
    sweeps = {}
    for name, s in scores.items():
        pairs = [(x, y) for x, y in zip(s, dev_y) if x is not None]
        if len(pairs) < 10:
            log.error("%s: only %d scored dev PRs; not freezing a threshold on that",
                      name, len(pairs))
            continue
        thresholds.values[name], sweeps[name] = sweep_threshold(
            [x for x, _ in pairs], [y for _, y in pairs])
        sweeps[name]["n_scored"] = len(pairs)
    thresholds.save(tpath)
    print(json.dumps({"thresholds": thresholds.values, "dev_sweep": sweeps}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
