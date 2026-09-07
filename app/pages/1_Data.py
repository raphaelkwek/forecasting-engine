"""Data page: get a signal CSV into the engine, then validate it.

Two ways in. A CSV already in the contract's shape is uploaded as it is.
Bloomberg CSV exports, one per security, are merged and mapped onto the
contract here in the app, so nobody needs a command line. Both roads end at
the same validation and the same quality report, and both leave the same
``AcceptedUpload`` in session state for the pages downstream.
"""

import streamlit as st

import bloomberg_panel
import fama_french_panel
import ui
import upload_panel
import validation_panel

SIGNAL_CSV = "A signal CSV"
BLOOMBERG = "Bloomberg exports"

st.set_page_config(page_title="Data · Forecasting Engine", page_icon=":material/database:")

ui.animated_background("data")
ui.inject()
ui.sidebar_brand()
ui.page_header(
    "Data", "Upload the signal CSV that feeds every forecast, or build it from Bloomberg exports."
)

source = st.radio(
    "What are you uploading?",
    [SIGNAL_CSV, BLOOMBERG],
    horizontal=True,
    help=(
        "A signal CSV already matches docs/data-specification.md. Bloomberg exports are "
        "the terminal's own CSV files, one per security; they are merged here."
    ),
)

with st.container(border=True, key="fe-card-upload"):
    accepted = upload_panel.render() if source == SIGNAL_CSV else bloomberg_panel.render()

if accepted is not None:
    with st.container(border=True, key="fe-card-validation"):
        validation_panel.render(accepted)
    with st.container(border=True, key="fe-card-factors"):
        fama_french_panel.render(accepted)
