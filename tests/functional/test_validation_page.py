"""The validation acceptance criteria, driven through the real Data page."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.store.validations import recent_validations

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"

HEADER = (
    "date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    "fx_impl_vol,breakeven_10y,term_spread"
)
ROWS = [
    "2024-01-01,100.0,50.0,15.0,3.5,1.2,8.0,2.2,1.0",
    "2024-01-02,101.0,50.1,16.0,3.6,1.2,8.1,2.2,1.0",
    "2024-01-03,102.0,50.2,17.0,3.7,1.3,8.2,2.3,1.1",
]

VALIDATED_KEY = "validated_upload"


def csv_bytes(rows=None, header=HEADER) -> bytes:
    return ("\n".join([header, *(rows or ROWS)]) + "\n").encode()


def without_vix() -> bytes:
    header = HEADER.replace(",vix", "")
    rows = [",".join(r.split(",")[:3] + r.split(",")[4:]) for r in ROWS]
    return csv_bytes(rows, header)


def with_text_in_vix() -> bytes:
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",not-a-number,")
    return csv_bytes(rows)


@pytest.fixture
def page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    return app


def upload(page, data, filename="signals.csv"):
    page.file_uploader[0].set_value((filename, data, "text/csv"))
    return page.run()


def texts(elements):
    return " ".join(e.value for e in elements)


# --- AC1: a missing column is named and blocks -----------------------------


def test_a_missing_column_is_named_on_the_page(page):
    result = upload(page, without_vix())

    assert "vix" in texts(result.error)


def test_a_missing_column_halts_the_pipeline(page):
    result = upload(page, without_vix())

    assert VALIDATED_KEY not in result.session_state
    assert "halted" in texts(result.caption).lower()


# --- AC2: a wrong data type reports the row and column ---------------------


def test_text_in_a_numeric_column_reports_the_column_and_line(page):
    result = upload(page, with_text_in_vix())

    message = texts(result.error)
    assert "vix" in message
    assert "line 3" in message


def test_a_type_error_halts_the_pipeline(page):
    result = upload(page, with_text_in_vix())
    assert VALIDATED_KEY not in result.session_state


# --- AC3: a conforming file proceeds to data preparation -------------------


def test_a_conforming_file_is_confirmed_and_proceeds(page):
    result = upload(page, csv_bytes())

    assert not result.error
    assert "Proceeding to data preparation" in texts(result.success)


def test_a_conforming_file_unlocks_the_preparation_gate(page):
    result = upload(page, csv_bytes())

    validated = result.session_state[VALIDATED_KEY]
    assert validated.frame.shape == (3, 9)
    assert validated.result.passed


def test_a_file_with_only_warnings_still_proceeds(page):
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",900.0,")
    result = upload(page, csv_bytes(rows))

    assert not result.error
    assert "Proceeding to data preparation" in texts(result.success)
    assert VALIDATED_KEY in result.session_state


# --- AC4: results are logged and surfaced in the quality report ------------


def test_the_quality_report_is_shown(page):
    result = upload(page, csv_bytes())
    assert "Data quality report" in texts(result.markdown)


def test_the_report_counts_blocking_and_warning_issues(page):
    result = upload(page, with_text_in_vix())

    labels = {m.label: m.value for m in result.metric}
    assert labels["Blocking"] == "1"
    assert labels["Warnings"] == "0"
    assert labels["Rows checked"] == "3"


def test_a_passing_validation_is_logged(page, tmp_path):
    upload(page, csv_bytes())

    (row,) = recent_validations(db_path=tmp_path / "data" / "forecasting.duckdb")
    assert row.passed is True
    assert row.filename == "signals.csv"


def test_a_failing_validation_is_logged_with_its_issues(page, tmp_path):
    upload(page, without_vix())

    (row,) = recent_validations(db_path=tmp_path / "data" / "forecasting.duckdb")
    assert row.passed is False
    assert row.issues[0]["column"] == "vix"


def test_a_clean_file_reports_no_issues(page):
    result = upload(page, csv_bytes())
    assert "No issues found." in texts(result.caption)


# --- the shared quality report model on the page ---------------------------


def test_the_report_is_available_to_later_pages(page):
    result = upload(page, csv_bytes())

    report = result.session_state["quality_report"]
    assert report.source.name == "signals.csv"
    assert report.coverage.rows == 3
    assert report.coverage.columns == 9


def test_checks_that_have_not_been_built_show_as_pending(page):
    # FYP-25 requires a pending state rather than a blank or broken view.
    result = upload(page, csv_bytes())

    caption = texts(result.caption)
    assert "Checks not yet run" in caption
    for title in ("Outliers", "Data gaps", "Missing values"):
        assert title in caption


def test_schema_does_not_appear_as_pending_once_it_has_run(page):
    result = upload(page, csv_bytes())
    assert "Schema validation," not in texts(result.caption)


def test_the_report_shows_the_coverage_period(page):
    result = upload(page, csv_bytes())
    assert "2024-01-01 to 2024-01-03" in texts(result.caption)


def test_a_finding_shows_the_date_of_the_offending_row(page):
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",900.0,")
    result = upload(page, csv_bytes(rows))

    report = result.session_state["quality_report"]
    (found,) = report.findings
    assert found.signal == "vix"
    assert found.dates == ("2024-01-02",)


def test_a_blocking_report_is_still_readable(page):
    result = upload(page, without_vix())

    report = result.session_state["quality_report"]
    assert report.status.value == "failed"
    assert not report.passed
    assert list(report.by_signal()) == ["vix"]
