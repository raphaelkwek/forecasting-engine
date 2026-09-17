"""The Models page, driven through the real Streamlit page script.

These render a stored run the way the page shows a previous result, rather than
fitting one: a derived fit is slow and nondeterministic, and what's under test
here is what the page shows, not the fitting.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.models.base import ModelDescription
from forecasting_engine.reporting.model_metrics import ModelRunResult, ScreeningSummary
from forecasting_engine.validation.crash import CrashDiagnostics

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "app_pages" / "4_Models.py"


def _committed() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 200
    return pd.DataFrame(
        {
            "Date": pd.bdate_range("2024-01-01", periods=n),
            "SPX_Index_PX_LAST": 4000 + np.cumsum(rng.normal(size=n)),
            "VIX_Index_PX_LAST": 15 + rng.normal(size=n),
            "LUACOAS_Index_PX_LAST": 1.2 + rng.normal(scale=0.1, size=n),
        }
    )


def _result(screening: ScreeningSummary | None) -> ModelRunResult:
    return ModelRunResult(
        ic=0.05,
        oos_rank_ic=0.04,
        rmse=0.01,
        pbo=0.3,
        crash=CrashDiagnostics(recall=0.5, precision=0.5, f1=0.5, n_true_tail_days=4),
        screening=screening,
    )


def _page(screening: ScreeningSummary | None) -> AppTest:
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state["extraction_committed"] = _committed()
    app.session_state["polynomial_result"] = _result(screening)
    app.session_state["polynomial_description"] = ModelDescription(
        name="Derived polynomial", terms=("VIX_Index_PX_LAST",), coefficients=(0.2,)
    )
    return app.run()


def _markdown(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown)


def _captions(app: AppTest) -> str:
    return " ".join(c.value for c in app.caption)


@pytest.fixture
def screened() -> ScreeningSummary:
    return ScreeningSummary(
        folds=8,
        fell_back=0,
        counts=(("VIX_Index_PX_LAST", 8), ("LUACOAS_Index_PX_LAST", 0)),
    )


def test_a_screened_run_shows_per_fold_signal_inclusion(screened):
    app = _page(screened)

    assert not app.exception
    assert "Signal inclusion across folds" in _markdown(app)


def test_each_signal_is_shown_against_the_number_of_folds(screened):
    app = _page(screened)

    tables = [d.value for d in app.dataframe]
    inclusion = next(t for t in tables if "Folds" in t.columns)
    assert dict(zip(inclusion["Signal"], inclusion["Folds"], strict=True)) == {
        "VIX_Index_PX_LAST": "8/8",
        "LUACOAS_Index_PX_LAST": "0/8",
    }


def test_a_signal_no_fold_used_is_still_shown(screened):
    app = _page(screened)

    inclusion = next(d.value for d in app.dataframe if "Folds" in d.value.columns)
    assert "0/8" in inclusion["Folds"].tolist()


def test_folds_that_fell_back_to_every_signal_are_called_out():
    app = _page(ScreeningSummary(folds=8, fell_back=3, counts=(("VIX_Index_PX_LAST", 8),)))
    assert "3 of 8 folds kept no signal" in _captions(app)


def test_no_fallback_note_when_no_fold_fell_back(screened):
    app = _page(screened)
    assert "kept no signal" not in _captions(app)


def test_a_run_without_screening_shows_no_inclusion_table():
    # FF5 and a user-supplied formula are handed their features; there is
    # nothing per-fold to report.
    app = _page(None)

    assert not app.exception
    assert "Signal inclusion across folds" not in _markdown(app)
    assert all("Folds" not in d.value.columns for d in app.dataframe)
