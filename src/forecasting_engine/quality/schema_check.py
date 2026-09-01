"""Schema validation, expressed as a section of the data quality report.

The adapter lives here rather than in ``ingest/validation.py`` so that the
validator stays independent of the report, and the report model stays
independent of the validator. Outlier and gap checks will add sibling modules
of the same shape.
"""

from __future__ import annotations

import pandas as pd

from forecasting_engine.ingest.schema import BLOCKING_KINDS, DATE_COLUMN
from forecasting_engine.ingest.upload import AcceptedUpload, date_range
from forecasting_engine.ingest.validation import ValidationResult
from forecasting_engine.quality.report import (
    CheckStatus,
    Coverage,
    QualityFinding,
    QualityReport,
    QualitySection,
    Severity,
)

CHECK = "schema"
TITLE = "Schema validation"


def schema_section(
    result: ValidationResult, frame: pd.DataFrame | None = None
) -> QualitySection:
    """Convert a validation result into a report section.

    Pass ``frame`` to have each finding carry the date of the row it concerns —
    the per-signal breakdown reads better with a date than a line number alone.
    """
    dates = _row_dates(frame)
    findings = tuple(_finding(issue, dates) for issue in result.issues)
    return QualitySection(
        check=CHECK,
        title=TITLE,
        status=_status(result),
        findings=findings,
        stats={
            "issue_count": len(result.issues),
            "blocking_count": len(result.blocking),
            "warning_count": len(result.warnings),
            "checked_at": result.checked_at.isoformat(),
        },
    )


def quality_report(
    accepted: AcceptedUpload, result: ValidationResult
) -> QualityReport:
    """The full report for one upload: schema filled in, the rest pending."""
    span = date_range(accepted.frame)
    return QualityReport(
        source=accepted.source,
        generated_at=result.checked_at,
        coverage=Coverage(
            rows=accepted.row_count,
            columns=len(accepted.frame.columns),
            start=span[0] if span else None,
            end=span[1] if span else None,
        ),
        sections=QualityReport.pending(accepted.source).sections,
    ).with_section(schema_section(result, accepted.frame))


def _status(result: ValidationResult) -> CheckStatus:
    if result.blocking:
        return CheckStatus.FAILED
    return CheckStatus.FLAGGED if result.issues else CheckStatus.PASSED


def _finding(issue, dates: pd.Series | None) -> QualityFinding:
    return QualityFinding(
        check=CHECK,
        severity=Severity.BLOCKING if issue.kind in BLOCKING_KINDS else Severity.WARNING,
        detail=issue.detail,
        signal=issue.column,
        rows=issue.rows,
        dates=_dates_for(issue, dates),
        count=issue.count,
        truncated=issue.truncated,
    )


def _row_dates(frame: pd.DataFrame | None) -> pd.Series | None:
    """The file's dates, positionally indexed, or None if they are unusable."""
    if frame is None or DATE_COLUMN not in frame.columns:
        return None
    parsed = pd.to_datetime(frame[DATE_COLUMN], errors="coerce", format="ISO8601")
    return parsed.reset_index(drop=True)


def _dates_for(issue, dates: pd.Series | None) -> tuple[str, ...]:
    """Look up the date of each offending row.

    Skipped for problems in the date column itself: quoting a date we could not
    parse back at the reader would be circular.
    """
    if dates is None or not issue.rows or issue.column == DATE_COLUMN:
        return ()
    found = []
    for line in issue.rows:
        position = line - 2  # line 1 is the header, and lines are 1-based
        if 0 <= position < len(dates):
            value = dates.iloc[position]
            if not pd.isna(value):
                found.append(value.date().isoformat())
    return tuple(found)
