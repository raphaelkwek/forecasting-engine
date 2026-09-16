"""Model Metrics page: comparison table of completed model runs.

No maths lives here — formatting is in forecasting_engine.reporting.model_metrics.
"""

from __future__ import annotations

import html

import streamlit as st

import ui
from forecasting_engine.reporting.model_metrics import Cell, build_metrics_rows

#: Matches app_pages/4_Models.py's result-key constants — duplicated rather than
#: imported because a page filename starting with a digit isn't a valid Python
#: module name.
POLYNOMIAL_RESULT_KEY = "polynomial_result"
FAMAFRENCH_RESULT_KEY = "famafrench_result"
ML_RESULT_KEY = "ml_result"

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

st.set_page_config(
    page_title="Model Metrics · Forecasting Engine", page_icon=":material/table_chart:"
)
ui.inject()

st.header("Model comparison")
st.caption(
    "Each model family's forecast-accuracy, overfitting, and crash diagnostics, "
    "side by side. OOS Rank IC and PBO carry a promotion-gate badge; crash "
    "figures are always diagnostic, never a pass/fail bar."
)

# All three model families (FYP-42/43/44) are real now, read from the Models
# page's session state — no placeholder data left.
results: dict = {}

famafrench_result = st.session_state.get(FAMAFRENCH_RESULT_KEY)
if famafrench_result is not None:
    results["FF5 Benchmark"] = famafrench_result

polynomial_result = st.session_state.get(POLYNOMIAL_RESULT_KEY)
if polynomial_result is not None:
    results["Polynomial"] = polynomial_result

ml_result = st.session_state.get(ML_RESULT_KEY)
if ml_result is not None:
    results["Machine Learning"] = ml_result


def _cell_html(cell: Cell) -> str:
    text = html.escape(cell.text)
    label = BADGE_LABELS.get(cell.tone)
    if label is None:
        return text
    return f"{text}&nbsp;&nbsp;{ui.lozenge(label, cell.tone)}"


if not results:
    st.info("No model has completed a run yet.")
else:
    rows = build_metrics_rows(results)
    header = "".join(f"<th>{col}</th>" for col in COLUMNS)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell_html(row[col])}</td>" for col in COLUMNS) + "</tr>"
        for row in rows
    )
    st.markdown(
        f'<table class="fe-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>',
        unsafe_allow_html=True,
    )
