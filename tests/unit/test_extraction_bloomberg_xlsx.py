"""Reading Bloomberg .xlsx workbook exports into the open-schema shape.

The workbooks built here mirror the real exports: a ``Data`` sheet of dates
and every field present, a ``Metadata`` sheet naming the security.
"""

from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from forecasting_engine.extraction.bloomberg_xlsx import BloombergXlsxError, read_export

DATES = ["2024-01-01", "2024-01-02", "2024-01-03"]


def workbook_bytes(
    *,
    security="SPX Index",
    fields=("PX_LAST",),
    rows=(("2024-01-01", 100.0),),
    data_sheet="Data",
    with_metadata=True,
) -> bytes:
    """A workbook shaped like the real Bloomberg exports, as raw bytes."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = data_sheet
    sheet.append(["Date", *fields])
    for row in rows:
        date, *values = row
        sheet.append([datetime.fromisoformat(date), *values])
    if with_metadata:
        meta = book.create_sheet("Metadata")
        meta.append(["Field", "Value"])
        meta.append(["Security", security])
        meta.append(["Period", "D"])
    from io import BytesIO

    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_security_comes_from_the_metadata_sheet_not_the_filename():
    data = workbook_bytes(security="VIX Index")

    export = read_export("misleading_spx_name.xlsx", data)

    assert export.security == "VIX Index"


def test_every_field_in_the_data_sheet_is_kept_not_just_one():
    data = workbook_bytes(
        security="SPX Index",
        fields=("PX_LAST", "PX_BID", "TOT_RETURN_INDEX_GROSS_DVDS"),
        rows=[("2024-01-01", 100.0, 99.9, 105.0)],
    )

    export = read_export("spx.xlsx", data)

    assert set(export.frame.columns) == {
        "Date",
        "SPX_Index_PX_LAST",
        "SPX_Index_PX_BID",
        "SPX_Index_TOT_RETURN_INDEX_GROSS_DVDS",
    }


def test_placeholder_values_become_nan_not_a_literal_string():
    data = workbook_bytes(
        security="JPMVXYGL Index",
        fields=("PX_LAST", "PX_BID"),
        rows=[("2024-01-01", 6.5, "#N/A N/A"), ("2024-01-02", 6.6, "#N/A N/A")],
    )

    export = read_export("jpm.xlsx", data)

    assert export.frame["JPMVXYGL_Index_PX_BID"].isna().all()
    assert export.frame["JPMVXYGL_Index_PX_LAST"].tolist() == [6.5, 6.6]


def test_a_workbook_without_a_data_sheet_is_refused():
    data = workbook_bytes(data_sheet="Sheet1")

    with pytest.raises(BloombergXlsxError, match="no 'Data' sheet"):
        read_export("odd.xlsx", data)


def test_a_workbook_without_metadata_still_reads_with_an_empty_security():
    data = workbook_bytes(with_metadata=False)

    export = read_export("mystery.xlsx", data)

    assert export.security == ""


def test_a_repeated_date_keeps_the_last_value_and_reports_a_note():
    data = workbook_bytes(
        security="A Index",
        fields=("PX_LAST",),
        rows=[("2024-01-01", 1.0), ("2024-01-01", 2.0), ("2024-01-02", 3.0)],
    )

    export = read_export("a.xlsx", data)

    assert export.frame["A_Index_PX_LAST"].tolist() == [2.0, 3.0]
    assert len(export.notes) == 1
    assert "repeated date" in export.notes[0]


def test_dates_are_parsed_as_real_datetimes():
    data = workbook_bytes(rows=[(d, 1.0) for d in DATES])

    export = read_export("spx.xlsx", data)

    assert pd.api.types.is_datetime64_any_dtype(export.frame["Date"])
    assert export.frame["Date"].tolist() == [pd.Timestamp(d) for d in DATES]


def test_not_a_real_xlsx_file_is_refused_not_crashed():
    with pytest.raises(BloombergXlsxError, match="not a readable .xlsx"):
        read_export("fake.xlsx", b"this is not a zip file")
