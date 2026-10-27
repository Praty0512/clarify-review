"""Stage 2: the branch point. Three designs, one interface."""

from __future__ import annotations

from pathlib import Path

from ..config import settings
from ..types import DetectorName
from .base import BaseDetector, Detector, NeverAskDetector, Thresholds
from .classifier import ClassifierDetector
from .heuristic import HeuristicDetector
from .uncertainty import PerturbationUncertaintyDetector, SamplingUncertaintyDetector

__all__ = [
    "BaseDetector",
    "ClassifierDetector",
    "Detector",
    "HeuristicDetector",
    "NeverAskDetector",
    "PerturbationUncertaintyDetector",
    "SamplingUncertaintyDetector",
    "Thresholds",
    "build",
    "live_thresholds",
]


def live_thresholds() -> Thresholds:
    """Thresholds for the live tool (CLI and bot).

    Defaults unless CLARIFYREVIEW_THRESHOLDS_PATH names an existing file. The
    study keeps using `settings().thresholds_path` through `build()`; nothing here
    changes that.
    """
    path = settings().clarifyreview_thresholds_path
    if path is not None:
        if not Path(path).exists():
            raise FileNotFoundError(f"CLARIFYREVIEW_THRESHOLDS_PATH does not exist: {path}")
        return Thresholds.load(Path(path))
    return Thresholds.load(None)


def build(name: str | DetectorName, **kwargs) -> BaseDetector:
    """Construct a detector by name. The one place the mapping lives."""
    key = DetectorName(name) if not isinstance(name, DetectorName) else name
    cfg = settings()
    thresholds = kwargs.pop("thresholds", None) or Thresholds.load(cfg.thresholds_path)

    if key is DetectorName.HEURISTIC:
        return HeuristicDetector(thresholds=thresholds, **kwargs)
    if key is DetectorName.CLASSIFIER:
        return ClassifierDetector(
            model_path=kwargs.pop("model_path", cfg.classifier_path),
            thresholds=thresholds,
            **kwargs,
        )
    if key is DetectorName.SAMPLING:
        return SamplingUncertaintyDetector(
            n=kwargs.pop("n", cfg.uncertainty_samples), thresholds=thresholds, **kwargs
        )
    if key is DetectorName.PERTURBATION:
        return PerturbationUncertaintyDetector(
            n=kwargs.pop("n", cfg.uncertainty_samples), thresholds=thresholds, **kwargs
        )
    raise ValueError(f"unknown detector: {name}")
