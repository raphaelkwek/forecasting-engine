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
            if panel.label_end is not None:
                reaching = _first_label_reaching(
                    panel.label_end, index, start, natural_train_end, index[test_start]
                )
                purge_boundary = min(purge_boundary, reaching)
            train_idx = index[start:purge_boundary]
            test_idx = index[test_start : test_start + self.test]
            yield train_idx, test_idx
            start += self.test


def _first_label_reaching(
    label_end: pd.Series,
    index: pd.DatetimeIndex,
    start: int,
    stop: int,
    test_start_date: pd.Timestamp,
) -> int:
    """Position of the first row in ``[start, stop)`` whose label's price is dated
    on or after the test window opens, or ``stop`` if none is.

    Counting ``horizon`` rows back from the test window is not enough on a merged
    frame: a day the target's market was shut is a row but not a trading day, so
    a label crossing it reaches further than ``horizon`` rows. ``label_end`` says
    where each label really ends. Label ends only increase with row order, so
    everything from the first reaching row onward is purged, and the rows before
    it are safe.
    """
    reaching = (label_end.reindex(index[start:stop]) >= test_start_date).to_numpy()
    return start + int(reaching.argmax()) if reaching.any() else stop
