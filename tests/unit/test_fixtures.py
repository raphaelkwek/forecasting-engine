"""The synthetic data generator."""

import pandas as pd

from forecasting_engine import fixtures


def test_a_clean_frame_is_complete_and_in_date_order():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert not frame.isna().any().any()
    assert frame[fixtures.DATE_COLUMN].is_unique
    assert frame[fixtures.DATE_COLUMN].is_monotonic_increasing


def test_generation_is_deterministic():
    first = fixtures.generate(years=2, seed=7, with_defects=False)
    second = fixtures.generate(years=2, seed=7, with_defects=False)
    pd.testing.assert_frame_equal(first, second)


def test_different_seeds_give_different_data():
    first = fixtures.generate(years=2, seed=1, with_defects=False)
    second = fixtures.generate(years=2, seed=2, with_defects=False)
    assert not first["vix"].equals(second["vix"])


def test_every_column_is_present_in_order():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert list(frame.columns) == [fixtures.DATE_COLUMN, *fixtures.SIGNAL_COLUMNS]


def test_defective_frame_contains_duplicates_and_blanks():
    frame = fixtures.generate(years=5, seed=1, with_defects=True)
    assert frame[fixtures.DATE_COLUMN].duplicated().any()
    assert frame.isna().any().any()


def test_the_defects_are_reportable_but_never_fatal():
    # The demo file has to load, so nothing injected may make a value unreadable:
    # duplicates and blanks only, never an unparseable date or text in a number
    # column. A file rejected at the door shows its defects to nobody.
    frame = fixtures.generate(years=5, seed=1, with_defects=True)
    assert pd.to_datetime(frame[fixtures.DATE_COLUMN], errors="coerce").notna().all()
    for column in fixtures.SIGNAL_COLUMNS:
        assert pd.api.types.is_numeric_dtype(frame[column]), column


def test_crash_window_produces_a_large_drawdown():
    frame = fixtures.generate(years=5, seed=1, with_defects=False)
    worst = frame["spx_close"].pct_change(20).min()
    assert worst < -0.15, f"expected a stress window, worst 20-day move was {worst:.1%}"


def test_volatility_spikes_when_equities_fall():
    # The leverage effect. Without it the VIX level scales equity volatility but
    # its movements are uncorrelated with returns, leaving nothing to learn.
    # Real markets sit near -0.7; anything approaching -1 is a giveaway that the
    # two series are the same random draw wearing different hats.
    frame = fixtures.generate(years=10, seed=3, with_defects=False)
    correlation = frame["spx_close"].pct_change().corr(frame["vix"].diff())
    assert -0.9 < correlation < -0.5, f"implausible leverage effect: {correlation:.2f}"


def test_spreads_track_volatility_without_being_copies_of_it():
    frame = fixtures.generate(years=10, seed=3, with_defects=False)
    correlation = frame["credit_spread_hy"].corr(frame["vix"])
    assert 0.5 < correlation < 0.95, f"implausible spread correlation: {correlation:.2f}"


def test_the_spreads_stay_in_ranges_a_reader_would_recognise():
    frame = fixtures.generate(years=10, seed=42, with_defects=False)
    assert 0.5 < frame["credit_spread_hy"].min() < 5
    assert 5 < frame["credit_spread_hy"].max() < 20
    assert 9 <= frame["vix"].min() < 15
    assert 25 < frame["vix"].max() < 90


def test_a_short_file_gets_the_same_treatment_as_a_long_one():
    frame = fixtures.generate(years=1, seed=1, with_defects=True)
    assert frame[fixtures.DATE_COLUMN].duplicated().any()


def test_dates_are_written_as_iso_dates(tmp_path):
    out = tmp_path / "signals.csv"
    fixtures.main(["--years", "1", "--out", str(out), "--clean"])
    assert out.read_text().splitlines()[1].split(",")[0].count("-") == 2


def test_cli_writes_a_readable_file(tmp_path):
    out = tmp_path / "signals.csv"
    exit_code = fixtures.main(["--years", "2", "--out", str(out), "--clean"])
    assert exit_code == 0
    written = pd.read_csv(out)
    assert list(written.columns) == [fixtures.DATE_COLUMN, *fixtures.SIGNAL_COLUMNS]
    assert not written.isna().any().any()


def test_the_cli_says_the_data_is_invented(tmp_path, capsys):
    fixtures.main(["--years", "1", "--out", str(tmp_path / "s.csv")])
    assert "SYNTHETIC" in capsys.readouterr().out


def test_the_default_filename_names_itself_synthetic():
    assert "synthetic" in fixtures.DEFAULT_OUT.name
    assert fixtures.DEFAULT_OUT.parts[0] == "data"


def test_the_output_directory_is_created(tmp_path):
    out = tmp_path / "nested" / "signals.csv"
    assert fixtures.main(["--years", "1", "--out", str(out)]) == 0
    assert out.exists()
