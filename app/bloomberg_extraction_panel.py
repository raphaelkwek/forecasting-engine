"""The Bloomberg extraction panel: file upload, merge, validate, download.

Rendering only. Parsing, merging and validation live in
``forecasting_engine.extraction`` and know nothing about Streamlit. The cached
Fama-French download is shared from ``forecasting_engine.ingest``.

The validation report renderer is shared between this page and the Home
page's summary — that sharing is the whole integration between the two.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import ui
from forecasting_engine.extraction import bloomberg_csv, validation, workbook
from forecasting_engine.extraction.validation import ValidationReport
from forecasting_engine.ingest import fama_french
from forecasting_engine.ingest.fama_french import FactorFetchError, FactorFile
from forecasting_engine.ingest.upload import (
    MAX_UPLOAD_BYTES,
    AcceptedUpload,
    UploadError,
    accept_upload,
    check_extension,
    check_size,
)
from forecasting_engine.store.uploads import record_upload

#: The raw merged frame and its report — the Data page's own working copy,
#: refreshed on every new upload regardless of any commit below.
MERGED_KEY = "extraction_merged"
REPORT_KEY = "extraction_report"
FACTORS_KEY = "fama_french"

#: The cleaned frame (and its own report) that Home and the Signals page
#: read. Only updated when the user clicks "Use Updated Data" — not on every
#: gap-review edit — so both pages stay stable while decisions are still
#: being made.
COMMITTED_KEY = "extraction_committed"
COMMITTED_REPORT_KEY = "extraction_committed_report"

#: What the merged file is called in the upload log and under data/uploads.
MERGED_NAME = "bloomberg_merged.csv"
_LOGGED_KEY = "_logged_bloomberg_merge"

#: Bumped by "Clear Data" so the file_uploader gets a fresh widget key and
#: drops whatever files it was showing, instead of re-displaying them.
_UPLOADER_VERSION_KEY = "_bloomberg_uploader_version"


def _fmt(date) -> str:
    """A date for display: dd/mm/yyyy, no time component."""
    return pd.Timestamp(date).strftime(bloomberg_csv.DATE_DISPLAY_FORMAT)


def render() -> None:
    ui.inject()
    st.header("Bloomberg data extraction")

    if st.button("Clear Data", help="Remove the current upload so you can start over."):
        for key in (MERGED_KEY, REPORT_KEY, COMMITTED_KEY, COMMITTED_REPORT_KEY, _LOGGED_KEY):
            st.session_state.pop(key, None)
        for stale in [k for k in st.session_state if k.startswith("gap_decisions_")]:
            st.session_state.pop(stale, None)
        st.session_state[_UPLOADER_VERSION_KEY] = (
            st.session_state.get(_UPLOADER_VERSION_KEY, 0) + 1
        )
        st.rerun()

    st.caption(
        f"Upload Bloomberg CSV exports, up to {MAX_UPLOAD_BYTES // 1_000_000} MB each. "
        "All selected files are merged on Date with an outer join. Gaps and outliers "
        "are reported for review without blocking the merge."
    )

    uploaded = st.file_uploader(
        "Bloomberg CSV exports",
        type=None,
        accept_multiple_files=True,
        key=f"bloomberg_uploader_{st.session_state.get(_UPLOADER_VERSION_KEY, 0)}",
    )

    if uploaded:
        exports, errors = [], []
        for file in uploaded:
            try:
                data = file.getvalue()
                check_extension(file.name)
                check_size(len(data), filename=file.name)
                exports.append(bloomberg_csv.read_export(file.name, data))
            except (UploadError, bloomberg_csv.BloombergCsvError) as exc:
                errors.append(str(exc))

        for message in errors:
            st.error(message)

        if exports:
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
            _keep_and_log(
                merged, file_id="|".join(getattr(f, "file_id", f.name) for f in uploaded)
            )

    # Falling back to session state (rather than returning when nothing was
    # just uploaded) is what keeps this page showing the last merge instead
    # of going blank when the user navigates here from another tab.
    merged = st.session_state.get(MERGED_KEY)
    report = st.session_state.get(REPORT_KEY)
    if merged is None or report is None:
        st.info("Upload Bloomberg CSV exports above to get started.")
        return

    _render_report(report, merged)

    st.markdown(ui.eyebrow("Fama-French Factors"), unsafe_allow_html=True)
    factors = _factor_file()
    if st.button("Download the latest factors"):
        factors = _download_factors()
    ff = _render_factors(factors, merged)

    download_merged = _render_gap_review(merged)

    st.divider()
    st.markdown(ui.eyebrow("Home & Signals"), unsafe_allow_html=True)
    st.caption(
        "Home's data quality report and the Signals page both read whichever "
        "dataset was last committed here — neither updates on every gap-review "
        "edit. Make your include/clean choices above, then click below to push "
        "them through."
    )
    if st.button("Use Updated Data"):
        st.session_state[COMMITTED_KEY] = download_merged
        st.session_state[COMMITTED_REPORT_KEY] = validation.validate(download_merged)
        st.success("Home and the Signals page now reflect this cleaned dataset.")
    elif COMMITTED_KEY in st.session_state:
        st.caption("A dataset is committed for Home and the Signals page.")
    else:
        st.caption("Nothing committed yet — Home and the Signals page have no data yet.")

    st.write("Download the following files:")
    bloomberg_col, factor_col, workbook_col, _spacer = st.columns([1, 1, 1, 3])
    bloomberg_col.download_button(
        "Bloomberg merged (.csv)",
        data=bloomberg_csv.with_display_dates(download_merged).to_csv(index=False).encode(),
        file_name="bloomberg_merged.csv",
        mime="text/csv",
    )
    if ff is not None:
        factor_col.download_button(
            "Fama-French only (.csv)",
            data=bloomberg_csv.with_display_dates(ff).to_csv(index=False).encode(),
            file_name="fama_french_factors.csv",
            mime="text/csv",
        )
        workbook_col.download_button(
            "Workbook (.xlsx)",
            data=workbook.build(
                bloomberg_csv.with_display_dates(download_merged),
                bloomberg_csv.with_display_dates(ff),
            ),
            file_name="Bloomberg + Fama-French.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def _keep_and_log(merged: pd.DataFrame, *, file_id: str) -> AcceptedUpload:
    """Store the merged file under its content hash and log it to DuckDB.

    The merge is an upload like any other: the bytes go under data/uploads and
    a row goes in the uploads table, once per set of files rather than once
    per Streamlit rerun. Dates are written ISO so the stored copy reads back
    unambiguously.
    """
    # A fixed line ending, so the same merge hashes the same on every machine.
    csv_bytes = merged.to_csv(index=False, date_format="%Y-%m-%d", lineterminator="\n").encode(
        "utf-8"
    )
    accepted = accept_upload(MERGED_NAME, csv_bytes)
    if st.session_state.get(_LOGGED_KEY) != file_id:
        record_upload(accepted)
        st.session_state[_LOGGED_KEY] = file_id
    st.caption(f"Stored as {MERGED_NAME}, content hash {accepted.source.short_hash}.")
    return accepted


def _factor_file() -> FactorFile | None:
    if FACTORS_KEY not in st.session_state:
        st.session_state[FACTORS_KEY] = fama_french.load_latest()
    return st.session_state[FACTORS_KEY]


def _download_factors() -> FactorFile | None:
    try:
        st.session_state[FACTORS_KEY] = fama_french.download()
    except FactorFetchError as exc:
        st.error(f"Could not download the factor file: {exc}")
    return st.session_state.get(FACTORS_KEY)


def _render_factors(factors: FactorFile | None, merged: pd.DataFrame) -> pd.DataFrame | None:
    if factors is None:
        st.info("No factor file yet. Download one to preview it and enable factor downloads.")
        return None
    ff = fama_french.restrict_to(
        factors.frame, merged["Date"].min(), merged["Date"].max()
    )
    st.caption(
        f"{len(ff):,} rows within the Bloomberg dates. "
        f"Content hash {factors.source.short_hash}."
    )
    if ff.empty:
        st.caption("No Fama-French rows fall within the Bloomberg data's date range.")
    else:
        st.caption(f"{_fmt(ff['Date'].min())} to {_fmt(ff['Date'].max())}.")
        st.dataframe(bloomberg_csv.with_display_dates(ff.head(10)), width="stretch")
    return ff


def _render_gap_review(merged: pd.DataFrame) -> pd.DataFrame:
    """Show every row with a missing value and why, and let the user clean some.

    Everything starts as-is — cleaning a row is the deliberate act, the same
    rule the outlier review on the old pipeline used, because a gap is
    usually a real calendar difference rather than a fault. No row is ever
    dropped: a row marked to clean has its missing signals forward-filled
    from the last available value instead. Returns the frame to download.
    """
    gaps = bloomberg_csv.missing_row_report(merged)
    if gaps.empty:
        return merged

    st.markdown(ui.eyebrow("Rows with missing values"), unsafe_allow_html=True)
    st.caption(
        "Each row below is missing at least one signal, with a likely reason — "
        "most are calendar gaps (a security's own market was closed), not "
        "errors. Nothing is removed from the report above, and no row is "
        "dropped from the downloads. Untick a row, or use the buttons below, "
        "to forward-fill it from the last available value in the downloads "
        "only, up to the gap length below."
    )

    key = f"gap_decisions_{len(merged)}_{hash(tuple(merged.columns))}"
    decisions: dict[str, str] = st.session_state.setdefault(key, {})

    clean_all, include_all, gap_col, _spacer = st.columns(
        [1, 1, 1.2, 2.8], vertical_alignment="bottom"
    )
    max_gap = gap_col.number_input(
        "Max fill-gap (days)",
        min_value=1,
        max_value=30,
        value=1,
        step=1,
        key=f"{key}_max_gap",
        help="A gap longer than this is left blank instead of forward-filled.",
    )
    if clean_all.button("Clean all listed rows", key=f"{key}_clean_all"):
        for date in gaps["Date"]:
            decisions[date.date().isoformat()] = "clean"
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
                "Include", help="Untick to forward-fill this row in the downloads", width="small"
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
        wanted = "include" if edited_row["Include"] else "clean"
        if decisions.get(iso) != wanted:
            decisions[iso] = wanted
            changed = True
    if changed:
        st.rerun()

    clean_dates = {pd.Timestamp(iso) for iso, choice in decisions.items() if choice == "clean"}
    cleaned = bloomberg_csv.forward_fill(merged, clean_dates, int(max_gap))

    if clean_dates:
        still_missing = bloomberg_csv.missing_row_report(cleaned)
        stuck = still_missing[still_missing["Date"].isin(clean_dates)]
        if not stuck.empty:
            st.caption(
                f"{len(stuck)} marked row(s) still have a gap longer than "
                f"{int(max_gap)} day(s) and remain missing in the downloads."
            )
    return cleaned


def render_summary() -> None:
    """The Home page's data quality report, read back from session state.

    Reflects whichever dataset was last committed on the Data page via
    "Use Updated Data" — the same commit the Signals page reads — not
    every upload or gap-review edit.
    """
    ui.inject()
    st.subheader("Data quality report")

    report: ValidationReport | None = st.session_state.get(COMMITTED_REPORT_KEY)
    merged = st.session_state.get(COMMITTED_KEY)
    if report is None or merged is None:
        _render_awaiting_upload()
        return

    _render_report(report, merged)


# --- shared between the Data page and the Home summary ---------------------


def _render_awaiting_upload() -> None:
    st.info(
        "No data committed yet. Upload Bloomberg CSV exports on the **Data** page and "
        "click **Use Updated Data**."
    )
    st.caption("This report fills in once a cleaned dataset is committed.")
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
        with st.expander(
            f"{column} — {len(moves)} statistically unusual "
            f"move{'s' if len(moves) != 1 else ''}"
        ):
            rows_html = "".join(
                ui.finding_row(
                    ui.lozenge("Info", "info"),
                    _fmt(move["date"]),
                    f"{move['change']:+,.4g} day-over-day change, "
                    f"{move['robust_score']:.0f}x the typical move",
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
