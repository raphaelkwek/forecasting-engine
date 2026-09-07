"""The Bloomberg extraction panel: file upload, merge, validate, download.

Rendering only. Parsing, merging, validation and the Fama-French fetch all
live in ``forecasting_engine.extraction`` and know nothing about Streamlit.

The validation report renderer is shared between this page and the Home
page's summary — that sharing is the whole integration between the two.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from forecasting_engine.extraction import bloomberg_csv, fama_french, validation, workbook
from forecasting_engine.extraction.validation import ValidationReport

#: The merged frame and its report, for the Home page to read back.
MERGED_KEY = "extraction_merged"
REPORT_KEY = "extraction_report"


@st.cache_data(ttl=86_400, show_spinner="Downloading Fama-French factors...")
def _fetch_fama_french():
    return fama_french.fetch()


def _fmt(date) -> str:
    """A date for display: dd/mm/yyyy, no time component."""
    return pd.Timestamp(date).strftime(bloomberg_csv.DATE_DISPLAY_FORMAT)


def render() -> None:
    ui.inject()
    st.header("Bloomberg data extraction")
    st.caption(
        "Upload Bloomberg CSV exports. Multiple files are merged on Date with "
        "an outer join and validated — nothing is dropped automatically, "
        "only reported."
    )

    multiple = st.toggle("Upload multiple files", value=True)
    uploaded = st.file_uploader(
        "Bloomberg CSV exports", type=None, accept_multiple_files=multiple
    )
    if not uploaded:
        return
    files = uploaded if multiple else [uploaded]

    exports, errors = [], []
    for file in files:
        try:
            exports.append(bloomberg_csv.read_export(file.name, file.getvalue()))
        except bloomberg_csv.BloombergCsvError as exc:
            errors.append(str(exc))

    for message in errors:
        st.error(message)
    if not exports:
        return

    merged = bloomberg_csv.merge(exports)
    merged, dropped = bloomberg_csv.drop_empty_columns(merged)

    st.success(
        f"Merged {len(exports)} file(s) into {len(merged):,} rows, "
        f"{len(merged.columns) - 1} data columns."
    )
    if dropped:
        st.caption(
            f"Dropped {len(dropped)} column(s) with no data at all (the security "
            f"has nothing for that field): {', '.join(dropped)}."
        )
    st.dataframe(bloomberg_csv.with_display_dates(merged.head(10)), width="stretch")

    report = validation.validate(merged)
    st.session_state[MERGED_KEY] = merged
    st.session_state[REPORT_KEY] = report
    _render_report(report, merged)

    try:
        ff = _fetch_fama_french()
    except Exception as exc:  # noqa: BLE001 - a network/parse failure, shown as-is
        st.error(f"Could not fetch Fama-French factors: {exc}")
        return
    ff = fama_french.restrict_to(ff, merged["Date"].min(), merged["Date"].max())

    st.markdown(ui.eyebrow("Fama-French Factors"), unsafe_allow_html=True)
    if ff.empty:
        st.caption("No Fama-French rows fall within the Bloomberg data's date range.")
    else:
        st.caption(f"{len(ff):,} rows, {_fmt(ff['Date'].min())} to {_fmt(ff['Date'].max())}.")
        st.dataframe(bloomberg_csv.with_display_dates(ff.head(10)), width="stretch")

    excluded = _render_gap_review(merged)
    download_merged = merged[~merged["Date"].isin(excluded)] if excluded else merged

    col1, col2, col3, _spacer = st.columns([1, 1, 1, 2])
    col1.download_button(
        "Signals (.csv)",
        data=bloomberg_csv.with_display_dates(download_merged).to_csv(index=False).encode(),
        file_name="signals.csv",
        mime="text/csv",
    )
    col2.download_button(
        "Fama-French only (.csv)",
        data=bloomberg_csv.with_display_dates(ff).to_csv(index=False).encode(),
        file_name="fama_french_factors.csv",
        mime="text/csv",
    )
    col3.download_button(
        "Workbook (.xlsx)",
        data=workbook.build(
            bloomberg_csv.with_display_dates(download_merged), bloomberg_csv.with_display_dates(ff)
        ),
        file_name="Signal + Fama-French.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _render_gap_review(merged: pd.DataFrame) -> set[pd.Timestamp]:
    """Show every row with a missing value and why, and let the user drop some.

    Everything starts included — excluding a row is the deliberate act, the
    same rule the outlier review on the old pipeline used, because a gap is
    usually a real calendar difference rather than a fault. Returns the
    dates ticked off, for the caller to leave out of the downloads.
    """
    gaps = bloomberg_csv.missing_row_report(merged)
    if gaps.empty:
        return set()

    st.markdown(ui.eyebrow("Rows with missing values"), unsafe_allow_html=True)
    st.caption(
        "Each row below is missing at least one signal, with a likely reason — "
        "most are calendar gaps (a security's own market was closed), not "
        "errors. Nothing is removed from the report above. Untick a row, or "
        "use the buttons below, to leave it out of the downloads only."
    )

    key = f"gap_decisions_{len(merged)}_{hash(tuple(merged.columns))}"
    decisions: dict[str, str] = st.session_state.setdefault(key, {})

    exclude_all, include_all = st.columns(2)
    if exclude_all.button("Exclude all listed rows", key=f"{key}_exclude_all"):
        for date in gaps["Date"]:
            decisions[date.date().isoformat()] = "exclude"
        st.rerun()
    if include_all.button("Include all listed rows", key=f"{key}_include_all"):
        decisions.clear()
        st.rerun()

    # The table shows dd/mm/yyyy for reading, but decisions are keyed on the
    # ISO string taken straight from each row's own Timestamp — matched back
    # up by position below, never by re-parsing the displayed text — so a
    # dd/mm date is never at risk of being misread as mm/dd.
    gap_rows = list(gaps.iterrows())
    edited = st.data_editor(
        [
            {
                "Include": decisions.get(row["Date"].date().isoformat(), "include") == "include",
                "Date": _fmt(row["Date"]),
                "Missing columns": row["Missing columns"],
                "Likely reason": row["Likely reason"],
            }
            for _, row in gap_rows
        ],
        width="stretch",
        hide_index=True,
        disabled=["Date", "Missing columns", "Likely reason"],
        column_config={
            "Include": st.column_config.CheckboxColumn(
                "Include", help="Untick to leave this row out of the downloads", width="small"
            ),
            "Date": st.column_config.TextColumn(width="small"),
            "Missing columns": st.column_config.TextColumn(width="large"),
            "Likely reason": st.column_config.TextColumn(width="medium"),
        },
        key=f"{key}_editor",
    )

    changed = False
    for (_, gap_row), edited_row in zip(gap_rows, edited, strict=True):
        iso = gap_row["Date"].date().isoformat()
        wanted = "include" if edited_row["Include"] else "exclude"
        if decisions.get(iso) != wanted:
            decisions[iso] = wanted
            changed = True
    if changed:
        st.rerun()

    return {pd.Timestamp(iso) for iso, choice in decisions.items() if choice == "exclude"}


def render_summary() -> None:
    """The Home page's data quality report, read back from session state."""
    ui.inject()
    st.subheader("Data quality report")

    report: ValidationReport | None = st.session_state.get(REPORT_KEY)
    merged = st.session_state.get(MERGED_KEY)
    if report is None or merged is None:
        _render_awaiting_upload()
        return

    _render_report(report, merged)


# --- shared between the Data page and the Home summary ---------------------


def _render_awaiting_upload() -> None:
    st.info("No data ingested yet. Upload Bloomberg CSV exports on the **Data** page.")
    st.caption("This report fills in once files are merged and validated.")
    badge = ui.lozenge("Pending", "neutral")
    rows = "".join(
        ui.status_row(title, badge)
        for title in ("Schema validation", "Duplicate dates", "Weekend rows", "Day-over-day moves")
    )
    st.markdown(rows, unsafe_allow_html=True)


def _render_report(report: ValidationReport, merged: pd.DataFrame) -> None:
    _render_verdict(report)
    _render_coverage(report, merged)
    _render_completeness(report)
    _render_breakdown(report)


def _flagged_count(report: ValidationReport) -> int:
    return report.duplicate_dates + report.weekend_rows + len(report.big_moves)


def _render_verdict(report: ValidationReport) -> None:
    if report.schema_errors:
        st.error(
            f"{len(report.schema_errors)} schema issue"
            f"{'s' if len(report.schema_errors) != 1 else ''} — see the columns "
            "listed below."
        )
        for message in report.schema_errors:
            st.caption(message)
        return

    flagged = _flagged_count(report)
    if flagged:
        st.success(
            f"Merged and validated. {flagged} observation"
            f"{'s' if flagged != 1 else ''} flagged below for information — "
            "none of them stop a run."
        )
    else:
        st.success("Merged and validated. Nothing flagged.")


def _render_coverage(report: ValidationReport, merged: pd.DataFrame) -> None:
    rows, signals, flag_col = st.columns(3)
    rows.metric("Rows", f"{len(merged):,}")
    signals.metric("Signals", len(merged.columns) - 1)
    flag_col.metric("Flagged", _flagged_count(report))

    dates = merged["Date"].dropna()
    if not dates.empty:
        st.caption(f"Covering {_fmt(dates.min())} to {_fmt(dates.max())}")


def _render_completeness(report: ValidationReport) -> None:
    incomplete = {k: v for k, v in report.missing_pct.items() if v > 0}
    if not incomplete:
        return
    st.markdown(ui.eyebrow("Completeness by column"), unsafe_allow_html=True)
    st.dataframe(
        [
            {"Column": name, "Missing %": pct}
            for name, pct in sorted(incomplete.items(), key=lambda kv: -kv[1])
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Column": st.column_config.TextColumn(width="medium"),
            "Missing %": st.column_config.NumberColumn("Missing %", format="%.1f%%"),
        },
    )


def _render_breakdown(report: ValidationReport) -> None:
    has_findings = (
        report.duplicate_date_values or report.weekend_date_values or not report.big_moves.empty
    )
    if not has_findings:
        return

    st.markdown(ui.eyebrow("Flagged observations"), unsafe_allow_html=True)

    if report.duplicate_date_values:
        row = _dates_row(report.duplicate_dates, report.duplicate_date_values)
        with st.expander(f"Duplicate dates — {report.duplicate_dates}"):
            st.markdown(row, unsafe_allow_html=True)

    if report.weekend_date_values:
        row = _dates_row(report.weekend_rows, report.weekend_date_values)
        with st.expander(f"Weekend rows — {report.weekend_rows}"):
            st.markdown(row, unsafe_allow_html=True)

    for column, moves in _by_column(report.big_moves):
        with st.expander(f"{column} — {len(moves)} move{'s' if len(moves) != 1 else ''} over 25%"):
            rows_html = "".join(
                ui.finding_row(
                    ui.lozenge("Info", "info"),
                    _fmt(move["date"]),
                    f"{move['pct_change']:.1%} day-over-day change",
                )
                for move in moves
            )
            st.markdown(rows_html, unsafe_allow_html=True)


def _dates_row(count: int, values: tuple[str, ...]) -> str:
    # ``values`` are ISO strings from the report; reformatted only for
    # display, never re-parsed back into anything that drives a decision.
    shown = ", ".join(_fmt(v) for v in values)
    remaining = count - len(values)
    if remaining > 0:
        shown += f" and {remaining} more"
    return ui.finding_row(ui.lozenge("Info", "info"), "", shown)


def _by_column(big_moves: pd.DataFrame) -> list[tuple[str, list]]:
    grouped: dict[str, list] = {}
    for _, row in big_moves.iterrows():
        grouped.setdefault(row["column"], []).append(row)
    return sorted(grouped.items(), key=lambda kv: -len(kv[1]))
