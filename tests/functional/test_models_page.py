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
PAGE = REPO_ROOT / "app" / "app_pages" / "3_Models.py"


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


# --- Phase 4.3: the horizon, the embargo, and where the lag lives -----------


@pytest.fixture
def splitter_calls(monkeypatch):
    """Record the arguments PurgedWalkForward is actually built with.

    The page imports the name when its script runs, so patching the module
    attribute beforehand is what the page picks up.
    """
    import forecasting_engine.validation.splitters as splitters

    calls: list[dict] = []
    real = splitters.PurgedWalkForward

    class Recording(real):
        def __init__(self, train: int, test: int, embargo: int):
            calls.append({"train": train, "test": test, "embargo": embargo})
            super().__init__(train, test, embargo)

    monkeypatch.setattr(splitters, "PurgedWalkForward", Recording)
    return calls


def _bare_page() -> AppTest:
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state["extraction_committed"] = _committed()
    return app.run()


def test_the_horizon_is_a_choice_of_exactly_one_or_five_days():
    app = _bare_page()

    (horizon,) = [c for c in app.segmented_control if c.label == "Forecast horizon"]
    assert list(horizon.options) == ["1 day", "5 days"]


def test_the_horizon_defaults_to_five_days():
    app = _bare_page()
    (horizon,) = [c for c in app.segmented_control if c.label == "Forecast horizon"]
    assert horizon.value == 5


def test_the_free_numeric_horizon_input_is_gone():
    app = _bare_page()
    assert all("horizon" not in n.label.lower() for n in app.number_input)


@pytest.mark.parametrize("chosen", [1, 5])
def test_the_embargo_is_five_whichever_horizon_is_chosen(splitter_calls, chosen):
    # Before, picking h=1 silently dropped the embargo to 1 as well.
    app = _bare_page()
    (horizon,) = [c for c in app.segmented_control if c.label == "Forecast horizon"]
    horizon.set_value(chosen)
    app.run()

    assert not app.exception
    assert splitter_calls, "the page must build a splitter"
    assert splitter_calls[-1]["embargo"] == 5


def test_the_embargo_is_no_longer_an_editable_input():
    app = _bare_page()
    assert all("embargo" not in n.label.lower() for n in app.number_input)


def test_signal_lag_lives_in_the_advanced_audit_section_not_the_main_row():
    app = _bare_page()

    (audit,) = [e for e in app.expander if e.label == "Advanced: lag-shift audit"]
    lag_inputs = [n for n in audit.number_input if n.label == "Signal lag (days)"]
    assert len(lag_inputs) == 1
    assert lag_inputs[0].value == 1

    everywhere = [n for n in app.number_input if n.label == "Signal lag (days)"]
    assert len(everywhere) == 1, "the lag control should exist only inside the audit section"
