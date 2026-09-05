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

import ui
from forecasting_engine.ingest.upload import AcceptedUpload
from forecasting_engine.ingest.validation import (
    ValidationFailed,
    ValidationResult,
    require_valid,
    validate_upload,
)
from forecasting_engine.quality.build import apply_decisions, build_report, with_decisions
from forecasting_engine.quality.report import CheckStatus, QualityReport, Severity
from forecasting_engine.store.validations import record_validation

#: The token data preparation will require. Absent means the pipeline is halted.
VALIDATED_KEY = "validated_upload"

#: The assembled report, for the pages downstream to read.
REPORT_KEY = "quality_report"

#: The frame a model should see, once exclusions are applied.
PREPARED_KEY = "prepared_frame"

#: finding id -> "include" | "exclude", surviving Streamlit's reruns.
DECISIONS_KEY = "outlier_decisions"

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
    ui.inject()
    st.subheader("Schema validation")

    result = validate_upload(accepted)
    _log_once(result)

    report = with_decisions(build_report(accepted, result), _decisions())
    st.session_state[REPORT_KEY] = report
    st.session_state[PREPARED_KEY] = apply_decisions(accepted.frame, report)

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
    _render_download(accepted)
    _render_report(report)


def _render_download(accepted: AcceptedUpload) -> None:
    csv_bytes = accepted.frame.to_csv(index=False).encode()
    st.download_button(
        "Download full CSV",
        data=csv_bytes,
        file_name="signals.csv",
        mime="text/csv",
    )


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
    st.markdown(ui.eyebrow("Data quality report"), unsafe_allow_html=True)

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
    _render_outlier_review(report)
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
        # never truncate. Auto-sizing clips the longer ones.
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


def _decisions() -> dict[str, str]:
    return st.session_state.setdefault(DECISIONS_KEY, {})


def _render_outlier_review(report: QualityReport) -> None:
    """Let the portfolio manager keep or drop each flagged outlier.

    Everything starts included. Excluding is the deliberate act, because on real
    institutional data every flag we have seen was a genuine dislocation — the
    COVID crash, February 2018 — rather than a fault. Those are the days a
    tail-risk model most needs, so dropping one should take a decision.
    """
    flagged = [f for f in report.findings if f.check == "outliers"]
    if not flagged:
        return

    excluded = sum(1 for f in flagged if f.decision == "exclude")
    with st.expander(
        f"Review outliers ({len(flagged)} flagged"
        + (f", {excluded} excluded" if excluded else "")
        + ")",
        expanded=bool(excluded),
    ):
        st.caption(
            "Flagged values are still in the data. Untick one to blank that single "
            "cell before the forecasting engine runs — the row and every other "
            "signal on it are kept. On clean data these are usually real market "
            "events, not faults."
        )

        edited = st.data_editor(
            [
                {
                    "Include": f.decision != "exclude",
                    "Signal": f.signal,
                    "Date": f.dates[0] if f.dates else "",
                    "Value": f.value,
                    "Why": f.detail,
                }
                for f in flagged
            ],
            width="stretch",
            hide_index=True,
            disabled=["Signal", "Date", "Value", "Why"],
            column_config={
                "Include": st.column_config.CheckboxColumn(
                    "Include", help="Untick to exclude this value from the run", width="small"
                ),
                "Signal": st.column_config.TextColumn(width="medium"),
                "Date": st.column_config.TextColumn(width="small"),
                "Value": st.column_config.NumberColumn(width="small"),
                "Why": st.column_config.TextColumn(width="large"),
            },
            key=f"outlier_review_{report.source.sha256[:12]}",
        )

        _record(flagged, edited)


def _record(flagged: list, edited: list[dict]) -> None:
    """Store what the editor came back with, and rerun if anything changed."""
    decisions = _decisions()
    changed = False
    for found, row in zip(flagged, edited, strict=False):
        wanted = "include" if row["Include"] else "exclude"
        if decisions.get(found.id) != wanted:
            decisions[found.id] = wanted
            changed = True
    if changed:
        st.rerun()
