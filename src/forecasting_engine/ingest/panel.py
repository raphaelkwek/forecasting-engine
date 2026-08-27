"""The lag-safe dataset every model consumes.

A FeaturePanel is the only thing a Forecaster is allowed to see. It is frozen,
it checks its own invariants on construction, and the sole way to build a
correct one is ``align_and_lag``. There is deliberately no way to hand a model a
bare DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from forecasting_engine.ingest.provenance import Provenance


@dataclass(frozen=True)
class FeaturePanel:
    """Lagged signals and forward targets on a shared date index.

    A row dated ``t`` holds signal values observed at ``t - lag_days`` and the
    return realised between ``t`` and ``t + horizon_days``. Predicting the target
    from the signals therefore uses no information from after ``t - lag_days``.
    """

    frame: pd.DataFrame
    signals: tuple[str, ...]
    targets: tuple[str, ...]
    lag_days: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.lag_days < 1:
            raise ValueError(
                f"lag_days must be at least 1 to prevent look-ahead bias, got {self.lag_days}"
            )
        if not isinstance(self.frame.index, pd.DatetimeIndex):
            raise ValueError(
                f"frame must have a DatetimeIndex, got {type(self.frame.index).__name__}"
            )
        if not self.frame.index.is_monotonic_increasing:
            raise ValueError("frame index must be sorted in ascending date order")

        overlap = set(self.signals) & set(self.targets)
        if overlap:
            raise ValueError(f"{sorted(overlap)} are declared as both a signal and a target")

        absent = (set(self.signals) | set(self.targets)) - set(self.frame.columns)
        if absent:
            raise ValueError(f"declared columns not present in frame: {sorted(absent)}")

    def matrix(
        self, index: pd.DatetimeIndex, target: str | None = None
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Return ``(features, target)`` for ``index``.

        This is the only accessor models should use. It cannot return a target
        column among the features.
        """
        name = target if target is not None else self.targets[0]
        if name not in self.targets:
            raise KeyError(
                f"{name!r} is not a target of this panel; available: {list(self.targets)}"
            )
        rows = self.frame.loc[index]
        return rows[list(self.signals)], rows[name]

    @property
    def horizon_days(self) -> int:
        return self.provenance.horizon_days

    def __len__(self) -> int:
        return len(self.frame)
