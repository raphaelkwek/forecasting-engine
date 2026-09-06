"""Data page: upload the signal CSV, then validate it against the schema."""

import streamlit as st

import ui
import upload_panel
import validation_panel

st.set_page_config(page_title="Data · Forecasting Engine", page_icon=":material/database:")

ui.animated_background("data")
ui.inject()
ui.sidebar_brand()
ui.page_header("Data", "Upload and validate the signal CSV that feeds every forecast.")

with st.container(border=True, key="fe-card-upload"):
    accepted = upload_panel.render()

if accepted is not None:
    with st.container(border=True, key="fe-card-validation"):
        validation_panel.render(accepted)
