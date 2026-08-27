import pandas as pd
import pytest

from forecasting_engine.ingest.panel import FeaturePanel
from forecasting_engine.ingest.provenance import Provenance, SourceFile

PROV = Provenance(
    sources=(SourceFile(path="x.csv", sha256="a" * 64, rows=3),),
    built_at="2026-07-29T00:00:00+00:00",
    horizon_days=5,
)


def make_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"vix": [1.0, 2.0, 3.0], "spx_fwd_5d": [0.01, 0.02, 0.03]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
    )


def make_panel(**overrides) -> FeaturePanel:
    kwargs = {
        "frame": make_frame(),
        "signals": ("vix",),
        "targets": ("spx_fwd_5d",),
        "lag_days": 1,
        "provenance": PROV,
    }
    kwargs.update(overrides)
    return FeaturePanel(**kwargs)


def test_valid_panel_constructs():
    assert make_panel().lag_days == 1


def test_zero_lag_is_rejected():
    with pytest.raises(ValueError, match="look-ahead"):
        make_panel(lag_days=0)


def test_negative_lag_is_rejected():
    with pytest.raises(ValueError, match="look-ahead"):
        make_panel(lag_days=-1)


def test_a_column_cannot_be_both_signal_and_target():
    with pytest.raises(ValueError, match="both a signal and a target"):
        make_panel(signals=("vix", "spx_fwd_5d"))


def test_unknown_column_is_rejected():
    with pytest.raises(ValueError, match="not present"):
        make_panel(signals=("vix", "does_not_exist"))


def test_unsorted_index_is_rejected():
    frame = make_frame().iloc[::-1]
    with pytest.raises(ValueError, match="ascending"):
        make_panel(frame=frame)


def test_non_datetime_index_is_rejected():
    frame = make_frame().reset_index(drop=True)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        make_panel(frame=frame)


def test_panel_is_immutable():
    panel = make_panel()
    with pytest.raises(Exception):
        panel.lag_days = 2


def test_matrix_returns_signals_and_one_target():
    panel = make_panel()
    features, target = panel.matrix(panel.frame.index, "spx_fwd_5d")
    assert list(features.columns) == ["vix"]
    assert len(target) == 3
    assert target.name == "spx_fwd_5d"


def test_matrix_defaults_to_the_first_target():
    panel = make_panel()
    _, target = panel.matrix(panel.frame.index)
    assert target.name == "spx_fwd_5d"


def test_matrix_rejects_an_unknown_target():
    panel = make_panel()
    with pytest.raises(KeyError, match="nope"):
        panel.matrix(panel.frame.index, "nope")


def test_matrix_never_leaks_a_target_into_the_features():
    panel = make_panel()
    features, _ = panel.matrix(panel.frame.index)
    assert not set(features.columns) & set(panel.targets)
