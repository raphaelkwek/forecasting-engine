"""The extract panel. Rendering only — every rule it enforces lives in the core.

Pulls market data from Yahoo Finance and economic data from FRED as an
alternative to uploading a CSV, then lets the user merge manual CSV exports
(``bond_index_global_agg``, ``fx_impl_vol``, or any new signal) uploaded through
a single multi-file dropzone.  The merged frame is passed through
``clean_output`` before the ``AcceptedUpload`` feeds the same validation pipeline.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

import ui
from forecasting_engine.ingest.extract import (
    MANUAL_COLUMNS,
    ExtractionReport,
    extract_all,
    merge_manual_columns,
    to_accepted,
)
from forecasting_engine.ingest.upload import AcceptedUpload

if TYPE_CHECKING:
    from forecasting_engine.ingest.extract import CleaningSummary

#: Where the accepted extraction is parked for the pages downstream.
SESSION_KEY = "accepted_upload"

_FRED_KEY = "fred_api_key"
_EXTRACT_REPORT = "_extract_report"
_EXTRACT_FRAME = "_extract_frame"
_EXTRACT_BUTTON_KEY = "_extract_button"
_MANUAL_FILES_KEY = "_manual_files"

_MANUAL_NOTE = (
    "This will auto-extract and merge with the data already pulled below. "
    "Any additional signals you upload will be included as new columns in the final CSV."
)

#: Documented filename stems that signal which column a manual CSV supplies.
#: The known column names are listed too, so a file already carrying a known
#: name maps straight to that column.
_MANUAL_COLUMN_ALIASES = {
    "legatruu": "bond_index_global_agg",
    "legatruu index": "bond_index_global_agg",
    "bloomberg global aggregate": "bond_index_global_agg",
    "bloomberg global agg": "bond_index_global_agg",
    "fximplvol": "fx_impl_vol",
    "fx_impl_vol": "fx_impl_vol",
    "g7 fx vol": "fx_impl_vol",
}


def render() -> AcceptedUpload | None:
    """Draw the panel, run the extraction, and merge manual signals.

    Uploaded manual CSVs are mapped to their target columns and merged into the
    extracted frame, which is then passed through ``clean_output``.  The cleaned
    frame becomes the ``AcceptedUpload`` handed to schema validation.  Returns
    None when there is nothing to validate.
    """
    ui.inject()
    st.header("Extract from APIs")
    st.caption(
        "Pull market prices from Yahoo Finance and economic data from FRED. "
        "bond_index_global_agg is auto-sourced; you can optionally override it, and "
        "fx_impl_vol must be supplied manually."
    )

    _render_fred_key()
    start, end = _render_date_range()

    _render_manual_upload_zone()

    if st.button("Extract", type="primary", key=_EXTRACT_BUTTON_KEY):
        api_key = st.session_state.get(_FRED_KEY, "")
        if not api_key:
            st.error("Enter a FRED API key to proceed.")
            return None
        frame, report = _run_extraction(api_key, start, end)
        if frame is None:
            return None
        st.session_state[_EXTRACT_FRAME] = frame
        st.session_state[_EXTRACT_REPORT] = report

    frame = st.session_state.get(_EXTRACT_FRAME)
    if frame is None:
        return None

    report = st.session_state.get(_EXTRACT_REPORT, ExtractionReport(rows=0))
    frame = _merge_manual_files(frame)

    # Imported here so that importing this panel does not require the core's new
    # cleaning step (landed in parallel with this change) to exist yet.
    from forecasting_engine.ingest.extract import clean_output

    # A manual CSV with repeated dates joins into duplicated rows; surface that
    # as a readable error rather than letting the guard raise a raw traceback.
    try:
        frame, summary = clean_output(frame)
    except ValueError as exc:
        st.error(str(exc))
        return None
    if frame.empty:
        st.warning(
            "No complete rows survive cleaning — every row has a null in some column that "
            "requires a value (the known short feeds, eur_fx_vol and the ff_* factors, are "
            "exempt). Check the uploaded files and the date range."
        )
        return None

    source = to_accepted(frame, report)
    accepted = AcceptedUpload(frame=frame, source=source)
    _render_confirmation(accepted, report, summary)
    return accepted


def _render_fred_key() -> None:
    if _FRED_KEY not in st.session_state:
        st.session_state[_FRED_KEY] = os.environ.get("FRED_API_KEY", "")
    st.text_input(
        "FRED API key",
        type="password",
        key=_FRED_KEY,
        help="Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html",
    )


def _render_date_range() -> tuple[date, date]:
    default_end = date.today()
    default_start = default_end - timedelta(days=365 * 10)
    cols = st.columns(2)
    with cols[0]:
        start = st.date_input("Start date", value=default_start)
    with cols[1]:
        end = st.date_input("End date", value=default_end)
    return start, end


def _run_extraction(
    api_key: str, start: date, end: date
) -> tuple[pd.DataFrame | None, ExtractionReport]:
    """Run the extraction and display results."""
    with st.spinner("Fetching data from Yahoo Finance and FRED..."):
        try:
            frame, report = extract_all(api_key, start, end)
        except Exception as exc:
            st.error(f"Extraction failed: {exc}")
            return None, ExtractionReport(rows=0)

    st.session_state[_EXTRACT_REPORT] = report
    _render_status(report)

    if frame.empty:
        st.warning("Extraction returned no data. Check your date range and API key.")
        return None, report

    return frame, report


def _render_manual_upload_zone() -> None:
    """Offer one multi-file dropzone for manual signal CSVs."""
    st.markdown(ui.eyebrow("Manual signals (optional)"), unsafe_allow_html=True)
    st.caption(
        "Drop one or more Bloomberg export CSVs. After extraction, each file is "
        "mapped to the signal it supplies; a signal the APIs do not carry becomes "
        "a new column."
    )
    st.file_uploader(
        "Manual signal CSVs",
        type="csv",
        accept_multiple_files=True,
        key=_MANUAL_FILES_KEY,
    )
    st.caption(_MANUAL_NOTE)


def _merge_manual_files(frame: pd.DataFrame) -> pd.DataFrame:
    """Merge every currently-uploaded manual CSV into ``frame`` by column.

    Files persist across reruns through the file-uploader widget key.  Each file
    picks its target column (a known signal, or its own stem as a new column);
    one unreadable file surfaces its error without aborting the others.
    """
    files = st.session_state.get(_MANUAL_FILES_KEY) or []
    if not files:
        return frame

    st.markdown(ui.eyebrow("Merge manual signals"), unsafe_allow_html=True)
    for i, uploaded in enumerate(files):
        options = _manual_options(uploaded.name)
        column = st.selectbox(
            f"Column for {uploaded.name}",
            options,
            index=options.index(_guess_manual_column(uploaded.name)),
            key=f"manual_map_{i}_{uploaded.name}",
        )
        try:
            frame = merge_manual_columns(frame, column, uploaded.getvalue())
            st.success(f"Merged {uploaded.name} into {column}.")
        except ValueError as exc:
            st.error(str(exc))
    return frame


def _guess_manual_column(filename: str) -> str:
    """Map a manual CSV filename to the signal column it most likely supplies.

    The stem (extension stripped, lowercased) is matched against the documented
    aliases, with underscores treated as spaces so ``fx_impl_vol``,
    ``FXIMPLVOL`` and ``G7_FX_VOL``-style spellings all resolve.  An
    unrecognised file defaults to its own stem as a brand-new column (per the
    dropzone's note, "a signal the APIs do not carry becomes a new column") —
    not to an existing one, which would overwrite its data.
    """
    stem = Path(filename).stem
    normalized = stem.strip().lower().replace("_", " ")
    for alias, column in _MANUAL_COLUMN_ALIASES.items():
        alias_norm = alias.replace("_", " ")
        if normalized == alias_norm or alias_norm in normalized:
            return column
    # No alias: the file names its own signal.  Return the stem exactly as
    # ``_manual_options`` offers it, so the selectbox default resolves.
    return stem or MANUAL_COLUMNS[0]


def _manual_options(filename: str) -> list[str]:
    """The selectable target columns for one manual CSV.

    The known signals, plus the file's stem as a fresh-column option unless it
    already names one of them (in which case selecting it overrides that signal).
    """
    stem = Path(filename).stem
    options = list(MANUAL_COLUMNS)
    if stem not in options:
        options.append(stem)
    return options


def _render_status(report: ExtractionReport) -> None:
    st.markdown(ui.eyebrow("Extraction status"), unsafe_allow_html=True)

    # Yahoo
    if report.yahoo_ok:
        badge = ui.lozenge("OK", "success")
        for col in report.yahoo_ok:
            st.markdown(ui.status_row(f"Yahoo: {col}", badge), unsafe_allow_html=True)
    for col, reason in report.yahoo_failed:
        badge = ui.lozenge("Failed", "danger")
        st.markdown(
            ui.status_row(f"Yahoo: {col}", badge, reason), unsafe_allow_html=True
        )

    # FRED
    if report.fred_ok:
        badge = ui.lozenge("OK", "success")
        for col in report.fred_ok:
            st.markdown(ui.status_row(f"FRED: {col}", badge), unsafe_allow_html=True)
    for col, reason in report.fred_failed:
        badge = ui.lozenge("Failed", "danger")
        st.markdown(
            ui.status_row(f"FRED: {col}", badge, reason), unsafe_allow_html=True
        )

    # Derived
    for col in report.derived:
        badge = ui.lozenge("Derived", "info")
        st.markdown(ui.status_row(f"FRED: {col}", badge), unsafe_allow_html=True)

    # Manual
    for col in report.manual:
        badge = ui.lozenge("Manual", "warning")
        st.markdown(
            ui.status_row(f"{col}", badge, "requires manual input"),
            unsafe_allow_html=True,
        )


def _render_confirmation(
    accepted: AcceptedUpload, report: ExtractionReport, summary: CleaningSummary
) -> None:
    span = f", {summary.start} to {summary.end}" if summary.start else ""
    st.success(
        f"Extracted {accepted.row_count:,} rows, "
        f"{len(accepted.frame.columns)} columns{span}."
    )
    dropped = ", ".join(summary.dropped_columns) or "no columns"
    exempt = ", ".join(summary.exempt_columns) if summary.exempt_columns else ""
    trailing = f"; {exempt} may trail blank" if exempt else ""
    st.caption(
        f"Cleaned {summary.rows_before:,} → {summary.rows_after:,} rows guaranteed complete"
        f" except for known short feeds (dropped {dropped}){trailing}; "
        f"{summary.start} to {summary.end}."
    )
    if not report.all_ok:
        st.warning(
            "Some sources failed. Missing columns will be reported by validation."
        )
    ui.preview(accepted.frame)