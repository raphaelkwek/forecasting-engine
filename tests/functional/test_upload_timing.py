"""Uploading a manual CSV BEFORE extraction runs, as a human does in the browser.

Guards the ordering: file upload -> extract click -> selectbox mapping ->
merged new column in the final CSV.  If the multi-file zone dropped files on
the Extract rerun, this test fails.
"""

from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

from extract_panel import _FRED_KEY
from forecasting_engine.ingest.extract import ExtractionReport

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "pages" / "1_Data.py"

_SCHEMA_COLUMNS = [
    "date", "spx_close", "spx_close_target", "bond_index_global_agg", "bond_index_target",
    "vix", "tnx_close", "dollar_index", "eur_fx_vol", "credit_spread_ig", "credit_spread_hy",
    "breakeven_5y", "breakeven_10y", "term_spread", "fx_impl_vol",
    "ff_mkt_rf", "ff_smb", "ff_hml", "ff_rmw", "ff_cma", "ff_rf",
]
_DATES = ["2025-01-02", "2025-01-03", "2025-01-06"]
RAW_FRAME = pd.DataFrame(
    {
        **{col: [1.0, 2.0, 3.0] for col in _SCHEMA_COLUMNS if col != "date"},
        "date": _DATES,
        "bond_index_global_agg": [float("nan"), float("nan"), float("nan")],
    }
)
REPORT = ExtractionReport(rows=3, start="2025-01-02", end="2025-01-06")


def test_new_column_from_an_upload_before_extraction():
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state[_FRED_KEY] = "test-key"
    with mock.patch(
        "extract_panel.extract_all", return_value=(RAW_FRAME.copy(), REPORT)
    ):
        app.run()
        app.radio[0].set_value("Extract from APIs")
        app.run()
        # Upload BEFORE extraction has produced any frame, as a human does.
        app.file_uploader[0].set_value(
            [("WTI_Price.csv", b"Date,PX_LAST\n2025-01-02,45.5\n2025-01-03,46.0\n2025-01-06,47.0\n", "text/csv")]
        )
        app.run()
        assert len(app.selectbox) == 0  # no mapping yet, nothing extracted
        app.button[0].click()
        app.run()

        assert not app.error, [e.value for e in app.error]
        # The upload happened before extraction; once extraction is clicked the
        # file must still be visible and map to a NEW column under its stem.
        assert app.file_uploader[0].value, "uploaded file survived the Extract click"
        assert app.selectbox[0].value == "WTI_Price"
        assert "Merged WTI_Price.csv into WTI_Price." in [
            s.value for s in app.success
        ]
        # 20 columns = 21 schema - bond_index_target - credit_spread_hy + the
        # new WTI_Price stem column.  Without the manual merge it would be 19.
        successes = [s.value for s in app.success]
        assert any("Extracted 3 rows, 20 columns," in v for v in successes)