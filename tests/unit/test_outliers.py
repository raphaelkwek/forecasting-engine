"""Outlier detection."""

import numpy as np
import pandas as pd
import pytest

from forecasting_engine.quality.outliers import (
    DEFAULT_THRESHOLD,
    detect,
    robust_z,
    threshold_for,
)
from forecasting_engine.quality.report import CheckStatus, Severity


def calm(n=300, start=100.0, step=0.5, signal="vix"):
    """A well-behaved series: steady small moves, no surprises."""
    rng = np.random.default_rng(5)
    values = start + np.cumsum(rng.normal(0, step, n))
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2020-01-01", periods=n).strftime("%Y-%m-%d"),
            signal: values,
        }
    )


# --- the score itself ------------------------------------------------------


def test_a_flat_series_has_no_outliers():
    assert robust_z(pd.Series([5.0] * 20)).abs().max() == 0


def test_a_lone_jump_in_an_otherwise_flat_series_is_not_swallowed():
    # More than half the values identical drives the median absolute deviation
    # to zero. Guarding that naively would call the one real move unremarkable.
    values = pd.Series([5.0] * 40 + [90.0])
    assert robust_z(values).abs().iloc[-1] > 8


def test_the_score_is_not_dragged_up_by_the_outlier_it_is_measuring():
    # The whole reason for using the median absolute deviation: one huge move
    # inflates a standard deviation enough to hide itself.
    values = pd.Series([1.0, -1.0] * 30 + [200.0])
    classic = abs((200.0 - values.mean()) / values.std())
    robust = robust_z(values).abs().iloc[-1]

    assert classic < 8
    assert robust > 50


# --- AC1: values beyond the threshold are flagged --------------------------


def test_an_injected_spike_is_detected():
    frame = calm()
    frame.loc[150, "vix"] = frame.loc[150, "vix"] + 90

    section = detect(frame)

    assert section.status is CheckStatus.FLAGGED
    assert any(f.signal == "vix" for f in section.findings)


def test_a_calm_series_produces_no_flags():
    section = detect(calm())

    assert section.status is CheckStatus.PASSED
    assert section.findings == ()


def test_a_misplaced_decimal_is_caught():
    # Detection runs on the change precisely so this is visible; as a level it
    # sits well inside a trending series' distribution.
    frame = calm(signal="spx_close", start=4000.0, step=8.0)
    frame.loc[150, "spx_close"] = frame.loc[150, "spx_close"] / 10

    flagged = {f.signal for f in detect(frame).findings}
    assert "spx_close" in flagged


def test_every_signal_is_checked_independently():
    frame = calm(signal="vix")
    frame["credit_spread_hy"] = 3.5
    frame.loc[100, "credit_spread_hy"] = 40.0

    flagged = {f.signal for f in detect(frame).findings}
    assert flagged == {"credit_spread_hy"}


def test_columns_that_are_not_signals_are_ignored():
    frame = calm()
    frame["analyst_note_length"] = 1.0
    frame.loc[100, "analyst_note_length"] = 9999.0

    assert detect(frame).findings == ()


def test_a_missing_signal_column_is_simply_skipped():
    frame = calm()[["date", "vix"]]
    section = detect(frame)
    assert section.stats["signals_checked"] == 1


# --- AC3: signal, date and value on every flag -----------------------------


def test_a_finding_carries_the_signal_date_and_value():
    frame = calm()
    frame.loc[150, "vix"] = 250.0

    (found,) = [f for f in detect(frame).findings if f.rows == (152,)]

    assert found.signal == "vix"
    assert found.dates == (frame.loc[150, "date"],)
    assert found.value == 250.0


def test_the_detail_says_how_far_out_the_move_was():
    frame = calm()
    frame.loc[150, "vix"] = 250.0

    (found,) = [f for f in detect(frame).findings if f.rows == (152,)]
    assert "in one day" in found.detail
    assert "the typical move" in found.detail


def test_findings_have_no_date_when_the_frame_has_no_date_column():
    frame = calm().drop(columns=["date"])
    frame.loc[150, "vix"] = 250.0

    assert all(f.dates == () for f in detect(frame).findings)


# --- AC2 and the severity contract ----------------------------------------


def test_flagged_values_are_left_in_the_frame_untouched():
    frame = calm()
    frame.loc[150, "vix"] = 250.0
    before = frame.copy()

    detect(frame)

    pd.testing.assert_frame_equal(frame, before)


def test_the_value_reported_is_the_one_still_in_the_data():
    frame = calm()
    frame.loc[150, "vix"] = 250.0

    (found,) = [f for f in detect(frame).findings if f.rows == (152,)]
    assert frame.loc[150, "vix"] == found.value


def test_outliers_are_informational_and_never_block():
    # FYP-25 requires the user to proceed regardless of flags.
    frame = calm()
    frame.loc[150, "vix"] = 250.0

    assert all(f.severity is Severity.INFO for f in detect(frame).findings)


def test_every_finding_starts_undecided():
    frame = calm()
    frame.loc[150, "vix"] = 250.0

    assert all(f.decision == "undecided" for f in detect(frame).findings)


# --- thresholds ------------------------------------------------------------


def test_the_default_threshold_applies_to_a_signal_with_no_override():
    assert threshold_for("vix") == DEFAULT_THRESHOLD


def test_an_override_is_used_when_one_exists(monkeypatch):
    monkeypatch.setattr("forecasting_engine.quality.outliers.THRESHOLDS", {"vix": 2.0})
    assert threshold_for("vix") == 2.0
    assert threshold_for("spx_close") == DEFAULT_THRESHOLD


def test_a_lower_threshold_flags_more(monkeypatch):
    frame = calm()
    strict = len(detect(frame).findings)

    monkeypatch.setattr("forecasting_engine.quality.outliers.THRESHOLDS", {"vix": 2.0})
    assert len(detect(frame).findings) > strict


def test_the_method_is_recorded_for_auditability():
    stats = detect(calm()).stats
    assert "median absolute deviation" in stats["method"]
    assert stats["default_threshold"] == DEFAULT_THRESHOLD


# --- edge cases ------------------------------------------------------------


def test_a_constant_signal_produces_no_flags():
    frame = calm()
    frame["vix"] = 15.0
    assert detect(frame).findings == ()


def test_blanks_do_not_become_outliers():
    frame = calm()
    frame.loc[150, "vix"] = np.nan

    assert all(f.rows != (152,) for f in detect(frame).findings)


@pytest.mark.parametrize("rows", [0, 1, 2])
def test_a_frame_too_short_to_have_a_distribution_is_handled(rows):
    frame = calm().head(rows)
    assert detect(frame).findings == ()
