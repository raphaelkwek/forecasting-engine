"""The Bloomberg extraction page, driven through the real Streamlit page."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.ingest.upload import MAX_UPLOAD_BYTES

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"
APP_DIR = REPO_ROOT / "app"

FAKE_FACTORS = pd.DataFrame({"Date": pd.to_datetime(["2020-01-02"]), "Mkt-RF": [0.1]})


def export(security, rows, fields="PX_LAST"):
    lines = [f"Security,{security}", "Period,Daily", "", f"Date,{fields}", *rows]
    return ("\n".join(lines) + "\n").encode()


SPX = export("SPX Index", ["1/2/2020,100.0", "1/3/2020,101.0"])
VIX = export("VIX Index", ["1/2/2020,15.0", "1/3/2020,16.0"])


@pytest.fixture(autouse=True)
def no_network_fetch(monkeypatch):
    """Stand in for the real Dartmouth download, which no test should reach."""
    sys.path.insert(0, str(APP_DIR))
    import bloomberg_extraction_panel

    monkeypatch.setattr(bloomberg_extraction_panel.fama_french, "fetch", lambda: FAKE_FACTORS)
    bloomberg_extraction_panel._fetch_fama_french.clear()


@pytest.fixture
def page(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    return app


def upload(page, files):
    page.file_uploader[0].set_value(files)
    return page.run()


def texts(elements):
    return " ".join(e.value for e in elements)


def test_nothing_is_shown_before_a_file_is_uploaded(page):
    assert not page.success
    assert not page.error


def test_multiple_files_are_merged_into_one_frame(page):
    result = upload(page, [("spx.csv", SPX, "text/csv"), ("vix.csv", VIX, "text/csv")])

    assert not result.error
    assert "Merged 2 file(s) into 2 rows, 2 data columns" in texts(result.success)


def test_original_exports_with_trailing_cells_and_any_field_merge_unchanged(page):
    total_return = (
        b"Security,SPX Index,\nPeriod,D,\n,,\n"
        b"Date,TOT_RETURN_INDEX_GROSS_DVDS,PX_BID\n"
        b"2024-01-02,100.0,99.9\n2024-01-03,101.0,100.9\n"
    )

    result = upload(page, [("spx-total-return.csv", total_return, "text/csv")])

    assert not result.error
    assert "Merged 1 file(s)" in texts(result.success)
    merged = result.session_state["extraction_merged"]
    assert "SPX_Index_TOT_RETURN_INDEX_GROSS_DVDS" in merged.columns


def test_a_file_with_no_date_header_is_reported_as_an_error_not_a_crash(page):
    result = upload(page, [("bad.csv", b"not,a,bloomberg,file\n1,2,3\n", "text/csv")])

    assert not result.exception
    assert "no 'Date,...' header row" in texts(result.error)


def test_the_coverage_metrics_are_shown_for_a_clean_file(page):
    result = upload(page, [("spx.csv", SPX, "text/csv")])

    labels = {m.label: m.value for m in result.metric}
    assert labels["Rows"] == "2"
    assert labels["Signals"] == "1"
    assert labels["Flagged"] == "0"
    assert "Nothing flagged" in texts(result.success)
    assert "02/01/2020 to 03/01/2020" in texts(result.caption)


def test_duplicate_dates_are_reported_and_named(page):
    # Same value both rows, so this exercises duplicate-date detection only —
    # not also the day-over-day move check.
    dup = export("A Index", ["1/2/2020,1.0", "1/2/2020,1.0"])
    result = upload(page, [("a.csv", dup, "text/csv")])

    labels = {m.label: m.value for m in result.metric}
    assert labels["Flagged"] == "1"
    assert any("Duplicate dates" in e.label for e in result.expander)
    assert "02/01/2020" in texts(result.markdown)


def test_all_three_downloads_are_offered_after_a_successful_merge(page):
    result = upload(page, [("spx.csv", SPX, "text/csv")])
    labels = [d.label for d in result.download_button]
    assert "Signals (.csv)" in labels
    assert "Fama-French only (.csv)" in labels
    assert "Workbook (.xlsx)" in labels


def test_fama_french_factors_are_previewed_on_the_page_not_only_in_the_download(page):
    result = upload(page, [("spx.csv", SPX, "text/csv")])
    assert "Fama-French Factors" in texts(result.markdown)
    assert "02/01/2020" in texts(result.caption)


def test_the_uploader_is_always_multi_file_without_a_toggle(page):
    assert not page.toggle
    assert page.file_uploader[0].accept_multiple_files is True


def test_an_oversized_export_is_rejected_before_merging(page):
    oversized = SPX + b"#" * (MAX_UPLOAD_BYTES - len(SPX) + 1)

    result = upload(page, [("oversized.csv", oversized, "text/csv")])

    assert "25.0 MB" in texts(result.error)
    assert not result.success


def test_a_column_with_no_data_at_all_is_dropped_and_noted(page):
    # Every JPMVXYGL_Index_PX_BID cell is Bloomberg's "#N/A N/A" — no data.
    rows = ["1/2/2020,6.5,#N/A N/A", "1/3/2020,6.6,#N/A N/A"]
    csv = export("JPMVXYGL Index", rows, fields="PX_LAST,PX_BID")
    result = upload(page, [("jpm.csv", csv, "text/csv")])

    merged = result.session_state["extraction_merged"]
    assert "JPMVXYGL_Index_PX_BID" not in merged.columns
    assert "Dropped 1 column" in texts(result.caption)


# --- explaining and excluding gap rows -------------------------------------


def gappy_csv():
    # 2016-09-05 is Labor Day; LF98TRUU has no row for it, LEGATRUU does —
    # merging on Date leaves that cell blank for LF98TRUU.
    lf98truu = export("LF98TRUU Index", ["9/6/2016,1772.0", "9/2/2016,1771.03"])
    legatruu = export(
        "LEGATRUU Index", ["9/6/2016,486.5722", "9/5/2016,482.7748", "9/2/2016,481.9552"]
    )
    return lf98truu, legatruu


def test_no_gap_review_section_when_nothing_is_missing(page):
    result = upload(page, [("spx.csv", SPX, "text/csv")])
    assert not any("missing values" in e.label.lower() for e in result.expander)
    assert "Rows with missing values" not in texts(result.markdown)


def test_a_gap_row_triggers_the_review_section(page):
    # AppTest has no data_editor accessor, so the section header and the
    # buttons around it are the testable surface — the reason text itself is
    # covered directly by test_bloomberg_csv.py's missing_row_report tests.
    lf98truu, legatruu = gappy_csv()
    result = upload(
        page, [("lf98truu.csv", lf98truu, "text/csv"), ("legatruu.csv", legatruu, "text/csv")]
    )

    assert "Rows with missing values" in texts(result.markdown)
    labels = [b.label for b in result.button]
    assert "Exclude all listed rows" in labels
    assert "Include all listed rows" in labels


def test_excluding_all_gap_rows_does_not_touch_the_report_above(page):
    lf98truu, legatruu = gappy_csv()
    result = upload(
        page, [("lf98truu.csv", lf98truu, "text/csv"), ("legatruu.csv", legatruu, "text/csv")]
    )
    assert len(result.session_state["extraction_merged"]) == 3

    exclude_button = next(b for b in result.button if b.label == "Exclude all listed rows")
    result = exclude_button.click().run()

    assert not result.exception
    # Exclusion only affects the downloads, never the merged data or its report.
    assert len(result.session_state["extraction_merged"]) == 3
    assert "Rows with missing values" in texts(result.markdown)
