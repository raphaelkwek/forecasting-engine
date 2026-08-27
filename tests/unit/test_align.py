import numpy as np
import pandas as pd
import pytest

from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import RawFrame
from forecasting_engine.ingest.provenance import SourceFile

SOURCE = SourceFile(path="synthetic.csv", sha256="b" * 64, rows=20)


def ramp_raw(n: int = 20) -> RawFrame:
    """Closes 100..119 and VIX 10..29 on consecutive business days."""
    index = pd.bdate_range("2024-01-01", periods=n)
    frame = pd.DataFrame(
        {
            "spx_close": np.arange(100.0, 100.0 + n),
            "agg_close": np.arange(50.0, 50.0 + n),
            "vix": np.arange(10.0, 10.0 + n),
            "credit_spread_hy": np.full(n, 3.5),
            "credit_spread_ig": np.full(n, 1.2),
            "fx_impl_vol": np.full(n, 8.0),
            "breakeven_10y": np.full(n, 2.2),
            "term_spread": np.full(n, 1.0),
        },
        index=index,
    )
    frame.index.name = "date"
    return RawFrame(frame=frame, source=SOURCE, issues=())


def test_signal_carries_the_previous_days_value():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    # Row index 5 of the raw frame is date d5; after a one-day lag its VIX is d4's value, 14.0
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    assert panel.frame.loc[d5, "vix"] == pytest.approx(14.0)


def test_target_is_the_forward_return_over_the_horizon():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    # close[d10] / close[d5] - 1 == 110 / 105 - 1
    assert panel.frame.loc[d5, "spx_fwd_5d"] == pytest.approx(110.0 / 105.0 - 1.0)


def test_two_day_lag_shifts_one_day_further():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=2)
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    assert panel.frame.loc[d5, "vix"] == pytest.approx(13.0)


def test_rows_without_a_full_target_window_are_dropped():
    panel = align_and_lag(ramp_raw(20), horizon_days=5, lag_days=1)
    # 20 rows, minus 1 leading row with no lagged signal, minus 5 trailing rows
    # with no realised forward return.
    assert len(panel) == 14


def test_target_names_encode_the_horizon():
    panel = align_and_lag(ramp_raw(), horizon_days=3, lag_days=1)
    assert panel.targets == ("spx_fwd_3d", "agg_fwd_3d")


def test_signals_exclude_price_columns():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    assert "spx_close" not in panel.signals
    assert "vix" in panel.signals


def test_zero_lag_is_refused():
    with pytest.raises(ValueError, match="look-ahead"):
        align_and_lag(ramp_raw(), lag_days=0)


def test_zero_horizon_is_refused():
    with pytest.raises(ValueError, match="horizon_days"):
        align_and_lag(ramp_raw(), horizon_days=0)


def test_provenance_records_the_source_and_horizon():
    panel = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    assert panel.provenance.sources == (SOURCE,)
    assert panel.provenance.horizon_days == 5


def test_gaps_are_forward_filled_up_to_the_limit():
    raw = ramp_raw()
    frame = raw.frame.copy()
    frame.iloc[3:5, frame.columns.get_loc("vix")] = np.nan
    filled = align_and_lag(
        RawFrame(frame=frame, source=SOURCE, issues=()), horizon_days=5, lag_days=1
    )
    d5 = pd.bdate_range("2024-01-01", periods=20)[5]
    # d3 and d4 are blank, so they carry d2's value of 12.0; row d5 sees d4.
    assert filled.frame.loc[d5, "vix"] == pytest.approx(12.0)


def test_gaps_longer_than_the_limit_drop_the_row():
    raw = ramp_raw()
    frame = raw.frame.copy()
    frame.iloc[3:12, frame.columns.get_loc("vix")] = np.nan
    panel = align_and_lag(
        RawFrame(frame=frame, source=SOURCE, issues=()),
        horizon_days=5,
        lag_days=1,
        ffill_limit=2,
    )
    dates = pd.bdate_range("2024-01-01", periods=20)
    assert dates[8] not in panel.frame.index


def test_result_is_deterministic():
    first = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    second = align_and_lag(ramp_raw(), horizon_days=5, lag_days=1)
    pd.testing.assert_frame_equal(first.frame, second.frame)
