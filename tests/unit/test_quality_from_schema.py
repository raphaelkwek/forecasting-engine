"""Turning schema validation into a section of the data quality report."""

from datetime import datetime

from forecasting_engine.ingest.upload import accept_upload
from forecasting_engine.ingest.validation import validate_upload
from forecasting_engine.quality.report import CheckStatus, Severity
from forecasting_engine.quality.schema_check import quality_report, schema_section

HEADER = (
    "date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    "fx_impl_vol,breakeven_10y,term_spread"
)
ROWS = [
    "2024-01-01,100.0,50.0,15.0,3.5,1.2,8.0,2.2,1.0",
    "2024-01-02,101.0,50.1,16.0,3.6,1.2,8.1,2.2,1.0",
    "2024-01-03,102.0,50.2,17.0,3.7,1.3,8.2,2.3,1.1",
]


def csv_bytes(rows=None, header=HEADER) -> bytes:
    return ("\n".join([header, *(rows or ROWS)]) + "\n").encode()


def checked(data: bytes, name: str = "signals.csv"):
    accepted = accept_upload(name, data, uploads_dir=None)
    return accepted, validate_upload(accepted, checked_at=datetime(2026, 9, 1, 12, 0))


def test_a_clean_file_produces_a_passed_section():
    _, result = checked(csv_bytes())
    section = schema_section(result)

    assert section.check == "schema"
    assert section.status is CheckStatus.PASSED
    assert section.findings == ()


def test_a_blocking_issue_produces_a_failed_section():
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",oops,")
    _, result = checked(csv_bytes(rows))
    section = schema_section(result)

    assert section.status is CheckStatus.FAILED
    (found,) = [f for f in section.findings if f.check == "schema"]
    assert found.severity is Severity.BLOCKING
    assert found.signal == "vix"
    assert found.rows == (3,)


def test_a_range_breach_is_a_warning_not_a_block():
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",900.0,")
    _, result = checked(csv_bytes(rows))
    section = schema_section(result)

    assert section.status is CheckStatus.FLAGGED
    (found,) = section.findings
    assert found.severity is Severity.WARNING


def test_a_missing_column_has_no_rows_and_names_the_signal():
    header = HEADER.replace(",vix", "")
    rows = [",".join(r.split(",")[:3] + r.split(",")[4:]) for r in ROWS]
    _, result = checked(csv_bytes(rows, header))

    (found,) = [f for f in schema_section(result).findings if f.check == "schema"]
    assert found.signal == "vix"
    assert found.rows == ()


def test_the_section_records_how_much_was_checked():
    _, result = checked(csv_bytes())
    stats = schema_section(result).stats

    assert stats["issue_count"] == 0
    assert stats["checked_at"] == "2026-09-01T12:00:00"


# --- dates on findings, which FYP-9 and FYP-25 both display ----------------


def test_a_finding_carries_the_date_of_the_offending_row():
    rows = list(ROWS)
    rows[2] = rows[2].replace(",17.0,", ",oops,")
    accepted, result = checked(csv_bytes(rows))

    (found,) = [f for f in schema_section(result, accepted.frame).findings]
    assert found.dates == ("2024-01-03",)


def test_dates_are_omitted_when_the_frame_is_not_supplied():
    rows = list(ROWS)
    rows[2] = rows[2].replace(",17.0,", ",oops,")
    _, result = checked(csv_bytes(rows))

    (found,) = schema_section(result).findings
    assert found.dates == ()


def test_dates_are_omitted_when_the_date_column_is_the_broken_one():
    # Quoting a date we could not parse back at the reader would be circular;
    # the line number is the only useful handle there.
    rows = list(ROWS)
    rows[1] = rows[1].replace("2024-01-02", "nonsense")
    accepted, result = checked(csv_bytes(rows))

    (found,) = schema_section(result, accepted.frame).findings
    assert found.signal == "date"
    assert found.rows == (3,)
    assert found.dates == ()


# --- the whole report ------------------------------------------------------


def test_the_report_carries_coverage_from_the_file():
    accepted, result = checked(csv_bytes())
    report = quality_report(accepted, result)

    assert report.coverage.rows == 3
    assert report.coverage.columns == 9
    assert report.coverage.start == "2024-01-01"
    assert report.coverage.end == "2024-01-03"


def test_the_report_leaves_checks_that_have_not_run_pending():
    accepted, result = checked(csv_bytes())
    report = quality_report(accepted, result)

    statuses = {s.check: s.status for s in report.sections}
    assert statuses["schema"] is CheckStatus.PASSED
    assert statuses["outliers"] is CheckStatus.PENDING
    assert statuses["gaps"] is CheckStatus.PENDING
    assert statuses["missing"] is CheckStatus.PENDING


def test_a_failing_report_does_not_pass():
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",oops,")
    accepted, result = checked(csv_bytes(rows))
    report = quality_report(accepted, result)

    assert not report.passed
    assert report.status is CheckStatus.FAILED


def test_a_report_with_only_warnings_still_passes():
    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",900.0,")
    accepted, result = checked(csv_bytes(rows))
    report = quality_report(accepted, result)

    assert report.passed
    assert report.summary["warning_count"] == 1


def test_the_report_identifies_the_file_it_describes():
    accepted, result = checked(csv_bytes(), "q3.csv")
    report = quality_report(accepted, result)

    assert report.source.sha256 == accepted.source.sha256
    assert report.source.name == "q3.csv"


def test_the_report_round_trips_with_a_schema_section():
    from forecasting_engine.quality.report import QualityReport

    rows = list(ROWS)
    rows[1] = rows[1].replace(",16.0,", ",oops,")
    accepted, result = checked(csv_bytes(rows))
    report = quality_report(accepted, result)

    assert QualityReport.from_dict(report.as_dict()) == report


def test_a_repeated_date_reports_the_date_that_repeats():
    # "repeated dates" with no date attached leaves the reader nowhere to look.
    rows = list(ROWS)
    rows[2] = rows[2].replace("2024-01-03", "2024-01-02")
    accepted, result = checked(csv_bytes(rows))

    (found,) = [f for f in schema_section(result, accepted.frame).findings]
    assert found.signal == "date"
    assert found.dates == ("2024-01-02",)
    assert found.rows == (4,)


def test_an_unparseable_date_still_quotes_no_date():
    # There is no date to name - the value did not parse. The line number is the
    # only handle, and repeating the junk back would be circular.
    rows = list(ROWS)
    rows[1] = rows[1].replace("2024-01-02", "nonsense")
    accepted, result = checked(csv_bytes(rows))

    (found,) = [f for f in schema_section(result, accepted.frame).findings]
    assert found.dates == ()
    assert found.rows == (3,)
