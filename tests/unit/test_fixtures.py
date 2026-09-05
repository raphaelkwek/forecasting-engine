"""The synthetic data generator."""

import pandas as pd

from forecasting_engine import fixtures
from forecasting_engine.ingest import schema


def test_clean_frame_satisfies_the_schema():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert schema.validate(frame) == []


def test_generation_is_deterministic():
    first = fixtures.generate(years=2, seed=7, with_defects=False)
    second = fixtures.generate(years=2, seed=7, with_defects=False)
    pd.testing.assert_frame_equal(first, second)


def test_different_seeds_give_different_data():
    first = fixtures.generate(years=2, seed=1, with_defects=False)
    second = fixtures.generate(years=2, seed=2, with_defects=False)
    assert not first["vix"].equals(second["vix"])


def test_all_required_columns_present():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert set(schema.REQUIRED_COLUMNS) <= set(frame.columns)


def test_the_unlagged_targets_track_their_sources():
    frame = fixtures.generate(years=2, seed=1, with_defects=False)
    assert frame["spx_close_target"].equals(frame["spx_close"])
    assert frame["bond_index_target"].equals(frame["bond_index_global_agg"])


def test_defective_frame_contains_duplicates_and_blanks():
    frame = fixtures.generate(years=5, seed=1, with_defects=True)
    kinds = {issue.kind for issue in schema.validate(frame)}
    assert "duplicate_date" in kinds
    assert frame.isna().any().any()


def test_the_defects_are_reportable_but_never_fatal():
    # The demo file has to reach the quality report, so nothing injected may
    # block. A file that halts the pipeline shows the report to nobody.
    frame = fixtures.generate(years=5, seed=1, with_defects=True)
    assert schema.blocking(schema.validate(frame)) == []


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
    assert 2 < frame["credit_spread_hy"].max() < 5
    assert 9 <= frame["vix"].min() < 15
    assert 25 < frame["vix"].max() < 90


def test_a_short_file_gets_the_same_treatment_as_a_long_one():
    frame = fixtures.generate(years=1, seed=1, with_defects=True)
    assert "duplicate_date" in {i.kind for i in schema.validate(frame)}


def test_dates_are_written_as_iso_dates(tmp_path):
    out = tmp_path / "signals.csv"
    fixtures.main(["--years", "1", "--out", str(out), "--clean"])
    assert out.read_text().splitlines()[1].split(",")[0].count("-") == 2


def test_cli_writes_a_readable_file(tmp_path):
    out = tmp_path / "signals.csv"
    exit_code = fixtures.main(["--years", "2", "--out", str(out), "--clean"])
    assert exit_code == 0
    written = pd.read_csv(out)
    assert schema.validate(written) == []


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
