"""The shared data quality report model.

Four tickets write into this: schema validation (FYP-8), outlier detection
(FYP-9), gap-versus-holiday checks (FYP-10), and the report view (FYP-25). The
tests below fix the parts each of them depends on.
"""

from datetime import datetime

import pytest

from forecasting_engine.ingest.provenance import SourceFile
from forecasting_engine.quality.report import (
    KNOWN_CHECKS,
    CheckStatus,
    Coverage,
    QualityFinding,
    QualityReport,
    QualitySection,
    Severity,
)

SOURCE = SourceFile(name="signals.csv", sha256="a" * 64, size_bytes=1024)
AT = datetime(2026, 9, 1, 12, 0)


def finding(**kwargs) -> QualityFinding:
    base = {
        "check": "outliers",
        "severity": Severity.INFO,
        "detail": "6.2 standard deviations from the mean",
        "signal": "vix",
    }
    return QualityFinding(**{**base, **kwargs})


def report(*sections, coverage=None) -> QualityReport:
    return QualityReport(
        source=SOURCE, generated_at=AT, coverage=coverage, sections=tuple(sections)
    )


# --- FYP-25: a pending report rather than a blank or broken view -----------


def test_a_pending_report_lists_every_known_check_as_pending():
    pending = QualityReport.pending(SOURCE, generated_at=AT)

    assert pending.status is CheckStatus.PENDING
    assert [s.check for s in pending.sections] == [key for key, _ in KNOWN_CHECKS]
    assert all(s.status is CheckStatus.PENDING for s in pending.sections)


def test_a_pending_report_has_no_findings_but_is_still_readable():
    pending = QualityReport.pending(SOURCE, generated_at=AT)

    assert pending.findings == ()
    assert pending.summary["pending_count"] == len(KNOWN_CHECKS)
    assert pending.by_signal() == {}


def test_checks_that_have_not_run_stay_pending_alongside_ones_that_have():
    filled = QualityReport.pending(SOURCE, generated_at=AT).with_section(
        QualitySection(check="schema", title="Schema", status=CheckStatus.PASSED)
    )

    statuses = {s.check: s.status for s in filled.sections}
    assert statuses["schema"] is CheckStatus.PASSED
    assert statuses["outliers"] is CheckStatus.PENDING
    assert filled.summary["pending_count"] == len(KNOWN_CHECKS) - 1


def test_adding_a_section_replaces_the_placeholder_rather_than_appending():
    filled = QualityReport.pending(SOURCE, generated_at=AT).with_section(
        QualitySection(check="schema", title="Schema", status=CheckStatus.PASSED)
    )
    assert len(filled.sections) == len(KNOWN_CHECKS)


def test_an_unknown_check_is_appended_so_new_checks_need_no_registry_edit():
    filled = report().with_section(
        QualitySection(check="bespoke", title="Bespoke", status=CheckStatus.PASSED)
    )
    assert [s.check for s in filled.sections] == ["bespoke"]


# --- severity: only schema blocks -----------------------------------------


def test_a_report_with_a_blocking_finding_has_failed_status():
    section = QualitySection(
        check="schema",
        title="Schema",
        status=CheckStatus.FAILED,
        findings=(finding(check="schema", severity=Severity.BLOCKING),),
    )
    assert report(section).status is CheckStatus.FAILED
    assert not report(section).passed


def test_informational_findings_never_block():
    # FYP-9 and FYP-25 both require the user to proceed regardless of flags.
    section = QualitySection(
        check="outliers",
        title="Outliers",
        status=CheckStatus.FLAGGED,
        findings=(finding(), finding(signal="term_spread")),
    )
    assert report(section).passed
    assert report(section).status is CheckStatus.FLAGGED


def test_a_report_where_everything_passed_reports_passed():
    section = QualitySection(check="schema", title="Schema", status=CheckStatus.PASSED)
    assert report(section).status is CheckStatus.PASSED


# --- FYP-9: signal, date and value on every flagged outlier ----------------


def test_a_finding_carries_the_signal_date_and_value():
    flagged = finding(dates=("2024-03-16",), value=82.69, rows=(54,))

    assert flagged.signal == "vix"
    assert flagged.dates == ("2024-03-16",)
    assert flagged.value == 82.69


def test_findings_have_stable_ids_so_a_decision_can_be_attached():
    first = finding(dates=("2024-03-16",), value=82.69)
    same = finding(dates=("2024-03-16",), value=82.69)
    other = finding(dates=("2024-03-17",), value=82.69)

    assert first.id == same.id
    assert first.id != other.id


def test_an_id_survives_a_change_of_wording():
    # The detail text is presentation. Rewording it must not orphan a decision
    # the portfolio manager already made about that outlier.
    original = finding(dates=("2024-03-16",), value=82.69, detail="6.2 sd from mean")
    reworded = finding(dates=("2024-03-16",), value=82.69, detail="6.2 SD above average")

    assert original.id == reworded.id


def test_a_finding_defaults_to_undecided():
    assert finding().decision == "undecided"


def test_a_decision_can_be_recorded_without_mutating_the_original():
    flagged = finding(dates=("2024-03-16",), value=82.69)
    excluded = flagged.decided("exclude")

    assert excluded.decision == "exclude"
    assert flagged.decision == "undecided"
    assert excluded.id == flagged.id


def test_an_unknown_decision_is_refused():
    with pytest.raises(ValueError):
        finding().decided("maybe")


def test_excluded_findings_can_be_separated_from_the_rest():
    kept = finding(dates=("2024-03-16",))
    dropped = finding(dates=("2024-03-17",)).decided("exclude")
    section = QualitySection(
        check="outliers", title="Outliers", status=CheckStatus.FLAGGED,
        findings=(kept, dropped),
    )

    assert [f.dates for f in report(section).excluded] == [("2024-03-17",)]


# --- FYP-25: per-signal breakdown expandable from a summary ----------------


def test_findings_group_by_signal():
    section = QualitySection(
        check="outliers",
        title="Outliers",
        status=CheckStatus.FLAGGED,
        findings=(
            finding(signal="vix", dates=("2024-03-16",)),
            finding(signal="vix", dates=("2024-03-17",)),
            finding(signal="term_spread", dates=("2024-05-02",)),
        ),
    )

    grouped = report(section).by_signal()
    assert set(grouped) == {"vix", "term_spread"}
    assert len(grouped["vix"]) == 2


def test_grouping_spans_every_check_so_one_signal_shows_all_its_problems():
    schema_section = QualitySection(
        check="schema", title="Schema", status=CheckStatus.FAILED,
        findings=(finding(check="schema", severity=Severity.BLOCKING, signal="vix"),),
    )
    outlier_section = QualitySection(
        check="outliers", title="Outliers", status=CheckStatus.FLAGGED,
        findings=(finding(signal="vix"),),
    )

    grouped = report(schema_section, outlier_section).by_signal()
    assert {f.check for f in grouped["vix"]} == {"schema", "outliers"}


def test_whole_file_findings_are_grouped_apart_from_named_signals():
    section = QualitySection(
        check="schema", title="Schema", status=CheckStatus.FAILED,
        findings=(finding(check="schema", signal=None, detail="file is empty"),),
    )
    assert list(report(section).by_signal()) == []
    assert len(report(section).whole_file) == 1


def test_the_summary_counts_each_severity():
    section = QualitySection(
        check="schema", title="Schema", status=CheckStatus.FAILED,
        findings=(
            finding(check="schema", severity=Severity.BLOCKING),
            finding(check="schema", severity=Severity.WARNING),
            finding(check="schema", severity=Severity.INFO),
            finding(check="schema", severity=Severity.INFO, signal="vix2"),
        ),
    )
    summary = report(section).summary
    assert summary["blocking_count"] == 1
    assert summary["warning_count"] == 1
    assert summary["info_count"] == 2
    assert summary["finding_count"] == 4


# --- coverage: date range and shape (FYP-25 AC1) ---------------------------


def test_coverage_records_the_range_and_shape():
    cov = Coverage(rows=1500, columns=9, start="2020-01-02", end="2025-10-01")
    assert report(coverage=cov).coverage.start == "2020-01-02"
    assert report(coverage=cov).summary["rows"] == 1500


def test_a_report_without_coverage_still_summarises():
    assert report().summary["rows"] is None


# --- serialisation, so the report survives a round trip through the store --


def test_a_report_round_trips_through_plain_data():
    cov = Coverage(rows=3, columns=9, start="2024-01-01", end="2024-01-03")
    section = QualitySection(
        check="outliers",
        title="Outliers",
        status=CheckStatus.FLAGGED,
        findings=(finding(dates=("2024-03-16",), value=82.69, rows=(54,)),),
        stats={"threshold": "4 sd"},
    )
    original = report(section, coverage=cov)

    restored = QualityReport.from_dict(original.as_dict())

    assert restored == original


def test_serialised_findings_are_plain_json_types():
    section = QualitySection(
        check="outliers", title="Outliers", status=CheckStatus.FLAGGED,
        findings=(finding(dates=("2024-03-16",), value=82.69),),
    )
    payload = report(section).as_dict()

    record = payload["sections"][0]["findings"][0]
    assert record["severity"] == "info"
    assert record["dates"] == ["2024-03-16"]
    assert isinstance(record["id"], str)
