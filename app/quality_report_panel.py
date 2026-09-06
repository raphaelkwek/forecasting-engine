"""The data quality report, as the portfolio manager reads it.

Lives on the dashboard's front page, not behind a settings menu: it is the
thing you check before trusting a forecast, so it should be the thing you see.

Everything here is informational. Nothing on this page can stop a run — the
report says what is known about the data, and the decision to proceed stays
with the person reading it.

Before an upload it renders a pending state naming every check, rather than a
blank page that leaves you wondering whether it is broken or just empty.
"""

from __future__ import annotations

import streamlit as st

import ui
from forecasting_engine.quality.report import (
    CheckStatus,
    QualityFinding,
    QualityReport,
    Severity,
)

#: Each check status as a word and the lozenge tone that carries it.
_STATUS = {
    CheckStatus.PENDING: ("Pending", "neutral"),
    CheckStatus.PASSED: ("Passed", "success"),
    CheckStatus.FLAGGED: ("Flagged", "warning"),
    CheckStatus.FAILED: ("Failed", "danger"),
}

_SEVERITY_WORD = {
    Severity.BLOCKING: "Blocking",
    Severity.WARNING: "Warning",
    Severity.INFO: "Info",
}


def render(report: QualityReport | None) -> None:
    """Draw the report, or a pending state when there is nothing to draw yet."""
    ui.inject()
    st.subheader("Data quality report")

    if report is None:
        _render_awaiting_upload()
        return

    _render_verdict(report)
    _render_coverage(report)
    _render_completeness(report)
    _render_breakdown(report)
    _render_checks(report)


def _render_awaiting_upload() -> None:
    """AC5: a legible pending state, not a blank page."""
    st.info("No data ingested yet. Upload a signal CSV on the **Data** page.")
    st.caption("These checks will run automatically once a file is accepted.")
    badge = ui.lozenge("Pending", "neutral")
    rows = "".join(ui.status_row(title, badge) for _, title in _pending_titles())
    st.markdown(rows, unsafe_allow_html=True)


def _pending_titles():
    from forecasting_engine.quality.report import KNOWN_CHECKS

    return KNOWN_CHECKS


def _render_verdict(report: QualityReport) -> None:
    summary = report.summary
    if not report.passed:
        st.error(
            f"{summary['blocking_count']} blocking issue"
            f"{'s' if summary['blocking_count'] != 1 else ''} — this file cannot be used. "
            "See the Data page for what to fix."
        )
        return

    flags = summary["warning_count"] + summary["info_count"]
    if flags:
        st.success(
            f"Ready for forecasting. {flags} observation"
            f"{'s' if flags != 1 else ''} flagged below for information — "
            "none of them stop a run."
        )
    else:
        st.success("Ready for forecasting. Nothing flagged.")


def _render_coverage(report: QualityReport) -> None:
    """AC1, first half: the ingested date range."""
    coverage = report.coverage
    if coverage is None:
        return

    # The date range goes in a caption rather than a metric: a metric column is
    # too narrow for two dates and truncates the second one, which is the half
    # that tells you whether the data is current.
    rows, signals, flagged = st.columns(3)
    rows.metric("Rows ingested", f"{coverage.rows:,}")
    signals.metric("Signals", coverage.columns)
    flagged.metric("Flagged", report.summary["finding_count"])

    if coverage.start:
        st.caption(f"Covering {coverage.start} to {coverage.end}")


def _render_completeness(report: QualityReport) -> None:
    """AC1, second half: missing values per signal."""
    section = report.section("missing")
    if section is None or section.status is CheckStatus.PENDING:
        return

    signals = section.stats.get("signals", {})
    if not signals:
        return

    st.markdown(ui.eyebrow("Completeness by signal"), unsafe_allow_html=True)
    st.dataframe(
        [
            {
                "Signal": name,
                "Present": counts["present"],
                "Missing": counts["missing"],
                "Complete": counts["completeness"] * 100,
            }
            for name, counts in signals.items()
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Signal": st.column_config.TextColumn(width="medium"),
            # A progress bar here renders in the theme's accent colour, which
            # reads as an alarm at 100%. A plain percentage says the same thing
            # without implying something is wrong.
            "Complete": st.column_config.NumberColumn("Complete", format="%.1f%%"),
        },
    )
    st.caption(section.stats.get("note", ""))


def _render_breakdown(report: QualityReport) -> None:
    """AC2: a summary, with the per-signal detail expandable from it."""
    by_signal = report.by_signal()
    whole_file = report.whole_file
    if not by_signal and not whole_file:
        return

    st.markdown(ui.eyebrow("Flagged observations"), unsafe_allow_html=True)
    st.caption(
        f"{report.summary['finding_count']} across "
        f"{len(by_signal)} signal{'s' if len(by_signal) != 1 else ''}"
        + (f", plus {len(whole_file)} affecting the file as a whole" if whole_file else "")
        + ". Expand a signal to see the detail."
    )

    for signal, findings in sorted(by_signal.items(), key=lambda kv: -len(kv[1])):
        with st.expander(f"{signal} — {_tally(findings)}"):
            _render_findings(findings)

    if whole_file:
        with st.expander(f"Whole file — {_tally(whole_file)}"):
            _render_findings(whole_file)


def _tally(findings: list[QualityFinding]) -> str:
    counts: dict[Severity, int] = {}
    for found in findings:
        counts[found.severity] = counts.get(found.severity, 0) + 1
    return ", ".join(
        f"{n} {_SEVERITY_WORD[severity].lower()}"
        for severity, n in sorted(counts.items(), key=lambda kv: kv[0].value)
    )


def _render_findings(findings: list[QualityFinding]) -> None:
    """Each finding on its own line, with its location and full message."""
    tone = {
        Severity.BLOCKING: "danger",
        Severity.WARNING: "warning",
        Severity.INFO: "info",
    }
    rows = [
        ui.finding_row(
            ui.lozenge(_SEVERITY_WORD[f.severity], tone[f.severity]),
            _where(f),
            f.detail,
        )
        for f in findings
    ]
    st.markdown("".join(rows), unsafe_allow_html=True)


def _where(found: QualityFinding) -> str:
    """Location, in the terms the reader has: dates first, then line numbers.

    A date is what a portfolio manager recognises; a line number is what they
    need to open the file at. Both are shown when both are known, and the count
    stands in when there are more than a handful.
    """
    parts: list[str] = []
    if found.dates:
        shown = ", ".join(found.dates[:3])
        if len(found.dates) < found.count:
            shown += f" and {found.count - len(found.dates)} more"
        parts.append(shown)
    elif found.count > 1:
        parts.append(f"{found.count} values")

    if found.rows:
        label = "line" if len(found.rows) == 1 else "lines"
        parts.append(f"{label} {', '.join(str(r) for r in found.rows[:3])}")

    if found.value is not None:
        parts.append(f"value {found.value:,.4g}")

    return " &middot; ".join(parts)


def _render_checks(report: QualityReport) -> None:
    """Which checks ran, and which have not been built yet."""
    st.markdown(ui.eyebrow("Checks"), unsafe_allow_html=True)
    rows = []
    for section in report.sections:
        word, tone = _STATUS[section.status]
        count = len(section.findings)
        meta = f"{count} flagged" if count else ""
        rows.append(ui.status_row(section.title, ui.lozenge(word, tone), meta))
    st.markdown("".join(rows), unsafe_allow_html=True)
