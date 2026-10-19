"""Detector (b): a small trained classifier over the same features.

Two models are fitted and compared: logistic regression and gradient-boosted
trees. Prefer logistic regression when it is within one standard error of the
tree, because you can print its coefficients in the paper and a rule-shaped
explanation is worth a paragraph of discussion that a tree ensemble is not.

Training data comes from the hand-labelled set (see experiments/); nothing here
ever sees the ablation split.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..types import DetectorName, PRContext
from .base import BaseDetector
from .features import FEATURE_NAMES, explain, extract, to_array


@dataclass
class TrainReport:
    model: str
    cv_mean_f1: float
    cv_std_f1: float
    cv_mean_auc: float
    n_train: int
    n_positive: int
    coefficients: dict[str, float] | None = None

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


class ClassifierDetector(BaseDetector):
    name = DetectorName.CLASSIFIER

    def __init__(self, model_path: Path | None = None, thresholds=None) -> None:
        super().__init__(thresholds)
        self._pipeline = None
        self._path = model_path
        if model_path is not None and model_path.exists():
            self.load(model_path)

    # ------------------------------------------------------------- inference

    def score(self, ctx: PRContext) -> tuple[float, str, dict]:
        if self._pipeline is None:
            raise RuntimeError(
                "ClassifierDetector has no fitted model. Run "
                "`experiments/train_classifier.py` first, or point "
                "settings().classifier_path at a trained .joblib."
            )
        f = extract(ctx)
        x = np.array([to_array(f)], dtype=float)
        proba = float(self._pipeline.predict_proba(x)[0, 1])
        why = f"classifier p(ambiguous)={proba:.2f} — {explain(f)}"
        return proba, why, {"features": f}

    # -------------------------------------------------------------- training

    @staticmethod
    def fit(
        X: list[dict[str, float]],
        y: list[int],
        *,
        seed: int = 20260831,
    ) -> tuple[object, list[TrainReport]]:
        """Fit both candidates, cross-validate, return the chosen pipeline.

        Stratified 5-fold because the positive class (ambiguous) is the minority
        and an unstratified split at n=200 can produce a fold with almost none.
        """
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_validate
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        Xa = np.array([to_array(f) for f in X], dtype=float)
        ya = np.array(y, dtype=int)
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)

        candidates = {
            "logistic_regression": Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "clf",
                        LogisticRegression(
                            max_iter=2000, class_weight="balanced", random_state=seed
                        ),
                    ),
                ]
            ),
            "gradient_boosting": Pipeline(
                [
                    (
                        "clf",
                        GradientBoostingClassifier(
                            n_estimators=150, max_depth=3, random_state=seed
                        ),
                    )
                ]
            ),
        }

        reports: list[TrainReport] = []
        scored: dict[str, tuple[float, float]] = {}
        for label, pipe in candidates.items():
            res = cross_validate(pipe, Xa, ya, cv=cv, scoring=("f1", "roc_auc"))
            mean_f1 = float(res["test_f1"].mean())
            std_f1 = float(res["test_f1"].std())
            scored[label] = (mean_f1, std_f1)
            reports.append(
                TrainReport(
                    model=label,
                    cv_mean_f1=round(mean_f1, 4),
                    cv_std_f1=round(std_f1, 4),
                    cv_mean_auc=round(float(res["test_roc_auc"].mean()), 4),
                    n_train=len(ya),
                    n_positive=int(ya.sum()),
                )
            )

        # Prefer the interpretable model unless the tree beats it by more than
        # one standard error - at this sample size, a smaller gap is noise.
        lr_f1, lr_std = scored["logistic_regression"]
        gb_f1, _ = scored["gradient_boosting"]
        chosen = (
            "gradient_boosting" if gb_f1 > lr_f1 + lr_std else "logistic_regression"
        )

        pipeline = candidates[chosen]
        pipeline.fit(Xa, ya)

        if chosen == "logistic_regression":
            coefs = pipeline.named_steps["clf"].coef_[0]
            report = next(r for r in reports if r.model == chosen)
            report.coefficients = {
                name: round(float(c), 4) for name, c in zip(FEATURE_NAMES, coefs)
            }

        for r in reports:
            r.model = f"{r.model}{' (chosen)' if r.model == chosen else ''}"
        return pipeline, reports

    # ------------------------------------------------------------ persistence

    def save(self, path: Path) -> None:
        import joblib

        path.parent.mkdir(parents=True, exist_ok=True)
        # The feature order is part of the artefact: a pickle that outlives a
        # change to FEATURE_NAMES would silently score garbage.
        joblib.dump(
            {"pipeline": self._pipeline, "feature_names": list(FEATURE_NAMES)}, path
        )

    def load(self, path: Path) -> None:
        import joblib

        blob = joblib.load(path)
        if tuple(blob["feature_names"]) != FEATURE_NAMES:
            raise ValueError(
                f"{path} was trained on a different feature set. Retrain before use."
            )
        self._pipeline = blob["pipeline"]
