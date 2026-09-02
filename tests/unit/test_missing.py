"""Per-signal completeness."""

import numpy as np
import pandas as pd

from forecasting_engine.quality.missing import detect
from forecasting_engine.quality.report import CheckStatus


def frame(**columns):
    base = {"date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]}
    return pd.DataFrame({**base, **columns})


def test_a_complete_file_passes():
    section = detect(frame(vix=[1.0, 2.0, 3.0, 4.0]))

    assert section.status is CheckStatus.PASSED
    assert section.stats["total_missing"] == 0


def test_blanks_are_counted_per_signal():
    section = detect(frame(vix=[1.0, np.nan, 3.0, np.nan], spx_close=[1.0, 2.0, 3.0, np.nan]))

    signals = section.stats["signals"]
    assert signals["vix"]["missing"] == 2
    assert signals["spx_close"]["missing"] == 1
    assert section.stats["total_missing"] == 3


def test_completeness_is_reported_as_a_fraction():
    section = detect(frame(vix=[1.0, np.nan, 3.0, 4.0]))
    assert section.stats["signals"]["vix"]["completeness"] == 0.75
    assert section.stats["signals"]["vix"]["present"] == 3


def test_a_file_with_blanks_is_flagged():
    assert detect(frame(vix=[1.0, np.nan, 3.0, 4.0])).status is CheckStatus.FLAGGED


def test_a_non_numeric_cell_counts_as_missing():
    section = detect(frame(vix=[1.0, "oops", 3.0, 4.0]))
    assert section.stats["signals"]["vix"]["missing"] == 1


def test_columns_that_are_not_signals_are_ignored():
    section = detect(frame(vix=[1.0, 2.0, 3.0, 4.0], analyst_note=[None, None, None, None]))
    assert set(section.stats["signals"]) == {"vix"}


def test_it_produces_no_findings_because_gaps_owns_the_dates():
    # Repeating the specific missing dates here would say the same thing twice.
    assert detect(frame(vix=[1.0, np.nan, 3.0, 4.0])).findings == ()


def test_nothing_is_claimed_to_have_been_filled_yet():
    stats = detect(frame(vix=[1.0, np.nan, 3.0, 4.0])).stats
    assert stats["filled"] == 0
    assert "data preparation" in stats["note"]


def test_an_empty_frame_does_not_divide_by_zero():
    section = detect(pd.DataFrame({"date": [], "vix": []}))
    assert section.stats["rows"] == 0
    assert section.stats["signals"]["vix"]["completeness"] == 0.0


def test_the_frame_is_not_modified():
    f = frame(vix=[1.0, np.nan, 3.0, 4.0])
    before = f.copy()
    detect(f)
    pd.testing.assert_frame_equal(f, before)
