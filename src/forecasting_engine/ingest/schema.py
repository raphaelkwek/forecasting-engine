"""The column contract for uploaded signal CSVs.

This module is the single source of truth for what a valid input file looks
like. ``docs/data-specification.md`` is the human-readable twin; change both or
neither.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DATE_COLUMN = "date"

#: How many offending line numbers an issue lists. A file with thousands of bad
#: cells should not produce thousands of line numbers; ``count`` stays exact, so
#: nothing is hidden by the cap.
MAX_REPORTED_ROWS = 10


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

    ``rows`` holds the CSV line numbers of the offending cells, numbered the way
    the user's spreadsheet numbers them: line 1 is the header, so the first data
    row is line 2. It is capped at ``MAX_REPORTED_ROWS`` while ``count`` stays
    exact — a whole-file problem such as a missing column has no rows at all.
    """

    kind: str
    column: str
    detail: str
    count: int = 1
    rows: tuple[int, ...] = ()

    @property
    def truncated(self) -> bool:
        """Whether ``rows`` lists fewer lines than ``count`` found."""
        return len(self.rows) < self.count

    @property
    def location(self) -> str:
        """Where the problem is, phrased for someone looking at the file."""
        where = f"column {self.column!r}"
        if not self.rows:
            return where
        lines = ", ".join(str(row) for row in self.rows)
        plural = "line" if len(self.rows) == 1 else "lines"
        if self.truncated:
            return f"{where}, {plural} {lines} and {self.count - len(self.rows)} more"
        return f"{where}, {plural} {lines}"


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
    """Return every contract violation in ``frame``. An empty list means valid.

    Every column is checked independently, so one missing column never hides a
    problem in another. A user fixing a malformed file should see the whole list
    at once rather than discovering it one round at a time.
    """
    issues: list[SchemaIssue] = []

    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    issues.extend(SchemaIssue("missing_column", name, _absent_detail(name)) for name in missing)

    if DATE_COLUMN not in missing:
        issues.extend(_date_issues(frame[DATE_COLUMN]))
    for spec in COLUMNS:
        if spec.name in frame.columns:
            issues.extend(_numeric_issues(frame[spec.name], spec))
    return issues


def _at(mask: pd.Series | np.ndarray) -> tuple[int, ...]:
    """CSV line numbers for the True positions in ``mask``, capped.

    Positional rather than index-based: the frame's index is whatever pandas
    made of the file, but the user is looking at line numbers.
    """
    positions = np.flatnonzero(np.asarray(mask))
    return tuple(int(pos) + 2 for pos in positions[:MAX_REPORTED_ROWS])


def _absent_detail(name: str) -> str:
    """Name the series as well as the column, since the reader may not know the code."""
    spec = next((c for c in COLUMNS if c.name == name), None)
    if spec is None or not spec.description:
        return f"required column {name!r} is absent"
    return f"required column {name!r} ({spec.description}) is absent"


def _date_issues(raw: pd.Series) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    # ISO8601 only, because that is what the contract says. Letting pandas infer
    # would quietly accept 01/02/2024 — a date whose meaning depends on which
    # side of the Atlantic exported it, which is precisely the ambiguity the
    # contract exists to remove. It also avoids a per-element dateutil fallback
    # that is slow over a full history.
    dates = pd.to_datetime(raw, errors="coerce", format="ISO8601")

    # As with numeric columns, a blank cell is missing data rather than a bad
    # value. Subtracting the original NaN count leaves only genuine parse errors.
    bad = dates.isna() & raw.notna()
    unparseable = int(bad.sum())
    if unparseable > 0:
        issues.append(
            SchemaIssue(
                "unparseable_date",
                DATE_COLUMN,
                "values are not valid dates",
                unparseable,
                _at(bad),
            )
        )

    # Flags the repeat, not the first occurrence: the earlier row is the one
    # the reader should keep, so pointing at it would misdirect the fix.
    repeated = dates.duplicated()
    duplicates = int(repeated.sum())
    if duplicates:
        issues.append(
            SchemaIssue(
                "duplicate_date", DATE_COLUMN, "repeated dates", duplicates, _at(repeated)
            )
        )

    present = dates.dropna()
    if not present.is_monotonic_increasing:
        issues.append(SchemaIssue("unsorted_dates", DATE_COLUMN, "dates are not ascending"))
    return issues


def _numeric_issues(raw: pd.Series, spec: ColumnSpec) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    values = pd.to_numeric(raw, errors="coerce")

    # A blank cell is missing data, not a type error — quality.py handles those.
    bad = values.isna() & raw.notna()
    unparseable = int(bad.sum())
    if unparseable > 0:
        issues.append(
            SchemaIssue("non_numeric", spec.name, "values are not numeric", unparseable, _at(bad))
        )

    if spec.minimum is not None:
        under = values < spec.minimum
        below = int(under.sum())
        if below:
            issues.append(
                SchemaIssue(
                    "out_of_range", spec.name, f"values below {spec.minimum}", below, _at(under)
                )
            )
    if spec.maximum is not None:
        over = values > spec.maximum
        above = int(over.sum())
        if above:
            issues.append(
                SchemaIssue(
                    "out_of_range", spec.name, f"values above {spec.maximum}", above, _at(over)
                )
            )
    return issues


def blocking(issues: list[SchemaIssue]) -> list[SchemaIssue]:
    """Filter to the issues that make a file unusable."""
    return [issue for issue in issues if issue.kind in BLOCKING_KINDS]
