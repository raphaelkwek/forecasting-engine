"""FeaturePanel: the lag-safe dataset screening and modelling consume.

Built by align_and_lag() from whatever quality.build.apply_decisions() (or,
today, the Bloomberg merge) produced. No screening or fitting function
accepts a bare DataFrame, so there is no type-legal way to run on unlagged
data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FeaturePanel:
    """A dataset where every signal is dated to when it was observable."""

    frame: pd.DataFrame
    signals: tuple[str, ...]
    targets: tuple[str, ...]
    lag_days: int

    def __post_init__(self) -> None:
        if self.lag_days < 1:
            raise ValueError(f"lag_days must be >= 1, got {self.lag_days}")
        overlap = set(self.signals) & set(self.targets)
        if overlap:
            raise ValueError(f"target column(s) {overlap} also listed as signals")


def align_and_lag(
    frame: pd.DataFrame,
    signal_cols: Sequence[str],
    price_col: str,
    horizon: int = 5,
    lag_days: int = 1,
) -> FeaturePanel:
    """Lag every signal, derive a forward-return target, freeze both into a FeaturePanel.

    ``price_col`` is a price/level column already present in ``frame``; the
    target is the ``horizon``-day forward return computed from it. Every
    signal in ``signal_cols`` is shifted forward ``lag_days`` so its value on
    a given date is what was actually observable on that date.
    """
    target_col = f"fwd_return_{horizon}d"
    out = frame.copy()
    out[target_col] = out[price_col].pct_change(horizon).shift(-horizon)
    out[list(signal_cols)] = out[list(signal_cols)].shift(lag_days)
    return FeaturePanel(
        frame=out,
        signals=tuple(signal_cols),
        targets=(target_col,),
        lag_days=lag_days,
    )
