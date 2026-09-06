"""The data quality summary on the dashboard's front page."""

import sys
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOME = REPO_ROOT / "app" / "Home.py"
DATA_PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"
APP_DIR = REPO_ROOT / "app"

FAKE_FACTORS = pd.DataFrame({"Date": pd.to_datetime(["2020-01-02"]), "Mkt-RF": [0.1]})

SPX = (
    b"Security,SPX Index\nPeriod,Daily\n\nDate,PX_LAST\n1/2/2020,100.0\n1/3/2020,101.0\n"
)


@pytest.fixture(autouse=True)
def no_network_fetch(monkeypatch):
    sys.path.insert(0, str(APP_DIR))
    import bloomberg_extraction_panel

    monkeypatch.setattr(bloomberg_extraction_panel.fama_french, "fetch", lambda: FAKE_FACTORS)
    bloomberg_extraction_panel._fetch_fama_french.clear()


def texts(elements):
    return " ".join(e.value for e in elements)


def test_before_any_upload_the_summary_is_pending_not_blank(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    home = AppTest.from_file(str(HOME), default_timeout=30)
    home.run()
    assert "No data ingested yet" in texts(home.info)


def test_after_an_upload_the_summary_shows_on_home(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    data_page = AppTest.from_file(str(DATA_PAGE), default_timeout=30)
    data_page.run()
    data_page.file_uploader[0].set_value(("spx.csv", SPX, "text/csv"))
    data_page.run()

    home = AppTest.from_file(str(HOME), default_timeout=30)
    for key, value in data_page.session_state.filtered_state.items():
        home.session_state[key] = value
    result = home.run()

    labels = {m.label: m.value for m in result.metric}
    assert labels["Rows"] == "2"
    assert labels["Signals"] == "1"
    assert "Nothing flagged" in texts(result.success)
    assert "02/01/2020 to 03/01/2020" in texts(result.caption)
