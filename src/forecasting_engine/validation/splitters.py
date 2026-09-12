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
            train_idx = index[start : start + self.train]
            test_start = start + self.train + self.embargo
            test_idx = index[test_start : test_start + self.test]
            yield train_idx, test_idx
            start += self.test
