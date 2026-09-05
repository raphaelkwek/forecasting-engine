"""The upload panel. Rendering only — every rule it enforces lives in the core.

Streamlit reruns the whole script on each interaction, so the one piece of
state this module keeps is which upload has already been written to the log.
Without it, clicking anything on the page would append another row.
"""

from __future__ import annotations

import streamlit as st

import ui
from forecasting_engine.ingest.upload import (
    MAX_UPLOAD_BYTES,
    AcceptedUpload,
    UploadError,
    accept_upload,
    date_range,
)
from forecasting_engine.store.uploads import recent_uploads, record_upload

#: Where the accepted upload is parked for the pages downstream.
SESSION_KEY = "accepted_upload"

_LOGGED_KEY = "_logged_upload_file_id"
_LIMIT_MB = MAX_UPLOAD_BYTES // 1_000_000


def render() -> AcceptedUpload | None:
    """Draw the panel and handle whatever the user has uploaded.

    Returns the accepted upload so the page can hand it to schema validation,
    or None when there is nothing to validate.
    """
    ui.inject()
    st.header("Upload signal data")
    st.caption(
        f"A single CSV of daily market and macroeconomic signals, up to {_LIMIT_MB} MB. "
        "See docs/data-specification.md for the column contract."
    )

    # No `type=` filter on purpose: it would drop non-CSV files in the browser,
    # and the user would get no explanation of why nothing happened.
    uploaded = st.file_uploader("Signal CSV", type=None, accept_multiple_files=False)

    if uploaded is None:
        _render_history()
        return None

    try:
        accepted = accept_upload(uploaded.name, uploaded.getvalue())
    except UploadError as exc:
        st.error(exc.message)
        _render_history()
        return None

    _log_once(accepted, file_id=getattr(uploaded, "file_id", accepted.source.sha256))
    st.session_state[SESSION_KEY] = accepted
    _render_confirmation(accepted)
    _render_history()
    return accepted


def _log_once(accepted: AcceptedUpload, *, file_id: str) -> None:
    """Record the upload, but only on the rerun that first saw it."""
    if st.session_state.get(_LOGGED_KEY) == file_id:
        return
    record_upload(accepted)
    st.session_state[_LOGGED_KEY] = file_id


def _render_confirmation(accepted: AcceptedUpload) -> None:
    dates = date_range(accepted.frame)
    span = f", {dates[0]} to {dates[1]}" if dates else ""
    st.success(
        f"Accepted {accepted.source.name} — {accepted.row_count:,} rows, "
        f"{len(accepted.frame.columns)} columns{span}."
    )
    st.caption(f"Content hash {accepted.source.short_hash}")
    ui.preview(accepted.frame)


def _render_history() -> None:
    history = recent_uploads(limit=10)
    if not history:
        return
    with st.expander(f"Upload history ({len(history)})"):
        st.dataframe(
            [
                {
                    "Uploaded": row.uploaded_at.strftime("%Y-%m-%d %H:%M"),
                    "File": row.filename,
                    "Rows": row.row_count,
                    "Size": f"{row.size_bytes / 1024:.0f} KB",
                    "Hash": row.sha256[:12],
                }
                for row in history
            ],
            width="stretch",
            hide_index=True,
        )
