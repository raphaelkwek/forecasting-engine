"""Writing the two-tab Excel deliverable: Bloomberg data, then Fama-French factors.

Separate sheets sharing a Date column, not a merged table — the two datasets
have different provenance and different update cadences, and merging them
would make it harder to tell which came from which.
"""

from __future__ import annotations

import io

import pandas as pd

BLOOMBERG_SHEET = "Bloomberg Data"
FAMA_FRENCH_SHEET = "Fama-French Factors"


def build(bloomberg: pd.DataFrame, fama_french: pd.DataFrame) -> bytes:
    """Return the .xlsx workbook as bytes, ready for a download button."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        bloomberg.to_excel(writer, sheet_name=BLOOMBERG_SHEET, index=False)
        fama_french.to_excel(writer, sheet_name=FAMA_FRENCH_SHEET, index=False)
    return buffer.getvalue()
