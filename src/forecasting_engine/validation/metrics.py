"""Prediction-quality metrics shared across screening and validation."""

from __future__ import annotations

import pandas as pd


def rank_ic(signal: pd.Series, target: pd.Series) -> float:
    """Spearman rank correlation between a signal and its target.

    Pairs with a NaN in either series are dropped before scoring. Returns NaN
    if fewer than two valid pairs remain.

    Computed as the Pearson correlation of ranks rather than
    ``Series.corr(method="spearman")`` directly: on the installed pandas
    version that path imports scipy internally, which isn't a project
    dependency. Ranking first and correlating is the textbook definition of
    Spearman's rho and needs no new dependency.
    """
    paired = pd.concat([signal, target], axis=1).dropna()
    if len(paired) < 2:
        return float("nan")
    ic = paired.iloc[:, 0].rank().corr(paired.iloc[:, 1].rank())
    # Pearson-of-ranks lands a hair off +/-1.0 on clean monotonic data due to
    # float rounding; correlation is bounded to [-1, 1] so 15 decimal places
    # is far more precision than the statistic carries anyway.
    return round(ic, 15)
