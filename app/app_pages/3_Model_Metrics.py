"""Model Metrics page: comparison table of completed model runs.

No maths lives here — formatting is in forecasting_engine.reporting.model_metrics.
"""

from __future__ import annotations

import html

import streamlit as st

import ui
from forecasting_engine.reporting.model_metrics import (
    Cell,
    ModelRunResult,
    build_metrics_rows,
)
from forecasting_engine.validation.crash import CrashDiagnostics

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

# TEMPORARY preview data until a real run store exists (FYP-42/43/44).
# Replace with `results = {}` once one does.
results: dict = {
    "FF5 Benchmark": ModelRunResult(
        ic=0.025,
        oos_rank_ic=0.022,
        rmse=0.018,
        pbo=None,
        crash=CrashDiagnostics(recall=0.55, precision=0.40, f1=0.4655, n_true_tail_days=11),
    ),
    "Polynomial": ModelRunResult(
        ic=0.031,
        oos_rank_ic=0.028,
        rmse=0.016,
        pbo=0.35,
        crash=CrashDiagnostics(recall=0.62, precision=0.48, f1=0.5379, n_true_tail_days=11),
    ),
    "Machine Learning": ModelRunResult(
        ic=0.019,
        oos_rank_ic=0.015,
        rmse=0.017,
        pbo=0.58,
        crash=CrashDiagnostics(recall=0.70, precision=0.45, f1=0.5470, n_true_tail_days=11),
    ),
}


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
