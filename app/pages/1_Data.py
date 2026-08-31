"""Data page: upload the signal CSV, then validate it against the schema."""

import streamlit as st

import upload_panel
import validation_panel

st.set_page_config(page_title="Data · Forecasting Engine", page_icon="📈")

accepted = upload_panel.render()
if accepted is not None:
    st.divider()
    validation_panel.render(accepted)
