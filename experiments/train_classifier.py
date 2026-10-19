"""Train detector (b), and freeze every detector's threshold on the dev split.

Two jobs, one script, because they must happen in that order and against the same
split. Nothing here is allowed to see the ablation set: thresholds tuned on the
data they are later evaluated on is the single easiest objection to raise against
a study like this one, and the fix costs an afternoon.

Input is the hand-labelled set - PRs labelled ambiguous/clear by both team members
with a written codebook, disagreements adjudicated, Cohen's kappa reported.

    python -m experiments.train_classifier --labels data/labelled_prs.jsonl
    python -m experiments.train_classifier --labels ... --sweep-thresholds
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np

from clarifyreview.config import settings
from clarifyreview.detect.base import DEFAULT_THRESHOLDS, Thresholds
from clarifyreview.detect.classifier import ClassifierDetector
from clarifyreview.detect.features import extract
from clarifyreview.detect.heuristic import HeuristicDetector
from clarifyreview.ingest import from_raw
from clarifyreview.types import LinkedIssue, PRContext

log = logging.getLogger("train")


def load_labelled(path: Path) -> tuple[list[PRContext], list[int]]:
    """Read the labelled set.

    Expected per line: {pr_id, diff, title, body, commit_messages, issue_body,
    label} where label is 1 for ambiguous, 0 for clear.
    """
    contexts: list[PRContext] = []
    labels: list[int] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        issue_body = row.get("issue_body") or ""
        contexts.append(
            from_raw(
                pr_id=row["pr_id"],
                diff=row["diff"],
                repo=row.get("repo", ""),
                title=row.get("title", ""),
                body=row.get("body", ""),
                commit_messages=row.get("commit_messages", []),
                linked_issue=(
                    LinkedIssue(number=row.get("issue_number", 0),
                                title=row.get("issue_title", ""), body=issue_body)
                    if issue_body.strip()
                    else None
                ),
            )
        )
        labels.append(int(row["label"]))
    return contexts, labels


def split(contexts, labels, train_frac: float = 0.667, seed: int = 20260831):
    """Deterministic train/dev split. Stratified, because ambiguous is the minority."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(labels))
    y = np.array(labels)
    train_idx, dev_idx = [], []
    for cls in (0, 1):
        cls_idx = idx[y == cls]
        rng.shuffle(cls_idx)
        cut = int(len(cls_idx) * train_frac)
        train_idx.extend(cls_idx[:cut].tolist())
        dev_idx.extend(cls_idx[cut:].tolist())
    train_idx.sort()
    dev_idx.sort()
    return (
        ([contexts[i] for i in train_idx], [labels[i] for i in train_idx]),
        ([contexts[i] for i in dev_idx], [labels[i] for i in dev_idx]),
    )


def sweep_threshold(scores: list[float], labels: list[int]) -> tuple[float, dict]:
    """Pick the threshold maximising F1 on the dev split.

    F1 rather than accuracy because the classes are unbalanced, and reporting the
    ask-rate alongside it because a detector that asks on everything can score
    respectably on recall while being useless in practice.
    """
    best = (0.5, -1.0, {})
    for t in np.arange(0.05, 0.96, 0.05):
        pred = [1 if s >= t else 0 for s in scores]
        tp = sum(p and y for p, y in zip(pred, labels))
        fp = sum(p and not y for p, y in zip(pred, labels))
        fn = sum((not p) and y for p, y in zip(pred, labels))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if f1 > best[1]:
            best = (
                round(float(t), 2),
                f1,
                {
                    "precision": round(prec, 4),
                    "recall": round(rec, 4),
                    "f1": round(f1, 4),
                    "ask_rate": round(sum(pred) / len(pred), 4),
                },
            )
    return best[0], best[2]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="data/labelled_prs.jsonl")
    ap.add_argument("--out", default=None, help="where to write the .joblib")
    ap.add_argument("--sweep-thresholds", action="store_true")
    ap.add_argument("--thresholds-out", default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = settings()
    labels_path = Path(args.labels)
    if not labels_path.exists():
        log.error(
            "no labelled set at %s. Label ~300 PRs first (both team members, "
            "independently, then adjudicate) - see the codebook in study/.",
            labels_path,
        )
        return 1

    contexts, labels = load_labelled(labels_path)
    log.info("%d labelled PRs, %d ambiguous (%.0f%%)",
             len(labels), sum(labels), 100 * sum(labels) / max(len(labels), 1))
    if len(labels) < 60:
        log.warning("fewer than 60 labels; cross-validated numbers will be very noisy")

    (train_ctx, train_y), (dev_ctx, dev_y) = split(contexts, labels)
    log.info("train=%d dev=%d", len(train_y), len(dev_y))

    # Detector (b).
    features = [extract(c) for c in train_ctx]
    pipeline, reports = ClassifierDetector.fit(features, train_y)
    for r in reports:
        print(r.to_json())

    det = ClassifierDetector()
    det._pipeline = pipeline  # noqa: SLF001 - fit() returns the fitted pipeline
    out_path = Path(args.out) if args.out else cfg.classifier_path
    det.save(out_path)
    log.info("saved classifier to %s", out_path)

    if not args.sweep_thresholds:
        return 0

    # Freeze thresholds for every detector that can be scored offline. The two
    # uncertainty detectors need API calls, so their sweep is a separate,
    # deliberately explicit step - see the note below.
    thresholds = dict(DEFAULT_THRESHOLDS)
    sweeps: dict[str, dict] = {}

    heuristic = HeuristicDetector()
    h_scores = [heuristic.score(c)[0] for c in dev_ctx]
    thresholds["heuristic"], sweeps["heuristic"] = sweep_threshold(h_scores, dev_y)

    c_scores = [det.score(c)[0] for c in dev_ctx]
    thresholds["classifier"], sweeps["classifier"] = sweep_threshold(c_scores, dev_y)

    tpath = Path(args.thresholds_out) if args.thresholds_out else cfg.thresholds_path
    Thresholds(thresholds, source=str(tpath)).save(tpath)
    log.info("froze thresholds to %s: %s", tpath, thresholds)
    print(json.dumps({"thresholds": thresholds, "dev_sweep": sweeps}, indent=2))
    log.warning(
        "sampling and perturbation thresholds are still at their defaults - they "
        "need API calls to sweep. Run experiments/sweep_uncertainty.py on the same "
        "dev split before using either in a reported run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
