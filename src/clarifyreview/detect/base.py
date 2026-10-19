"""The detector contract.

Three implementations, one interface, one input. The review generator never
learns which detector ran - that is what makes the three-way comparison an
ablation rather than three different systems sharing a name.

Thresholds live in a JSON file that is frozen on the dev split and committed.
Nothing in this package is allowed to tune a threshold against the ablation set;
`Thresholds.load` is the only way one enters the pipeline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..types import Decision, DetectorName, PRContext

# Fallbacks used before a dev-split sweep has been run. Deliberately explicit so
# a run that used them is identifiable in the log.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "heuristic": 0.50,
    "classifier": 0.50,
    "sampling": 0.35,
    "perturbation": 0.35,
}


class Thresholds:
    def __init__(self, values: dict[str, float], source: str) -> None:
        self.values = values
        self.source = source

    @classmethod
    def load(cls, path: Path | None = None) -> Thresholds:
        if path is not None and path.exists():
            data = json.loads(path.read_text())
            merged = {**DEFAULT_THRESHOLDS, **data}
            return cls(merged, source=str(path))
        return cls(dict(DEFAULT_THRESHOLDS), source="defaults (dev sweep not run)")

    def for_(self, name: DetectorName) -> float:
        return self.values[name.value]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.values, indent=2, sort_keys=True))


@runtime_checkable
class Detector(Protocol):
    name: DetectorName

    def score(self, ctx: PRContext) -> tuple[float, str, dict]:
        """Return (ambiguity score in [0,1], why, extra diagnostics)."""

    def decide(self, ctx: PRContext) -> Decision: ...


class BaseDetector:
    """Shared decide() so the threshold comparison happens in exactly one place."""

    name: DetectorName

    def __init__(self, thresholds: Thresholds | None = None) -> None:
        self.thresholds = thresholds or Thresholds.load()

    def score(self, ctx: PRContext) -> tuple[float, str, dict]:
        raise NotImplementedError

    def decide(self, ctx: PRContext) -> Decision:
        started = time.monotonic()
        score, why, extra = self.score(ctx)
        threshold = self.thresholds.for_(self.name)
        return Decision(
            ask=score >= threshold,
            score=round(score, 4),
            why=why,
            detector=self.name,
            threshold=threshold,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=float(extra.pop("cost_usd", 0.0)),
            extra=extra,
        )


class NeverAskDetector(BaseDetector):
    """The single-pass control condition, expressed as a detector.

    The plain reviewer is not a separate code path - it is this detector plugged
    into the same pipeline. That is the only way to guarantee the baseline and the
    treatment differ in exactly one thing.
    """

    name = DetectorName.HEURISTIC  # logged by condition, not by detector name

    def score(self, ctx: PRContext) -> tuple[float, str, dict]:
        return 0.0, "control condition: never asks", {"control": True}

    def decide(self, ctx: PRContext) -> Decision:
        d = super().decide(ctx)
        d.ask = False
        return d
