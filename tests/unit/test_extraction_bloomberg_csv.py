"""Robustness checks for the active generic Bloomberg extraction path."""

import pandas as pd

from forecasting_engine.extraction.bloomberg_csv import missing_row_report


def test_a_missing_value_on_an_unreadable_date_is_reported_without_crashing():
    frame = pd.DataFrame({"Date": [pd.NaT], "A_Index_PX_LAST": [None]})

    report = missing_row_report(frame)

    assert len(report) == 1
    assert report.iloc[0]["Likely reason"] == "Unreadable date"
