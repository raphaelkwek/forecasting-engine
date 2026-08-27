"""The column contract for uploaded signal CSVs.

This module is the single source of truth for what a valid input file looks
like. ``docs/data-specification.md`` is the human-readable twin; change both or
neither.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

DATE_COLUMN = "date"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    minimum: float | None = None
    maximum: float | None = None
    description: str = ""


@dataclass(frozen=True)
class SchemaIssue:
    """One problem found in an input file.

    ``kind`` is a stable machine-readable tag; ``detail`` is shown to the user.
    """

    kind: str
    column: str
    detail: str
    count: int = 1


PRICE_COLUMNS: tuple[str, ...] = ("spx_close", "agg_close")

COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("spx_close", minimum=0.0, description="S&P 500 index close"),
    ColumnSpec("agg_close", minimum=0.0, description="Bloomberg Global Aggregate close"),
    ColumnSpec("vix", minimum=0.0, maximum=200.0, description="CBOE Volatility Index"),
    ColumnSpec("credit_spread_hy", minimum=0.0, maximum=50.0, description="US HY OAS, percent"),
    ColumnSpec("credit_spread_ig", minimum=0.0, maximum=20.0, description="US IG OAS, percent"),
    ColumnSpec("fx_impl_vol", minimum=0.0, maximum=100.0, description="G7 FX implied volatility"),
    ColumnSpec("breakeven_10y", minimum=-5.0, maximum=15.0, description="10y breakeven, percent"),
    ColumnSpec("term_spread", minimum=-10.0, maximum=10.0, description="10y minus 2y, percent"),
)

SIGNAL_COLUMNS: tuple[str, ...] = tuple(c.name for c in COLUMNS if c.name not in PRICE_COLUMNS)
REQUIRED_COLUMNS: tuple[str, ...] = (DATE_COLUMN,) + tuple(c.name for c in COLUMNS)

#: Issue kinds that make a file unusable rather than merely imperfect.
BLOCKING_KINDS: frozenset[str] = frozenset({"missing_column", "unparseable_date", "non_numeric"})


def validate(frame: pd.DataFrame) -> list[SchemaIssue]:
    """Return every contract violation in ``frame``. An empty list means valid."""
    issues: list[SchemaIssue] = []

    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    issues.extend(
        SchemaIssue("missing_column", name, f"required column {name!r} is absent")
        for name in missing
    )
    if DATE_COLUMN in missing:
        return issues

    issues.extend(_date_issues(frame[DATE_COLUMN]))
    for spec in COLUMNS:
        if spec.name in frame.columns:
            issues.extend(_numeric_issues(frame[spec.name], spec))
    return issues


def _date_issues(raw: pd.Series) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    dates = pd.to_datetime(raw, errors="coerce")

    unparseable = int(dates.isna().sum() - raw.isna().sum())
    if unparseable > 0:
        issues.append(
            SchemaIssue("unparseable_date", DATE_COLUMN, "values are not valid dates", unparseable)
        )

    duplicates = int(dates.duplicated().sum())
    if duplicates:
        issues.append(SchemaIssue("duplicate_date", DATE_COLUMN, "repeated dates", duplicates))

    present = dates.dropna()
    if not present.is_monotonic_increasing:
        issues.append(SchemaIssue("unsorted_dates", DATE_COLUMN, "dates are not ascending"))
    return issues


def _numeric_issues(raw: pd.Series, spec: ColumnSpec) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    values = pd.to_numeric(raw, errors="coerce")

    # A blank cell is missing data, not a type error — quality.py handles those.
    unparseable = int(values.isna().sum() - raw.isna().sum())
    if unparseable > 0:
        issues.append(SchemaIssue("non_numeric", spec.name, "values are not numeric", unparseable))

    if spec.minimum is not None:
        below = int((values < spec.minimum).sum())
        if below:
            issues.append(
                SchemaIssue("out_of_range", spec.name, f"values below {spec.minimum}", below)
            )
    if spec.maximum is not None:
        above = int((values > spec.maximum).sum())
        if above:
            issues.append(
                SchemaIssue("out_of_range", spec.name, f"values above {spec.maximum}", above)
            )
    return issues


def blocking(issues: list[SchemaIssue]) -> list[SchemaIssue]:
    """Filter to the issues that make a file unusable."""
    return [issue for issue in issues if issue.kind in BLOCKING_KINDS]
