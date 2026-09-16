import pandas as pd

from forecasting_engine.ingest.align import FeaturePanel
from forecasting_engine.models.base import ModelDescription
from forecasting_engine.validation import metrics
from forecasting_engine.validation.harness import evaluate, select_best_candidate, summarize
from forecasting_engine.validation.splitters import PurgedWalkForward


def _panel(n: int = 20) -> FeaturePanel:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame({"signal_a": range(n), "fwd_return_1d": range(n)}, index=idx)
    return FeaturePanel(frame=frame, signals=("signal_a",), targets=("fwd_return_1d",), lag_days=1)


def _panel_with_varying_folds(n: int = 20) -> FeaturePanel:
    """Predicted (signal_a) and realised (fwd_return_1d) differ, and differ
    *differently* fold to fold, so a per-fold mean is distinguishable from
    just reading one fold's value — degenerate perfect-prediction data
    (predicted == realised everywhere) wouldn't catch a bug like that."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    signal = list(range(n))
    target = [v + (1 if i % 2 == 0 else -3) for i, v in enumerate(signal)]
    frame = pd.DataFrame({"signal_a": signal, "fwd_return_1d": target}, index=idx)
    return FeaturePanel(frame=frame, signals=("signal_a",), targets=("fwd_return_1d",), lag_days=1)


class _EchoForecaster:
    """A deterministic stub: predicts the signal column unchanged, so fold
    results are trivial to check against the panel by hand."""

    name = "Echo"

    def __init__(self) -> None:
        self.fit_calls: list[pd.DatetimeIndex] = []

    def fit(self, panel: FeaturePanel, train: pd.DatetimeIndex) -> None:
        self.fit_calls.append(train)

    def predict(self, panel: FeaturePanel, idx: pd.DatetimeIndex) -> pd.Series:
        return panel.frame.loc[idx, "signal_a"].astype(float)

    def describe(self) -> ModelDescription:
        return ModelDescription(name=self.name, terms=("signal_a",), coefficients=(1.0,))


class _InverseForecaster:
    """Predicts the *negative* of the signal — deliberately anti-correlated
    with the target, so its rank IC is a real, clearly worse number (not NaN,
    which would make max()'s comparison order-dependent and unreliable)."""

    name = "Inverse"

    def fit(self, panel: FeaturePanel, train: pd.DatetimeIndex) -> None:
        pass

    def predict(self, panel: FeaturePanel, idx: pd.DatetimeIndex) -> pd.Series:
        return -panel.frame.loc[idx, "signal_a"].astype(float)

    def describe(self) -> ModelDescription:
        return ModelDescription(name=self.name, terms=("signal_a",), coefficients=(-1.0,))


def test_evaluate_produces_one_fold_result_per_split():
    panel = _panel()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    results = evaluate(_EchoForecaster, panel, splitter)
    assert len(results) == len(list(splitter.split(panel)))


def test_fold_predicted_and_realised_match_the_panel_slice():
    panel = _panel()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    results = evaluate(_EchoForecaster, panel, splitter)

    fold = results[0]
    assert list(fold.predicted) == list(panel.frame.loc[fold.test, "signal_a"])
    assert list(fold.realised) == list(panel.frame.loc[fold.test, "fwd_return_1d"])
    assert list(fold.predicted_train) == list(panel.frame.loc[fold.train, "signal_a"])
    assert list(fold.realised_train) == list(panel.frame.loc[fold.train, "fwd_return_1d"])


def test_each_fold_fits_a_fresh_instance_on_only_its_own_train_window():
    panel = _panel()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    seen_train_windows = []

    class _RecordingForecaster(_EchoForecaster):
        def fit(self, panel: FeaturePanel, train: pd.DatetimeIndex) -> None:
            super().fit(panel, train)
            seen_train_windows.append(train)

    results = evaluate(_RecordingForecaster, panel, splitter)
    # one fit() call per fold, each on exactly that fold's own train window —
    # a shared/reused instance would instead show every fold's window piling
    # up against the first fold's forecaster.
    assert seen_train_windows == [f.train for f in results]


def test_description_travels_with_its_own_fold():
    panel = _panel()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    results = evaluate(_EchoForecaster, panel, splitter)
    for fold in results:
        assert fold.description == ModelDescription(
            name="Echo", terms=("signal_a",), coefficients=(1.0,)
        )


def test_summarize_averages_ic_rank_ic_rmse_across_folds():
    panel = _panel_with_varying_folds()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    folds = evaluate(_EchoForecaster, panel, splitter)
    assert len(folds) > 1, "fixture must produce more than one fold to test averaging"

    result, _description = summarize(folds, pbo=None)

    expected_ic = sum(metrics.ic(f.predicted, f.realised) for f in folds) / len(folds)
    expected_rank_ic = sum(metrics.rank_ic(f.predicted, f.realised) for f in folds) / len(folds)
    expected_rmse = sum(metrics.rmse(f.predicted, f.realised) for f in folds) / len(folds)
    assert result.ic == expected_ic
    assert result.oos_rank_ic == expected_rank_ic
    assert result.rmse == expected_rmse


def test_summarize_passes_pbo_through_unchanged():
    panel = _panel()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    folds = evaluate(_EchoForecaster, panel, splitter)

    assert summarize(folds, pbo=0.42)[0].pbo == 0.42
    assert summarize(folds, pbo=None)[0].pbo is None


def test_summarize_returns_the_most_recent_folds_description():
    panel = _panel()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    folds = evaluate(_EchoForecaster, panel, splitter)

    _result, description = summarize(folds, pbo=None)

    assert description == folds[-1].description


def test_summarize_computes_crash_diagnostics():
    panel = _panel_with_varying_folds()
    splitter = PurgedWalkForward(train=10, test=3, embargo=2)
    folds = evaluate(_EchoForecaster, panel, splitter)

    result, _description = summarize(folds, pbo=None)

    assert result.crash.n_true_tail_days >= 0


def test_select_best_candidate_picks_the_higher_rank_ic_candidate():
    # A bigger panel than the summarize()/evaluate() tests above — PBO's CSCV
    # splits the combined strategy-return series into n_blocks pieces, so it
    # needs enough total rows across folds to be meaningful.
    panel = _panel_with_varying_folds(n=80)
    splitter = PurgedWalkForward(train=30, test=8, embargo=2)
    strong = evaluate(_EchoForecaster, panel, splitter)
    weak = evaluate(_InverseForecaster, panel, splitter)

    best_name, pbo_value = select_best_candidate({"strong": strong, "weak": weak}, n_blocks=4)

    assert best_name == "strong"
    assert 0.0 <= pbo_value <= 1.0
