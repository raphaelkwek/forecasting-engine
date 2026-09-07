"""Merging Bloomberg CSV exports into one contract-shaped upload. Rendering only.

Each export is read into the shape the workbook converter joins and mapped
through the same ticker map, so what leaves this panel is an ordinary
``AcceptedUpload``: the signal CSV the data specification describes, built in
the app rather than at a command line. Schema validation, the quality report
and the upload log then run on it exactly as they do on a file uploaded
directly, and the pages downstream find it under the same session key.
"""

from __future__ import annotations

import streamlit as st

import ui
from forecasting_engine.ingest.bloomberg import ConversionReport, combine
from forecasting_engine.ingest.bloomberg_csv import read_export
from forecasting_engine.ingest.upload import (
    AcceptedUpload,
    UploadError,
    accept_upload,
    check_extension,
    check_size,
    date_range,
)
from forecasting_engine.store.uploads import record_upload
from upload_panel import SESSION_KEY

#: What the merged file is called in the upload log and the quality report.
MERGED_NAME = "bloomberg_signals.csv"

_LOGGED_KEY = "_logged_bloomberg_merge"


def render() -> AcceptedUpload | None:
    """Draw the panel, merge whatever was uploaded, and hand back the result.

    Returns the merged file as an accepted upload for the page to validate, or
    None when there is nothing usable yet.
    """
    ui.inject()
    st.header("Merge Bloomberg exports")
    st.caption(
        "One CSV history export per security, as the terminal saves them. They are "
        "joined on date and mapped onto the column contract here. See "
        "docs/bloomberg-exports.md for which securities to pull."
    )

    # No `type=` filter, for the same reason as the signal uploader: a wrong
    # file should be refused with an explanation, not silently dropped.
    uploaded = st.file_uploader("Bloomberg CSV exports", type=None, accept_multiple_files=True)
    if not uploaded:
        return None

    exports, problems = _read(uploaded)
    for problem in problems:
        st.error(problem)
    if not exports:
        return None

    frame, report = combine(exports)
    _render_conversion(report)
    if not report.used:
        st.error("None of these files supplies a signal the contract asks for.")
        return None

    accepted = accept_upload(MERGED_NAME, frame.to_csv(index=False).encode("utf-8"))
    _log_once(accepted, file_id="|".join(getattr(f, "file_id", f.name) for f in uploaded))
    st.session_state[SESSION_KEY] = accepted
    _render_confirmation(accepted, len(exports))
    return accepted


def _read(uploaded) -> tuple[list, list[str]]:
    """Every readable export, and one message per file that was not."""
    exports, problems = [], []
    for file in uploaded:
        data = file.getvalue()
        try:
            check_extension(file.name)
            check_size(len(data), filename=file.name)
            exports.append(read_export(file.name, data))
        except UploadError as exc:
            problems.append(exc.message)
        except ValueError as exc:
            problems.append(str(exc))
    return exports, problems


def _render_conversion(report: ConversionReport) -> None:
    """Which contract signals the exports supplied, and which they did not."""
    st.markdown(ui.eyebrow("Signals"), unsafe_allow_html=True)
    rows = [
        ui.status_row(column, ui.lozenge("Supplied", "success"), security)
        for column, security in sorted(report.used.items())
    ]
    rows.extend(
        ui.status_row(column, ui.lozenge("Missing", "danger"), "no export supplied this")
        for column in report.missing
    )
    st.markdown("".join(rows), unsafe_allow_html=True)

    for note in report.skipped:
        st.warning(note)
    for note in report.warnings:
        st.warning(note)
    for note in report.notes:
        st.caption(note)
    if report.missing:
        st.caption(
            "Validation below will name the missing signals. The file cannot feed a "
            "forecast until every signal in the contract is supplied."
        )


def _log_once(accepted: AcceptedUpload, *, file_id: str) -> None:
    """Record the merge as an upload, but only on the rerun that first saw it."""
    if st.session_state.get(_LOGGED_KEY) == file_id:
        return
    record_upload(accepted)
    st.session_state[_LOGGED_KEY] = file_id


def _render_confirmation(accepted: AcceptedUpload, exports: int) -> None:
    dates = date_range(accepted.frame)
    span = f", {dates[0]} to {dates[1]}" if dates else ""
    st.success(
        f"Merged {exports} export{'s' if exports != 1 else ''} into {MERGED_NAME} — "
        f"{accepted.row_count:,} rows, {len(accepted.frame.columns)} columns{span}."
    )
    st.caption(f"Content hash {accepted.source.short_hash}")
    st.dataframe(accepted.frame.head(10), width="stretch")
    st.download_button(
        "Signals (.csv)",
        data=accepted.frame.to_csv(index=False).encode("utf-8"),
        file_name=MERGED_NAME,
        mime="text/csv",
    )
