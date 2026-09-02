"""Distinguishing genuine data gaps from days the market was closed."""

import pandas as pd
import pytest

from forecasting_engine.quality.gaps import (
    CALENDARS,
    DEFAULT_CALENDAR,
    calendar_for,
    detect,
    expected_sessions,
)
from forecasting_engine.quality.report import CheckStatus, Severity

# December 2024: the 25th is Christmas, the 21st/22nd and 28th/29th weekends.
DECEMBER = [
    "2024-12-18", "2024-12-19", "2024-12-20", "2024-12-23", "2024-12-24",
    "2024-12-26", "2024-12-27", "2024-12-30", "2024-12-31",
]


def frame(dates, signal="spx_close", values=None):
    return pd.DataFrame({"date": dates, signal: values or [100.0] * len(dates)})


def gaps_for(f):
    return detect(f).findings


def flagged_dates(f):
    return {d for found in gaps_for(f) for d in found.dates}


# --- AC1: holidays and weekends are never flagged --------------------------


def test_a_complete_month_has_no_gaps():
    section = detect(frame(DECEMBER))
    assert section.status is CheckStatus.PASSED
    assert section.findings == ()


def test_christmas_day_is_not_a_gap():
    # 2024-12-25 is absent from the data and must stay absent from the report.
    assert "2024-12-25" not in flagged_dates(frame(DECEMBER))


def test_weekends_are_not_gaps():
    assert not {"2024-12-21", "2024-12-22", "2024-12-28", "2024-12-29"} & flagged_dates(
        frame(DECEMBER)
    )


@pytest.mark.parametrize(
    ("holiday", "name"),
    [
        ("2024-01-01", "New Year's Day"),
        ("2024-03-29", "Good Friday"),
        ("2024-05-27", "Memorial Day"),
        ("2024-07-04", "Independence Day"),
        ("2024-11-28", "Thanksgiving"),
    ],
)
def test_each_exchange_holiday_is_excluded(holiday, name):
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-01", "2024-12-31")]
    days.remove(holiday)
    assert holiday not in flagged_dates(frame(days)), name


# --- AC2: a genuine trading-day gap stays flagged --------------------------


def test_a_missing_trading_day_is_flagged():
    days = [d for d in DECEMBER if d != "2024-12-19"]
    (found,) = gaps_for(frame(days))

    assert found.dates == ("2024-12-19",)
    assert found.count == 1


def test_a_date_absent_from_the_file_is_reported_once_not_once_per_signal():
    # A whole missing row said eight ways buries the per-signal gaps, which are
    # the ones that need a column name to make sense.
    f = frame([d for d in DECEMBER if d != "2024-12-19"])
    for extra in ("vix", "agg_close", "credit_spread_ig"):
        f[extra] = 1.0

    findings = gaps_for(f)
    assert len(findings) == 1
    assert findings[0].signal is None
    assert "missing from the file" in findings[0].detail


def test_a_blank_cell_is_reported_against_its_own_signal():
    values = [100.0] * len(DECEMBER)
    values[3] = None
    f = frame(DECEMBER, values=values)
    f["vix"] = 1.0

    (found,) = gaps_for(f)
    assert found.signal == "spx_close"
    assert "NYSE" in found.detail


def test_the_detail_names_the_calendar_that_says_the_market_was_open():
    values = [100.0] * len(DECEMBER)
    values[1] = None
    f = frame(DECEMBER, values=values)
    f["vix"] = 1.0

    (found,) = gaps_for(f)
    assert "NYSE" in found.detail


def test_a_blank_value_counts_as_a_gap_not_as_data():
    values = [100.0] * len(DECEMBER)
    values[3] = None
    assert flagged_dates(frame(DECEMBER, values=values)) == {"2024-12-23"}


def test_a_whole_file_gap_names_the_signals_that_expected_data():
    # Only FX trades on Good Friday, so only FX is short of an observation.
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-03-25", "2024-04-05")]
    without = [d for d in days if d != "2024-03-29"]
    f = frame(without, signal="spx_close")
    f["fx_impl_vol"] = 8.0

    (found,) = gaps_for(f)
    assert found.dates == ("2024-03-29",)
    assert "fx_impl_vol" in found.detail
    assert "spx_close" not in found.detail


def test_consecutive_missing_sessions_group_into_one_finding():
    days = [d for d in DECEMBER if d not in ("2024-12-19", "2024-12-20")]
    (found,) = gaps_for(frame(days))

    assert found.count == 2
    assert found.dates == ("2024-12-19", "2024-12-20")
    assert "consecutive sessions" in found.detail


def test_a_gap_spanning_a_weekend_is_one_run_not_two():
    # Friday and the following Monday are consecutive sessions.
    days = [d for d in DECEMBER if d not in ("2024-12-20", "2024-12-23")]
    (found,) = gaps_for(frame(days))
    assert found.count == 2


def test_separate_gaps_stay_separate():
    days = [d for d in DECEMBER if d not in ("2024-12-19", "2024-12-27")]
    assert len(gaps_for(frame(days))) == 2


def test_gaps_outside_the_files_own_range_are_not_invented():
    # A file covering one week must not be told it is missing the rest of the year.
    assert gaps_for(frame(DECEMBER[:3])) == ()


# --- per-signal calendars --------------------------------------------------


def test_equity_and_credit_use_different_calendars():
    assert calendar_for("spx_close") == "NYSE"
    assert calendar_for("credit_spread_ig") == "SIFMA_US"


def test_an_unmapped_signal_falls_back_to_the_default():
    assert calendar_for("something_new") == DEFAULT_CALENDAR


def test_every_contract_signal_has_a_calendar():
    from forecasting_engine.ingest.schema import COLUMNS

    assert {c.name for c in COLUMNS} <= set(CALENDARS)


def test_columbus_day_is_a_gap_for_equities_but_not_for_credit():
    # The exchange trades; the bond market does not. Judging a credit spread by
    # the equity calendar flags this day, every year, as missing data.
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-10-07", "2024-10-18")]
    without = [d for d in days if d != "2024-10-14"]

    assert "2024-10-14" in flagged_dates(frame(without, signal="spx_close"))
    assert "2024-10-14" not in flagged_dates(frame(without, signal="credit_spread_ig"))


def test_fx_is_checked_against_plain_weekdays():
    assert calendar_for("fx_impl_vol") == "weekdays"
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-10-07", "2024-10-18")]
    without = [d for d in days if d != "2024-10-14"]
    assert "2024-10-14" in flagged_dates(frame(without, signal="fx_impl_vol"))


# --- session generation ----------------------------------------------------


def test_expected_sessions_excludes_weekends_and_holidays():
    sessions = expected_sessions("NYSE", pd.Timestamp("2024-12-18").date(),
                                 pd.Timestamp("2024-12-31").date())
    assert {d.isoformat() for d in sessions} == set(DECEMBER)


def test_weekday_sessions_include_holidays():
    sessions = expected_sessions(WEEK := "weekdays", pd.Timestamp("2024-12-24").date(),
                                 pd.Timestamp("2024-12-26").date())
    assert len(sessions) == 3, WEEK


def test_an_inverted_range_yields_nothing():
    later, earlier = pd.Timestamp("2024-12-31").date(), pd.Timestamp("2024-01-01").date()
    assert expected_sessions("NYSE", later, earlier) == set()


# --- the contract this check keeps ----------------------------------------


def test_gaps_are_informational_and_never_block():
    days = [d for d in DECEMBER if d != "2024-12-19"]
    assert all(f.severity is Severity.INFO for f in gaps_for(frame(days)))


def test_the_calendar_source_is_recorded_for_auditability():
    stats = detect(frame(DECEMBER)).stats

    assert stats["source"] == "pandas_market_calendars"
    assert stats["version"]
    assert stats["calendars"]["spx_close"] == "NYSE"


def test_a_frame_without_dates_is_handled():
    section = detect(pd.DataFrame({"spx_close": [1.0, 2.0]}))
    assert section.findings == ()
    assert "no usable date column" in section.stats["reason"]


def test_a_very_long_gap_lists_a_sample_and_counts_the_rest():
    days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2024-01-02", "2024-06-28")]
    kept = days[:5] + days[-5:]
    (found,) = gaps_for(frame(kept))

    assert found.count > 100
    assert len(found.dates) == 10
    assert found.truncated
