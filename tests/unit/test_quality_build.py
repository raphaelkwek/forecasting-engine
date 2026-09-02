"""Assembling the report, and acting on the decisions taken against it."""

import numpy as np
import pandas as pd
import pytest

from forecasting_engine.ingest.upload import accept_upload
from forecasting_engine.ingest.validation import validate_upload
from forecasting_engine.quality.build import apply_decisions, build_report, with_decisions
from forecasting_engine.quality.report import CheckStatus

HEADER = (
    "date,spx_close,agg_close,vix,credit_spread_hy,credit_spread_ig,"
    "fx_impl_vol,breakeven_10y,term_spread"
)


def csv_bytes(n=300, spike_at=None, spike=180.0, break_column=None):
    rng = np.random.default_rng(4)
    dates = pd.bdate_range("2020-01-01", periods=n).strftime("%Y-%m-%d")
    vix = 15 + np.cumsum(rng.normal(0, 0.2, n))
    rows = [HEADER]
    for i, date in enumerate(dates):
        v = spike if spike_at == i else round(vix[i], 2)
        rows.append(
            f"{date},{4000 + i:.2f},{100 + i * 0.01:.3f},{v},"
            f"{3.5 + rng.normal(0, 0.02):.2f},1.2,8.0,2.2,1.0"
        )
    if break_column:
        rows[3] = rows[3].replace(",15", ",oops", 1)
    return ("\n".join(rows) + "\n").encode()


def ingest(data: bytes):
    accepted = accept_upload("signals.csv", data, uploads_dir=None)
    return accepted, validate_upload(accepted)


def _outlier_for(report, signal):
    """Outlier findings only — schema may flag the same signal for its own reasons."""
    return [f for f in report.findings if f.check == "outliers" and f.signal == signal]


# --- AC5: detection runs on every upload -----------------------------------


def test_outlier_detection_runs_without_being_asked():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)

    section = report.section("outliers")
    assert section.status is CheckStatus.FLAGGED
    assert any(f.signal == "vix" for f in section.findings)


def test_a_clean_upload_records_the_check_as_passed():
    accepted, result = ingest(csv_bytes())
    assert build_report(accepted, result).section("outliers").status is CheckStatus.PASSED


def test_detection_is_skipped_when_validation_failed():
    # Scoring the spread of a column that would not parse as numbers produces
    # findings about nothing.
    broken = csv_bytes().replace(b"date,spx_close", b"date,NOT_spx_close", 1)
    accepted, result = ingest(broken)
    report = build_report(accepted, result)

    assert not result.passed
    assert report.section("outliers").status is CheckStatus.PENDING


def test_gap_detection_runs_alongside_the_outlier_check():
    accepted, result = ingest(csv_bytes())
    assert build_report(accepted, result).section("gaps").status is CheckStatus.PASSED


def test_checks_that_do_not_exist_yet_stay_pending():
    accepted, result = ingest(csv_bytes())
    statuses = {s.check: s.status for s in build_report(accepted, result).sections}

    assert statuses["missing"] is CheckStatus.PENDING


def test_gap_detection_is_skipped_when_validation_failed():
    broken = csv_bytes().replace(b"date,spx_close", b"date,NOT_spx_close", 1)
    accepted, result = ingest(broken)
    assert build_report(accepted, result).section("gaps").status is CheckStatus.PENDING


def test_outliers_never_stop_the_report_passing():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)

    assert report.passed
    assert report.summary["blocking_count"] == 0
    assert report.summary["info_count"] > 0


# --- recording the portfolio manager's decisions ---------------------------


def test_a_decision_is_recorded_against_the_right_finding():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    (found,) = _outlier_for(report, "vix")

    reviewed = with_decisions(report, {found.id: "exclude"})

    assert [f.id for f in reviewed.excluded] == [found.id]


def test_findings_not_mentioned_keep_their_decision():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    first = report.findings[0]

    once = with_decisions(report, {first.id: "exclude"})
    twice = with_decisions(once, {})

    assert [f.id for f in twice.excluded] == [first.id]


def test_recording_a_decision_does_not_touch_the_original_report():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)

    with_decisions(report, {report.findings[0].id: "exclude"})

    assert report.excluded == ()


def test_an_unknown_decision_is_refused():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)

    with pytest.raises(ValueError):
        with_decisions(report, {report.findings[0].id: "probably"})


# --- AC2 and AC4: what a model actually sees -------------------------------


def test_nothing_changes_while_every_flag_is_undecided():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)

    pd.testing.assert_frame_equal(apply_decisions(accepted.frame, report), accepted.frame)


def test_an_included_outlier_stays_in_the_data():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    (found,) = _outlier_for(report, "vix")

    kept = apply_decisions(accepted.frame, with_decisions(report, {found.id: "include"}))
    assert kept.loc[150, "vix"] == 180.0


def test_an_excluded_outlier_is_blanked_not_deleted():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    (found,) = _outlier_for(report, "vix")

    adjusted = apply_decisions(accepted.frame, with_decisions(report, {found.id: "exclude"}))

    assert pd.isna(adjusted.loc[150, "vix"])
    assert len(adjusted) == len(accepted.frame), "the row must survive"


def test_excluding_one_signal_leaves_the_rest_of_that_row_alone():
    # Dropping the row would discard eight good observations to lose one.
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    (found,) = _outlier_for(report, "vix")

    adjusted = apply_decisions(accepted.frame, with_decisions(report, {found.id: "exclude"}))

    assert adjusted.loc[150, "spx_close"] == accepted.frame.loc[150, "spx_close"]
    assert adjusted.loc[150, "date"] == accepted.frame.loc[150, "date"]


def test_the_uploaded_data_is_never_modified():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    before = accepted.frame.copy()

    apply_decisions(accepted.frame, with_decisions(report, {report.findings[0].id: "exclude"}))

    pd.testing.assert_frame_equal(accepted.frame, before)


def test_an_exclusion_is_reversible():
    accepted, result = ingest(csv_bytes(spike_at=150))
    report = build_report(accepted, result)
    (found,) = _outlier_for(report, "vix")

    excluded = with_decisions(report, {found.id: "exclude"})
    restored = with_decisions(excluded, {found.id: "include"})

    assert apply_decisions(accepted.frame, restored).loc[150, "vix"] == 180.0
