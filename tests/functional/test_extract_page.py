"""The Extract-from-APIs tab, driven through the real Streamlit page.

The layout tests cover the first render, before any data is pulled. The pipeline
test mocks ``extract_all`` — the only network caller — and drives a manual CSV
through the real uploader, so no live Yahoo/FRED traffic happens.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

from extract_panel import (
    _EXTRACT_BUTTON_KEY,
    _FRED_KEY,
    _MANUAL_FILES_KEY,
    _MANUAL_NOTE,
)
from forecasting_engine.ingest.extract import ExtractionReport

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"


def _extract_tab() -> AppTest:
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    app.radio[0].set_value("Extract from APIs")
    app.run()
    return app


def _widget_key_order(app: AppTest) -> list[str]:
    """The widget keys in the order Streamlit rendered them."""
    order = []
    for node in app.main:
        key = getattr(node, "key", None)
        if key:
            order.append(key)
    return order


def test_a_single_multi_file_upload_zone_replaces_the_two_uploaders():
    app = _extract_tab()

    # Exactly one uploader: the old per-column pair is gone.
    (zone,) = app.file_uploader
    assert zone.accept_multiple_files
    assert zone.allowed_type == [".csv"]
    assert zone.key == _MANUAL_FILES_KEY


def test_the_manual_note_is_shown_verbatim():
    app = _extract_tab()

    assert _MANUAL_NOTE in [c.value for c in app.caption]


def test_the_section_is_labelled():
    app = _extract_tab()

    marks = [m.value for m in app.markdown]
    assert any("Manual signals (optional)" in m for m in marks)


def test_the_upload_zone_sits_above_the_extract_button():
    app = _extract_tab()

    order = _widget_key_order(app)
    assert order.index(_MANUAL_FILES_KEY) < order.index(_EXTRACT_BUTTON_KEY)


# --- post-extraction pipeline (extract_all mocked, no network) -------------

_SCHEMA_COLUMNS = [
    "date",
    "spx_close",
    "spx_close_target",
    "bond_index_global_agg",
    "bond_index_target",
    "vix",
    "tnx_close",
    "dollar_index",
    "eur_fx_vol",
    "credit_spread_ig",
    "credit_spread_hy",
    "breakeven_5y",
    "breakeven_10y",
    "term_spread",
    "fx_impl_vol",
    "ff_mkt_rf",
    "ff_smb",
    "ff_hml",
    "ff_rmw",
    "ff_cma",
    "ff_rf",
]
_DATES = ["2025-01-02", "2025-01-03", "2025-01-06"]

# A schema-complete extraction. bond_index_target is pipeline-internal and is
# dropped by clean_output; bond_index_global_agg carries a NaN the manual
# override fills, so validation below sees a fully-populated frame.
RAW_FRAME = pd.DataFrame(
    {
        **{col: [1.0, 2.0, 3.0] for col in _SCHEMA_COLUMNS if col != "date"},
        "date": _DATES,
        "bond_index_global_agg": [float("nan"), float("nan"), float("nan")],
    }
)
REPORT = ExtractionReport(rows=3, start="2025-01-02", end="2025-01-06")

# A Bloomberg-style export whose stem (bloomberg_global_agg) resolves via the
# "bloomberg global agg" alias to bond_index_global_agg.
MANUAL_CSV = b"Dates,PX_LAST\n2025-01-02,10.5\n2025-01-03,11.0\n2025-01-06,12.5\n"


def test_uploaded_manual_csv_is_merged_cleaned_and_confirmed():
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state[_FRED_KEY] = "test-key"
    # The patch must stay active for every run() until the extraction's data
    # has been consumed; AppTest re-executes the script on each interaction.
    with mock.patch("extract_panel.extract_all", return_value=(RAW_FRAME.copy(), REPORT)):
        app.run()
        app.radio[0].set_value("Extract from APIs")
        app.run()
        app.file_uploader[0].set_value(
            [("bloomberg_global_agg.csv", MANUAL_CSV, "text/csv")]
        )
        app.button[0].click()
        app.run()

    # The per-file mapping defaults to the guessed column.
    assert app.selectbox[0].value == "bond_index_global_agg"
    assert "Merged bloomberg_global_agg.csv into bond_index_global_agg." in [
        s.value for s in app.success
    ]
    # The manual override filled the automated NaN column, and clean_output
    # dropped bond_index_target and credit_spread_hy before confirmation.
    assert "Extracted 3 rows, 19 columns, 2025-01-02 to 2025-01-06." in [
        s.value for s in app.success
    ]
    (summary,) = [c.value for c in app.caption if c.value.startswith("Cleaned ")]
    assert "3 → 3 rows" in summary
    assert "guaranteed complete" in summary
    assert "dropped bond_index_target" in summary
    assert "2025-01-02 to 2025-01-06." in summary
    assert not app.error  # the manual override fed a schema-valid frame