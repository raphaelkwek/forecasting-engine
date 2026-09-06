"""Downloading and cleaning the Fama-French 5-factor daily dataset.

The zip's CSV has explanatory prose before and after the data table, and no
declared column count to skip by. The only reliable marker of a data row is
that its first field parses as an 8-digit ``YYYYMMDD`` date, so rows are kept
or dropped on that basis rather than by assuming a fixed number of header or
footer lines.
"""

from __future__ import annotations

import io
import re
import zipfile
from urllib.request import urlopen

import pandas as pd

URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
)

DATE_COLUMN = "Date"

_DATE_RE = re.compile(r"^\d{8}$")
_TIMEOUT_SECONDS = 30


def fetch() -> pd.DataFrame:
    """Download and parse the factor file. Raises on a network or shape failure."""
    with urlopen(URL, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed, documented URL
        return parse(response.read())


def parse(zip_bytes: bytes) -> pd.DataFrame:
    """Parse the factor CSV out of the downloaded zip's bytes."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("Fama-French zip contained no CSV file")
        raw = archive.read(names[0]).decode("utf-8")

    lines = raw.splitlines()
    header = next((line for line in lines if "Mkt-RF" in line), None)
    if header is None:
        raise ValueError("Fama-French CSV has no 'Mkt-RF' header row")
    factor_columns = [c.strip() for c in header.split(",") if c.strip()]

    data_rows = [
        line.split(",") for line in lines if _DATE_RE.match(line.split(",", 1)[0].strip())
    ]
    frame = pd.DataFrame(data_rows, columns=[DATE_COLUMN, *factor_columns])
    frame[DATE_COLUMN] = pd.to_datetime(frame[DATE_COLUMN], format="%Y%m%d")
    for column in factor_columns:
        frame[column] = pd.to_numeric(frame[column])
    return frame


def restrict_to(frame: pd.DataFrame, start, end) -> pd.DataFrame:
    """Factors from ``start`` through ``end`` (inclusive), or the latest available.

    The full series runs back to 1963; a caller only wants the span the
    Bloomberg data actually covers. ``end`` is clipped to whatever the factor
    file has, since it will usually lag today's date.
    """
    mask = (frame[DATE_COLUMN] >= start) & (frame[DATE_COLUMN] <= end)
    return frame.loc[mask].reset_index(drop=True)
