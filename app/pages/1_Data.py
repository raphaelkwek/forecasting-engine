"""Data page: upload the signal CSV or extract from APIs, then validate."""

import streamlit as st

import extract_panel
import upload_panel
import validation_panel

st.set_page_config(page_title="Data · Forecasting Engine", page_icon=":material/database:")

source = st.radio("Data source", ["Upload CSV", "Extract from APIs"], horizontal=True)

if source == "Upload CSV":
    accepted = upload_panel.render()
else:
    accepted = extract_panel.render()

if accepted is not None:
    st.divider()
    validation_panel.render(accepted)
