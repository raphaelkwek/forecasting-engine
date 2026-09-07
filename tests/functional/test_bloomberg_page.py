"""Building the signal CSV from Bloomberg exports, driven through the real Data page.

The journey: choose "Bloomberg exports", drop in one file per security, read
what the page says back. The merged file must then go through the same
validation as a file uploaded directly, which is what most of these check.
"""

from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.ingest import fama_french
from forecasting_engine.store.uploads import recent_uploads

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"

BLOOMBERG = "Bloomberg exports"
DATES = ["1/2/2020", "1/3/2020", "1/6/2020"]

FAKE_FACTORS = pd.DataFrame(
    {"Date": pd.to_datetime(["2020-01-02", "2020-01-03"]), "Mkt-RF": [0.1, -0.2]}
)


def export(security: str, values=(1.0, 2.0, 3.0), field="PX_LAST") -> bytes:
    rows = [f"{date},{value},#N/A N/A" for date, value in zip(DATES, values, strict=True)]
    lines = [f"Security,{security}", "Period,Daily", "", f"Date,{field},PX_BID", *rows]
    return ("\n".join(lines) + "\n").encode()


def every_signal() -> list[tuple[str, bytes, str]]:
    """One export per security the contract asks for, legs included."""
    securities = [
        "SPX Index",
        "LEGATRUU Index",
        "VIX Index",
        "LF98OAS Index",
        "LUACOAS Index",
        "JPMVXYG7 Index",
        "USGGBE10 Index",
        "USGG10YR Index",
        "USGG2YR Index",
    ]
    return [
        (f"{s.split()[0].lower()}.csv", export(s, (1.0, 1.1, 1.2)), "text/csv") for s in securities
    ]


@pytest.fixture
def page(tmp_path, monkeypatch):
    """The Data page in Bloomberg mode, rooted in a scratch directory."""
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    app.radio[0].set_value(BLOOMBERG)
    app.run()
    return app


def upload(page, files):
    page.file_uploader[0].set_value(files)
    return page.run()


def texts(elements):
    return " ".join(e.value for e in elements)


# --- the page ------------------------------------------------------------------


def test_the_signal_csv_is_the_default_way_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    assert app.radio[0].value == "A signal CSV"


def test_nothing_is_said_before_a_file_is_uploaded(page):
    assert not page.success
    assert not page.error


def test_the_uploader_takes_several_files_and_does_not_filter_in_the_browser(page):
    assert page.file_uploader[0].accept_multiple_files is True
    assert page.file_uploader[0].allowed_type == []


# --- merging -------------------------------------------------------------------


def test_two_exports_are_merged_into_one_upload(page):
    result = upload(
        page,
        [
            ("spx.csv", export("SPX Index"), "text/csv"),
            ("vix.csv", export("VIX Index"), "text/csv"),
        ],
    )

    assert "Merged 2 exports into bloomberg_signals.csv" in texts(result.success)
    accepted = result.session_state["accepted_upload"]
    assert accepted.row_count == 3
    assert list(accepted.frame.columns) == ["date", "spx_close", "vix"]
    assert accepted.frame["date"].tolist() == ["2020-01-02", "2020-01-03", "2020-01-06"]


def test_the_page_says_which_signals_were_supplied_and_which_were_not(page):
    result = upload(page, [("spx.csv", export("SPX Index"), "text/csv")])

    body = texts(result.markdown)
    assert "spx_close" in body and "Supplied" in body
    assert "credit_spread_hy" in body and "Missing" in body


def test_a_near_miss_ticker_is_explained_on_the_page(page):
    result = upload(page, [("hy.csv", export("LF98TRUU Index"), "text/csv")])

    warnings = texts(result.warning)
    assert "LF98OAS Index" in warnings
    assert "total return index" in warnings


def test_a_file_that_is_not_an_export_is_reported_not_fatal(page):
    result = upload(
        page,
        [
            ("notes.csv", b"just,some,text\n1,2,3\n", "text/csv"),
            ("spx.csv", export("SPX Index"), "text/csv"),
        ],
    )

    assert not result.exception
    assert "no 'Date,...' header row" in texts(result.error)
    assert "Merged 1 export" in texts(result.success), "one bad file must not lose the good one"


def test_a_spreadsheet_is_refused_by_extension(page):
    xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    result = upload(page, [("spx.xlsx", export("SPX Index"), xlsx)])

    assert ".csv" in texts(result.error)
    assert not result.success


def test_the_merged_file_can_be_downloaded(page):
    result = upload(page, [("spx.csv", export("SPX Index"), "text/csv")])
    assert "Signals (.csv)" in [d.label for d in result.download_button]


def test_the_merge_is_logged_as_an_upload_once(page, tmp_path):
    result = upload(page, [("spx.csv", export("SPX Index"), "text/csv")])
    result.run()  # a rerun must not log it again

    (row,) = recent_uploads(db_path=tmp_path / "data" / "forecasting.duckdb")
    assert row.filename == "bloomberg_signals.csv"
    assert row.row_count == 3


# --- the merged file goes through the contract validation --------------------


def test_a_partial_merge_is_validated_and_halts_on_the_missing_signals(page):
    result = upload(page, [("spx.csv", export("SPX Index"), "text/csv")])

    assert "validated_upload" not in result.session_state
    assert "credit_spread_hy" in texts(result.error)
    assert result.session_state["quality_report"].source.name == "bloomberg_signals.csv"


def test_a_complete_merge_passes_validation_and_unlocks_preparation(page):
    result = upload(page, every_signal())

    assert "Proceeding to data preparation" in texts(result.success)
    validated = result.session_state["validated_upload"]
    assert validated.frame.shape == (3, 9)
    assert validated.result.passed


def test_the_quality_report_runs_on_the_merged_file(page):
    result = upload(page, every_signal())

    statuses = {s.check: s.status.value for s in result.session_state["quality_report"].sections}
    assert "pending" not in statuses.values()


# --- the Fama-French factors -----------------------------------------------------


def test_nothing_downloads_until_asked(page):
    result = upload(page, every_signal())
    assert "No factor file yet" in texts(result.info)
    assert "Download the latest factors" in [b.label for b in result.button]


def test_a_download_is_kept_and_previewed(page, tmp_path, monkeypatch):
    monkeypatch.setattr(fama_french, "fetch", lambda: FAKE_FACTORS)
    result = upload(page, every_signal())

    button = next(b for b in result.button if b.label == "Download the latest factors")
    result = button.click().run()

    assert "2 rows within the signals' dates" in texts(result.caption)
    labels = [d.label for d in result.download_button]
    assert "Fama-French (.csv)" in labels
    assert "Signals + Fama-French (.xlsx)" in labels
    stored = list((tmp_path / "data" / "fama_french").glob("*.csv"))
    assert len(stored) == 1


def test_a_failed_download_is_an_error_not_a_crash(page, monkeypatch):
    def broken():
        raise fama_french.FactorFetchError("URLError: no route to host")

    monkeypatch.setattr(fama_french, "fetch", broken)
    result = upload(page, every_signal())
    button = next(b for b in result.button if b.label == "Download the latest factors")
    result = button.click().run()

    assert not result.exception
    assert "Could not download the factor file" in texts(result.error)
