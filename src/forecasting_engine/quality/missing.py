"""Per-signal completeness: how much of each signal actually arrived.

This is the report's context section rather than a problem list. It answers
"how complete is this file", one row per signal, which is what a portfolio
manager wants before deciding whether to trust a forecast built on it.

It deliberately produces **no findings**. Which specific sessions are absent is
the gap check's job, and repeating those dates here would say the same thing
twice in two places. This section carries counts.

A note on the word "filled". Nothing is filled at this stage. The contract
allows a forward fill capped at five days, and that happens later, in data
preparation. Until then this reports what is *missing*, and the report says so
rather than implying a repair that has not happened.
"""

from __future__ import annotations

import pandas as pd

from forecasting_engine.ingest.schema import COLUMNS, TARGET_COLUMNS
from forecasting_engine.quality.report import CheckStatus, QualitySection

CHECK = "missing"
TITLE = "Missing values"

#: Signals this section counts.  The ``*_target`` columns are derived unlagged
#: levels, not signals, so they are screened through their sources alone.
_SIGNALS: tuple[str, ...] = tuple(
    spec.name for spec in COLUMNS if spec.name not in TARGET_COLUMNS
)


def detect(frame: pd.DataFrame) -> QualitySection:
    """Count blank cells per signal. ``frame`` is never modified."""
    signals = [s for s in _SIGNALS if s in frame.columns]
    rows = len(frame)

    per_signal: dict[str, dict[str, float | int]] = {}
    for signal in signals:
        blanks = int(pd.to_numeric(frame[signal], errors="coerce").isna().sum())
        per_signal[signal] = {
            "missing": blanks,
            "present": rows - blanks,
            "completeness": round((rows - blanks) / rows, 4) if rows else 0.0,
        }

    total = sum(int(s["missing"]) for s in per_signal.values())
    return QualitySection(
        check=CHECK,
        title=TITLE,
        status=CheckStatus.FLAGGED if total else CheckStatus.PASSED,
        stats={
            "rows": rows,
            "signals": per_signal,
            "total_missing": total,
            "filled": 0,
            "note": (
                "Counts what is absent. Filling happens in data preparation, "
                "forward only and capped at five days."
            ),
        },
    )
