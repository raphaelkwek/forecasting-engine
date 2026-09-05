"""Flagging statistically extreme moves in signal data.

Nothing here alters the data. Detection produces findings; the values stay
exactly as uploaded, and only an explicit decision by the portfolio manager
removes anything from what a model sees.

Three choices define the method, each forced by what the real data did.

**Detection runs on the day-over-day change, not the level.** A trending price
series has a level distribution wide enough to swallow almost anything: dividing
one `spx_close` by ten — the classic misplaced decimal — scored 2.5 standard
deviations as a level, well under any usable threshold, and 32.7 as a change.
Level-based detection on `spx_close` and `bond_index_global_agg` flagged nothing at all, at
any threshold, on ten years of Bloomberg data.

**Spread is measured by median absolute deviation, not standard deviation.**
Standard deviation is inflated by the very moves we are looking for. On the real
`vix` series a classic z-score above 4 caught 16 days; the robust score caught
100, because March 2020 had dragged the standard deviation up far enough to hide
everything either side of it.

**The default threshold is 8, not the textbook 3.** Financial changes are
fat-tailed, so a robust score of 4 is unremarkable — it flagged 282 points
across five signals over ten years. The portfolio manager has to review each
flag by hand, so the number has to land in the tens. At 8 the same data yields
44.

A note on what this catches. Run against clean institutional data, every flag it
produced was a genuine dislocation — the COVID crash, February 2018, April 2025
— and not one was a data error. That is the expected result on good data, and it
is why excluding a flagged point is a decision with teeth: those are the days a
tail-risk model most needs to see.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from forecasting_engine.ingest.schema import COLUMNS, DATE_COLUMN, TARGET_COLUMNS
from forecasting_engine.quality.report import (
    CheckStatus,
    QualityFinding,
    QualitySection,
    Severity,
)

CHECK = "outliers"
TITLE = "Outliers"

#: Robust score beyond which a move is flagged. See the module docstring for why
#: this is 8 rather than the textbook 3.
DEFAULT_THRESHOLD = 8.0

#: Per-signal overrides. Empty on purpose: on the ten years of real data we have,
#: `vix` and the credit spreads do flag more often than the rest, but every one
#: of those flags was a real market event rather than a fault. Tuning eight
#: separate thresholds to a single sample would be fitting noise. Add an entry
#: here when a signal earns one, and say in the commit what data justified it.
THRESHOLDS: Mapping[str, float] = {}

#: 0.6745 is the 75th percentile of the standard normal, which puts a median
#: absolute deviation on the same scale as a standard deviation.
_MAD_TO_SIGMA = 0.6745

_SIGNALS: tuple[str, ...] = tuple(
    spec.name for spec in COLUMNS if spec.name not in TARGET_COLUMNS
)


def threshold_for(signal: str) -> float:
    return THRESHOLDS.get(signal, DEFAULT_THRESHOLD)


def robust_z(values: pd.Series) -> pd.Series:
    """Distance from the median, scaled by the median absolute deviation.

    Falls back to the mean absolute deviation when the median one is zero. That
    happens whenever more than half the values are identical — a signal pegged
    at a constant, or a feed that has gone stale — and it is exactly the case
    where a single jump matters most. Scaling by zero would either divide by
    zero or, guarded, silently call the jump unremarkable.

    Returns all zeros only when the series genuinely never moves, which has no
    outliers to find.
    """
    median = values.median()
    if np.isnan(median):
        return pd.Series(0.0, index=values.index)

    spread = (values - median).abs().median()
    if not spread or np.isnan(spread):
        spread = (values - median).abs().mean()
    if not spread or np.isnan(spread):
        return pd.Series(0.0, index=values.index)

    return _MAD_TO_SIGMA * (values - median) / spread


def detect(frame: pd.DataFrame) -> QualitySection:
    """Flag extreme daily moves in every signal the frame carries.

    ``frame`` is never modified.
    """
    dates = _dates(frame)
    findings: list[QualityFinding] = []

    for signal in _SIGNALS:
        if signal not in frame.columns:
            continue
        findings.extend(_findings_for(frame, signal, dates))

    findings.sort(key=lambda f: -abs(f.value if f.value is not None else 0))
    return QualitySection(
        check=CHECK,
        title=TITLE,
        status=CheckStatus.FLAGGED if findings else CheckStatus.PASSED,
        findings=tuple(findings),
        stats={
            "method": "robust z-score (median absolute deviation) on day-over-day change",
            "default_threshold": DEFAULT_THRESHOLD,
            "overrides": dict(THRESHOLDS),
            "signals_checked": sum(1 for s in _SIGNALS if s in frame.columns),
            "flagged": len(findings),
        },
    )


def _findings_for(
    frame: pd.DataFrame, signal: str, dates: pd.Series | None
) -> list[QualityFinding]:
    values = pd.to_numeric(frame[signal], errors="coerce")
    changes = values.diff()
    scores = robust_z(changes.dropna()).abs()
    limit = threshold_for(signal)

    flagged = _drop_rebounds(scores[scores > limit], changes)
    findings = []
    for position, score in flagged.items():
        index = frame.index.get_loc(position)
        findings.append(
            QualityFinding(
                check=CHECK,
                severity=Severity.INFO,
                detail=(
                    f"moved {changes.loc[position]:+,.4g} in one day, "
                    f"{score:.0f}x the typical move"
                ),
                signal=signal,
                dates=_date_at(dates, index),
                rows=(index + 2,),  # line 1 is the header, and lines are 1-based
                value=float(values.loc[position]),
            )
        )
    return findings


def _drop_rebounds(flagged: pd.Series, changes: pd.Series) -> pd.Series:
    """Collapse a spike and its rebound into one flag, on the offending row.

    A single bad value makes two extreme changes: the move onto it and the move
    back off. Reporting both doubles the review and puts half the flags on rows
    whose values are fine. When consecutive days are flagged in opposite
    directions, the anomaly is the first of them — that is the row holding the
    odd value.

    Consecutive moves in the *same* direction are left alone. A crash is several
    bad days in a row, and each is a genuine observation.
    """
    if len(flagged) < 2:
        return flagged

    positions = list(flagged.index)
    rebounds = set()
    for earlier, later in zip(positions, positions[1:], strict=False):
        if later in rebounds:
            continue
        adjacent = changes.index.get_loc(later) - changes.index.get_loc(earlier) == 1
        opposed = changes.loc[earlier] * changes.loc[later] < 0
        if adjacent and opposed:
            rebounds.add(later)
    return flagged.drop(index=list(rebounds))


def _dates(frame: pd.DataFrame) -> pd.Series | None:
    if DATE_COLUMN not in frame.columns:
        return None
    parsed = pd.to_datetime(frame[DATE_COLUMN], errors="coerce", format="ISO8601")
    return parsed.reset_index(drop=True)


def _date_at(dates: pd.Series | None, index: int) -> tuple[str, ...]:
    if dates is None or not 0 <= index < len(dates):
        return ()
    value = dates.iloc[index]
    return () if pd.isna(value) else (value.date().isoformat(),)
