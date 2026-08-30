"""Entry point for the dashboard. Run with: uv run streamlit run app/Home.py"""

import streamlit as st

st.set_page_config(page_title="Forecasting Engine", page_icon="📈")

st.title("Forecasting Engine")
st.write(
    "Forecasts short-horizon returns for liquid equity and bond indices, "
    "validates them against overfitting, and reports tail risk."
)
st.info("Start on the **Data** page by uploading a signal CSV.", icon="📈")
