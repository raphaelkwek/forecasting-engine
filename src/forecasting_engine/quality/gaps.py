"""Telling a missing trading day apart from a day the market was shut.

A naive gap check counts calendar days and flags every weekend and holiday, so
its output is noise. This one asks a market calendar which days the relevant
market was actually open, and only reports the ones where it was open and the
data is absent.

**Each signal is checked against its own market's calendar**, because they do
not share one. Measured against ten years of Bloomberg data, using the NYSE
calendar for everything produced 18 false gaps; using plain weekdays produced
257; the per-signal mapping below produces 5, four of which are the file simply
ending a day earlier for some series than others.

The difference is concrete: on Columbus Day and Veterans Day the New York Stock
Exchange trades while the US bond market is closed. Judging a credit spread by
the equity calendar flags both days, every year, as missing data.

Calendars come from ``pandas_market_calendars``. See
``docs/market-calendars.md`` for the source, the evidence and the known limits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

import pandas as pd
import pandas_market_calendars as mcal

from forecasting_engine.ingest.schema import COLUMNS, DATE_COLUMN
from forecasting_engine.quality.report import (
    CheckStatus,
    QualityFinding,
    QualitySection,
    Severity,
)

CHECK = "gaps"
TITLE = "Data gaps"

#: Which market's calendar governs each signal. Equity and volatility follow the
#: exchange; rates and credit follow the bond market, which keeps different
#: holidays; FX trades on any weekday.
CALENDARS: Mapping[str, str] = {
    "spx_close": "NYSE",
    "vix": "CBOE_Index_Options",
    "agg_close": "SIFMA_US",
    "credit_spread_hy": "SIFMA_US",
    "credit_spread_ig": "SIFMA_US",
    "breakeven_10y": "SIFMA_US",
    "term_spread": "SIFMA_US",
    "fx_impl_vol": "weekdays",
}

#: For a signal with no entry above. The bond calendar is the safer default: it
#: is the most permissive of the real ones, so an unmapped signal errs towards
#: reporting a gap rather than hiding one.
DEFAULT_CALENDAR = "SIFMA_US"

#: Not an exchange — FX trades around the clock on weekdays, so every weekday in
#: range counts as a session.
WEEKDAYS = "weekdays"

_SIGNALS: tuple[str, ...] = tuple(spec.name for spec in COLUMNS)


def calendar_for(signal: str) -> str:
    return CALENDARS.get(signal, DEFAULT_CALENDAR)


def expected_sessions(calendar: str, start: date, end: date) -> set[date]:
    """Days the market was open between ``start`` and ``end``, inclusive."""
    if start > end:
        return set()
    if calendar == WEEKDAYS:
        return {d.date() for d in pd.bdate_range(start, end)}
    return {d.date() for d in mcal.get_calendar(calendar).valid_days(start, end)}


def detect(frame: pd.DataFrame) -> QualitySection:
    """Report trading days each signal should have covered but does not.

    Weekends and holidays are never reported: they are not sessions, so they
    never enter the expected sequence in the first place.
    """
    dates = _dates(frame)
    if dates is None or dates.empty:
        return _section([], {"reason": "no usable date column"})

    present_rows = {d.date() for d in dates}
    signals = [s for s in _SIGNALS if s in frame.columns]
    used = {signal: calendar_for(signal) for signal in signals}

    # A date missing from the file altogether is one gap, not one per signal.
    # Reporting it eight times says the same thing eight ways and buries the
    # per-signal gaps, which are the ones that need a column name to make sense.
    findings = _whole_file_findings(signals, present_rows)
    for signal in signals:
        findings.extend(_findings_for(frame, signal, dates, present_rows))

    return _section(
        findings,
        {
            "source": "pandas_market_calendars",
            "version": mcal.__version__,
            "calendars": used,
            "checked_from": dates.min().date().isoformat(),
            "checked_to": dates.max().date().isoformat(),
            "missing_sessions": sum(f.count for f in findings),
        },
    )


def _whole_file_findings(
    signals: list[str], present_rows: set[date]
) -> list[QualityFinding]:
    """Dates absent from the file entirely, reported once against the file."""
    if not present_rows or not signals:
        return []

    start, end = min(present_rows), max(present_rows)
    expected: set[date] = set()
    wanted_by: dict[date, list[str]] = {}
    for signal in signals:
        for day in expected_sessions(calendar_for(signal), start, end):
            expected.add(day)
            wanted_by.setdefault(day, []).append(signal)

    absent = sorted(expected - present_rows)
    return [
        _finding(None, _who_expected(run, wanted_by, signals), run)
        for run in _consecutive(absent, expected)
    ]


def _who_expected(
    run: list[date], wanted_by: dict[date, list[str]], signals: list[str]
) -> str:
    """A clause naming who expected data on these dates.

    Naming the signals matters when only some of them did: a day the bond market
    is shut but FX trades is a gap for FX alone, and saying so stops the reader
    hunting for missing equity data that was never due.
    """
    affected = sorted({s for day in run for s in wanted_by.get(day, ())})
    if len(affected) == len(signals):
        return "every signal's market was open"
    if len(affected) == 1:
        return f"{affected[0]}'s market was open"
    return f"the markets for {', '.join(affected)} were open"


def _findings_for(
    frame: pd.DataFrame, signal: str, dates: pd.Series, present_rows: set[date]
) -> list[QualityFinding]:
    """Dates where the row exists but this one signal is blank."""
    present = {
        d.date()
        for d in dates[pd.to_numeric(frame[signal], errors="coerce").notna().to_numpy()]
        if not pd.isna(d)
    }
    if not present:
        return []

    calendar = calendar_for(signal)
    expected = expected_sessions(calendar, min(present), max(present))
    # Whole-file absences are reported separately; this is about blank cells.
    absent = sorted((expected - present) & present_rows)

    return [
        _finding(signal, f"{calendar} says the market was open", run)
        for run in _consecutive(absent, expected)
    ]


def _consecutive(absent: Sequence[date], expected: set[date]) -> list[list[date]]:
    """Group missing days into runs of consecutive *sessions*.

    A Friday and the following Monday are consecutive sessions even though three
    calendar days separate them, so an outage over a weekend reads as one gap
    rather than two.
    """
    if not absent:
        return []
    ordered = sorted(expected)
    position = {day: i for i, day in enumerate(ordered)}

    runs: list[list[date]] = [[absent[0]]]
    for day in absent[1:]:
        if position[day] - position[runs[-1][-1]] == 1:
            runs[-1].append(day)
        else:
            runs.append([day])
    return runs


def _finding(signal: str | None, because: str, run: list[date]) -> QualityFinding:
    """One gap. ``because`` is the clause explaining why it counts as one."""
    span = (
        f"{run[0].isoformat()}"
        if len(run) == 1
        else f"{run[0].isoformat()} to {run[-1].isoformat()}"
    )
    label = "session" if len(run) == 1 else "consecutive sessions"
    what = "missing from the file" if signal is None else "blank"
    return QualityFinding(
        check=CHECK,
        severity=Severity.INFO,
        detail=f"{len(run)} {label} {what} ({span}); {because}",
        signal=signal,
        dates=tuple(d.isoformat() for d in run[:10]),
        count=len(run),
        truncated=len(run) > 10,
    )


def _section(findings: list[QualityFinding], stats: dict) -> QualitySection:
    return QualitySection(
        check=CHECK,
        title=TITLE,
        status=CheckStatus.FLAGGED if findings else CheckStatus.PASSED,
        findings=tuple(findings),
        stats=stats,
    )


def _dates(frame: pd.DataFrame) -> pd.Series | None:
    if DATE_COLUMN not in frame.columns:
        return None
    parsed = pd.to_datetime(frame[DATE_COLUMN], errors="coerce", format="ISO8601")
    return parsed.dropna()
