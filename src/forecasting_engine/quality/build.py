"""Assembling the data quality report, and applying the decisions taken on it.

One place that knows which checks exist and in what order they run, so the
dashboard does not. Checks not yet built stay pending, which is what the report
view renders instead of a blank page.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from forecasting_engine.ingest.upload import AcceptedUpload, date_range
from forecasting_engine.ingest.validation import ValidationResult
from forecasting_engine.quality import outliers
from forecasting_engine.quality.report import Coverage, QualityFinding, QualityReport
from forecasting_engine.quality.schema_check import schema_section


def build_report(accepted: AcceptedUpload, result: ValidationResult) -> QualityReport:
    """Run every available check over one upload.

    Outlier detection runs on every upload, chained after schema validation —
    but only when validation passed. Scoring the spread of a column that failed
    to parse as numbers would produce findings about nothing.
    """
    span = date_range(accepted.frame)
    report = QualityReport(
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

    if result.passed:
        report = report.with_section(outliers.detect(accepted.frame))
    return report


def with_decisions(
    report: QualityReport, decisions: Mapping[str, str]
) -> QualityReport:
    """A copy of ``report`` carrying the portfolio manager's include/exclude calls.

    ``decisions`` maps a finding id to "include" or "exclude". Ids absent from
    it keep whatever they had, so a partly-reviewed report is not reset.
    """
    if not decisions:
        return report
    updated = report
    for section in report.sections:
        if not section.findings:
            continue
        findings = tuple(
            f.decided(decisions[f.id]) if f.id in decisions else f for f in section.findings
        )
        if findings != section.findings:
            updated = updated.with_section(
                type(section)(
                    check=section.check,
                    title=section.title,
                    status=section.status,
                    findings=findings,
                    stats=section.stats,
                )
            )
    return updated


def apply_decisions(frame: pd.DataFrame, report: QualityReport) -> pd.DataFrame:
    """The data a model should see, given what the portfolio manager excluded.

    Excluded cells are blanked, not deleted: the row survives, every other
    signal on that date survives, and the gap is handled by the same
    missing-value machinery as any other. Removing the row would silently drop
    seven good observations to discard one.

    ``frame`` is not modified — the uploaded data stays exactly as delivered,
    which is what makes an exclusion reversible.
    """
    excluded = report.excluded
    if not excluded:
        return frame

    adjusted = frame.copy()
    for found in excluded:
        if found.signal is None or found.signal not in adjusted.columns:
            continue
        for position in _positions(found, len(adjusted)):
            adjusted.iloc[position, adjusted.columns.get_loc(found.signal)] = pd.NA
    return adjusted


def _positions(found: QualityFinding, height: int) -> list[int]:
    """Row positions for a finding, from the CSV line numbers it carries."""
    return [line - 2 for line in found.rows if 0 <= line - 2 < height]
