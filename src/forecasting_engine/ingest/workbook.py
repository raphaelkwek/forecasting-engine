"""The two-tab workbook download: the signals, then the Fama-French factors.

Separate sheets sharing a date column rather than one merged table. The two
datasets have different provenance and different update cadences, and merging
them would make it harder to tell which came from which. Nothing downstream
reads this file; it is a convenience for whoever wants the data in Excel.
"""

from __future__ import annotations

import io

import pandas as pd

SIGNALS_SHEET = "Signals"
FAMA_FRENCH_SHEET = "Fama-French Factors"


def build(signals: pd.DataFrame, fama_french: pd.DataFrame) -> bytes:
    """Return the .xlsx workbook as bytes, ready for a download button."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        signals.to_excel(writer, sheet_name=SIGNALS_SHEET, index=False)
        fama_french.to_excel(writer, sheet_name=FAMA_FRENCH_SHEET, index=False)
    return buffer.getvalue()
