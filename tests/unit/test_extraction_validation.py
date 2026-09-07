"""The extraction package's pandera schema and plain-pandas report."""

import pandas as pd

from forecasting_engine.extraction.validation import _format_failure, validate


def frame(dates, **columns):
    return pd.DataFrame({"Date": pd.to_datetime(dates), **columns})


def test_a_clean_file_reports_nothing():
    data = frame(["2024-01-02", "2024-01-03"], A_Index_PX_LAST=[100.0, 101.0])
    report = validate(data)
    assert report.is_clean


def test_duplicate_dates_are_counted_not_dropped():
    data = frame(["2024-01-02", "2024-01-02"], A_Index_PX_LAST=[100.0, 101.0])
    report = validate(data)
    assert report.duplicate_dates == 1
    assert len(data) == 2  # nothing removed


def test_duplicate_dates_alone_are_not_a_schema_error():
    # A repeated date is a revision, not a fault — it must not block the file
    # the way a genuinely bad column does.
    data = frame(["2024-01-02", "2024-01-02"], A_Index_PX_LAST=[100.0, 101.0])
    report = validate(data)
    assert not report.schema_errors


def test_weekend_rows_are_counted():
    # 2024-01-06 and 2024-01-07 are a Saturday and Sunday.
    data = frame(["2024-01-05", "2024-01-06", "2024-01-07"], A_Index_PX_LAST=[1.0, 2.0, 3.0])
    report = validate(data)
    assert report.weekend_rows == 2
    assert report.weekend_date_values == ("2024-01-06", "2024-01-07")


def test_duplicate_dates_are_named_not_just_counted():
    data = frame(["2024-01-02", "2024-01-02"], A_Index_PX_LAST=[100.0, 101.0])
    report = validate(data)
    assert report.duplicate_date_values == ("2024-01-02",)


def test_missing_pct_is_reported_per_column_and_nulls_are_not_an_error():
    data = frame(["2024-01-01", "2024-01-02"], A_Index_PX_LAST=[100.0, None])
    report = validate(data)
    assert report.missing_pct["A_Index_PX_LAST"] == 50.0
    assert not report.schema_errors


def test_a_big_day_over_day_move_is_flagged():
    data = frame(
        ["2024-01-01", "2024-01-02", "2024-01-03"],
        A_Index_PX_LAST=[100.0, 100.0, 200.0],
    )
    report = validate(data)
    assert len(report.big_moves) == 1
    assert report.big_moves.iloc[0]["column"] == "A_Index_PX_LAST"


def test_a_negative_price_column_is_a_schema_error():
    data = frame(["2024-01-01", "2024-01-02"], A_Index_PX_LAST=[100.0, -5.0])
    report = validate(data)
    assert any("PX_LAST" in e for e in report.schema_errors)


def test_a_non_price_column_uses_the_generic_sane_range_not_positivity():
    # A spread-like column can legitimately be negative (e.g. a breakeven rate).
    data = frame(["2024-01-01", "2024-01-02"], A_Index_SPREAD=[-1.5, 2.0])
    report = validate(data)
    assert not report.schema_errors


def test_an_out_of_range_non_price_value_is_a_schema_error():
    data = frame(["2024-01-01", "2024-01-02"], A_Index_SPREAD=[1.0, 50_000.0])
    report = validate(data)
    assert any("SPREAD" in e for e in report.schema_errors)


def test_unsorted_dates_are_a_schema_error():
    data = frame(["2024-01-02", "2024-01-01"], A_Index_PX_LAST=[1.0, 2.0])
    report = validate(data)
    assert any("ascending" in e for e in report.schema_errors)


def test_a_timestamp_failure_case_is_shown_as_dd_mm_yyyy_with_no_time():
    assert _format_failure(pd.Timestamp("2017-02-23")) == "23/02/2017"


def test_a_non_date_failure_case_is_shown_as_its_repr():
    assert _format_failure(False) == "False"
