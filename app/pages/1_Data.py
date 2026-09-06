"""Data page: upload Bloomberg CSV exports, merge and validate them."""

import streamlit as st

import bloomberg_extraction_panel

st.set_page_config(page_title="Data · Forecasting Engine", page_icon=":material/database:")

bloomberg_extraction_panel.render()
