"""Guards against look-ahead bias creeping back in.

Success Criterion 1 of the project proposal requires look-ahead bias to be
structurally prevented. These tests are that structure.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from forecasting_engine.ingest.align import align_and_lag
from forecasting_engine.ingest.loader import RawFrame
from forecasting_engine.ingest.provenance import SourceFile

SRC = Path(__file__).resolve().parents[2] / "src"
BANNED = ("bfill(", "backfill(", "fillna(method=", "interpolate(")

SOURCE = SourceFile(path="synthetic.csv", sha256="c" * 64, rows=40)


def canary_raw(n: int = 40) -> RawFrame:
    """A frame whose VIX column is a perfect copy of a *future* price.

    If any code path fails to lag, the canary shows up as a signal that matches
    a value it could not possibly have known.
    """
    index = pd.bdate_range("2024-01-01", periods=n)
    closes = np.linspace(100.0, 200.0, n)
    frame = pd.DataFrame(
        {
            "spx_close": closes,
            "agg_close": np.linspace(50.0, 60.0, n),
            "vix": closes,  # the canary
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


def test_source_contains_no_backward_filling():
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in BANNED:
            if token in text:
                offenders.append(f"{path.relative_to(SRC)} uses {token}")
    assert not offenders, (
        "Backward-fill and interpolation move future values into the past, which is "
        "exactly the look-ahead bias this project is required to prevent. "
        "Use ffill with a cap instead. Offenders: " + "; ".join(offenders)
    )


def test_only_align_and_lag_constructs_a_panel():
    """FeaturePanel(...) should appear in panel.py, align.py and tests — nowhere else."""
    offenders = [
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if "FeaturePanel(" in path.read_text(encoding="utf-8")
        and path.name not in {"panel.py", "align.py"}
    ]
    assert not offenders, (
        "FeaturePanel must only be constructed by align_and_lag so the lag is applied "
        f"exactly once. Offenders: {offenders}"
    )


def test_lagged_signal_never_equals_the_same_day_raw_value():
    raw = canary_raw()
    panel = align_and_lag(raw, horizon_days=5, lag_days=1)
    same_day = raw.frame.loc[panel.frame.index, "vix"]
    assert not np.allclose(panel.frame["vix"].to_numpy(), same_day.to_numpy()), (
        "the panel's signal column matches the same day's raw value, so no lag was applied"
    )


def test_lagged_signal_equals_the_previous_raw_value_exactly():
    raw = canary_raw()
    panel = align_and_lag(raw, horizon_days=5, lag_days=1)
    expected = raw.frame["vix"].shift(1).loc[panel.frame.index]
    np.testing.assert_allclose(panel.frame["vix"].to_numpy(), expected.to_numpy())


def test_extra_lag_changes_the_data():
    """The lag-shift audit from Risk 2, as an automated check."""
    raw = canary_raw()
    one = align_and_lag(raw, horizon_days=5, lag_days=1)
    two = align_and_lag(raw, horizon_days=5, lag_days=2)
    shared = one.frame.index.intersection(two.frame.index)
    assert not np.allclose(
        one.frame.loc[shared, "vix"].to_numpy(), two.frame.loc[shared, "vix"].to_numpy()
    ), "changing lag_days had no effect, so the lag is not being applied"


def test_no_target_is_reachable_as_a_signal():
    panel = align_and_lag(canary_raw(), horizon_days=5, lag_days=1)
    features, _ = panel.matrix(panel.frame.index)
    assert not set(features.columns) & set(panel.targets)


def test_final_rows_without_a_realised_return_are_absent():
    raw = canary_raw(40)
    panel = align_and_lag(raw, horizon_days=5, lag_days=1)
    assert panel.frame.index.max() <= raw.frame.index[-6], (
        "a row survived whose forward return had not yet happened"
    )
