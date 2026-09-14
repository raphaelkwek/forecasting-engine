"""Crash-day labelling and recall/precision/F1, per Validation Metrics v2:
a day is flagged when its predicted return falls below the 5th percentile of
the training-window forecast distribution; a day is a true tail event when
its realised return falls below -2 SD of the training-window return
distribution. Thresholds always come from the training window, applied to
the test window — never the other way round.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

FLAG_PERCENTILE: float = 0.05
TAIL_STD_MULTIPLE: float = 2.0


@dataclass(frozen=True)
class CrashDiagnostics:
    """A diagnostic, not a gate — reported with ``n_true_tail_days`` so a
    reader can judge how much signal a handful of rare events can carry."""

    recall: float
    precision: float
    f1: float
    n_true_tail_days: int


def label_crash_days(
    predicted: pd.Series,
    realised: pd.Series,
    train_idx: pd.Index,
    test_idx: pd.Index,
) -> pd.DataFrame:
    """Label each date in ``test_idx`` as flagged and/or a true tail event,
    using thresholds computed only from ``train_idx``."""
    predicted_threshold = predicted.loc[train_idx].quantile(FLAG_PERCENTILE)
    train_realised = realised.loc[train_idx]
    tail_threshold = train_realised.mean() - TAIL_STD_MULTIPLE * train_realised.std(ddof=1)

    return pd.DataFrame(
        {
            "flagged": predicted.loc[test_idx] < predicted_threshold,
            "true_tail": realised.loc[test_idx] < tail_threshold,
        },
        index=test_idx,
    )


def crash_diagnostics(flagged: pd.Series, true_tail: pd.Series) -> CrashDiagnostics:
    """Score already-labelled days. NaN recall/precision means the relevant
    count (true tail days, or flagged days) was zero — not a bug, since
    crashes are rare by definition."""
    aligned = pd.concat([flagged, true_tail], axis=1, keys=["flagged", "true_tail"]).dropna()
    flagged_b = aligned["flagged"].astype(bool)
    true_b = aligned["true_tail"].astype(bool)

    true_positives = int((flagged_b & true_b).sum())
    n_flagged = int(flagged_b.sum())
    n_true_tail = int(true_b.sum())

    recall = true_positives / n_true_tail if n_true_tail else float("nan")
    precision = true_positives / n_flagged if n_flagged else float("nan")
    f1 = (
        2 * precision * recall / (precision + recall)
        if n_true_tail and n_flagged and (precision + recall) > 0
        else float("nan")
    )
    return CrashDiagnostics(
        recall=recall, precision=precision, f1=f1, n_true_tail_days=n_true_tail
    )


def crash_diagnostics_over_folds(
    predicted: pd.Series,
    realised: pd.Series,
    folds: Iterable[tuple[pd.Index, pd.Index]],
) -> CrashDiagnostics:
    """Runs label_crash_days() per fold, then scores every fold's test
    window together — same split as screen_signals()/screen_over_folds()."""
    labels = pd.concat(
        label_crash_days(predicted, realised, train_idx, test_idx)
        for train_idx, test_idx in folds
    )
    return crash_diagnostics(labels["flagged"], labels["true_tail"])
