"""The single gate between raw data and anything that models it.

Every rule that prevents look-ahead bias lives here, applied once, centrally.
Nothing downstream shifts a series, fills a gap, or builds a target.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from forecasting_engine.ingest.loader import RawFrame
from forecasting_engine.ingest.panel import FeaturePanel
from forecasting_engine.ingest.provenance import Provenance
from forecasting_engine.ingest.schema import PRICE_COLUMNS, SIGNAL_COLUMNS

DEFAULT_HORIZON_DAYS = 5
DEFAULT_LAG_DAYS = 1
DEFAULT_FFILL_LIMIT = 5


def align_and_lag(
    raw: RawFrame,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    lag_days: int = DEFAULT_LAG_DAYS,
    ffill_limit: int = DEFAULT_FFILL_LIMIT,
) -> FeaturePanel:
    """Turn a loaded file into a lag-safe panel.

    Signals are shifted forward by ``lag_days`` so a row dated ``t`` carries only
    what was observable at ``t - lag_days``. Targets are the forward return from
    ``t`` to ``t + horizon_days``. Rows without both are dropped.

    Forward-fill only, capped at ``ffill_limit``. Backward-fill and interpolation
    are prohibited: both move future values into the past.
    """
    if lag_days < 1:
        raise ValueError(f"lag_days must be at least 1 to prevent look-ahead bias, got {lag_days}")
    if horizon_days < 1:
        raise ValueError(f"horizon_days must be at least 1, got {horizon_days}")

    frame = raw.frame.sort_index().ffill(limit=ffill_limit)

    targets = {
        _target_name(price, horizon_days): frame[price]
        .pct_change(periods=horizon_days)
        .shift(-horizon_days)
        for price in PRICE_COLUMNS
        if price in frame.columns
    }
    signals = tuple(name for name in SIGNAL_COLUMNS if name in frame.columns)

    combined = pd.concat(
        [frame[list(signals)].shift(lag_days), pd.DataFrame(targets, index=frame.index)],
        axis=1,
    ).dropna(how="any")

    return FeaturePanel(
        frame=combined,
        signals=signals,
        targets=tuple(targets),
        lag_days=lag_days,
        provenance=Provenance(
            sources=(raw.source,),
            built_at=datetime.now(UTC).isoformat(),
            horizon_days=horizon_days,
        ),
    )


def _target_name(price_column: str, horizon_days: int) -> str:
    """``spx_close`` with a 5-day horizon becomes ``spx_fwd_5d``."""
    stem = price_column.removesuffix("_close")
    return f"{stem}_fwd_{horizon_days}d"
