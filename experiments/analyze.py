"""Statistics for Study A, and the Wilcoxon test for Study B.

The tests here are chosen for the design, not for convenience:

  * Study A outcomes are paired per instance and binary, so the primary test is
    McNemar's exact test - a t-test would be wrong twice over (unpaired, and
    parametric on a binary outcome).
  * Gap recovery, (treatment - floor) / (ceiling - floor), is the number the
    abstract should carry, with a bootstrap CI because the ratio of two
    proportions has no clean closed form at n=100.
  * Study B is a paired ordinal design at n~15, so Wilcoxon signed-rank plus
    matched-pairs rank-biserial correlation as the effect size. Reporting the
    p-value alone at that sample size says very little.

    python -m experiments.analyze --db data/clarifyreview.db
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from clarifyreview.config import settings
from clarifyreview.store import db
from clarifyreview.pipeline import (
    CONDITION_FULL_PLAIN,
    CONDITION_STRIPPED_CLARIFY,
    CONDITION_STRIPPED_PLAIN,
)

log = logging.getLogger("analyze")


@dataclass
class PairedBinaryTest:
    n_pairs: int
    a_only: int  # A correct, B wrong
    b_only: int  # B correct, A wrong
    both: int
    neither: int
    p_value: float
    a_rate: float
    b_rate: float
    difference: float
    ci_low: float
    ci_high: float


def mcnemar(a: list[int], b: list[int], seed: int = 20260831) -> PairedBinaryTest:
    """Exact McNemar plus a bootstrap CI on the difference in proportions.

    The exact binomial form is used rather than the chi-square approximation
    because the discordant count at n=100 is often small enough for the
    approximation to misbehave.
    """
    from scipy import stats

    if len(a) != len(b):
        raise ValueError("paired test needs equal-length vectors")
    a_arr, b_arr = np.array(a, dtype=int), np.array(b, dtype=int)

    b_only = int(((b_arr == 1) & (a_arr == 0)).sum())
    a_only = int(((a_arr == 1) & (b_arr == 0)).sum())
    both = int(((a_arr == 1) & (b_arr == 1)).sum())
    neither = int(((a_arr == 0) & (b_arr == 0)).sum())

    discordant = a_only + b_only
    p = (
        float(stats.binomtest(b_only, discordant, 0.5).pvalue)
        if discordant > 0
        else 1.0
    )

    rng = np.random.default_rng(seed)
    n = len(a_arr)
    diffs = np.empty(4000)
    for i in range(4000):
        idx = rng.integers(0, n, n)
        diffs[i] = b_arr[idx].mean() - a_arr[idx].mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])

    return PairedBinaryTest(
        n_pairs=n,
        a_only=a_only,
        b_only=b_only,
        both=both,
        neither=neither,
        p_value=round(p, 5),
        a_rate=round(float(a_arr.mean()), 4),
        b_rate=round(float(b_arr.mean()), 4),
        difference=round(float(b_arr.mean() - a_arr.mean()), 4),
        ci_low=round(float(lo), 4),
        ci_high=round(float(hi), 4),
    )


def gap_recovery(
    floor: list[int], treatment: list[int], ceiling: list[int], seed: int = 20260831
) -> dict:
    """How much of the ambiguity-induced gap the treatment closed.

    1.0 means the treatment reached the full-context ceiling; 0.0 means it did no
    better than the handicapped baseline. Values above 1.0 are possible and should
    be treated as suspicious - the most likely explanation is oracle leakage, not
    a system that beats full context.
    """
    f, t, c = (np.array(x, dtype=float) for x in (floor, treatment, ceiling))
    denom = c.mean() - f.mean()
    point = float((t.mean() - f.mean()) / denom) if abs(denom) > 1e-9 else float("nan")

    rng = np.random.default_rng(seed)
    n = len(f)
    samples = []
    for _ in range(4000):
        idx = rng.integers(0, n, n)
        d = c[idx].mean() - f[idx].mean()
        if abs(d) > 1e-9:
            samples.append((t[idx].mean() - f[idx].mean()) / d)
    lo, hi = (np.percentile(samples, [2.5, 97.5]) if samples else (float("nan"),) * 2)

    return {
        "floor_rate": round(float(f.mean()), 4),
        "treatment_rate": round(float(t.mean()), 4),
        "ceiling_rate": round(float(c.mean()), 4),
        "gap_recovery": round(point, 4),
        "ci_low": round(float(lo), 4),
        "ci_high": round(float(hi), 4),
    }


def wilcoxon_paired(a: list[float], b: list[float]) -> dict:
    """Study B. Signed-rank plus matched-pairs rank-biserial effect size."""
    from scipy import stats

    a_arr, b_arr = np.array(a, dtype=float), np.array(b, dtype=float)
    diff = b_arr - a_arr
    nonzero = diff[diff != 0]
    if len(nonzero) == 0:
        return {"n": len(a_arr), "p_value": 1.0, "effect_size_r": 0.0,
                "median_difference": 0.0, "note": "every pair tied"}

    res = stats.wilcoxon(a_arr, b_arr, zero_method="wilcox", alternative="two-sided")
    ranks = stats.rankdata(np.abs(nonzero))
    r_plus = float(ranks[nonzero > 0].sum())
    r_minus = float(ranks[nonzero < 0].sum())
    total = r_plus + r_minus
    return {
        "n": int(len(a_arr)),
        "n_nonzero_pairs": int(len(nonzero)),
        "statistic": float(res.statistic),
        "p_value": round(float(res.pvalue), 5),
        "effect_size_r": round((r_plus - r_minus) / total, 4) if total else 0.0,
        "median_difference": round(float(np.median(diff)), 4),
        "mean_a": round(float(a_arr.mean()), 4),
        "mean_b": round(float(b_arr.mean()), 4),
    }


def cohens_kappa(a: list[int], b: list[int]) -> float:
    """Inter-rater agreement. Reported for the labelling pass and the judge check."""
    a_arr, b_arr = np.array(a, dtype=int), np.array(b, dtype=int)
    observed = float((a_arr == b_arr).mean())
    categories = set(a_arr.tolist()) | set(b_arr.tolist())
    expected = sum(
        (a_arr == c).mean() * (b_arr == c).mean() for c in categories
    )
    return round((observed - expected) / (1 - expected), 4) if expected < 1 else 1.0


# ------------------------------------------------------------- Study A report


def _paired_outcomes(db_path: Path, metric: str, variant: str | None = None) -> dict:
    """Pull one judged metric per (pr_id, condition), keeping only complete triples.

    Dropping incomplete triples is what keeps the test genuinely paired: an
    instance that errored in one condition cannot contribute to a comparison
    involving that condition.
    """
    with db.connect(db_path) as conn:
        sql = f"""
            SELECT r.pr_id, r.condition, j.{metric} AS value, i.variant
            FROM runs r
            JOIN judgements j ON j.run_id = r.id
            JOIN instances i ON i.pr_id = r.pr_id
            WHERE r.error IS NULL
        """
        args: tuple = ()
        if variant:
            sql += " AND i.variant = ?"
            args = (variant,)
        rows = [dict(r) for r in conn.execute(sql, args)]

    by_pr: dict[str, dict[str, int]] = {}
    for row in rows:
        by_pr.setdefault(row["pr_id"], {})[row["condition"]] = int(row["value"] or 0)

    needed = {CONDITION_FULL_PLAIN, CONDITION_STRIPPED_PLAIN, CONDITION_STRIPPED_CLARIFY}
    complete = {k: v for k, v in by_pr.items() if needed <= set(v)}
    dropped = len(by_pr) - len(complete)
    if dropped:
        log.warning("dropped %d instances without all three conditions", dropped)

    keys = sorted(complete)
    return {
        "pr_ids": keys,
        "full_plain": [complete[k][CONDITION_FULL_PLAIN] for k in keys],
        "stripped_plain": [complete[k][CONDITION_STRIPPED_PLAIN] for k in keys],
        "stripped_clarify": [complete[k][CONDITION_STRIPPED_CLARIFY] for k in keys],
        "dropped": dropped,
    }


def study_a_report(db_path: Path) -> dict:
    report: dict = {}

    # Primary: intent recovery across all instances.
    data = _paired_outcomes(db_path, "intent_recovered")
    if data["pr_ids"]:
        report["intent_recovery"] = {
            "n": len(data["pr_ids"]),
            "primary_mcnemar_floor_vs_treatment": asdict(
                mcnemar(data["stripped_plain"], data["stripped_clarify"])
            ),
            "gap_recovery": gap_recovery(
                data["stripped_plain"], data["stripped_clarify"], data["full_plain"]
            ),
        }

    # Detection, mutants only - the cell where a defect actually exists.
    mut = _paired_outcomes(db_path, "defect_caught", variant="mutant")
    if mut["pr_ids"]:
        report["defect_detection_mutants"] = {
            "n": len(mut["pr_ids"]),
            "mcnemar_floor_vs_treatment": asdict(
                mcnemar(mut["stripped_plain"], mut["stripped_clarify"])
            ),
            "gap_recovery": gap_recovery(
                mut["stripped_plain"], mut["stripped_clarify"], mut["full_plain"]
            ),
        }

    # False alarms, golden only - the cell where nothing is wrong.
    gold = _paired_outcomes(db_path, "false_alarm", variant="golden")
    if gold["pr_ids"]:
        report["false_alarms_golden"] = {
            "n": len(gold["pr_ids"]),
            "mcnemar_floor_vs_treatment": asdict(
                mcnemar(gold["stripped_plain"], gold["stripped_clarify"])
            ),
            "note": "lower is better here; a negative difference is the good direction",
        }

    report["detector"] = detector_report(db_path)
    report["cost"] = cost_report(db_path)
    return report


def detector_report(db_path: Path) -> dict:
    """Ask-rate and accuracy against the constructed labels.

    Stripped instances are ambiguous by construction and full-context ones are
    clear by construction, so the detector's own accuracy is measurable on exactly
    the distribution the ablation runs on - no hand labelling needed for this part.
    """
    with db.connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT detector, condition, ask, ambiguity_score, latency_ms, cost_usd "
                "FROM runs WHERE ask IS NOT NULL AND error IS NULL"
            )
        ]
    if not rows:
        return {}

    out: dict = {}
    for detector in sorted({r["detector"] for r in rows if r["detector"]}):
        subset = [r for r in rows if r["detector"] == detector]
        # Ground truth: stripped == ambiguous.
        y_true = [1 if r["condition"] != CONDITION_FULL_PLAIN else 0 for r in subset]
        y_pred = [int(r["ask"]) for r in subset]
        tp = sum(t and p for t, p in zip(y_true, y_pred))
        fp = sum((not t) and p for t, p in zip(y_true, y_pred))
        fn = sum(t and (not p) for t, p in zip(y_true, y_pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        out[detector] = {
            "n": len(subset),
            "ask_rate": round(sum(y_pred) / len(subset), 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "mean_latency_ms": round(float(np.mean([r["latency_ms"] for r in subset])), 1),
            "mean_cost_usd": round(float(np.mean([r["cost_usd"] for r in subset])), 6),
        }
    return out


def cost_report(db_path: Path) -> dict:
    with db.connect(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT condition, cost_usd, latency_ms, input_tokens, output_tokens, "
                "cache_read_tokens FROM runs WHERE error IS NULL"
            )
        ]
    if not rows:
        return {}
    out: dict = {"total_usd": round(sum(r["cost_usd"] for r in rows), 4)}
    for cond in sorted({r["condition"] for r in rows}):
        sub = [r for r in rows if r["condition"] == cond]
        out[cond] = {
            "n": len(sub),
            "usd": round(sum(r["cost_usd"] for r in sub), 4),
            "mean_latency_ms": round(float(np.mean([r["latency_ms"] for r in sub])), 1),
            "cache_read_tokens": sum(r["cache_read_tokens"] for r in sub),
        }
    # A zero here means prompt caching is silently not working, which quadruples
    # the bill without changing any output.
    if not any(r["cache_read_tokens"] for r in rows):
        out["warning"] = "no cache reads recorded - check for a volatile prompt prefix"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default="runs/study_a_report.json")
    ap.add_argument("--study-b", help="CSV of paired ratings from the developer study")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.study_b:
        print(json.dumps(_study_b_from_csv(Path(args.study_b)), indent=2))
        return 0

    db_path = Path(args.db) if args.db else settings().clarifyreview_db
    report = study_a_report(db_path)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nwritten to {args.out}")
    return 0


def _study_b_from_csv(path: Path) -> dict:
    """Expects columns: participant, pr_id, condition, usefulness, trust, would_act."""
    import csv

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    per_participant: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        p = per_participant.setdefault(row["participant"], {"plain": [], "clarify": []})
        key = "clarify" if "clarify" in row["condition"] else "plain"
        p[key].append(float(row["usefulness"]))

    participants = sorted(k for k, v in per_participant.items() if v["plain"] and v["clarify"])
    a = [float(np.mean(per_participant[p]["plain"])) for p in participants]
    b = [float(np.mean(per_participant[p]["clarify"])) for p in participants]
    return {"usefulness": wilcoxon_paired(a, b), "participants": len(participants)}


if __name__ == "__main__":
    raise SystemExit(main())
