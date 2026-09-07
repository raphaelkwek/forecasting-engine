"""Reading Bloomberg CSV exports into the shape the workbook converter joins.

A CSV history export from the terminal is a metadata block (``Security``,
``Start Date``, ``End Date``, ``Period`` and sometimes more), a blank line,
then a table headed ``Date,PX_LAST,...``. The table starts on whichever line
the metadata block ends, so it is found by scanning for that header rather
than assumed to sit at a fixed offset.

What comes out is the same ``BloombergExport`` the workbook reader produces:
one security, one field, values by ISO date. ``combine`` in
``ingest.bloomberg`` then joins CSV and workbook exports alike, through the
same ticker map, into the same contract-shaped frame. There is one converter,
with two readers in front of it.

Dates are the one thing this reader is strict about. Bloomberg writes them as
``m/d/yyyy`` or ``d/m/yyyy`` depending on the terminal's locale, and cell by
cell the two are indistinguishable for any day up to the 12th. The order is
settled once per file from every date in it, the metadata's start and end
dates included: a component above 12 anywhere decides it, and a file with none
is read month first, Bloomberg's own default. Guessing per cell is how
2 January becomes 1 February, which is the ambiguity the data specification
exists to remove.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from io import StringIO
from pathlib import Path

import pandas as pd

from forecasting_engine.ingest.bloomberg import DEFAULT_FIELD, BloombergExport, dedupe_dates
from forecasting_engine.ingest.schema import DATE_COLUMN

#: The table's header row: ``Date`` then a comma, quoted or not, any case.
_HEADER = re.compile(r'^\s*"?date"?\s*,', re.IGNORECASE)

#: A slash- or dash-separated date with a four-digit year, with or without a
#: trailing time of day.
_SLASHED = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:[T\s].*)?$")
_ISO = re.compile(r"^\s*\d{4}-\d{2}-\d{2}(?:[T\s].*)?$")

#: Metadata keys whose values are dates, and so help settle the date order.
_DATE_KEYS = ("start date", "end date")

ISO = "iso"
MONTH_FIRST = "month-first"
DAY_FIRST = "day-first"


def read_export(filename: str, data: bytes, field: str = DEFAULT_FIELD) -> BloombergExport:
    """Read one Bloomberg CSV export from its bytes.

    Raises ``ValueError`` if the file is not shaped like an export, naming what
    was found instead, so a caller can report one bad file without losing the
    good ones.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{filename} is not a UTF-8 CSV ({exc.reason})") from exc

    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if _HEADER.match(line)), None)
    if header is None:
        raise ValueError(
            f"{filename} has no 'Date,...' header row, so it is not a Bloomberg CSV export"
        )

    metadata = _metadata(lines[:header])
    table = _table(filename, lines[header:])
    if field not in table.columns:
        raise ValueError(f"{filename} has no {field!r} column (found {list(table.columns)})")

    hints = [metadata.get(key, "") for key in _DATE_KEYS]
    try:
        dates = parse_dates(table[table.columns[0]], hints)
    except ValueError as exc:
        raise ValueError(f"{filename}: {exc}") from exc

    values = pd.to_numeric(table[field], errors="coerce")
    keep = dates.notna() & values.notna()
    series = pd.Series(
        values[keep].to_numpy(dtype=float),
        index=pd.Index([d.date().isoformat() for d in dates[keep]], name=DATE_COLUMN),
    ).sort_index()
    series, notes = dedupe_dates(series, filename)

    return BloombergExport(
        path=Path(filename),
        security=metadata.get("security", ""),
        field=field,
        series=series,
        notes=notes,
    )


def parse_dates(raw: pd.Series, hints: Sequence[str] = ()) -> pd.Series:
    """Parse a column of export dates, settling day/month order once for the file.

    ``hints`` are further dates from the same file, such as the metadata's
    start and end, which take part in settling the order but are not parsed.
    Cells that do not fit the settled format come back ``NaT``; a column with
    no readable date at all raises ``ValueError``.
    """
    strings = [s for s in raw.tolist() if isinstance(s, str)]
    order = date_order([*strings, *hints])
    if order == ISO:
        parsed = pd.to_datetime(raw, errors="coerce", format="ISO8601")
    else:
        pattern = "%m/%d/%Y" if order == MONTH_FIRST else "%d/%m/%Y"
        parsed = pd.to_datetime(raw.map(_slashed), errors="coerce", format=pattern)
    if parsed.notna().sum() == 0:
        raise ValueError("no readable dates in the Date column")
    return parsed


def date_order(strings: Iterable[str]) -> str:
    """Which way round a file's slashed dates are, from every date it holds.

    A day above 12 in the first position means day first; in the second
    position, month first. A file with neither is ambiguous and read month
    first. Both at once means the file mixes conventions, which no format can
    read, so that raises rather than guesses.
    """
    slashed = [m for s in strings if (m := _SLASHED.match(s or ""))]
    if not slashed:
        if any(_ISO.match(s or "") for s in strings):
            return ISO
        raise ValueError("no recognisable dates: expected m/d/yyyy, d/m/yyyy or yyyy-mm-dd")
    first_over = any(int(m.group(1)) > 12 for m in slashed)
    second_over = any(int(m.group(2)) > 12 for m in slashed)
    if first_over and second_over:
        raise ValueError("dates mix day-first and month-first order, so neither can be trusted")
    return DAY_FIRST if first_over else MONTH_FIRST


def _slashed(value: object) -> str | None:
    """The ``a/b/yyyy`` part of a cell, separators normalised, or None."""
    if not isinstance(value, str):
        return None
    match = _SLASHED.match(value)
    if match is None:
        return None
    return "/".join(match.groups())


def _metadata(lines: Sequence[str]) -> dict[str, str]:
    """The ``key,value`` pairs above the table, keys lower-cased."""
    found: dict[str, str] = {}
    for line in lines:
        key, _, value = line.partition(",")
        key = key.strip().strip('"').lower()
        if key:
            found[key] = value.strip().strip('"')
    return found


def _table(filename: str, lines: Sequence[str]) -> pd.DataFrame:
    """The data table, every cell as text so placeholders stay visible."""
    try:
        table = pd.read_csv(StringIO("\n".join(lines)), dtype=str)
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"{filename}: the data table could not be parsed ({exc})") from exc
    if table.empty:
        raise ValueError(f"{filename} has an empty data table")
    table.columns = [str(column).strip() for column in table.columns]
    return table
