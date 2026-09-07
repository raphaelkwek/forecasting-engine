"""Parsing and merging Bloomberg CSV exports."""

import pandas as pd
import pytest

from forecasting_engine.extraction.bloomberg_csv import (
    BloombergCsvError,
    drop_empty_columns,
    merge,
    missing_row_report,
    read_export,
    with_display_dates,
)


def export_bytes(security="SPX Index", header_rows=4, fields="PX_LAST,PX_BID", rows=None):
    """A Bloomberg CSV export: metadata block, blank line, then the data table.

    ``header_rows`` varies the metadata block's length, since the real exports
    do not always carry the same set of metadata fields.
    """
    meta = [f"Security,{security}", "Start Date,1/1/2020", "End Date,12/31/2020", "Period,Daily"]
    meta = meta[:header_rows]
    rows = rows or ["1/2/2020,100.5,100.4", "1/3/2020,101.0,100.9"]
    lines = [*meta, "", f"Date,{fields}", *rows]
    return ("\n".join(lines) + "\n").encode()


def test_the_data_row_is_found_regardless_of_metadata_block_length():
    export = read_export("a.csv", export_bytes(header_rows=3))
    assert list(export.frame[export.frame.columns[0]]) == list(
        pd.to_datetime(["2020-01-02", "2020-01-03"])
    )


def test_the_security_comes_from_the_metadata_block():
    export = read_export("a.csv", export_bytes(security="VIX Index"))
    assert export.security == "VIX Index"


def test_data_columns_are_labelled_with_the_security():
    export = read_export("a.csv", export_bytes(security="SPX Index"))
    assert list(export.frame.columns) == ["Date", "SPX_Index_PX_LAST", "SPX_Index_PX_BID"]


def test_a_file_with_no_date_header_row_is_rejected():
    with pytest.raises(BloombergCsvError, match="no 'Date,...' header row"):
        read_export("bad.csv", b"just,some,columns\n1,2,3\n")


def test_a_file_with_no_security_falls_back_to_its_filename():
    data = export_bytes(security="", header_rows=1)
    export = read_export("my export.csv", data)
    assert list(export.frame.columns)[1:] == ["my_export_PX_LAST", "my_export_PX_BID"]


# --- merging -----------------------------------------------------------


def test_merge_outer_joins_on_date_so_no_file_loses_dates():
    a = read_export("a.csv", export_bytes(security="A Index", rows=["1/2/2020,1.0,2.0"]))
    b = read_export("b.csv", export_bytes(security="B Index", rows=["1/3/2020,3.0,4.0"]))

    merged = merge([a, b])

    assert len(merged) == 2
    assert merged["A_Index_PX_LAST"].isna().sum() == 1
    assert merged["B_Index_PX_LAST"].isna().sum() == 1


def test_merge_sorts_by_date_ascending():
    a = read_export(
        "a.csv", export_bytes(security="A Index", rows=["1/3/2020,2.0,2.0", "1/2/2020,1.0,1.0"])
    )
    merged = merge([a])
    assert list(merged["Date"]) == list(pd.to_datetime(["2020-01-02", "2020-01-03"]))


def test_merge_of_no_exports_is_an_empty_frame_with_a_date_column():
    merged = merge([])
    assert list(merged.columns) == ["Date"]
    assert merged.empty


def test_two_files_sharing_a_security_are_relabelled_by_filename_not_collided():
    # SPX price and SPX total return both carry "Security,SPX Index" and both
    # export a PX_BID column — the real files that surfaced this.
    price = read_export(
        "spx_price.csv", export_bytes(security="SPX Index", fields="PX_LAST,PX_BID")
    )
    total_return = read_export(
        "spx_total_return.csv",
        export_bytes(security="SPX Index", fields="TOT_RETURN_INDEX_GROSS_DVDS,PX_BID"),
    )

    merged = merge([price, total_return])

    assert "SPX_Index_PX_BID" not in merged.columns
    assert "SPX_Index_PX_BID_x" not in merged.columns
    assert "spx_price_PX_BID" in merged.columns
    assert "spx_total_return_PX_BID" in merged.columns
    assert "spx_total_return_TOT_RETURN_INDEX_GROSS_DVDS" in merged.columns


# --- dropping empty columns -------------------------------------------


def test_a_column_with_no_values_at_all_is_dropped():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "VIX_Index_PX_LAST": [15.0, 16.0],
            "VIX_Index_PX_VOLUME": [None, None],
        }
    )
    cleaned, dropped = drop_empty_columns(frame)

    assert "VIX_Index_PX_VOLUME" not in cleaned.columns
    assert dropped == ["VIX_Index_PX_VOLUME"]


def test_a_column_with_some_values_is_kept():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "VIX_Index_PX_LAST": [15.0, None],
        }
    )
    cleaned, dropped = drop_empty_columns(frame)

    assert "VIX_Index_PX_LAST" in cleaned.columns
    assert dropped == []


# --- explaining gaps -----------------------------------------------------


def test_a_weekend_gap_is_labelled_a_weekend():
    # 2020-01-04 is a Saturday.
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2020-01-03", "2020-01-04", "2020-01-06"]),
            "A_Index_PX_LAST": [1.0, None, 3.0],
        }
    )
    report = missing_row_report(frame)
    (row,) = report[report["Date"] == pd.Timestamp("2020-01-04")].to_dict("records")
    assert row["Likely reason"] == "Weekend"
    assert row["Missing columns"] == "A_Index_PX_LAST"


def test_a_us_market_holiday_gap_is_named():
    # 2016-09-05 was Labor Day — the real gap that prompted this feature.
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2016-09-02", "2016-09-05", "2016-09-06"]),
            "LF98TRUU_Index_PX_LAST": [1771.03, None, 1772.0],
        }
    )
    report = missing_row_report(frame)
    (row,) = report[report["Date"] == pd.Timestamp("2016-09-05")].to_dict("records")
    assert "market holiday" in row["Likely reason"].lower()


def test_a_weekday_non_holiday_gap_is_unexplained():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2020-01-06", "2020-01-07", "2020-01-08"]),
            "A_Index_PX_LAST": [1.0, None, 3.0],
        }
    )
    report = missing_row_report(frame)
    (row,) = report[report["Date"] == pd.Timestamp("2020-01-07")].to_dict("records")
    assert row["Likely reason"] == "Unexplained gap"


def test_with_display_dates_formats_as_day_month_year_no_time():
    frame = pd.DataFrame(
        {"Date": pd.to_datetime(["2016-08-31", "2016-09-05"]), "A_Index_PX_LAST": [1.0, 2.0]}
    )
    shown = with_display_dates(frame)
    assert list(shown["Date"]) == ["31/08/2016", "05/09/2016"]
    assert list(frame["Date"]) == list(pd.to_datetime(["2016-08-31", "2016-09-05"]))  # unchanged


def test_a_clean_frame_has_no_gap_rows():
    frame = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
            "A_Index_PX_LAST": [1.0, 2.0],
        }
    )
    assert missing_row_report(frame).empty
