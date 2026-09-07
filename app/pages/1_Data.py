"""Data page: upload Bloomberg CSV exports, merge and validate them."""

import streamlit as st

import bloomberg_extraction_panel
import ui

st.set_page_config(page_title="Data · Forecasting Engine", page_icon=":material/database:")

ui.animated_background("data")
ui.inject()
ui.sidebar_brand()
ui.page_header("Data", "Upload Bloomberg CSV exports, merge and validate them.")

with st.container(border=True, key="fe-card-upload"):
    bloomberg_extraction_panel.render()
