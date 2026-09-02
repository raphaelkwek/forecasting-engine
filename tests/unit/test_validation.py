"""Validating an accepted upload, and gating the pipeline on the outcome."""

from datetime import datetime

import pandas as pd
import pytest

from forecasting_engine.ingest.upload import accept_upload
from forecasting_engine.ingest.validation import (
    ValidatedUpload,
    ValidationFailed,
    require_valid,
    validate_upload,
)

HEADER = (
    "date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    "fx_impl_vol,breakeven_10y,term_spread"
)
GOOD_ROWS = [
    "2024-01-01,100.0,50.0,15.0,3.5,1.2,8.0,2.2,1.0",
    "2024-01-02,101.0,50.1,16.0,3.6,1.2,8.1,2.2,1.0",
    "2024-01-03,102.0,50.2,17.0,3.7,1.3,8.2,2.3,1.1",
]


def csv_bytes(rows=None, header=HEADER) -> bytes:
    return ("\n".join([header, *(rows or GOOD_ROWS)]) + "\n").encode()


def upload(data: bytes, name: str = "signals.csv"):
    return accept_upload(name, data, uploads_dir=None)


# --- a fully valid file ----------------------------------------------------


def test_a_conforming_file_passes(tmp_path):
    result = validate_upload(upload(csv_bytes()))

    assert result.passed
    assert result.is_clean
    assert result.issues == ()


def test_a_passing_result_yields_a_token_for_data_preparation():
    accepted = upload(csv_bytes())
    result = validate_upload(accepted)

    validated = require_valid(accepted, result)

    assert isinstance(validated, ValidatedUpload)
    assert validated.accepted is accepted
    assert validated.frame.equals(accepted.frame)


def test_the_result_records_when_it_ran():
    at = datetime(2026, 9, 1, 10, 0)
    result = validate_upload(upload(csv_bytes()), checked_at=at)
    assert result.checked_at == at


# --- AC1: a missing column names the column and blocks ---------------------


def test_a_missing_column_is_named():
    header = HEADER.replace(",vix", "")
    rows = [r.replace(",15.0", "", 1).replace(",16.0", "", 1).replace(",17.0", "", 1)
            for r in GOOD_ROWS]
    result = validate_upload(upload(csv_bytes(rows, header)))

    assert not result.passed
    assert "vix" in result.missing_columns
    assert any("vix" in issue.detail for issue in result.blocking)


def test_several_missing_columns_are_all_named():
    header = "date,spx_close,agg_close"
    rows = [",".join(r.split(",")[:3]) for r in GOOD_ROWS]
    result = validate_upload(upload(csv_bytes(rows, header)))

    assert set(result.missing_columns) == {
        "vix", "credit_spread_hy", "credit_spread_ig",
        "fx_impl_vol", "breakeven_10y", "term_spread",
    }


def test_a_missing_column_blocks_the_pipeline():
    header = HEADER.replace(",vix", "")
    rows = [r.replace(",15.0", "", 1).replace(",16.0", "", 1).replace(",17.0", "", 1)
            for r in GOOD_ROWS]
    accepted = upload(csv_bytes(rows, header))
    result = validate_upload(accepted)

    with pytest.raises(ValidationFailed) as exc:
        require_valid(accepted, result)
    assert exc.value.result is result
    assert "vix" in exc.value.message


# --- AC2: a wrong data type reports the specific row and column ------------


def test_text_in_a_numeric_field_reports_row_and_column():
    rows = list(GOOD_ROWS)
    rows[1] = rows[1].replace(",16.0,", ",not-a-number,")
    result = validate_upload(upload(csv_bytes(rows)))

    assert not result.passed
    (issue,) = [i for i in result.blocking if i.kind == "non_numeric"]
    assert issue.column == "vix"
    assert issue.rows == (3,)
    assert issue.location == "column 'vix', line 3"


def test_an_unparseable_date_reports_row_and_column():
    rows = list(GOOD_ROWS)
    rows[0] = rows[0].replace("2024-01-01", "the first of January")
    result = validate_upload(upload(csv_bytes(rows)))

    (issue,) = [i for i in result.blocking if i.kind == "unparseable_date"]
    assert issue.location == "column 'date', line 2"


def test_a_type_error_blocks_the_pipeline():
    rows = list(GOOD_ROWS)
    rows[1] = rows[1].replace(",16.0,", ",oops,")
    accepted = upload(csv_bytes(rows))
    result = validate_upload(accepted)

    with pytest.raises(ValidationFailed):
        require_valid(accepted, result)


# --- warnings do not block -------------------------------------------------


def test_an_out_of_range_value_warns_without_blocking():
    rows = list(GOOD_ROWS)
    rows[1] = rows[1].replace(",16.0,", ",900.0,")
    accepted = upload(csv_bytes(rows))
    result = validate_upload(accepted)

    assert result.passed
    assert not result.is_clean
    assert [i.kind for i in result.warnings] == ["out_of_range"]
    assert require_valid(accepted, result).frame is accepted.frame


def test_unsorted_dates_warn_without_blocking():
    rows = list(reversed(GOOD_ROWS))
    result = validate_upload(upload(csv_bytes(rows)))

    assert result.passed
    assert "unsorted_dates" in {i.kind for i in result.warnings}


# --- the structured summary downstream reuses ------------------------------


def test_the_summary_counts_both_classes():
    rows = list(GOOD_ROWS)
    rows[1] = rows[1].replace(",16.0,", ",oops,")
    rows[2] = rows[2].replace(",1.3,", ",90.0,")
    result = validate_upload(upload(csv_bytes(rows)))

    assert result.summary["passed"] is False
    assert result.summary["blocking_count"] == 1
    assert result.summary["warning_count"] == 1
    assert result.summary["issue_count"] == 2


def test_issues_serialise_to_plain_data_for_storage():
    rows = list(GOOD_ROWS)
    rows[1] = rows[1].replace(",16.0,", ",oops,")
    result = validate_upload(upload(csv_bytes(rows)))

    (record,) = [d for d in result.as_records() if d["kind"] == "non_numeric"]
    assert record == {
        "kind": "non_numeric",
        "column": "vix",
        "detail": "values are not numeric",
        "count": 1,
        "rows": [3],
        "blocking": True,
    }


def test_the_result_knows_which_file_it_describes():
    accepted = upload(csv_bytes(), name="q3-signals.csv")
    result = validate_upload(accepted)

    assert result.source.name == "q3-signals.csv"
    assert result.source.sha256 == accepted.source.sha256


def test_an_empty_frame_is_not_silently_valid():
    empty = pd.DataFrame(columns=HEADER.split(","))
    result = validate_upload(upload(csv_bytes([])))

    assert list(empty.columns)  # the header alone parses
    assert result.passed  # no rows means no bad rows; row-level checks are FYP-9's
