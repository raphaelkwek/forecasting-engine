"""Robustness checks for the active generic Bloomberg extraction path."""

import pandas as pd

from forecasting_engine.extraction.bloomberg_csv import (
    forward_fill,
    missing_row_report,
    read_export,
)


def test_a_missing_value_on_an_unreadable_date_is_reported_without_crashing():
    frame = pd.DataFrame({"Date": [pd.NaT], "A_Index_PX_LAST": [None]})

    report = missing_row_report(frame)

    assert len(report) == 1
    assert report.iloc[0]["Likely reason"] == "Unreadable date"


def test_a_trailing_empty_metadata_field_does_not_leak_into_the_security():
    # Real exports pad the row with a trailing empty field
    # ("Security,SPX Index,") rather than leaving it bare.
    data = b"Security,SPX Index,\nPeriod,D,\n,,\nDate,PX_LAST\n2024-01-02,100.0\n"

    export = read_export("spx.csv", data)

    assert export.security == "SPX Index"


def _daily(values):
    dates = pd.date_range("2024-01-01", periods=len(values))
    return pd.DataFrame({"Date": dates, "A": values})


def test_every_gap_is_filled_automatically_up_to_the_cap():
    frame = _daily([1.0, None, None, 4.0])

    out = forward_fill(frame, max_gap=5)

    assert out["A"].tolist() == [1.0, 1.0, 1.0, 4.0]


def test_a_gap_longer_than_max_gap_stays_blank_past_the_limit():
    frame = _daily([1.0, None, None, None, 5.0])

    out = forward_fill(frame, max_gap=2)

    assert out["A"].tolist()[:3] == [1.0, 1.0, 1.0]
    assert pd.isna(out["A"].iloc[3])


def test_an_excluded_column_is_never_filled_however_short_the_gap():
    # A target price column: a filled cell on a closed-market day would read
    # as a real trading day and fabricate a return that never happened.
    frame = _daily([1.0, None, 3.0])

    out = forward_fill(frame, max_gap=5, exclude={"A"})

    assert out["A"].iloc[0] == 1.0
    assert pd.isna(out["A"].iloc[1])
    assert out["A"].iloc[2] == 3.0


def test_excluding_one_column_does_not_stop_others_filling():
    frame = _daily([1.0, None, 3.0])
    frame["B"] = [10.0, None, 30.0]

    out = forward_fill(frame, max_gap=5, exclude={"A"})

    assert pd.isna(out["A"].iloc[1])
    assert out["B"].iloc[1] == 10.0
