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
    b"date,spx_close,bond_index_global_agg,vix,tnx_close,dollar_index,"
    b"eur_fx_vol,credit_spread_ig,"
    b"credit_spread_hy,breakeven_5y,breakeven_10y,term_spread,fx_impl_vol,"
    b"ff_mkt_rf,ff_smb,ff_hml,ff_rmw,ff_cma,ff_rf\n"
    b"2026-01-02,4750.5,102.3,13.2,4.0,100.0,10.0,1.0,3.0,2.0,8.4,2.31,1.12,0.05,0.02,0.01,0.02,0.01,0.01\n"
    b"2026-01-05,4762.1,102.1,12.9,4.1,101.0,11.0,1.1,3.1,2.1,8.3,2.33,1.11,0.02,0.01,0.02,0.01,0.01,0.01\n"
    b"2026-01-06,4739.8,102.6,14.1,4.2,102.0,12.0,1.2,3.2,2.2,8.9,2.29,1.15,0.01,0.03,0.01,0.02,0.01,0.01\n"
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


def confirmation(result):
    """The upload panel's own success message.

    Schema validation adds a second success below it, so select by content
    rather than assuming this page shows exactly one.
    """
    (message,) = [s for s in result.success if s.value.startswith("Accepted ")]
    return message


# --- AC1: a valid CSV is accepted with a confirmation ----------------------


def test_a_valid_csv_is_accepted_and_confirmed(page):
    result = upload(page, "signals.csv", VALID_CSV)

    assert not result.error
    success = confirmation(result)
    assert "signals.csv" in success.value
    assert "3 rows" in success.value
    assert "19 columns" in success.value


def test_the_confirmation_reports_the_date_range(page):
    success = confirmation(upload(page, "signals.csv", VALID_CSV))
    assert "2026-01-02 to 2026-01-06" in success.value


def test_a_valid_upload_is_written_to_the_history_log(page, tmp_path):
    upload(page, "signals.csv", VALID_CSV)

    (row,) = recent_uploads(db_path=tmp_path / "data" / "forecasting.duckdb")
    assert row.filename == "signals.csv"
    assert row.row_count == 3


def test_the_preview_shows_the_earliest_rows_of_a_long_file(page):
    # Revert of the dual render: a file longer than the preview window shows one
    # table of its earliest rows, the window in which every source — the
    # Fama-French factors included — has data. The newest rows, past where the
    # factors publish, are cut off.
    extra = b"".join(
        (
            f"2026-01-{day:02d},4750.5,102.3,13.2,4.0,100.0,10.0,1.0,3.0,2.0,"
            "8.4,2.31,1.12,0.05,0.02,0.01,0.02,0.01,0.01\n"
        ).encode()
        for day in range(9, 17)
    )
    result = upload(page, "long.csv", VALID_CSV + extra)

    marks = [m.value for m in result.markdown]
    assert "Newest rows" not in " ".join(marks)

    (preview,) = [d.value for d in result.dataframe if "date" in d.value.columns]
    assert str(preview["date"].iloc[0])[:10] == "2026-01-02"  # the earliest date
    assert str(preview["date"].iloc[-1])[:10] == "2026-01-15"  # newest is cut off
    assert preview["ff_mkt_rf"].iloc[0] == 0.05  # a Fama-French value is shown


def test_the_confirmation_explains_empty_cells_instead_of_silently_drawing_them(page):
    # The preview caption must answer "why is this blank" where the user can see
    # it, not force a trip to a spreadsheet. Past a fully-populated file it says
    # nothing; past one with blanks it names the column and the count.
    upload(page, "signals.csv", VALID_CSV)
    contents = "\n".join(c.value for c in page.caption)
    assert "Empty cells:" not in contents

    gap = VALID_CSV.replace(b",4739.8,102.6,14.1,", b",,,,")
    upload(page, "gap.csv", gap)
    contents = "\n".join(c.value for c in page.caption)
    assert "Empty cells:" in contents
    assert "spx_close" in contents


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


def test_the_page_states_the_documented_limit(page):
    # The caption is the only place a limit is quoted; Streamlit's own looser
    # number is hidden. If this stops matching the constant, the two have drifted.
    assert f"up to {MAX_UPLOAD_BYTES // 1_000_000} MB" in page.caption[0].value


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
