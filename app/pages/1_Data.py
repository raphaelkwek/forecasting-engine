"""Data page: upload the signal CSV that everything downstream runs on."""

import streamlit as st

from upload_panel import render

st.set_page_config(page_title="Data · Forecasting Engine", page_icon="📈")
render()
