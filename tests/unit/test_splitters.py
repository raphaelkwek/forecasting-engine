import pandas as pd

from forecasting_engine.ingest.align import FeaturePanel
from forecasting_engine.validation.splitters import PurgedWalkForward


def _panel(n: int) -> FeaturePanel:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    frame = pd.DataFrame({"signal_a": range(n), "fwd_return_1d": range(n)}, index=idx)
    return FeaturePanel(
        frame=frame, signals=("signal_a",), targets=("fwd_return_1d",), lag_days=1
    )


def test_split_yields_expected_fold_sizes():
    panel = _panel(20)
    folds = list(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    assert len(folds[0][0]) == 10
    assert len(folds[0][1]) == 3


def test_embargo_gap_excluded_from_both_sides():
    panel = _panel(20)
    train_idx, test_idx = next(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    gap = panel.frame.index[10:12]
    assert not gap.isin(train_idx).any()
    assert not gap.isin(test_idx).any()


def test_folds_roll_forward():
    panel = _panel(20)
    folds = list(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    assert len(folds) == 2
    assert folds[1][0][0] == panel.frame.index[3]


def test_stops_when_not_enough_data_left():
    panel = _panel(15)
    folds = list(PurgedWalkForward(train=10, test=3, embargo=2).split(panel))
    assert len(folds) == 1
