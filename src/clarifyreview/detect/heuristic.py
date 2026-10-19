"""Detector (c): hand-set rules over the feature vector.

Built first, deliberately. It is the baseline (a) and (b) have to beat to justify
their cost, and having it running end to end unblocks Stages 3 and 4 on day one.

The weights below are a stated prior, not a fit. They encode the archetype the
whole project is about: a deletion-heavy diff, with no stated reason, that removes
something protective, and brings no test with it. Anything (b) or (a) buys over
this is the actual contribution.
"""

from __future__ import annotations

from ..types import DetectorName, PRContext
from .base import BaseDetector
from .features import explain, extract

# Additive evidence weights. Sum is squashed into [0,1] by dividing by the total
# available evidence, which keeps the score interpretable as "what fraction of the
# ambiguity signals fired" rather than an uncalibrated number.
WEIGHTS: dict[str, float] = {
    "no_linked_issue": 0.30,
    "generic_commit_msg": 0.20,
    "removes_guard": 0.25,
    "no_test_alongside": 0.10,
    "public_api_touched": 0.10,
    "signature_changed": 0.10,
    "sensitive_code": 0.15,
    "deletion_heavy": 0.10,
    "sprawling": 0.05,
}
_TOTAL = sum(WEIGHTS.values())


class HeuristicDetector(BaseDetector):
    name = DetectorName.HEURISTIC

    def score(self, ctx: PRContext) -> tuple[float, str, dict]:
        f = extract(ctx)
        fired: dict[str, float] = {}

        def fire(rule: str, condition: bool) -> None:
            if condition:
                fired[rule] = WEIGHTS[rule]

        fire("no_linked_issue", f["has_linked_issue"] == 0.0)
        fire("generic_commit_msg", f["commit_msg_generic"] == 1.0)
        fire("removes_guard", f["removes_guard"] == 1.0)
        fire("no_test_alongside", f["test_file_changed"] == 0.0)
        fire("public_api_touched", f["touches_public_symbol"] == 1.0)
        fire("signature_changed", f["signature_changed"] == 1.0)
        fire("sensitive_code", f["touches_sensitive_symbol"] == 1.0)
        fire("deletion_heavy", f["deletion_ratio"] > 0.6)
        fire("sprawling", f["files_touched"] > 8)

        raw = sum(fired.values())

        # A PR that states why it exists is rarely ambiguous however risky it
        # looks, so a substantive issue body damps everything else. Without this
        # the detector asks constantly on large, well-documented refactors, which
        # is exactly the nuisance behaviour the project is trying to avoid.
        if f["has_linked_issue"] == 1.0 and f["issue_body_len"] > 200:
            raw *= 0.45
            fired["damped_by_substantive_issue"] = -0.0

        score = min(raw / _TOTAL, 1.0)
        why = f"rules fired: {', '.join(sorted(fired)) or 'none'} — {explain(f)}"
        return score, why, {"fired": fired, "features": f}
