"""The validation acceptance criteria, driven through the real Data page."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.store.validations import recent_validations

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"

HEADER = (
    "date,spx_close,bond_index_global_agg,vix,tnx_close,dollar_index,"
    "eur_fx_vol,credit_spread_ig,"
    "credit_spread_hy,breakeven_5y,breakeven_10y,term_spread,fx_impl_vol,"
    "ff_mkt_rf,ff_smb,ff_hml,ff_rmw,ff_cma,ff_rf"
)
ROWS = [
    "2024-01-01,100.0,50.0,15.0,4.0,100.0,10.0,1.0,3.0,2.0,8.0,2.2,10.0,0.05,0.02,0.01,0.02,0.01,0.01",
    "2024-01-02,101.0,50.1,16.0,4.1,101.0,11.0,1.1,3.1,2.1,8.1,2.3,11.0,0.02,0.01,0.02,0.01,0.01,0.01",
    "2024-01-03,102.0,50.2,17.0,4.2,102.0,12.0,1.2,3.2,2.2,8.2,2.4,12.0,0.01,0.03,0.01,0.02,0.01,0.01",
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
    assert validated.frame.shape == (3, 19)
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
    assert report.coverage.columns == 19


def test_no_check_is_left_pending_on_a_valid_upload(page):
    result = upload(page, csv_bytes())

    assert "Checks not yet run" not in texts(result.caption)
    statuses = {s.check: s.status.value for s in result.session_state["quality_report"].sections}
    assert "pending" not in statuses.values()


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


# --- FYP-9: reviewing flagged outliers on the page -------------------------


def spiked_csv() -> bytes:
    """A file with one obvious anomaly, inside the contract's ranges."""
    rows = list(ROWS)
    for i in range(60):
        day = f"2024-02-{i % 28 + 1:02d}" if i >= 28 else f"2024-01-{i + 4:02d}"
        rows.append(f"{day},{100 + i}.0,50.0,15.{i % 9},4.0,100.0,10.0,1.0,3.0,2.0,8.0,2.2,10.0,0.05,0.02,0.01,0.02,0.01,0.01")  # noqa: E501
    rows[30] = rows[30].replace(",15.", ",190.", 1)
    return csv_bytes(sorted(rows))


def test_a_flagged_outlier_can_be_reviewed_on_the_page(page):
    result = upload(page, spiked_csv())

    report = result.session_state["quality_report"]
    flagged = [f for f in report.findings if f.check == "outliers"]
    assert flagged, "expected the injected spike to be flagged"
    assert all(f.severity.value == "info" for f in flagged)


def test_flagged_outliers_do_not_stop_the_pipeline(page):
    result = upload(page, spiked_csv())

    assert "validated_upload" in result.session_state
    assert result.session_state["quality_report"].passed


def test_everything_starts_included(page):
    result = upload(page, spiked_csv())

    report = result.session_state["quality_report"]
    assert report.excluded == ()


def test_the_prepared_frame_matches_the_upload_until_something_is_excluded(page):
    result = upload(page, spiked_csv())

    prepared = result.session_state["prepared_frame"]
    accepted = result.session_state["accepted_upload"]
    assert prepared.equals(accepted.frame)


def test_the_review_control_appears_when_something_is_flagged(page):
    # AppTest has no data_editor accessor in Streamlit 1.62, so the expander
    # wrapping it is the testable surface.
    result = upload(page, spiked_csv())
    labels = [e.label for e in result.expander]
    assert any("Review outliers" in label for label in labels), labels


def test_no_review_control_when_nothing_is_flagged(page):
    result = upload(page, csv_bytes())
    assert not any("Review outliers" in e.label for e in result.expander)
