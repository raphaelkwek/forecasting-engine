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


def test_defective_frame_contains_duplicates_and_blanks():
    frame = fixtures.generate(years=5, seed=1, with_defects=True)
    kinds = {issue.kind for issue in schema.validate(frame)}
    assert "duplicate_date" in kinds
    assert frame.isna().any().any()


def test_crash_window_produces_a_large_drawdown():
    frame = fixtures.generate(years=5, seed=1, with_defects=False)
    worst = frame["spx_close"].pct_change(20).min()
    assert worst < -0.15, f"expected a stress window, worst 20-day move was {worst:.1%}"


def test_cli_writes_a_readable_file(tmp_path):
    out = tmp_path / "signals.csv"
    exit_code = fixtures.main(["--years", "2", "--out", str(out), "--clean"])
    assert exit_code == 0
    written = pd.read_csv(out)
    assert schema.validate(written) == []
