"""Schema validation and the data quality report. Rendering only.

Runs after a file has been accepted as a file. A pass unlocks data preparation
by putting a ``ValidatedUpload`` in session state; a failure leaves that key
absent, which is what halts the pipeline.
"""

from __future__ import annotations

import streamlit as st

from forecasting_engine.ingest.upload import AcceptedUpload
from forecasting_engine.ingest.validation import (
    ValidationFailed,
    ValidationResult,
    require_valid,
    validate_upload,
)
from forecasting_engine.store.validations import record_validation

#: The token data preparation will require. Absent means the pipeline is halted.
VALIDATED_KEY = "validated_upload"

_LOGGED_KEY = "_logged_validation_sha"

_SEVERITY = {True: "Blocking", False: "Warning"}


def render(accepted: AcceptedUpload) -> None:
    """Validate ``accepted``, gate the pipeline on the outcome, and report."""
    st.subheader("Schema validation")

    result = validate_upload(accepted)
    _log_once(result)

    try:
        validated = require_valid(accepted, result)
    except ValidationFailed as exc:
        # Clear any earlier pass, so a bad file cannot inherit a stale unlock.
        st.session_state.pop(VALIDATED_KEY, None)
        st.error(exc.message)
        st.caption("Pipeline halted. Fix the file and upload it again.")
        _render_report(result, rows=accepted.row_count)
        return

    st.session_state[VALIDATED_KEY] = validated
    if result.is_clean:
        st.success("Matches the schema. Proceeding to data preparation.")
    else:
        st.success(
            f"Matches the schema, with {len(result.warnings)} "
            f"{'point' if len(result.warnings) == 1 else 'points'} to note below. "
            "Proceeding to data preparation."
        )
    _render_report(result, rows=accepted.row_count)


def _log_once(result: ValidationResult) -> None:
    """Record the run, but only on the rerun that first saw this file."""
    if st.session_state.get(_LOGGED_KEY) == result.source.sha256:
        return
    record_validation(result)
    st.session_state[_LOGGED_KEY] = result.source.sha256


def _render_report(result: ValidationResult, *, rows: int) -> None:
    """The data quality report: every issue, with its severity and location."""
    st.markdown("**Data quality report**")

    summary = result.summary
    checked, blockers, warnings = st.columns(3)
    checked.metric("Rows checked", f"{rows:,}")
    blockers.metric("Blocking", summary["blocking_count"])
    warnings.metric("Warnings", summary["warning_count"])

    if result.is_clean:
        st.caption("No issues found.")
        return

    st.dataframe(
        [
            {
                "Severity": _SEVERITY[record["blocking"]],
                "Column": record["column"],
                "Lines": _lines(record),
                "Cells": record["count"],
                "Problem": record["detail"],
            }
            for record in result.as_records()
        ],
        width="stretch",
        hide_index=True,
    )


def _lines(record: dict) -> str:
    """Line numbers as the user's spreadsheet numbers them."""
    rows = record["rows"]
    if not rows:
        return "whole file"
    listed = ", ".join(str(row) for row in rows)
    remaining = record["count"] - len(rows)
    return f"{listed} +{remaining} more" if remaining > 0 else listed
