"""Reading Bloomberg exports and joining them into the contract shape.

The workbooks built here mirror the real exports: a ``Data`` sheet of dates and
fields, a ``Metadata`` sheet naming the security, ``#N/A N/A`` in the columns we
do not read.
"""

from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from forecasting_engine.ingest.bloomberg import (
    combine,
    convert,
    read_export,
    suspicious,
)

DATES = ["2024-01-01", "2024-01-02", "2024-01-03"]


def workbook(
    tmp_path, name, security, field="PX_LAST", values=(1.0, 2.0, 3.0), dates=DATES,
    extra_field="PX_BID", data_sheet="Data", with_metadata=True,
):
    """A workbook shaped like the real Bloomberg exports."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = data_sheet
    sheet.append(["Date", field, extra_field])
    for date, value in zip(dates, values, strict=False):
        sheet.append([datetime.fromisoformat(date), value, "#N/A N/A"])
    if with_metadata:
        meta = book.create_sheet("Metadata")
        meta.append(["Field", "Value"])
        meta.append(["Security", security])
        meta.append(["Period", "D"])
    path = tmp_path / name
    book.save(path)
    return path


# --- reading one export ----------------------------------------------------


def test_the_security_comes_from_the_metadata_sheet(tmp_path):
    path = workbook(tmp_path, "anything.xlsx", "VIX Index")
    export = read_export(path)

    assert export.security == "VIX Index"
    assert export.column == "vix"


def test_a_misleading_filename_does_not_change_what_the_file_is(tmp_path):
    # The real export named ...LF98OAS... contained LF98TRUU.
    path = workbook(tmp_path, "credit_spread_LF98OAS_values.xlsx", "LF98TRUU Index")
    export = read_export(path)

    assert export.security == "LF98TRUU Index"
    assert export.column is None


def test_dates_and_values_are_read_into_a_series(tmp_path):
    path = workbook(tmp_path, "vix.xlsx", "VIX Index", values=(13.4, 13.5, 12.0))
    series = read_export(path).series

    assert list(series.index) == DATES
    assert series.tolist() == [13.4, 13.5, 12.0]


def test_placeholder_values_are_skipped_rather_than_read_as_numbers(tmp_path):
    path = workbook(tmp_path, "vix.xlsx", "VIX Index", values=(13.4, "#N/A N/A", 12.0))
    series = read_export(path).series

    assert series.index.tolist() == ["2024-01-01", "2024-01-03"]


def test_a_workbook_without_a_data_sheet_is_refused(tmp_path):
    path = workbook(tmp_path, "odd.xlsx", "VIX Index", data_sheet="Sheet1")
    with pytest.raises(ValueError, match="no 'Data' sheet"):
        read_export(path)


def test_a_workbook_without_the_field_is_refused_and_says_what_it_had(tmp_path):
    path = workbook(tmp_path, "tr.xlsx", "SPX Index", field="TOT_RETURN_INDEX_GROSS_DVDS")
    with pytest.raises(ValueError, match="no 'PX_LAST' column"):
        read_export(path)


def test_a_workbook_without_metadata_still_reads_but_cannot_be_placed(tmp_path):
    path = workbook(tmp_path, "mystery.xlsx", "VIX Index", with_metadata=False)
    export = read_export(path)

    assert export.security == ""
    assert export.column is None


# --- joining ---------------------------------------------------------------


def test_exports_are_joined_on_date(tmp_path):
    exports = [
        read_export(workbook(tmp_path, "spx.xlsx", "SPX Index", values=(100, 101, 102))),
        read_export(workbook(tmp_path, "vix.xlsx", "VIX Index", values=(13, 14, 15))),
    ]
    frame, report = combine(exports)

    assert list(frame.columns) == ["date", "spx_close", "vix"]
    assert frame["spx_close"].tolist() == [100, 101, 102]
    assert report.used == {"spx_close": "SPX Index", "vix": "VIX Index"}


def test_columns_come_out_in_contract_order(tmp_path):
    exports = [
        read_export(workbook(tmp_path, "vix.xlsx", "VIX Index")),
        read_export(workbook(tmp_path, "spx.xlsx", "SPX Index")),
        read_export(workbook(tmp_path, "agg.xlsx", "LEGATRUU Index")),
    ]
    frame, _ = combine(exports)
    assert list(frame.columns) == ["date", "spx_close", "agg_close", "vix"]


def test_a_date_only_one_export_saw_is_kept_with_the_others_blank(tmp_path):
    # Indices keep different trading calendars; the union is the honest answer.
    exports = [
        read_export(workbook(tmp_path, "spx.xlsx", "SPX Index", values=(100, 101))),
        read_export(
            workbook(tmp_path, "vix.xlsx", "VIX Index", values=(13, 14, 15), dates=DATES)
        ),
    ]
    frame, report = combine(exports)

    assert report.rows == 3
    assert pd.isna(frame.loc[frame["date"] == "2024-01-03", "spx_close"]).all()


def test_gaps_are_not_forward_filled(tmp_path):
    exports = [
        read_export(
            workbook(tmp_path, "spx.xlsx", "SPX Index", values=(100,), dates=["2024-01-01"])
        ),
        read_export(workbook(tmp_path, "vix.xlsx", "VIX Index")),
    ]
    frame, _ = combine(exports)
    assert frame["spx_close"].isna().sum() == 2


def test_an_unwanted_security_is_skipped_with_a_reason(tmp_path):
    exports = [read_export(workbook(tmp_path, "gold.xlsx", "XAU Curncy"))]
    _, report = combine(exports)

    assert report.used == {}
    assert "XAU Curncy is not a signal the contract asks for" in report.skipped[0]


def test_a_near_miss_ticker_says_what_to_export_instead(tmp_path):
    exports = [read_export(workbook(tmp_path, "hy.xlsx", "LF98TRUU Index"))]
    _, report = combine(exports)

    (note,) = report.skipped
    assert "total return index, not its spread" in note
    assert "LF98OAS Index" in note


def test_the_global_fx_index_is_named_as_the_wrong_one(tmp_path):
    exports = [read_export(workbook(tmp_path, "fx.xlsx", "JPMVXYGL Index"))]
    _, report = combine(exports)

    (note,) = report.skipped
    assert "JPMVXYG7 Index" in note


def test_a_duplicate_signal_is_skipped_rather_than_overwriting(tmp_path):
    exports = [
        read_export(workbook(tmp_path, "a.xlsx", "VIX Index", values=(13, 14, 15))),
        read_export(workbook(tmp_path, "b.xlsx", "VIX Index", values=(99, 99, 99))),
    ]
    frame, report = combine(exports)

    assert frame["vix"].tolist() == [13, 14, 15]
    assert "already supplied" in report.skipped[0]


def test_signals_with_no_export_are_reported_as_missing(tmp_path):
    exports = [read_export(workbook(tmp_path, "vix.xlsx", "VIX Index"))]
    _, report = combine(exports)

    assert "spx_close" in report.missing
    assert "term_spread" in report.missing
    assert not report.complete


# --- term_spread, which has no ticker of its own ---------------------------


def test_the_term_spread_is_computed_from_its_two_legs(tmp_path):
    exports = [
        read_export(workbook(tmp_path, "t10.xlsx", "USGG10YR Index", values=(4.2, 4.3, 4.1))),
        read_export(workbook(tmp_path, "t2.xlsx", "USGG2YR Index", values=(3.6, 3.8, 3.7))),
    ]
    frame, report = combine(exports)

    assert frame["term_spread"].round(2).tolist() == [0.6, 0.5, 0.4]
    assert report.used["term_spread"] == "USGG10YR Index minus USGG2YR Index"


def test_one_leg_alone_reports_what_is_still_needed(tmp_path):
    exports = [read_export(workbook(tmp_path, "t10.xlsx", "USGG10YR Index"))]
    _, report = combine(exports)

    assert "term_spread" in report.missing
    assert any("USGG2YR Index was not supplied" in n for n in report.skipped)


# --- catching the wrong Bloomberg field -----------------------------------


def test_a_total_return_index_in_a_spread_column_is_flagged():
    # The mistake that motivated this check: every value parses, every value is
    # wrong, and the only tell is that they sit far outside the documented range.
    frame = pd.DataFrame({"credit_spread_hy": [1770.79, 2033.79, 2992.90]})
    (note,) = suspicious(frame)

    assert "credit_spread_hy" in note
    assert "3 of 3" in note
    assert "wrong Bloomberg field" in note


def test_a_genuine_market_dislocation_is_not_flagged():
    # One breach in a hundred is an event worth keeping, not a bad export.
    frame = pd.DataFrame({"vix": [15.0] * 99 + [250.0]})
    assert suspicious(frame) == []


def test_a_column_within_range_is_not_flagged():
    frame = pd.DataFrame({"credit_spread_ig": [1.35, 1.36, 3.73]})
    assert suspicious(frame) == []


def test_the_suspect_note_reaches_the_report(tmp_path):
    exports = [
        read_export(
            workbook(tmp_path, "hy.xlsx", "LF98OAS Index", values=(1770.0, 2033.0, 2992.0))
        )
    ]
    _, report = combine(exports)

    assert report.warnings
    assert not report.complete


# --- the whole conversion --------------------------------------------------


def test_convert_reads_a_pile_of_paths(tmp_path):
    paths = [
        workbook(tmp_path, "spx.xlsx", "SPX Index", values=(100, 101, 102)),
        workbook(tmp_path, "vix.xlsx", "VIX Index", values=(13, 14, 15)),
    ]
    frame, report = convert(paths)

    assert len(frame) == 3
    assert set(report.used) == {"spx_close", "vix"}


def test_an_unreadable_workbook_is_reported_not_fatal(tmp_path):
    paths = [
        workbook(tmp_path, "spx.xlsx", "SPX Index"),
        workbook(tmp_path, "odd.xlsx", "VIX Index", data_sheet="Sheet1"),
    ]
    _, report = convert(paths)

    assert "spx_close" in report.used
    assert any("no 'Data' sheet" in n for n in report.skipped)


def test_the_description_names_every_outcome(tmp_path):
    paths = [
        workbook(tmp_path, "vix.xlsx", "VIX Index"),
        workbook(tmp_path, "hy.xlsx", "LF98TRUU Index"),
    ]
    _, report = convert(paths)
    described = report.describe()

    assert "ok       vix" in described
    assert "skipped" in described
    assert "MISSING  spx_close" in described
