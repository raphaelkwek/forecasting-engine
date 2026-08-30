"""The three acceptance criteria, driven through the real Streamlit page.

Each test walks the journey a portfolio manager takes: open the Data page,
choose a file, look at what the page says back. Streamlit's AppTest drives the
actual ``st.file_uploader`` widget, so these exercise the page as shipped
rather than a stand-in for it.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.ingest.upload import MAX_UPLOAD_BYTES
from forecasting_engine.store.uploads import recent_uploads

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"

VALID_CSV = (
    b"date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    b"fx_impl_vol,breakeven_10y,term_spread\n"
    b"2026-01-02,4750.5,102.3,13.2,3.41,1.12,8.4,2.31,0.62\n"
    b"2026-01-05,4762.1,102.1,12.9,3.38,1.11,8.3,2.33,0.64\n"
    b"2026-01-06,4739.8,102.6,14.1,3.55,1.15,8.9,2.29,0.59\n"
)

XLSX_BYTES = b"PK\x03\x04\x14\x00\x08\x08\x08\x00" + bytes(range(256)) * 4

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def oversized_csv() -> bytes:
    """Just over the limit, derived from it so the two cannot drift apart.

    Built on demand rather than held in a module constant, so that a failing
    assertion does not try to render 25 MB of bytes into the report.
    """
    row = b"2026-01-02,4750.5\n"
    return b"date,spx_close\n" + row * (MAX_UPLOAD_BYTES // len(row) + 1)


@pytest.fixture
def page(tmp_path, monkeypatch):
    """The Data page, rooted in a scratch directory so uploads stay disposable."""
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    return app


def upload(page, filename, data, mime="text/csv"):
    page.file_uploader[0].set_value((filename, data, mime))
    return page.run()


# --- AC1: a valid CSV is accepted with a confirmation ----------------------


def test_a_valid_csv_is_accepted_and_confirmed(page):
    result = upload(page, "signals.csv", VALID_CSV)

    assert not result.error
    (success,) = result.success
    assert "signals.csv" in success.value
    assert "3 rows" in success.value
    assert "9 columns" in success.value


def test_the_confirmation_reports_the_date_range(page):
    (success,) = upload(page, "signals.csv", VALID_CSV).success
    assert "2026-01-02 to 2026-01-06" in success.value


def test_a_valid_upload_is_written_to_the_history_log(page, tmp_path):
    upload(page, "signals.csv", VALID_CSV)

    (row,) = recent_uploads(db_path=tmp_path / "data" / "forecasting.duckdb")
    assert row.filename == "signals.csv"
    assert row.row_count == 3


def test_the_uploaded_file_is_kept_for_later_pages(page):
    result = upload(page, "signals.csv", VALID_CSV)

    accepted = result.session_state["accepted_upload"]
    assert accepted.row_count == 3
    assert accepted.source.name == "signals.csv"


# --- AC2: a non-CSV file is rejected with an error -------------------------


def test_a_spreadsheet_is_rejected_with_an_error(page):
    result = upload(page, "q1-export.xlsx", XLSX_BYTES, mime=XLSX_MIME)

    assert not result.success
    (error,) = result.error
    assert ".xlsx" in error.value
    assert ".csv" in error.value


def test_a_renamed_spreadsheet_is_rejected_too(page):
    result = upload(page, "q1-export.csv", XLSX_BYTES)

    assert not result.success
    (error,) = result.error
    assert "could not be read as a CSV" in error.value


def test_the_uploader_does_not_filter_by_type_in_the_browser(page):
    # If it did, a non-CSV would never reach the server and AC2's error could
    # never be shown. This is load-bearing, not incidental.
    assert page.file_uploader[0].allowed_type == []


# --- AC3: an oversized file is rejected with a size-limit error ------------


def test_an_oversized_file_is_rejected_with_the_limit_quoted(page):
    result = upload(page, "decades.csv", oversized_csv())

    assert not result.success
    (error,) = result.error
    assert "25.0 MB" in error.value
    assert "over the" in error.value


# --- rejections leave no trace ---------------------------------------------


@pytest.mark.parametrize("case", ["wrong-type", "oversized"])
def test_a_rejected_upload_is_not_logged(page, tmp_path, case):
    if case == "wrong-type":
        upload(page, "q1.xlsx", XLSX_BYTES, mime=XLSX_MIME)
    else:
        upload(page, "decades.csv", oversized_csv())

    db = tmp_path / "data" / "forecasting.duckdb"
    assert not db.exists() or recent_uploads(db_path=db) == []
