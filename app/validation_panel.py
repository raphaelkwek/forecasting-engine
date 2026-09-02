"""Schema validation and the data quality report. Rendering only.

Runs after a file has been accepted as a file. A pass unlocks data preparation
by putting a ``ValidatedUpload`` in session state; a failure leaves that key
absent, which is what halts the pipeline.

The report is rendered from ``QualityReport`` — the model schema validation,
outlier detection and gap checks all write into — so the checks that have not
been built yet already show as pending rather than as an absence.
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
from forecasting_engine.quality.report import CheckStatus, QualityReport, Severity
from forecasting_engine.quality.schema_check import quality_report
from forecasting_engine.store.validations import record_validation

#: The token data preparation will require. Absent means the pipeline is halted.
VALIDATED_KEY = "validated_upload"

#: The assembled report, for the pages downstream to read.
REPORT_KEY = "quality_report"

_LOGGED_KEY = "_logged_validation_sha"

_SEVERITY_LABEL = {
    Severity.BLOCKING: "Blocking",
    Severity.WARNING: "Warning",
    Severity.INFO: "Info",
}

_STATUS_LABEL = {
    CheckStatus.PENDING: "Pending",
    CheckStatus.PASSED: "Passed",
    CheckStatus.FLAGGED: "Flagged",
    CheckStatus.FAILED: "Failed",
}


def render(accepted: AcceptedUpload) -> None:
    """Validate ``accepted``, gate the pipeline on the outcome, and report."""
    st.subheader("Schema validation")

    result = validate_upload(accepted)
    _log_once(result)

    report = quality_report(accepted, result)
    st.session_state[REPORT_KEY] = report

    try:
        validated = require_valid(accepted, result)
    except ValidationFailed as exc:
        # Clear any earlier pass, so a bad file cannot inherit a stale unlock.
        st.session_state.pop(VALIDATED_KEY, None)
        st.error(exc.message)
        st.caption("Pipeline halted. Fix the file and upload it again.")
        _render_report(report)
        return

    st.session_state[VALIDATED_KEY] = validated
    st.success(_pass_message(result))
    _render_report(report)


def _pass_message(result: ValidationResult) -> str:
    if result.is_clean:
        return "Matches the schema. Proceeding to data preparation."
    noted = len(result.warnings)
    return (
        f"Matches the schema, with {noted} {'point' if noted == 1 else 'points'} "
        "to note below. Proceeding to data preparation."
    )


def _log_once(result: ValidationResult) -> None:
    """Record the run, but only on the rerun that first saw this file."""
    if st.session_state.get(_LOGGED_KEY) == result.source.sha256:
        return
    record_validation(result)
    st.session_state[_LOGGED_KEY] = result.source.sha256


def _render_report(report: QualityReport) -> None:
    """The data quality report: coverage, headline counts, then every finding."""
    st.markdown("**Data quality report**")

    summary = report.summary
    checked, blockers, warnings = st.columns(3)
    checked.metric("Rows checked", f"{summary['rows']:,}" if summary["rows"] else "—")
    blockers.metric("Blocking", summary["blocking_count"])
    warnings.metric("Warnings", summary["warning_count"])

    if report.coverage and report.coverage.start:
        st.caption(
            f"{report.coverage.columns} signals, "
            f"{report.coverage.start} to {report.coverage.end}"
        )

    _render_findings(report)
    _render_check_status(report)


def _render_findings(report: QualityReport) -> None:
    if not report.findings:
        st.caption("No issues found.")
        return

    st.dataframe(
        [
            {
                "Severity": _SEVERITY_LABEL[found.severity],
                "Signal": found.signal or "whole file",
                "Lines": _lines(found),
                "Date": found.dates[0] if found.dates else "",
                "Cells": found.count,
                "Problem": found.detail,
            }
            for found in report.findings
        ],
        width="stretch",
        hide_index=True,
        # The signal name is the answer to "where is the problem", so it must
        # never truncate. Auto-sizing clips the longer ones (credit_spread_hy).
        column_config={
            "Severity": st.column_config.TextColumn(width="small"),
            "Signal": st.column_config.TextColumn(width="medium"),
            "Lines": st.column_config.TextColumn(width="medium"),
            "Date": st.column_config.TextColumn(width="small"),
            "Cells": st.column_config.NumberColumn(width="small"),
            "Problem": st.column_config.TextColumn(width="large"),
        },
    )


def _render_check_status(report: QualityReport) -> None:
    """Which checks have run. Pending ones are named rather than left blank."""
    waiting = [s.title for s in report.sections if s.status is CheckStatus.PENDING]
    if not waiting:
        return
    st.caption(
        "Checks not yet run: " + ", ".join(waiting) + ". "
        "These arrive with outlier detection, gap analysis and missing-value handling."
    )


def _lines(found) -> str:
    """Line numbers as the user's spreadsheet numbers them."""
    if not found.rows:
        return "whole file"
    listed = ", ".join(str(row) for row in found.rows)
    remaining = found.count - len(found.rows)
    return f"{listed} +{remaining} more" if remaining > 0 else listed
