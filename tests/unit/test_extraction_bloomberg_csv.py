"""Robustness checks for the active generic Bloomberg extraction path."""

import pandas as pd

from forecasting_engine.extraction.bloomberg_csv import forward_fill, missing_row_report


def test_a_missing_value_on_an_unreadable_date_is_reported_without_crashing():
    frame = pd.DataFrame({"Date": [pd.NaT], "A_Index_PX_LAST": [None]})

    report = missing_row_report(frame)

    assert len(report) == 1
    assert report.iloc[0]["Likely reason"] == "Unreadable date"


def _daily(values):
    dates = pd.date_range("2024-01-01", periods=len(values))
    return pd.DataFrame({"Date": dates, "A": values})


def test_a_short_gap_marked_to_clean_is_carried_forward():
    frame = _daily([1.0, None, None, 4.0])
    clean_dates = {frame["Date"][1], frame["Date"][2]}

    out = forward_fill(frame, clean_dates, max_gap=5)

    assert out["A"].tolist() == [1.0, 1.0, 1.0, 4.0]


def test_a_gap_longer_than_max_gap_stays_blank_past_the_limit():
    frame = _daily([1.0, None, None, None, 5.0])
    clean_dates = {frame["Date"][1], frame["Date"][2], frame["Date"][3]}

    out = forward_fill(frame, clean_dates, max_gap=2)

    assert out["A"].tolist()[:3] == [1.0, 1.0, 1.0]
    assert pd.isna(out["A"].iloc[3])


def test_a_row_not_marked_to_clean_is_left_untouched():
    frame = _daily([1.0, None, 3.0])

    out = forward_fill(frame, clean_dates=set(), max_gap=5)

    assert out["A"].iloc[0] == 1.0
    assert pd.isna(out["A"].iloc[1])
    assert out["A"].iloc[2] == 3.0
