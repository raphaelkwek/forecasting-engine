"""The data quality report on the dashboard's front page.

One test per acceptance criterion, driven through the real page.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOME = REPO_ROOT / "app" / "Home.py"
DATA_PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"

HEADER = (
    "date,spx_close,bond_index_global_agg,vix,tnx_close,dollar_index,"
    "eur_fx_vol,credit_spread_ig,"
    "credit_spread_hy,breakeven_5y,breakeven_10y,term_spread,fx_impl_vol,"
    "ff_mkt_rf,ff_smb,ff_hml,ff_rmw,ff_cma,ff_rf"
)


def signals_csv(n=300, spike_at=None, blank_at=None) -> bytes:
    rng = np.random.default_rng(4)
    dates = pd.bdate_range("2024-01-01", periods=n).strftime("%Y-%m-%d")
    vix = 15 + np.cumsum(rng.normal(0, 0.2, n))
    rows = [HEADER]
    for i, date in enumerate(dates):
        v = "" if blank_at == i else (180.0 if spike_at == i else round(vix[i], 2))
        rows.append(f"{date},{4000 + i:.2f},{100 + i * 0.01:.3f},{v},4.00,100.00,10.00,1.00,3.00,2.00,8.00,2.20,10.00,0.05,0.02,0.01,0.02,0.01,0.01")  # noqa: E501
    return ("\n".join(rows) + "\n").encode()


def broken_csv() -> bytes:
    return signals_csv().replace(b"date,spx_close", b"date,NOT_spx_close", 1)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(HOME), default_timeout=30)
    app.run()
    return app


def ingested(tmp_path, monkeypatch, data: bytes):
    """Upload on the Data page, then open Home with that session state."""
    monkeypatch.chdir(tmp_path)
    data_page = AppTest.from_file(str(DATA_PAGE), default_timeout=30)
    data_page.run()
    data_page.file_uploader[0].set_value(("signals.csv", data, "text/csv"))
    data_page.run()

    home = AppTest.from_file(str(HOME), default_timeout=30)
    for key, value in data_page.session_state.filtered_state.items():
        home.session_state[key] = value
    return home.run()


def texts(elements):
    return " ".join(e.value for e in elements)


# --- AC5: a pending state, not a blank or broken view ----------------------


def test_before_any_upload_the_report_is_pending_not_blank(home):
    assert "No data ingested yet" in texts(home.info)


def test_the_pending_view_names_every_check_that_will_run(home):
    body = texts(home.markdown)
    for title in ("Schema validation", "Data gaps", "Outliers", "Missing values"):
        assert title in body, title
    assert "Pending" in body


def test_the_pending_view_does_not_error(home):
    assert not home.exception
    assert not home.error


# --- AC3: on the main dashboard, not behind a setting ----------------------


def test_the_report_is_on_the_front_page(home):
    assert any("Data quality report" in h.value for h in home.subheader)


def test_no_expander_hides_the_report_itself(home):
    # The report renders directly; expanders are only used for per-signal detail.
    assert not home.expander


# --- AC1: date range and per-signal missing counts -------------------------


def test_the_report_shows_what_was_ingested(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv())

    labels = {m.label: m.value for m in home.metric}
    assert labels["Rows ingested"] == "300"
    assert labels["Signals"] == "19"


def test_the_report_shows_the_full_date_range(tmp_path, monkeypatch):
    # Both ends, in a caption rather than a metric: a metric column truncates
    # the second date, which is the half that says whether the data is current.
    home = ingested(tmp_path, monkeypatch, signals_csv())

    captions = texts(home.caption)
    assert "2024-01-01" in captions
    assert "2025-02-21" in captions


def test_the_report_breaks_completeness_down_by_signal(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv(blank_at=10))

    assert "Completeness by signal" in texts(home.markdown)
    report = home.session_state["quality_report"]
    signals = report.section("missing").stats["signals"]
    assert signals["vix"]["missing"] == 1
    assert signals["spx_close"]["missing"] == 0


def test_nothing_claims_to_have_been_filled_yet(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv(blank_at=10))
    assert "Filling happens in data preparation" in texts(home.caption)


# --- AC2: anomalies listed, per-signal breakdown from a summary ------------


def test_flagged_observations_are_summarised(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv(spike_at=150))

    assert "Flagged observations" in texts(home.markdown)
    assert "Expand a signal to see the detail" in texts(home.caption)


def test_each_affected_signal_expands_to_its_own_detail(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv(spike_at=150))

    labels = [e.label for e in home.expander]
    assert any(label.startswith("vix — ") for label in labels), labels


def test_a_clean_file_shows_no_breakdown(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv())
    assert "Flagged observations" not in texts(home.markdown)


# --- AC4: informational only; the user may proceed -------------------------


def test_flags_do_not_prevent_proceeding(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv(spike_at=150))

    assert not home.error
    assert "Ready for forecasting" in texts(home.success)
    assert "none of them stop a run" in texts(home.success)


def test_a_clean_file_says_so_plainly(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv())
    assert "Nothing flagged" in texts(home.success)


def test_a_blocking_failure_is_the_one_thing_that_is_not_informational(
    tmp_path, monkeypatch
):
    home = ingested(tmp_path, monkeypatch, broken_csv())

    assert "cannot be used" in texts(home.error)
    assert not home.success


# --- the check list --------------------------------------------------------


def test_every_check_reports_its_own_status(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv())

    body = texts(home.markdown)
    for title in ("Schema validation", "Data gaps", "Outliers", "Missing values"):
        assert title in body, title


def test_a_failed_file_shows_its_checks_as_pending_rather_than_absent(
    tmp_path, monkeypatch
):
    home = ingested(tmp_path, monkeypatch, broken_csv())

    # Status is a lozenge beside the check name, so assert on the rendered row.
    body = texts(home.markdown)
    assert "Outliers" in body
    assert "Schema validation" in body
    assert "Pending" in body and "Failed" in body

    statuses = {s.check: s.status.value for s in home.session_state["quality_report"].sections}
    assert statuses["outliers"] == "pending"
    assert statuses["schema"] == "failed"


def test_status_is_shown_as_a_lozenge_not_a_symbol(tmp_path, monkeypatch):
    home = ingested(tmp_path, monkeypatch, signals_csv())

    body = texts(home.markdown)
    assert "fe-lozenge" in body
    for symbol in ("✓", "✕", "⋯"):
        assert symbol not in body, symbol


def test_the_stylesheet_reaches_home_even_after_the_data_page_rendered(
    tmp_path, monkeypatch
):
    # Streamlit renders each page from scratch, so a session-scoped injection
    # guard leaves whichever page runs second unstyled.
    home = ingested(tmp_path, monkeypatch, signals_csv())
    assert "fe-lozenge" in texts(home.markdown)
    assert "fe-eyebrow" in texts(home.markdown)
