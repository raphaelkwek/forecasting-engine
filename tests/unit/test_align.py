import pandas as pd
import pytest

from forecasting_engine.ingest.align import FeaturePanel, align_and_lag


def _frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame(
        {"signal_a": range(10), "price": [100 + i for i in range(10)]},
        index=idx,
    )


def test_align_and_lag_shifts_signals_forward():
    panel = align_and_lag(_frame(), ["signal_a"], "price", horizon=2, lag_days=1)
    assert panel.frame["signal_a"].iloc[2] == 1
    assert pd.isna(panel.frame["signal_a"].iloc[0])


def test_align_and_lag_computes_forward_return_target():
    panel = align_and_lag(_frame(), ["signal_a"], "price", horizon=2, lag_days=1)
    assert panel.targets == ("fwd_return_2d",)
    expected = (102 / 100) - 1
    assert panel.frame["fwd_return_2d"].iloc[0] == pytest.approx(expected)
    assert pd.isna(panel.frame["fwd_return_2d"].iloc[-1])


def test_lag_days_must_be_positive():
    with pytest.raises(ValueError):
        align_and_lag(_frame(), ["signal_a"], "price", lag_days=0)


def test_target_cannot_also_be_a_signal():
    with pytest.raises(ValueError):
        FeaturePanel(
            frame=_frame(),
            signals=("fwd_return_2d",),
            targets=("fwd_return_2d",),
            lag_days=1,
        )
