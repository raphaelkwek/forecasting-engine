"""Upload through validation to the data-preparation gate, chained end to end.

Picks up where the upload flow leaves off: bytes on the wire become an accepted
file, an accepted file becomes a validation verdict, and a passing verdict
becomes the token data preparation will demand.
"""

import pytest

from forecasting_engine.ingest.upload import accept_upload
from forecasting_engine.ingest.validation import (
    ValidatedUpload,
    ValidationFailed,
    require_valid,
    validate_upload,
)
from forecasting_engine.store.uploads import recent_uploads, record_upload
from forecasting_engine.store.validations import (
    latest_validation,
    recent_validations,
    record_validation,
)

HEADER = (
    "date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    "fx_impl_vol,breakeven_10y,term_spread"
)
ROWS = [
    "2024-01-01,100.0,50.0,15.0,3.5,1.2,8.0,2.2,1.0",
    "2024-01-02,101.0,50.1,16.0,3.6,1.2,8.1,2.2,1.0",
    "2024-01-03,102.0,50.2,17.0,3.7,1.3,8.2,2.3,1.1",
]


def csv_bytes(rows=None, header=HEADER) -> bytes:
    return ("\n".join([header, *(rows or ROWS)]) + "\n").encode()


@pytest.fixture(autouse=True)
def in_a_scratch_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def ingest(data: bytes, name: str = "signals.csv"):
    """The whole chain a file goes through, exactly as the page runs it."""
    accepted = accept_upload(name, data)
    record_upload(accepted)
    result = validate_upload(accepted)
    record_validation(result)
    return accepted, result


def test_a_conforming_file_reaches_the_preparation_gate():
    accepted, result = ingest(csv_bytes())

    validated = require_valid(accepted, result)
    assert isinstance(validated, ValidatedUpload)
    assert validated.frame.shape == (3, 9)
    assert validated.source.sha256 == accepted.source.sha256


def test_both_logs_record_the_same_file(in_a_scratch_workspace):
    accepted, _ = ingest(csv_bytes())

    (upload_row,) = recent_uploads()
    (validation_row,) = recent_validations()
    assert upload_row.sha256 == validation_row.sha256 == accepted.source.sha256
    assert validation_row.passed is True


def test_a_missing_column_stops_the_chain_and_is_logged():
    header = HEADER.replace(",vix", "")
    rows = [",".join(r.split(",")[:3] + r.split(",")[4:]) for r in ROWS]
    accepted, result = ingest(csv_bytes(rows, header))

    with pytest.raises(ValidationFailed) as exc:
        require_valid(accepted, result)
    assert "vix" in exc.value.message

    (row,) = recent_validations()
    assert row.passed is False
    assert row.issues[0]["kind"] == "missing_column"
    assert row.issues[0]["column"] == "vix"


def test_a_type_error_stops_the_chain_and_keeps_the_line_number():
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",not-a-number,")
    accepted, result = ingest(csv_bytes(rows))

    with pytest.raises(ValidationFailed):
        require_valid(accepted, result)

    (row,) = recent_validations()
    (issue,) = [i for i in row.issues if i["kind"] == "non_numeric"]
    assert issue["column"] == "vix"
    assert issue["rows"] == [3]


def test_a_rejected_file_is_still_stored_and_still_logged_as_an_upload():
    # The file arrived and is on disk; it is the *schema* that failed. Keeping
    # the upload row means the history shows the attempt rather than a gap.
    rows = list(ROWS)
    rows[0] = rows[0].replace(",15.0,", ",oops,")
    accepted, _ = ingest(csv_bytes(rows))

    assert accepted.source.path.exists()
    assert len(recent_uploads()) == 1


def test_a_warning_does_not_stop_the_chain():
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",900.0,")
    accepted, result = ingest(csv_bytes(rows))

    validated = require_valid(accepted, result)
    assert validated.result.warnings
    (row,) = recent_validations()
    assert row.passed is True
    assert row.warning_count == 1


def test_the_verdict_for_a_file_can_be_looked_up_by_hash():
    accepted, _ = ingest(csv_bytes())

    found = latest_validation(accepted.source.sha256)
    assert found is not None
    assert found.filename == "signals.csv"
    assert found.passed is True


def test_re_uploading_a_fixed_file_supersedes_the_earlier_verdict():
    broken = list(ROWS)
    broken[1] = broken[1].replace(",16.0,", ",oops,")
    ingest(csv_bytes(broken), "signals.csv")

    fixed_accepted, fixed_result = ingest(csv_bytes(), "signals.csv")

    assert len(recent_validations()) == 2
    assert recent_validations()[0].passed is True
    assert require_valid(fixed_accepted, fixed_result).frame.shape == (3, 9)
