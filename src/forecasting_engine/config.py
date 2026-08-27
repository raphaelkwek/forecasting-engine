"""Everything needed to reproduce a run, in one frozen object.

The content hash of a RunConfig is the run id. Same config in, same numbers out
— which makes both the DuckDB run history and the result cache trivial.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class DataSpec:
    """Which file, identified by content rather than path alone."""

    path: str
    sha256: str
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class FeatureSpec:
    """How raw data becomes a FeaturePanel, and which signals survive screening.

    Defaults follow the working assumptions in the architecture spec: a five-day
    forecast horizon with a one-day observation lag.
    """

    horizon_days: int = 5
    lag_days: int = 1
    ffill_limit: int = 5
    screen: str = "rank_ic"
    top_k: int = 5


@dataclass(frozen=True)
class ModelSpec:
    kind: str = "derived_polynomial"
    degree: int = 3
    params: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class SplitSpec:
    """Walk-forward geometry. The embargo must cover the label window."""

    train_days: int = 756
    test_days: int = 63
    embargo_days: int = 6


@dataclass(frozen=True)
class PortfolioSpec:
    objective: str = "max_sharpe"
    benchmark: str = "equal_weight"


@dataclass(frozen=True)
class RunConfig:
    data: DataSpec
    features: FeatureSpec = field(default_factory=FeatureSpec)
    model: ModelSpec = field(default_factory=ModelSpec)
    split: SplitSpec = field(default_factory=SplitSpec)
    portfolio: PortfolioSpec = field(default_factory=PortfolioSpec)
    seed: int = 42

    def __post_init__(self) -> None:
        if self.split.embargo_days <= self.features.horizon_days:
            raise ValueError(
                f"embargo_days ({self.split.embargo_days}) must exceed horizon_days "
                f"({self.features.horizon_days}); overlapping label windows leak across the split"
            )

    @property
    def run_id(self) -> str:
        """A stable 16-character identity for this exact configuration."""
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
