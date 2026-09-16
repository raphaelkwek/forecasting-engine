"""FYP-44: the machine-learning Forecaster — XGBoost and LightGBM, Optuna-tuned once,
SHAP feature attribution.

**Refit cadence (FYP-129), confirmed with the user:** hyperparameter tuning is
expensive, so it happens *once* per run — on the first walk-forward fold's own train
window, via ``tune_hyperparameters()`` — not once per fold. Every fold then refits with
those *fixed* hyperparameters, the same "fix the configuration, refit per fold" shape
``DerivedPolynomial`` already uses for its degree/regularizer grid. That also gives PBO
two genuine candidates (tuned XGBoost vs. tuned LightGBM) to compare via CSCV — the
comparison FF5 structurally can't have.

**FYP-149's SHAP feature attribution** reuses ``ModelDescription``'s existing
terms/coefficients shape (feature name -> mean |SHAP value|) rather than extending the
contract — it renders through the Models page's existing "Fitted terms" table for free,
satisfying FYP-44's AC2 ("feature attribution shown alongside for interpretability")
with no new UI.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import optuna
import pandas as pd
import shap
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor

from forecasting_engine.ingest.align import FeaturePanel
from forecasting_engine.models.base import ModelDescription
from forecasting_engine.reporting.model_metrics import ModelRunResult
from forecasting_engine.validation.harness import evaluate, select_best_candidate, summarize
from forecasting_engine.validation.metrics import rmse
from forecasting_engine.validation.pbo import N_BLOCKS
from forecasting_engine.validation.splitters import PurgedWalkForward

optuna.logging.set_verbosity(optuna.logging.WARNING)

_LIBRARIES: dict[str, type] = {"xgboost": XGBRegressor, "lightgbm": LGBMRegressor}

#: Fixed, non-tuned stability settings per library — kept out of the search space
#: so a tiny synthetic dataset (a unit test) doesn't need special-casing.
_FIXED_PARAMS: dict[str, dict] = {
    "xgboost": {"verbosity": 0},
    "lightgbm": {"verbose": -1, "min_child_samples": 1, "min_data_in_leaf": 1},
}

N_TRIALS: int = 15
"""Working default (not sponsor-confirmed): Optuna trials per library, tuned once
per run — see the module docstring on refit cadence."""

_MIN_TRAINING_ROWS: int = 15
"""Same threshold FamaFrench5 uses — below this a fit is more noise than signal."""


class BoostedConfigError(ValueError):
    """A tuning/fitting request or the merged data is invalid.

    The message is written for a portfolio manager and is safe to render
    directly in the dashboard — mirrors PolynomialConfigError/FamaFrenchDataError.
    """


def _search_space(trial: optuna.Trial) -> dict:
    """Working default (not sponsor-confirmed), shared by both libraries so PBO's
    comparison reflects the algorithm, not an unevenly-sized search."""
    return {
        "n_estimators": trial.suggest_int("n_estimators", 20, 100),
        "max_depth": trial.suggest_int("max_depth", 2, 5),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
    }


def tune_hyperparameters(
    panel: FeaturePanel,
    train: pd.DatetimeIndex,
    library: str,
    n_trials: int = N_TRIALS,
    seed: int = 0,
) -> dict:
    """Optuna search, once, on an 80/20 holdout split of ``train``.

    A single holdout, not a nested walk-forward loop — keeps tuning bounded,
    per FYP-129's "refit cadence separate from the rebalance step".
    """
    if library not in _LIBRARIES:
        raise BoostedConfigError(f"library must be one of {sorted(_LIBRARIES)}, got {library!r}.")
    signals = list(panel.signals)
    frame = panel.frame.loc[train, [*signals, panel.targets[0]]].dropna()
    if len(frame) < _MIN_TRAINING_ROWS:
        raise BoostedConfigError(
            f"not enough complete training rows to tune {library} "
            f"(need at least {_MIN_TRAINING_ROWS}, got {len(frame)})."
        )
    split = min(max(1, int(len(frame) * 0.8)), len(frame) - 1)
    x, y = frame[signals], frame[panel.targets[0]]
    x_train, x_val = x.iloc[:split], x.iloc[split:]
    y_train, y_val = y.iloc[:split], y.iloc[split:]

    def objective(trial: optuna.Trial) -> float:
        params = {**_search_space(trial), **_FIXED_PARAMS[library]}
        model = _LIBRARIES[library](**params).fit(x_train, y_train)
        predicted = pd.Series(model.predict(x_val), index=x_val.index)
        return rmse(predicted, y_val)

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return {**study.best_params, **_FIXED_PARAMS[library]}


@dataclass
class BoostedForecaster:
    """One library, fixed (already-tuned) hyperparameters.

    ``fit``/``predict`` mirror ``DerivedPolynomial``'s incomplete-row masking
    for consistency across every model family, even though XGBoost/LightGBM
    handle NaN natively — a comparison exercise across models shouldn't let
    one silently impute differently from the others.
    """

    library: str
    params: Mapping[str, object]
    name: str = field(init=False)

    def __post_init__(self) -> None:
        if self.library not in _LIBRARIES:
            raise BoostedConfigError(
                f"library must be one of {sorted(_LIBRARIES)}, got {self.library!r}."
            )
        self.name = f"Boosted[{self.library}]"
        self._model = None
        self._signals: list[str] | None = None
        self._fit_x: pd.DataFrame | None = None

    def fit(self, panel: FeaturePanel, train: pd.DatetimeIndex) -> None:
        signals = list(panel.signals)
        frame = panel.frame.loc[train, [*signals, panel.targets[0]]].dropna()
        if len(frame) < _MIN_TRAINING_ROWS:
            raise BoostedConfigError(
                f"not enough complete training rows to fit {self.library} "
                f"(need at least {_MIN_TRAINING_ROWS}, got {len(frame)})."
            )
        x, y = frame[signals], frame[panel.targets[0]]
        self._model = _LIBRARIES[self.library](**self.params).fit(x, y)
        self._signals = signals
        self._fit_x = x

    def predict(self, panel: FeaturePanel, idx: pd.DatetimeIndex) -> pd.Series:
        if self._model is None or self._signals is None:
            raise RuntimeError("predict() called before fit()")
        predicted = pd.Series(np.nan, index=idx, dtype=float)
        raw = panel.frame.loc[idx, self._signals].dropna()
        if raw.empty:
            return predicted
        predicted.loc[raw.index] = self._model.predict(raw)
        return predicted

    def describe(self) -> ModelDescription:
        """FYP-149: mean |SHAP value| per feature, reusing the terms/coefficients
        contract Polynomial and FF5 already report through."""
        if self._model is None or self._signals is None or self._fit_x is None:
            raise RuntimeError("describe() called before fit()")
        explainer = shap.TreeExplainer(self._model)
        importance = np.abs(explainer.shap_values(self._fit_x)).mean(axis=0)
        return ModelDescription(
            name=self.name,
            terms=tuple(self._signals),
            coefficients=tuple(float(v) for v in importance),
        )


def run_boosted(
    panel: FeaturePanel,
    splitter: PurgedWalkForward,
    n_trials: int = N_TRIALS,
    n_blocks: int = N_BLOCKS,
) -> tuple[ModelRunResult, ModelDescription]:
    """Tunes XGBoost and LightGBM once each (on the first fold's train window),
    evaluates both as fixed-hyperparameter candidates through the shared harness,
    compares via PBO, and reports the one with the best mean OOS Rank IC — the
    same shape ``run_derived_polynomial`` uses, XGBoost/LightGBM standing in for
    a degree/regularizer grid.
    """
    first_fold = next(iter(splitter.split(panel)), None)
    if first_fold is None:
        raise BoostedConfigError(
            "the walk-forward split produced no folds — the committed dataset is too "
            "short for the chosen train/test/embargo window."
        )
    first_train, _first_test = first_fold
    tuned = {
        library: tune_hyperparameters(panel, first_train, library, n_trials=n_trials)
        for library in _LIBRARIES
    }
    per_candidate = {
        library: evaluate(
            lambda library=library: BoostedForecaster(library, tuned[library]), panel, splitter
        )
        for library in _LIBRARIES
    }
    best_name, pbo_value = select_best_candidate(per_candidate, n_blocks=n_blocks)
    return summarize(per_candidate[best_name], pbo=pbo_value)
