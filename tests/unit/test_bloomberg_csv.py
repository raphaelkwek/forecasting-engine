"""Reading Bloomberg CSV exports into the converter's shape.

The files built here mirror the real exports: a metadata block of varying
length, a blank line, then ``Date,PX_LAST,...`` with ``#N/A N/A`` where the
security has no value.
"""

import pytest

from forecasting_engine.ingest.bloomberg import combine
from forecasting_engine.ingest.bloomberg_csv import (
    DAY_FIRST,
    ISO,
    MONTH_FIRST,
    date_order,
    read_export,
)

ROWS = ["1/2/2020,100.5,100.4", "1/3/2020,101.0,100.9", "1/6/2020,102.0,101.9"]


def export(
    security="SPX Index",
    rows=ROWS,
    fields="PX_LAST,PX_BID",
    metadata_lines=4,
    start="1/1/2020",
    end="12/31/2020",
) -> bytes:
    """A Bloomberg CSV export. ``metadata_lines`` trims the block, since the
    real exports do not all carry the same metadata."""
    metadata = [f"Security,{security}", f"Start Date,{start}", f"End Date,{end}", "Period,Daily"]
    lines = [*metadata[:metadata_lines], "", f"Date,{fields}", *rows]
    return ("\n".join(lines) + "\n").encode()


# --- finding the table -----------------------------------------------------


@pytest.mark.parametrize("metadata_lines", [1, 2, 3, 4])
def test_the_table_is_found_however_long_the_metadata_block_is(metadata_lines):
    series = read_export("spx.csv", export(metadata_lines=metadata_lines)).series
    assert series.index.tolist() == ["2020-01-02", "2020-01-03", "2020-01-06"]


def test_the_security_comes_from_the_metadata_block():
    assert read_export("a.csv", export(security="VIX Index")).security == "VIX Index"


def test_trailing_empty_metadata_cells_are_ignored_like_bloomberg_exports_them():
    data = export().replace(b"Security,SPX Index", b"Security,SPX Index,")

    exported = read_export("spx.csv", data)

    assert exported.security == "SPX Index"
    assert exported.column == "spx_close"


def test_a_file_with_no_security_still_reads_but_cannot_be_placed():
    exported = read_export("mystery.csv", export(metadata_lines=0))
    assert exported.security == ""
    assert exported.column is None


def test_the_filename_is_kept_for_messages():
    assert read_export("my export.csv", export()).path.name == "my export.csv"


def test_a_file_with_no_date_header_is_refused_by_name():
    with pytest.raises(ValueError, match="no 'Date,...' header row"):
        read_export("bad.csv", b"just,some,columns\n1,2,3\n")


def test_a_file_that_is_not_utf8_is_refused():
    with pytest.raises(ValueError, match="not a UTF-8 CSV"):
        read_export("latin.csv", export().replace(b"SPX", b"\xff\xfe"))


def test_a_byte_order_mark_is_tolerated():
    exported = read_export("bom.csv", b"\xef\xbb\xbf" + export())
    assert exported.security == "SPX Index"


# --- which column is read ----------------------------------------------------


def test_px_last_is_read_and_the_other_fields_are_ignored():
    series = read_export("spx.csv", export()).series
    assert series.tolist() == [100.5, 101.0, 102.0]


def test_a_file_without_px_last_is_refused_and_says_what_it_had():
    total_return = export(fields="TOT_RETURN_INDEX_GROSS_DVDS,PX_BID")
    with pytest.raises(ValueError, match="no 'PX_LAST' column") as caught:
        read_export("tr.csv", total_return)
    assert "TOT_RETURN_INDEX_GROSS_DVDS" in str(caught.value)


def test_placeholder_values_are_missing_data_not_numbers():
    rows = ["1/2/2020,100.5,1", "1/3/2020,#N/A N/A,1", "1/6/2020,102.0,1"]
    series = read_export("spx.csv", export(rows=rows)).series
    assert series.index.tolist() == ["2020-01-02", "2020-01-06"]


# --- day/month order is settled once per file ---------------------------------


def test_an_ambiguous_file_is_read_month_first_like_bloomberg_writes_it():
    rows = ["1/2/2020,1,1", "1/3/2020,2,2"]
    series = read_export("a.csv", export(rows=rows, metadata_lines=1)).series
    assert series.index.tolist() == ["2020-01-02", "2020-01-03"]


def test_a_day_above_twelve_in_first_position_makes_the_file_day_first():
    rows = ["13/2/2020,1,1", "14/2/2020,2,2", "2/3/2020,3,3"]
    series = read_export("a.csv", export(rows=rows, metadata_lines=1)).series
    assert series.index.tolist() == ["2020-02-13", "2020-02-14", "2020-03-02"]


def test_the_metadata_dates_take_part_in_settling_the_order():
    # Every row is ambiguous, but an end date of 31/12 is not.
    rows = ["1/2/2020,1,1", "1/3/2020,2,2"]
    series = read_export("a.csv", export(rows=rows, end="31/12/2020")).series
    assert series.index.tolist() == ["2020-02-01", "2020-03-01"]


def test_a_file_that_mixes_conventions_is_refused_rather_than_guessed():
    rows = ["13/2/2020,1,1", "2/13/2020,2,2"]
    with pytest.raises(ValueError, match="mix day-first and month-first"):
        read_export("mixed.csv", export(rows=rows, metadata_lines=1))


def test_iso_dates_are_read_as_they_are():
    rows = ["2020-01-02,1,1", "2020-01-03,2,2"]
    series = read_export("iso.csv", export(rows=rows, metadata_lines=1)).series
    assert series.index.tolist() == ["2020-01-02", "2020-01-03"]


def test_a_time_of_day_after_the_date_is_ignored():
    rows = ["1/2/2020 0:00,1,1", "1/3/2020 0:00,2,2"]
    series = read_export("t.csv", export(rows=rows, metadata_lines=1)).series
    assert series.index.tolist() == ["2020-01-02", "2020-01-03"]


def test_a_file_with_no_readable_dates_is_refused():
    rows = ["yesterday,1,1", "today,2,2"]
    with pytest.raises(ValueError, match="no recognisable dates"):
        read_export("words.csv", export(rows=rows, metadata_lines=1))


@pytest.mark.parametrize(
    ("strings", "expected"),
    [
        (["1/2/2020", "1/3/2020"], MONTH_FIRST),
        (["13/2/2020"], DAY_FIRST),
        (["2/13/2020"], MONTH_FIRST),
        (["2020-01-02"], ISO),
        (["1-2-2020", "1-31-2020"], MONTH_FIRST),
    ],
)
def test_date_order_from_the_dates_alone(strings, expected):
    assert date_order(strings) == expected


# --- a repeated date within one export ----------------------------------------


def test_a_repeated_date_keeps_the_last_value_and_says_so():
    rows = ["1/2/2020,100.0,1", "1/2/2020,101.0,1", "1/3/2020,102.0,1"]
    exported = read_export("rev.csv", export(rows=rows))

    assert exported.series.tolist() == [101.0, 102.0]
    (note,) = exported.notes
    assert "rev.csv" in note
    assert "2020-01-02" in note
    assert "last value" in note


def test_the_repeat_note_reaches_the_conversion_report():
    rows = ["1/2/2020,100.0,1", "1/2/2020,101.0,1"]
    _, report = combine([read_export("rev.csv", export(rows=rows))])
    assert any("2020-01-02" in note for note in report.notes)
    assert "note" in report.describe()


# --- joined through the same converter as the workbooks ----------------------


def test_csv_exports_join_into_the_contract_shape():
    exports = [
        read_export("spx.csv", export("SPX Index")),
        read_export("vix.csv", export("VIX Index", rows=["1/2/2020,14,1", "1/3/2020,13.5,1"])),
    ]
    frame, report = combine(exports)

    assert list(frame.columns) == ["date", "spx_close", "vix"]
    assert frame["date"].tolist() == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert frame["vix"].isna().sum() == 1, "the date only SPX saw is kept, VIX blank"
    assert report.used == {"spx_close": "SPX Index", "vix": "VIX Index"}


def test_the_term_spread_is_derived_from_two_csv_legs():
    exports = [
        read_export("t10.csv", export("USGG10YR Index", rows=["1/2/2020,4.2,1", "1/3/2020,4.3,1"])),
        read_export("t2.csv", export("USGG2YR Index", rows=["1/2/2020,3.6,1", "1/3/2020,3.8,1"])),
    ]
    frame, report = combine(exports)

    assert frame["term_spread"].round(2).tolist() == [0.6, 0.5]
    assert report.used["term_spread"] == "USGG10YR Index minus USGG2YR Index"


def test_a_near_miss_ticker_in_a_csv_says_what_to_export_instead():
    _, report = combine([read_export("hy.csv", export("LF98TRUU Index"))])
    (note,) = report.skipped
    assert "hy.csv" in note
    assert "LF98OAS Index" in note
