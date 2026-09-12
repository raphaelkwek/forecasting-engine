"""PurgedWalkForward: the only splitter in the codebase.

Rolls a fixed-size train/test window forward across a FeaturePanel's index,
dropping an embargo gap between train and test so overlapping forward-return
labels can't leak across the split.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from forecasting_engine.ingest.align import FeaturePanel


class PurgedWalkForward:
    def __init__(self, train: int, test: int, embargo: int):
        self.train = train
        self.test = test
        self.embargo = embargo

    def split(
        self, panel: FeaturePanel
    ) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        index = panel.frame.index
        start = 0
        while start + self.train + self.embargo + self.test <= len(index):
            natural_train_end = start + self.train
            test_start = natural_train_end + self.embargo
            # A training row's label looks `panel.horizon` days past its own
            # date. If that reaches test_start or beyond, the label needs a
            # price the model isn't supposed to see yet — purge those rows
            # regardless of how large `embargo` is, rather than trusting the
            # caller to have picked embargo >= horizon.
            purge_boundary = min(natural_train_end, test_start - panel.horizon)
            train_idx = index[start:purge_boundary]
            test_idx = index[test_start : test_start + self.test]
            yield train_idx, test_idx
            start += self.test
