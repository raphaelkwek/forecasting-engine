"""The Model Metrics page, driven through the real Streamlit page script.

Task 4.2: results are read per target role, never pooled — two sections,
Equity and Bond, each independent.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from forecasting_engine.reporting.model_metrics import ModelRunResult
from forecasting_engine.validation.crash import CrashDiagnostics

REPO_ROOT = Path(__file__).resolve().parents[2]
PAGE = REPO_ROOT / "app" / "app_pages" / "4_Model_Metrics.py"


def _result(pbo=0.3) -> ModelRunResult:
    return ModelRunResult(
        ic=0.05,
        oos_rank_ic=0.04,
        rmse=0.01,
        pbo=pbo,
        crash=CrashDiagnostics(recall=0.5, precision=0.5, f1=0.5, n_true_tail_days=4),
    )


@pytest.fixture
def page() -> AppTest:
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    return app


def _table_text(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown if '<table class="fe-table"' in m.value)


def test_both_target_sections_are_always_shown(page):
    subheadings = [s.value for s in page.subheader]
    assert "Equity — S&P 500" in subheadings
    assert "Bond — US Aggregate" in subheadings


def test_an_empty_section_says_nothing_has_run(page):
    assert len([i for i in page.info if "No model has completed a run" in i.value]) == 2


def test_equity_and_bond_results_are_shown_in_their_own_sections():
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state["polynomial_result_equity"] = _result(pbo=0.1)
    app.session_state["ml_result_bond"] = _result(pbo=0.2)
    app.run()

    tables = [m.value for m in app.markdown if '<table class="fe-table"' in m.value]
    assert len(tables) == 2
    equity_table, bond_table = tables
    assert "0.1000" in equity_table and "0.2000" not in equity_table
    assert "0.2000" in bond_table and "0.1000" not in bond_table


def test_a_bond_result_does_not_leak_into_the_equity_section():
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state["famafrench_result_bond"] = _result(pbo=None)
    app.run()

    # FF5 shouldn't even be offered for Bond (Task 4.2's guard on the Models
    # page) — if a result somehow exists there anyway, it must still not
    # show up under Equity.
    tables = [m.value for m in app.markdown if '<table class="fe-table"' in m.value]
    assert len(tables) == 1  # only the Bond section has anything to show


def test_famafrench_shows_not_applicable_under_bond_not_not_run():
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    # Something ran for Bond so that section renders a table at all.
    app.session_state["polynomial_result_bond"] = _result()
    app.run()

    tables = [m.value for m in app.markdown if '<table class="fe-table"' in m.value]
    (bond_table,) = tables
    assert "N/A" in bond_table and "not applicable" in bond_table


def test_famafrench_shows_not_run_under_equity_when_nothing_ran():
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.session_state["polynomial_result_equity"] = _result()
    app.run()

    tables = [m.value for m in app.markdown if '<table class="fe-table"' in m.value]
    (equity_table,) = tables
    assert "Not run" in equity_table
    assert "not applicable" not in equity_table
