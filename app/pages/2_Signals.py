"""Signals page: per-signal IC screening and the inclusion registry.

Reads the dataset committed via "Use New Data" on the Data page; no maths
lives here — screening logic is in forecasting_engine.features.screening.
"""

from __future__ import annotations

import streamlit as st

import bloomberg_extraction_panel
from forecasting_engine.extraction.bloomberg_csv import DATE_COLUMN
from forecasting_engine.features.screening import run_screening

st.set_page_config(page_title="Signals · Forecasting Engine", page_icon=":material/query_stats:")

st.header("Signal screening")
st.caption(
    "Each ingested signal is scored by its rank IC against the forward return. "
    "Signals below the inclusion threshold stay visible here, excluded from modelling."
)

merged = st.session_state.get(bloomberg_extraction_panel.SCREENING_KEY)
if merged is None:
    st.info("No data committed yet — click \"Use New Data\" on the Data page first.")
else:
    numeric_cols = [
        c for c in merged.columns if c != DATE_COLUMN and merged[c].dtype.kind in "fi"
    ]
    price_col = st.selectbox("Target price/level column", numeric_cols)
    signal_cols = [c for c in numeric_cols if c != price_col]
    if price_col and signal_cols:
        indexed = merged.set_index(DATE_COLUMN)
        scores = run_screening(indexed, signal_cols, price_col)
        st.dataframe(
            [
                {
                    "Signal": s.signal,
                    "IC": round(s.ic, 4) if s.ic == s.ic else None,
                    "Included": "Yes" if s.included else "No",
                }
                for s in scores
            ],
            width="stretch",
        )
