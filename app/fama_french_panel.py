"""The Fama-French factors beside the signals. Rendering only.

They feed the FF5 benchmark, not the signal contract, so they sit apart from
validation. A copy already kept under ``data/fama_french`` is shown if there
is one, and a button fetches today's. Nothing downloads on its own: the
sponsor's brief is manual data with no automated feeds, and a run must be
able to name the exact file it used.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from forecasting_engine.ingest import fama_french, workbook
from forecasting_engine.ingest.fama_french import FactorFetchError, FactorFile
from forecasting_engine.ingest.upload import AcceptedUpload, date_range

#: The factor file in use, for the pages downstream.
FACTORS_KEY = "fama_french"

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render(accepted: AcceptedUpload) -> None:
    ui.inject()
    st.subheader("Fama-French factors")
    st.caption(
        "Ken French's daily five-factor file, for the FF5 benchmark. Each download is "
        "kept under data/fama_french under its content hash, so a run can name the copy "
        "it used."
    )

    if FACTORS_KEY not in st.session_state:
        st.session_state[FACTORS_KEY] = fama_french.load_latest()
    if st.button("Download the latest factors"):
        _download()

    factors: FactorFile | None = st.session_state[FACTORS_KEY]
    if factors is None:
        st.info("No factor file yet. Download one to preview it here and add it to the workbook.")
        return
    _render_factors(factors, accepted)


def _download() -> None:
    try:
        st.session_state[FACTORS_KEY] = fama_french.download()
    except FactorFetchError as exc:
        st.error(f"Could not download the factor file: {exc}")


def _render_factors(factors: FactorFile, accepted: AcceptedUpload) -> None:
    frame = factors.frame
    span = date_range(accepted.frame)
    if span:
        frame = fama_french.restrict_to(frame, pd.Timestamp(span[0]), pd.Timestamp(span[1]))

    st.caption(
        f"{len(frame):,} rows within the signals' dates. Content hash {factors.source.short_hash}."
    )
    if frame.empty:
        st.caption("No factor rows fall inside the signals' date range.")
    else:
        st.dataframe(frame.head(10), width="stretch")

    csv, xlsx, _ = st.columns([1, 1, 2])
    csv.download_button(
        "Fama-French (.csv)",
        data=frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8"),
        file_name="fama_french_factors.csv",
        mime="text/csv",
    )
    xlsx.download_button(
        "Signals + Fama-French (.xlsx)",
        data=workbook.build(accepted.frame, frame),
        file_name="signals_and_fama_french.xlsx",
        mime=_XLSX,
    )
