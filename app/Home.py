"""Dashboard front page: the data quality report.

Run with: uv run streamlit run app/Home.py

The report is here rather than behind a settings menu because it is what you
check before trusting a forecast built on this data.
"""

import streamlit as st

import quality_report_panel
import ui
from validation_panel import REPORT_KEY

st.set_page_config(page_title="Forecasting Engine", page_icon=":material/monitoring:")

ui.animated_background("home")
ui.inject()
ui.sidebar_brand()
ui.page_header(
    "Forecasting Engine",
    "Forecasts short-horizon returns for liquid equity and bond indices, "
    "validates them against overfitting, and reports tail risk.",
)

with st.container(border=True, key="fe-card-quality-report"):
    quality_report_panel.render(st.session_state.get(REPORT_KEY))
