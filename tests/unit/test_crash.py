import pandas as pd
import pytest

from forecasting_engine.validation.crash import (
    crash_diagnostics,
    crash_diagnostics_over_folds,
    label_crash_days,
)


def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx)


def test_label_crash_days_thresholds_come_from_the_training_window_only():
    # Train predicted = 1..10; 5th percentile (linear interpolation) = 1.45.
    # Train realised has mean 0, sample std ~0.014907; threshold = -2*std ~ -0.029814.
    predicted = _series(list(range(1, 11)) + [1.0, 1.5, 2.0])
    realised = _series(
        [-0.02, -0.01, 0, 0.01, 0.02, -0.02, -0.01, 0, 0.01, 0.02] + [-0.05, -0.02, 0.01]
    )
    train_idx = predicted.index[:10]
    test_idx = predicted.index[10:]

    labels = label_crash_days(predicted, realised, train_idx, test_idx)

    assert list(labels["flagged"]) == [True, False, False]
    assert list(labels["true_tail"]) == [True, False, False]


def test_crash_diagnostics_recall_precision_f1():
    flagged = pd.Series([True, True, False, False, True])
    true_tail = pd.Series([True, False, False, True, False])

    result = crash_diagnostics(flagged, true_tail)

    assert result.recall == pytest.approx(0.5)
    assert result.precision == pytest.approx(1 / 3)
    assert result.f1 == pytest.approx(0.4)
    assert result.n_true_tail_days == 2


def test_crash_diagnostics_recall_is_nan_with_no_true_tail_days():
    flagged = pd.Series([True, False])
    true_tail = pd.Series([False, False])

    result = crash_diagnostics(flagged, true_tail)

    assert result.recall != result.recall  # NaN
    assert result.n_true_tail_days == 0


def test_crash_diagnostics_precision_is_nan_with_no_flagged_days():
    flagged = pd.Series([False, False])
    true_tail = pd.Series([True, False])

    result = crash_diagnostics(flagged, true_tail)

    assert result.precision != result.precision  # NaN


def test_crash_diagnostics_over_folds_concatenates_every_fold_before_scoring():
    predicted = _series([5, 5, 5, 5, 1, 5, 5, 5, 5, 1])
    realised = _series([0, 0, 0, 0, -1, 0, 0, 0, 0, -1])
    folds = [
        (predicted.index[:4], predicted.index[4:5]),
        (predicted.index[5:9], predicted.index[9:10]),
    ]

    result = crash_diagnostics_over_folds(predicted, realised, folds)

    assert result.recall == 1.0
    assert result.precision == 1.0
    assert result.n_true_tail_days == 2
