"""Model Metrics page: comparison table of completed model runs.

No maths lives here — formatting is in forecasting_engine.reporting.model_metrics.
"""

from __future__ import annotations

import html

import streamlit as st

import glossary
import ui
from forecasting_engine.extraction.targets import TargetRole
from forecasting_engine.reporting.model_metrics import Cell, build_metrics_rows

#: Matches app_pages/3_Models.py's result-key constants and role-namespacing
#: (``_role_key``) — duplicated rather than imported because a page filename
#: starting with a digit isn't a valid Python module name.
POLYNOMIAL_RESULT_KEY = "polynomial_result"
FAMAFRENCH_RESULT_KEY = "famafrench_result"
ML_RESULT_KEY = "ml_result"

TARGET_LABELS: dict[TargetRole, str] = {
    TargetRole.EQUITY: "Equity — S&P 500",
    TargetRole.BOND: "Bond — US Aggregate",
}

#: Models not designed for a given target, even though the Models page's own
#: guard (Task 4.2) keeps them from actually being run against it — shown as
#: "N/A — not applicable" rather than "Not run" so the two read differently.
INAPPLICABLE: dict[TargetRole, frozenset[str]] = {
    TargetRole.EQUITY: frozenset(),
    TargetRole.BOND: frozenset({"FF5 Benchmark"}),
}


def _role_key(base: str, role: TargetRole) -> str:
    return f"{base}_{role.value}"

COLUMNS: tuple[str, ...] = (
    "Model",
    "IC",
    "OOS Rank IC",
    "RMSE",
    "PBO",
    "Crash Recall",
    "Crash Precision",
    "Crash F1",
)

BADGE_LABELS = {"success": "Gate met", "danger": "Gate failed"}

#: Column heading -> the glossary term explaining it. "Model" needs none, and
#: the three crash columns share one explanation.
COLUMN_TERMS = {
    "IC": "IC",
    "OOS Rank IC": "OOS Rank IC",
    "RMSE": "RMSE",
    "PBO": "PBO",
    "Crash Recall": "Crash diagnostics",
    "Crash Precision": "Crash diagnostics",
    "Crash F1": "Crash diagnostics",
}

st.set_page_config(
    page_title="Model Metrics · Forecasting Engine", page_icon=":material/table_chart:"
)
ui.inject()

st.header("Model comparison")
st.caption(
    "Each model family's forecast-accuracy, overfitting, and crash diagnostics, "
    "side by side. OOS Rank IC and PBO carry a promotion-gate badge; crash "
    "figures are always diagnostic, never a pass/fail bar.",
    help=glossary.term("Promotion gate"),
)
st.caption("Hover a column heading for what it measures and why it matters.")

def _results_for(role: TargetRole) -> dict:
    """The completed runs for one target, read from the Models page's
    role-namespaced session state (Task 4.2) — the two targets are
    independent forecasting problems and are never pooled."""
    results: dict = {}
    famafrench_result = st.session_state.get(_role_key(FAMAFRENCH_RESULT_KEY, role))
    if famafrench_result is not None:
        results["FF5 Benchmark"] = famafrench_result

    polynomial_result = st.session_state.get(_role_key(POLYNOMIAL_RESULT_KEY, role))
    if polynomial_result is not None:
        results["Polynomial"] = polynomial_result

    ml_result = st.session_state.get(_role_key(ML_RESULT_KEY, role))
    if ml_result is not None:
        results["Machine Learning"] = ml_result
    return results


def _header_html(column: str) -> str:
    term = COLUMN_TERMS.get(column)
    if term is None:
        return f"<th>{html.escape(column)}</th>"
    hint = html.escape(glossary.term(term), quote=True)
    return (
        f'<th title="{hint}">{html.escape(column)}'
        f'<span class="fe-eyebrow-help" title="{hint}">i</span></th>'
    )


def _cell_html(cell: Cell) -> str:
    text = html.escape(cell.text)
    label = BADGE_LABELS.get(cell.tone)
    if label is None:
        return text
    return f"{text}&nbsp;&nbsp;{ui.lozenge(label, cell.tone)}"


for role in TargetRole:
    st.subheader(TARGET_LABELS[role])
    results = _results_for(role)
    if not results:
        st.info("No model has completed a run yet.")
        continue

    rows = build_metrics_rows(results, inapplicable=INAPPLICABLE[role])
    # A hand-built table has no Streamlit help=, so each heading explains
    # itself through the browser's own title tooltip.
    header = "".join(_header_html(col) for col in COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell_html(row[col])}</td>" for col in COLUMNS) + "</tr>"
        for row in rows
    )
    st.markdown(
        f'<table class="fe-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>',
        unsafe_allow_html=True,
    )
